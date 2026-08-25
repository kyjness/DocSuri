from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AbstainReason,
    EvidenceAbstainResult,
    EvidenceRequest,
    EvidenceResult,
)

from .checkpoints import TurnCheckpoints
from .domain.models import AgentRunContext as LoopRunContext
from .domain.models import iter_refs
from .models import (
    AttachmentInput,
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
    TurnErrorResult,
    TurnPendingResult,
    TurnResult,
    TurnSuccessResult,
    _new_id,
    _utc_now,
)
from .repository import EvidenceRepository, SessionBusy
from .runner import EvidenceTurnRunner

logger = logging.getLogger(__name__)

_SESSION_LIST_MAX = 100
_TITLE_MAX_LEN = 120


# ---------------------------------------------------------------------------
# 서비스 응답 DTO (D5 외부 — 내부 전용)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TurnResponse:
    """채팅 턴 실행 결과 — controller 직렬화용."""
    session_id: str
    turn_id: str
    result: TurnResult
    created_at: datetime


@dataclass(frozen=True)
class SessionSummary:
    """세션 목록 항목."""
    session_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# EvidenceChatService — 턴 수락·마감 (FR-36, FR-37, v3 §5)
# ---------------------------------------------------------------------------

# 미실행 턴을 고아로 볼 때까지의 배수 — 워커 콜드스타트 + 백로그를 버틴다.
_UNPICKED_STALE_FACTOR = 3


class DispatchFailed(RuntimeError):
    """턴 행은 저장됐는데 실행자에게 넘기지 못했다 — 턴은 error로 닫혔고 controller가 503."""


