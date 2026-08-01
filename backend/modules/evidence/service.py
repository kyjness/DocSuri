from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
    EvidenceResult,
)

from .domain.models import AgentRunContext as LoopRunContext
from .domain.models import ToolCallRecord
from .models import (
    AttachmentInput,
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
    TurnPendingResult,
    TurnResult,
    TurnSuccessResult,
    _new_id,
    _utc_now,
)
from .repository import EvidenceRepository
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
# EvidenceChatService — 채팅 턴 오케스트레이션 (FR-36, FR-37)
# ---------------------------------------------------------------------------

class EvidenceChatService:
    """세션 load/create → Agent 실행 위임 → 턴 저장."""

    def __init__(
        self,
        *,
        repo: EvidenceRepository,
        runner: EvidenceTurnRunner,
        sqs_enqueue: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._repo = repo
        self._runner = runner
        self._sqs_enqueue = sqs_enqueue

    def run_turn(
        self,
        *,
        owner_id: str,
        request: EvidenceRequest,
        session_id: str | None = None,
        budget_signal: dict[str, Any] | None = None,
        request_id: str = '',
        attachment_docs: tuple[AttachmentInput, ...] = (),
        on_progress: Any = None,
    ) -> TurnResponse:
        """채팅 턴 1회 실행.

        sqs_enqueue 주입 시 비동기 경로(BR-EV-6): TurnPendingResult 즉시 반환 + SQS enqueue.
        미주입 시 동기 경로: orchestrator 직접 실행. on_progress(US-EV2/NFR-P6)는 동기
        경로에서만 의미가 있다 — 비동기 잡은 폴링으로 진행을 본다.
        """
        session = self._load_or_create_session(owner_id, request, session_id)
        turn = EvidenceTurn(
            session_id=session.session_id,
            owner_id=owner_id,
            topic=request.topic,
            # FR-38: 첨부 핸들도 턴에 영속한다 — 원시 파일이 아니라 참조 id다(INV-EV-4).
            attachments=list(request.attachments or []),
            request=request,
        )
        loop_ctx = build_run_context(
            self._repo,
            owner_id=owner_id,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            request_id=request_id,
        )

        if self._sqs_enqueue is not None:
            # 비동기 경로(BR-EV-6): pending 상태로 즉시 반환
            job_id = _new_id()
            turn.result = TurnPendingResult(job_id=job_id, started_at=_utc_now())
            turn.job_id = job_id
            self._repo.add_turn(turn)
            self._sqs_enqueue({
                'ownerId': owner_id,
                'sessionId': session.session_id,
                'turnId': turn.turn_id,
                'jobId': job_id,
                'topic': request.topic,
                'scope': (request.scope.value if request.scope else 'auto'),
                'paperIds': list(request.paperIds or []),
                'attachments': list(request.attachments or []),
                'attachmentDocs': _attachment_doc_payloads(attachment_docs),
            })
        else:
            # 동기 경로: async 분기와 달리 add_turn을 빠뜨려 저장된 턴이 0건이었다 —
            # 응답의 turnId를 이후 세션 이력(list_turns)에서 되찾을 수 없었다
            # (PR #338 리뷰 Blocking #1/FR-38).
            # 턴 행을 **먼저** 저장한다 — 트레이스가 턴을 참조하므로 루프가 도는
            # 동안 append하려면 부모 행이 있어야 한다.
            turn.result = TurnPendingResult(job_id='', started_at=_utc_now())
            self._repo.add_turn(turn)

            def _sink(record: Any) -> None:
                # 진행 표시는 advisory다(NFR-O1) — 실패가 근거형성을 막지 않는다.
                row = trace_row(record)
                try:
                    self._repo.append_trace(owner_id, turn.turn_id, row)
                except Exception:  # noqa: BLE001
                    logger.warning('evidence trace append failed', exc_info=True)
                if on_progress is not None:
                    on_progress('tool', row)

            result = self._runner.run(
                loop_ctx,
                request,
                budget_signal=budget_signal or {},
                attachments=attachment_docs,
                on_trace=_sink,
            )
            turn.result = result
            self._repo.update_turn_result(owner_id, turn.turn_id, result)

        self._repo.commit()
        return TurnResponse(
            session_id=session.session_id,
            turn_id=turn.turn_id,
            result=turn.result,
            created_at=turn.created_at,
        )

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
    """세션 목록·삭제·초기화 — BR-EV-8~10, INV-EV-1."""

    def __init__(self, *, repo: EvidenceRepository) -> None:
        self._repo = repo

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

    def reset_all(self, owner_id: str) -> None:
        """BR-EV-9: 해당 사용자 모든 세션 소프트 삭제."""
        self._repo.soft_delete_all_sessions(owner_id)
        self._repo.commit()


# ---------------------------------------------------------------------------
# EvidenceFormationService — EvidenceFormationPort 구현 (D5, U12 소비)
# ---------------------------------------------------------------------------

class EvidenceFormationService:
    """EvidenceFormationPort 구현체 — U12가 shared/ports 추상으로만 소비.

    U12는 이 클래스를 직접 import 금지. shared.ports.EvidenceFormationPort만 참조.
    순환 차단: U12 → shared/ports ← U11(구현). Trace: D5.
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
        budget_signal = getattr(ctx, 'budget_signal', {}) or {}
        owner_id = getattr(ctx, 'owner_id', '')
        request_id = getattr(ctx, 'request_id', '')

        # U12 경로는 세션을 저장하지 않는다 — 호출자의 잡이 산출물을 소유한다.
        loop_ctx = LoopRunContext(
            owner_id=owner_id,
            session_id=f'port:{owner_id or "anon"}',
            turn_id=_new_id(),
            request_id=request_id,
        )

        result = await asyncio.to_thread(
            lambda: self._runner.run(loop_ctx, request, budget_signal=budget_signal)
        )

        if isinstance(result, TurnSuccessResult):
            return result.outcome
        if isinstance(result, TurnAbstainResult):
            return result.outcome
        # TurnErrorResult → 기권으로 수렴(BR-EV-12 fail-closed)
        return EvidenceAbstainResult(state='abstain', abstainReason='llm_unavailable')


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _derive_title(topic: str) -> str:
    """첫 질문 topic에서 세션 제목 도출."""
    stripped = topic.strip()
    if len(stripped) <= _TITLE_MAX_LEN:
        return stripped
    return stripped[:_TITLE_MAX_LEN - 1] + '…'


# 멀티턴 맥락으로 되짚는 이전 턴 수 — 검색 맥락이지 대화 전체 기억이 아니다.
_PRIOR_TURNS = 3


def build_run_context(
    repo: EvidenceRepository,
    *,
    owner_id: str,
    session_id: str,
    turn_id: str,
    request_id: str = '',
) -> LoopRunContext:
    """루프 실행 컨텍스트 조립 — 동기(service)·비동기(worker) **양쪽이 이 하나를 쓴다**.

    두 벌로 두면 갈라진다: 실제로 워커 사본이 prior_topics를 빠뜨려 비동기 턴만
    멀티턴이 안 되는 상태였다. 맥락 필드가 늘어나면 여기만 고친다.

    prior 맥락은 저장 컬럼에서 읽는다 — `t.request`는 SQL 복원 턴에서 None이라
    (요청 원문은 영속하지 않는다) 그걸 읽으면 인메모리에서만 동작한다.
    """
    try:
        prior = repo.recent_turns(owner_id, session_id, _PRIOR_TURNS)
    except KeyError:
        prior = []
    paper_ids: dict[str, None] = {}
    for t in prior:
        for pid in _cited_paper_ids(t.result):
            paper_ids.setdefault(pid, None)
    return LoopRunContext(
        owner_id=owner_id,
        session_id=session_id,
        turn_id=turn_id,
        request_id=request_id,
        prior_topics=tuple(t.topic for t in prior if t.topic),
        prior_paper_ids=tuple(paper_ids),
    )


def _cited_paper_ids(result: TurnResult | None) -> tuple[str, ...]:
    """이전 턴이 실제로 인용한 논문 — "그중에서" 류 후속 질문의 좁히기 재료."""
    if not isinstance(result, TurnSuccessResult):
        return ()
    seen: dict[str, None] = {}
    for item in result.outcome.claims:
        for ref in (*item.supporting, *item.conflicting):
            seen.setdefault(ref.paperId, None)
    return tuple(seen)


def _attachment_doc_payloads(attachment_docs: tuple[AttachmentInput, ...]) -> list[dict[str, Any]]:
    from .attachments import attachment_inputs_to_payloads

    return attachment_inputs_to_payloads(attachment_docs)


def trace_row(record: ToolCallRecord) -> dict[str, Any]:
    """트레이스 저장·전송 형태 — service와 worker가 공유한다. sanitized 요약만(INV-EV-5)."""
    return {
        'seq': record.seq,
        'tool': record.tool,
        'argsSummary': record.args_summary,
        'outcome': record.outcome.value,
        'resultSummary': record.result_summary,
        'costUsd': record.cost_usd,
    }