class EvidenceChatService:
    """세션 load/create → 턴 행(pending) 저장 → 실행자에게 dispatch. 실행은 여기서 안 한다."""

    def __init__(
        self,
        *,
        repo: EvidenceRepository,
        dispatch: Callable[[dict[str, Any]], None] | None = None,
        checkpoints: TurnCheckpoints | None = None,
        stale_after: timedelta = timedelta(seconds=600),
    ) -> None:
        self._repo = repo
        # 읽기 경로(폴링·이벤트·취소)는 dispatch가 없다 — 수락만 필요로 한다.
        self._dispatch = dispatch
        self._checkpoints = checkpoints
        self._stale_after = stale_after

    def accept_turn(
        self,
        *,
        owner_id: str,
        request: EvidenceRequest,
        session_id: str | None = None,
        request_id: str = '',
        attachment_docs: tuple[AttachmentInput, ...] = (),
    ) -> TurnResponse:
        """턴 1회 수락 — pending 행을 **커밋한 뒤** 실행자에게 넘긴다.

        커밋이 먼저인 이유: 프로세스 내 실행자는 스레드가 즉시 출발하므로 행이 보이지 않으면
        "턴 없음"으로 돌아가 영원히 pending이 남는다. 대신 dispatch가 실패하면 여기서 error로
        닫는다 — 안 그러면 커밋된 pending 행이 세션 잠금(§5.4)이 되어 stale 시간까지 막는다.
        """
        del request_id  # 실행자는 turn_id를 요청 id로 쓴다
        if self._dispatch is None:
            raise DispatchFailed("dispatch is not configured")
        session = self._load_or_create_session(owner_id, request, session_id)
        # 이 사전 검사와 부분 유니크 인덱스는 **둘 다** 필요하다 — 검사는 고아 턴 마감을
        # 트리거하고(그래야 죽은 실행자가 세션을 영원히 막지 않는다), 인덱스는 두 API 태스크가
        # 동시에 통과하는 경쟁을 닫는다. 하나만 두면 각각 다른 쪽 구멍이 남는다.
        active = self._repo.active_turn(owner_id, session.session_id)
        if active is not None and not self.finalize_if_stale(owner_id, active):
            raise SessionBusy(session.session_id)
        turn = EvidenceTurn(
            session_id=session.session_id,
            owner_id=owner_id,
            topic=request.topic,
            # FR-38: 첨부 핸들도 턴에 영속한다 — 원시 파일이 아니라 참조 id다(INV-EV-4).
            attachments=list(request.attachments or []),
            request=request,
            result=TurnPendingResult(started_at=_utc_now()),
        )
        self._repo.add_turn(turn)
        self._repo.commit()
        # 응답은 수락 시점의 pending이다 — 실행자가 같은 객체를 공유하는 저장소(인메모리)에서
        # 먼저 끝내 버려도 수락 응답이 결과로 둔갑하지 않는다.
        accepted = turn.result
        try:
            self._dispatch({
                'ownerId': owner_id,
                'sessionId': session.session_id,
                'turnId': turn.turn_id,
                'topic': request.topic,
                'scope': (request.scope.value if request.scope else 'auto'),
                'paperIds': list(request.paperIds or []),
                'attachments': list(request.attachments or []),
                'attachmentDocs': _attachment_doc_payloads(attachment_docs),
            })
        except Exception as exc:
            logger.exception('evidence turn dispatch failed (turn=%s)', turn.turn_id)
            turn.result = TurnErrorResult(error_code='dispatch_failed')
            self._repo.update_turn_result(owner_id, turn.turn_id, turn.result)
            self._repo.commit()
            raise DispatchFailed(str(exc)) from exc
        return TurnResponse(
            session_id=session.session_id,
            turn_id=turn.turn_id,
            result=accepted,
            created_at=turn.created_at,
        )

    def request_cancel(self, owner_id: str, turn_id: str) -> bool:
        """협조적 취소(§5.2) — 플래그만 세운다. 이미 종단이면 False(controller 409)."""
        accepted = self._repo.request_cancel(owner_id, turn_id)
        self._repo.commit()
        return accepted

    def finalize_if_stale(self, owner_id: str, turn: EvidenceTurn) -> bool:
        """실행자가 죽은 pending 턴을 마지막 체크포인트로 마감한다(§5.5). 마감했으면 True.

        하트비트(없으면 생성 시각)가 stale 기준보다 오래됐을 때만. 조건부 UPDATE라 두 API
        태스크가 동시에 발견해도 한 번만 쓰인다. 스냅샷이 없으면(체크포인터 없음·첫 스텝 전
        죽음) 부분 답이 없으므로 정직하게 error로 닫는다.
        """
        if not isinstance(turn.result, TurnPendingResult):
            return False
        # 실행자가 한 번도 집지 않은 턴(heartbeat 없음)은 큐 대기 중일 수 있다 — SQS 워커가
        # 0에서 콜드스타트하면 대기만으로 10분을 넘긴다. 실행 중 고아보다 3배 길게 기다린다.
        if turn.heartbeat_at is None:
            last_seen, limit = turn.created_at, self._stale_after * _UNPICKED_STALE_FACTOR
        else:
            last_seen, limit = turn.heartbeat_at, self._stale_after
        if _utc_now() - last_seen < limit:
            return False
        result: TurnResult | None = None
        if self._checkpoints is not None:
            try:
                result = self._checkpoints.finalize(turn.turn_id, turn.topic)
            except Exception:  # noqa: BLE001 — 마감 실패가 조회를 깨지 않는다
                logger.warning('evidence stale finalize failed (turn=%s)', turn.turn_id,
                               exc_info=True)
        if result is None:
            result = TurnErrorResult(error_code='internal_error')
        logger.warning('evidence turn %s stale since %s; finalized as %s',
                       turn.turn_id, last_seen.isoformat(), type(result).__name__)
        self._repo.update_turn_result(owner_id, turn.turn_id, result)
        self._repo.commit()
        turn.result = result
        return True

    def get_turn(self, owner_id: str, turn_id: str) -> EvidenceTurn:
        """폴링 폴백 — stale이면 마감한 뒤 돌려준다. INV-EV-1: KeyError → 404."""
        turn = self._repo.get_turn(owner_id, turn_id)
        self.finalize_if_stale(owner_id, turn)
        return turn

    def _load_or_create_session(
        self,
        owner_id: str,
        request: EvidenceRequest,
        session_id: str | None,
    ) -> EvidenceSession:
        if session_id:
            # INV-EV-1: 소유권 불일치 → KeyError → controller 404
            return self._repo.get_session(owner_id, session_id)

        title = _derive_title(request.topic)
        session = EvidenceSession(owner_id=owner_id, title=title)
        return self._repo.create_session(session)


# ---------------------------------------------------------------------------
# EvidenceSessionManagementService — 세션 CRUD (FR-38)
# ---------------------------------------------------------------------------

class EvidenceSessionManagementService:
    """세션 목록·삭제·초기화 — BR-EV-8~10, INV-EV-1.

    삭제·초기화는 그 세션 턴들의 체크포인트 스레드도 지운다(체크포인터가 있을 때) — 세션이
    지워졌는데 루프 스냅샷(질문·초록)이 남으면 보존 기간까지 유령 데이터다.
    """

    def __init__(
        self, *, repo: EvidenceRepository, checkpoints: TurnCheckpoints | None = None
    ) -> None:
        self._repo = repo
        self._checkpoints = checkpoints

    def list_sessions(
        self, owner_id: str, limit: int = 50
    ) -> list[SessionSummary]:
        """BR-EV-10: 본인 active 세션만, updated_at DESC."""
        clamped = max(1, min(limit, _SESSION_LIST_MAX))
        sessions = self._repo.list_sessions(owner_id, clamped)
        return [
            SessionSummary(
                session_id=s.session_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]

    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession:
        """INV-EV-1: 소유권 불일치 → KeyError → controller 404(SEC-9)."""
        return self._repo.get_session(owner_id, session_id)

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        return self._repo.list_turns(owner_id, session_id)

    def delete_session(self, owner_id: str, session_id: str) -> None:
        """BR-EV-8: 소프트 삭제. INV-EV-1: 소유권 불일치 → KeyError → 404."""
        self._repo.soft_delete_session(owner_id, session_id)
        self._repo.commit()
        self._drop_checkpoints(owner_id, [session_id])

    def reset_all(self, owner_id: str) -> None:
        """BR-EV-9: 해당 사용자 모든 세션 소프트 삭제."""
        session_ids = [s.session_id for s in self._repo.list_sessions(owner_id, _SESSION_LIST_MAX)]
        self._repo.soft_delete_all_sessions(owner_id)
        self._repo.commit()
        self._drop_checkpoints(owner_id, session_ids)

    def _drop_checkpoints(self, owner_id: str, session_ids: list[str]) -> None:
        if self._checkpoints is None or not session_ids:
            return
        try:
            turn_ids = self._repo.turn_ids_for_sessions(owner_id, session_ids)
            self._checkpoints.delete(turn_ids)
        except Exception:  # noqa: BLE001 — 정리 실패가 삭제를 되돌리지 않는다
            logger.warning('evidence checkpoint cleanup failed', exc_info=True)


# ---------------------------------------------------------------------------
# EvidenceFormationService — EvidenceFormationPort 구현 (D5, U12 소비)
# ---------------------------------------------------------------------------

class EvidenceFormationService:
    """EvidenceFormationPort 구현체 — U12가 shared/ports 추상으로만 소비.

    U12는 이 클래스를 직접 import 금지. shared.ports.EvidenceFormationPort만 참조.
    순환 차단: U12 → shared/ports ← U11(구현). Trace: D5.

    **여기 오는 러너에는 체크포인터가 붙으면 안 된다** — 이 경로는 `evidence_turns` 행 없이
    돌아서 정리 대상 질의에 잡히지 않고, 남은 스레드가 보존기간과 무관하게 쌓인다.
    """

    def __init__(self, *, runner: EvidenceTurnRunner) -> None:
        self._runner = runner

    async def form_evidence(
        self,
        request: EvidenceRequest,
        ctx: Any,
    ) -> EvidenceResult | EvidenceAbstainResult:
        """EvidenceFormationPort 계약 구현.

        Orchestrator는 동기 — asyncio.to_thread로 호출해 이벤트 루프 차단 방지.
        Trace: D5, FR-37, SEC-9.
        """
        owner_id = getattr(ctx, 'owner_id', '')
        request_id = getattr(ctx, 'request_id', '')

        # U12 경로는 세션을 저장하지 않는다 — 호출자의 잡이 산출물을 소유한다.
        loop_ctx = LoopRunContext(
            owner_id=owner_id,
            session_id=f'port:{owner_id or "anon"}',
            turn_id=_new_id(),
            request_id=request_id,
        )

        result = await asyncio.to_thread(lambda: self._runner.run(loop_ctx, request))

        if isinstance(result, TurnSuccessResult):
            return result.outcome
        if isinstance(result, TurnAbstainResult):
            return result.outcome
        # TurnErrorResult → 기권으로 수렴(BR-EV-12 fail-closed). 다만 **사유는 지어내지
        # 않는다** — 종전에는 어떤 실패든 'llm_unavailable'로 못박고 로그도 안 남겨서, 호출자
        # (U12)의 산출물에 "LLM 사용 불가"라고 적히는데 워커 로그에는 아무 것도 없었다
        # (2026-08-24 실측). `error_code`는 이미 SEC-9를 지나 API로 나가는 비기술 코드이므로
        # 그대로 나른다. worker.py의 같은 자리도 범용 코드를 쓴다.
        logger.warning('evidence port: turn failed (%s)', result.error_code)
        # `abstainReason`은 닫힌 어휘다(스키마 `AbstainReason`). 저장된 턴에서 되살린
        # 코드는 그 어휘 밖일 수 있으므로 unknown으로 수렴시킨다 — 원래 값은 위 로그에
        # 남는다. 사유를 **지어내지** 않는다는 원칙은 그대로다: 모른다고 말하는 것과
        # 'LLM 사용 불가'라고 단정하는 것은 다르다.
        try:
            reason = AbstainReason(result.error_code)
        except ValueError:
            reason = AbstainReason.unknown
        return EvidenceAbstainResult(state='abstain', abstainReason=reason)


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _derive_title(topic: str) -> str:
    """첫 질문 topic에서 세션 제목 도출."""
    stripped = topic.strip()
    if len(stripped) <= _TITLE_MAX_LEN:
        return stripped
    return stripped[:_TITLE_MAX_LEN - 1] + '…'


# 이전 대화를 싣는 **토큰 예산**(설계 §3.4). 종전의 `_PRIOR_TURNS = 3`은 근거 없이 옮겨온
# 수치라 폐기했다 — 짧은 턴 셋과 긴 턴 셋이 같은 3이었고, 실제로 드는 비용은 열 배 갈렸다.
#
# 문자로 잰다. 정확한 토큰 수는 모델별 토크나이저를 타야 하는데, 여기서 재는 것은 상한이지
# 과금이 아니다 — 실제 과금은 Bedrock 사용량이 권위이고 예산 대장이 따로 본다. 한국어·영어가
# 섞인 프롬프트에서 4자/토큰이 보수적인 어림이고, 빗나가도 상한이 조금 헐거워질 뿐이다.
_PRIOR_TOKEN_BUDGET = 8_000
_CHARS_PER_TOKEN = 4
_PRIOR_CHAR_BUDGET = _PRIOR_TOKEN_BUDGET * _CHARS_PER_TOKEN

# 예산 안에서 되짚어 볼 최대 턴 수 — 예산이 남아도 여기서 끊는다. 긴 세션에서 recent_turns가
# 수백 행을 역직렬화하는 것을 막는 상한이고, 예산이 그보다 먼저 차는 것이 정상이다.
_PRIOR_TURN_CEILING = 20


def build_run_context(
    repo: EvidenceRepository,
    *,
    owner_id: str,
    session_id: str,
    turn_id: str,
    request_id: str = '',
) -> LoopRunContext:
    """루프 실행 컨텍스트 조립 — 실행자(SQS 워커·프로세스 내 스레드) 공통 경로가 쓴다.

    두 벌로 두면 갈라진다: 실제로 워커 사본이 prior_topics를 빠뜨려 비동기 턴만
    멀티턴이 안 되는 상태였다. 맥락 필드가 늘어나면 여기만 고친다.

    prior 맥락은 저장 컬럼에서 읽는다 — `t.request`는 SQL 복원 턴에서 None이라
    (요청 원문은 영속하지 않는다) 그걸 읽으면 인메모리에서만 동작한다.
    """
    try:
        # +1로 읽고 현재 턴을 걸러낸다 — 동기 경로는 add_turn 전에 조립하지만
        # 워커 경로는 pending 턴이 이미 저장된 뒤라, 거르지 않으면 현재 질문이
        # "이전 턴 질문"으로 자기 자신에게 다시 보인다.
        recent = [
            t
            for t in repo.recent_turns(owner_id, session_id, _PRIOR_TURN_CEILING + 1)
            if t.turn_id != turn_id
        ]
        summary = repo.get_session(owner_id, session_id).summary
    except KeyError:
        recent, summary = [], ""

    # 인용 논문 id는 **세션 전체**에서 모은다(§3.4) — 좁히기("그중에서")가 가리키는 집합은
    # 토큰 예산과 무관하고, 밀려난 턴의 논문이라고 사용자가 잊은 것이 아니다.
    paper_ids: dict[str, None] = {}
    for t in recent:
        for pid in cited_paper_ids(t.result):
            paper_ids.setdefault(pid, None)

    kept, over_budget = _within_token_budget(recent)

    # 접을 대상은 둘이다.
    #   1. 예산을 넘겨 관찰에서 빠진 턴(창 **안**) — 드물다. 질문 하나가 비정상으로 길 때만.
    #   2. 천장 밖으로 밀려 **애초에 안 읽힌** 턴 — 긴 세션의 정상 경로다.
    # 종전에는 1번만 봤는데, 그쪽은 현실적인 턴에서 거의 안 물고(턴당 ~144자 · 예산 32,000자)
    # 정작 맥락에서 사라지는 것은 2번이었다. **옛 턴을 보존하려는 기능이 정작 잃는 턴을
    # 구조적으로 못 보고 있었다.**
    folding: list[tuple[str, str]] = [
        (t.turn_id, t.topic or "") for t in over_budget if t.summarized_at is None
    ]
    try:
        folding += repo.unsummarized_before(owner_id, session_id, _PRIOR_TURN_CEILING + 1)
    except KeyError:
        pass

    # **아직 안 접힌 것만** 접는다. 도장이 없던 동안 같은 턴이 매 턴 다시 접혔고(실측 1→2→3회),
    # 세션 요약 상한이 앞을 자르므로 사본이 쌓이면 정작 보존하려던 옛 내용이 밀려 나갔다.
    # §7의 `checkpoints_pruned_at`이 같은 이유로 쓰는 패턴이다.
    if folding:
        text = _summarize_evicted([topic for _tid, topic in folding])
        if text:
            try:
                # 붙인 **결과를 받는다** — 여기서 다시 이어 붙이면 상한이 한쪽에만 걸려
                # 모델이 읽는 값과 DB 값이 갈린다(실제로 갈렸다).
                summary = repo.append_session_summary(owner_id, session_id, text)
                repo.mark_summarized(owner_id, [tid for tid, _topic in folding])
            except KeyError:
                pass

    return LoopRunContext(
        owner_id=owner_id,
        session_id=session_id,
        turn_id=turn_id,
        request_id=request_id,
        prior_topics=tuple(t.topic for t in kept if t.topic),
        prior_paper_ids=tuple(paper_ids),
        # 이어가기 씨앗은 **직전 턴**의 체크포인트에서 읽는다(§3.4). 더 거슬러 올라가지
        # 않는다 — "이어서 더 찾아줘"가 가리키는 것은 방금 멈춘 그 탐색이다.
        prior_turn_id=recent[-1].turn_id if recent else None,
        prior_summary=summary,
    )


def _within_token_budget(turns: list) -> tuple[list, list]:
    """(예산 안에 남는 턴, 밀려난 턴) — 최근 것부터 채운다.

    최근 턴을 **그대로** 싣고 넘치는 앞쪽을 요약으로 접는다(§3.4). 반대로 하면 방금 한
    질문이 요약으로 뭉개져 후속 질문 해석이 가장 필요한 자리에서 정보가 가장 적어진다.

    **턴 하나가 관찰에서 차지하는 것 전부를 잰다** — 질문 + 그 턴이 인용한 논문 id(§2.5:
    "질문·답변 요약·인용 논문, 턴당 약 400토큰"). 질문 문자열만 재면 턴당 15~25토큰이라
    21턴이 500토큰밖에 안 되고, 8천 토큰 예산은 **영원히 안 물어** 요약 경로 전체가 죽는다
    (실측: 퇴출이 일어나려면 최근 20개 질문 평균이 1,600자를 넘어야 했다).
    """
    kept: list = []
    spent = 0
    for turn in reversed(turns):
        cost = _prior_turn_cost(turn)
        if kept and spent + cost > _PRIOR_CHAR_BUDGET:
            break
        kept.append(turn)
        spent += cost
    kept.reverse()
    return kept, turns[: len(turns) - len(kept)]


def _prior_turn_cost(turn) -> int:
    """관찰에 실릴 때 이 턴이 차지하는 문자 수 — 질문 + 인용 논문 id."""
    ids = cited_paper_ids(turn.result)
    return len(turn.topic or "") + sum(len(pid) + 2 for pid in ids)


def _summarize_evicted(topics: list[str]) -> str:
    """밀려난 턴을 한 단락으로 접는다 — **모델을 부르지 않는다.**

    질문 목록이 곧 요약이다. 여기서 LLM을 부르면 턴 실행 전에 한 번 더 왕복하고, 그 비용이
    턴 예산에 잡히지 않은 채 나간다. 나중에 이 자리가 부족하다고 판정되면 그때 모델을
    붙이면 되고, 그 판정은 실측으로 한다.
    """
    shortened = [_short(t) for t in topics if (t or "").strip()]
    if not shortened:
        return ""
    # 머리표는 붙이지 않는다 — 라벨과 상한은 저장 쪽(`_joined_summary`)이 소유한다.
    # 두 모듈이 같은 문자열을 각자 쓰면 한 글자만 달라져도 조용히 안 맞고,
    # 그러면 접을 때마다 라벨이 다시 쌓인다(그 회귀를 방금 고쳤다).
    return " / ".join(shortened)


# 요약에 싣는 질문 하나의 길이 상한. 접는 단계에서 줄이지 않으면 긴 질문 하나가 요약 전체를
# 차지하고, 세션 요약 상한이 그 앞을 잘라 "이전에 물어본 것" 라벨까지 날아간다 — 남는 것은
# 맥락이라 읽히지 않는 원문 조각이다.
_MAX_SUMMARY_TOPIC_CHARS = 120


def _short(topic: str) -> str:
    text = topic.strip()
    if len(text) <= _MAX_SUMMARY_TOPIC_CHARS:
        return text
    return text[: _MAX_SUMMARY_TOPIC_CHARS - 1] + "…"



def cited_paper_ids(result: TurnResult | None) -> tuple[str, ...]:
    """이전 턴이 실제로 인용한 논문 — "그중에서" 류 후속 질문의 좁히기 재료."""
    if not isinstance(result, TurnSuccessResult):
        return ()
    seen: dict[str, None] = {}
    for item in result.outcome.claims:
        for ref in iter_refs(item):
            seen.setdefault(ref.paperId, None)
    return tuple(seen)


def _attachment_doc_payloads(attachment_docs: tuple[AttachmentInput, ...]) -> list[dict[str, Any]]:
    from .attachments import attachment_inputs_to_payloads

    return attachment_inputs_to_payloads(attachment_docs)
