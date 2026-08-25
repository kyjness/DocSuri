"""턴 실행(BLM §0) — 비용 게이트 → 루프 → 조립 → 영속.

도구를 **턴마다 새로 만든다**. 루프 상태를 쥐고 있으므로 재사용하면 세션 간
상태가 섞인다 — 격리를 조립 시점에 강제하는 편이 실행 중 검사보다 안전하다.

비용 게이트는 루프 **시작 전**에 본다(BR-EV-7). 호출을 시작한 뒤 중단하면 이미
지출한 뒤이고, U6가 저하를 알린 이유가 사라지지 않는다.

그래프는 프로세스당 한 번 컴파일된 것을 **받아서** 쓴다(deps는 context로 가므로 턴마다 다시
만들 이유가 없다). 체크포인트 조회·정리는 `checkpoints.TurnCheckpoints`가 소유한다 — 러너는
돌리기만 한다.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AbstainReason,
    EvidenceAbstainResult,
    EvidenceRequest,
)

from .adapters.tools import (
    CorpusSearchTool,
    ExtractEvidenceTool,
    FetchPaperTool,
    LiveLookupTool,
    ReadPaperTool,
    ViewFigureTool,
)
from .domain.loop import LoopDeps, compile_loop_graph, run_loop
from .domain.models import (
    AgentRunContext,
    LoopBudget,
    LoopState,
    PaperHandle,
    PaperOrigin,
    TerminationReason,
    ToolCallRecord,
)
from .models import TurnAbstainResult, TurnResult, to_turn_result
from .ports.tools import ToolRegistry

log = logging.getLogger("docsuri.evidence.runner")

# 사적 문서 네임스페이스 — 코퍼스 논문 id로 위장해 들어올 수 없다(_seed_explicit).
_RESERVED_ID_PREFIXES = re.compile(r"^(?:userdoc|upload|attachment):", re.IGNORECASE)

__all__ = ["EvidenceTurnRunner", "RunnerDeps"]

ABSTAIN_COST_DEGRADED = AbstainReason.cost_degraded


@dataclass(slots=True)
class RunnerDeps:
    """턴 실행에 필요한 바깥 것들. 없는 것은 그 도구가 등록되지 않을 뿐이다."""

    llm: Any
    extractor: Any
    # 판단 층(§4.2). None이면 `answer` 노드가 아무 것도 안 하고 마감이 결정론
    # 이어붙이기로 떨어진다 — 다른 선택 의존성과 같은 규칙이다.
    answer: Any | None = None
    corpus_search: Any | None = None
    live_lookup: Any | None = None
    doc_models: Any | None = None
    promotion: Any | None = None
    # 백그라운드 색인 큐(§2.6 4단계). 없으면 코퍼스가 안 자랄 뿐 턴은 그대로 돈다.
    index_queue: Any | None = None
    assets: Any | None = None
    cost_guard: Any | None = None
    budget_factory: Callable[[], LoopBudget] | None = None
    max_image_bytes: int = 4_000_000


class EvidenceTurnRunner:
    def __init__(self, deps: RunnerDeps, *, checkpoints: Any | None = None) -> None:
        self._deps = deps
        # 체크포인트 객체가 그래프를 소유한다(§3.1) — 없으면 체크포인터 없이 컴파일하고
        # 이어가기가 자연히 꺼진다. `graph=`를 따로 받던 인자는 지웠다: `checkpoints=`를
        # 더한 뒤 호출자가 하나도 안 남았는데 세 갈래 `None` 조정만 남아 있었다.
        self._checkpoints = checkpoints
        self._graph = checkpoints.graph if checkpoints is not None else compile_loop_graph(None)

    # -- 비용 -----------------------------------------------------------------
    def _cost_degraded(self) -> bool:
        guard = self._deps.cost_guard
        if guard is None:
            return False
        try:
            from docsuri_ops.cost_guard import is_cost_critical

            return is_cost_critical(guard.get_budget_state())
        except Exception:  # noqa: BLE001 — 게이트 조회 실패로 턴을 막지 않는다
            log.warning("evidence cost gate lookup failed", exc_info=True)
            return False

    # -- 실행 -----------------------------------------------------------------
    def run(
        self,
        ctx: AgentRunContext,
        request: EvidenceRequest,
        *,
        attachments: tuple[Any, ...] = (),
        on_trace: Callable[[ToolCallRecord], None] | None = None,
        should_stop: Callable[[], TerminationReason | None] | None = None,
    ) -> TurnResult:
        if self._cost_degraded():
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state="abstain", abstainReason=ABSTAIN_COST_DEGRADED
                )
            )

        state = LoopState(topic=request.topic)
        _seed_attachments(state, attachments)
        scope = _effective_scope(request)
        _seed_explicit(state, request, scope)
        _seed_continuation(state, self._checkpoints, ctx, scope)

        budget = (self._deps.budget_factory or _default_budget)()
        registry = self._build_registry(state, scope=scope)
        outcome = run_loop(
            state,
            LoopDeps(
                llm=self._deps.llm,
                registry=registry,
                budget=budget,
                ctx=ctx,
                on_trace=on_trace,
                should_stop=should_stop,
                answer=self._deps.answer,
            ),
            graph=self._graph,
        )
        _queue_for_indexing(state, self._deps.index_queue)
        return to_turn_result(state, outcome.reason, query_used=request.topic)

    def _build_registry(self, state: LoopState, *, scope: str) -> ToolRegistry:
        """설정이 없는 도구는 등록되지 않는다 — 도구 목록이 자연 축소된다.

        **explicit scope는 검색 도구를 아예 등록하지 않는다**(BR-EV-2, PBT-EV-4).
        "명시 집합만 사용, 자동 검색 금지"를 프롬프트 당부가 아니라 구조로 강제한다 —
        도구가 목록에 없으면 모델이 그 경로를 시도할 방법 자체가 없다. 명시 논문의
        본문 확보(fetch/read)와 근거 추출은 그대로 열려 있다.
        """
        registry = ToolRegistry()
        deps = self._deps
        searchable = scope != "explicit"

        if searchable and deps.corpus_search is not None:
            registry.register(CorpusSearchTool(deps.corpus_search, state))
        if searchable and deps.live_lookup is not None:
            registry.register(LiveLookupTool(deps.live_lookup, state))
        if deps.doc_models is not None:
            registry.register(
                FetchPaperTool(
                    doc_models=deps.doc_models, promotion=deps.promotion, state=state
                )
            )
            registry.register(ReadPaperTool(state))
        if deps.assets is not None:
            registry.register(
                ViewFigureTool(deps.assets, max_image_bytes=deps.max_image_bytes)
            )
        registry.register(ExtractEvidenceTool(deps.extractor, state))
        return registry


def _seed_attachments(state: LoopState, attachments: tuple[Any, ...]) -> None:
    """첨부는 이미 확보된 문서다 — 검색 없이 바로 확인 대상이 된다(US-EV4)."""
    for doc in attachments:
        paper_id = getattr(doc, "paper_id", None) or f"attachment:{getattr(doc, 'name', '')}"
        state.examine(
            PaperHandle(
                paper_id=paper_id,
                record_ref=getattr(doc, "record_ref", None) or paper_id,
                origin=PaperOrigin.ATTACHMENT,
                title=getattr(doc, "name", "") or "첨부 문서",
                doc_model=getattr(doc, "doc_model", None),
                abstract_text=getattr(doc, "text", "") or "",
            )
        )


def _seed_continuation(
    state: LoopState, checkpoints: Any | None, ctx: AgentRunContext, scope: str
) -> None:
    """직전 턴이 찾아 둔 논문을 새 턴의 **후보**로 옮긴다(설계 §3.4 이어가기).

    **판정은 모델이, 이식은 기계다.** 설계 초안은 모델이 `continuation: true`를 선언하면
    옮긴다고 적었으나 그럴 자리가 없다 — 이식은 루프가 돌기 **전**이라 모델은 아직 아무것도
    못 봤다. 그래서 씨앗은 무조건 심고 관찰의 "확인 대기 논문"에 실어 모델이 쓸지 고르게
    한다. explicit scope에서 이미 그 자리가 그렇게 동작한다.

    **`discovered`로 심는다 — `papers`가 아니다.** `examined`는 `len(self.papers)`이므로
    확인분으로 심으면 **이번 턴이 열어보지도 않은 논문이 "확인함"으로 세어지고**, 화면의
    "후보 N편 중 M편 확인"이 그 수를 그대로 쓴다. 설계 §3.4가 씨앗을 "관찰의 **확인 대기
    논문**에 실어"라고 적은 것이 곧 이 버킷이다.

    이식은 `prior_turn_id`만 있으면 도므로 새 주제 턴(§2.5의 "QLoRA는?")에도 심긴다 —
    설계가 그 턴에서 이전 논문이 **후보로 남는다**고 적은 것과 같다.

    이미 있는 id는 덮지 않는다: 첨부·명시 논문이 먼저 심어졌고 그쪽이 더 구체적이다
    (본문·소유권이 확인된 핸들).
    """
    if checkpoints is None or scope == "explicit" or not ctx.prior_turn_id:
        return
    try:
        seeds = checkpoints.seeds_from(ctx.prior_turn_id)
    except Exception:  # noqa: BLE001 — 씨앗을 못 읽는 것이 새 턴을 깨뜨리면 안 된다
        log.warning("evidence: continuation seeds unavailable", exc_info=True)
        return
    for handle in seeds:
        if state.handle(handle.paper_id) is None:
            state.discovered[handle.paper_id] = handle


def _queue_for_indexing(state: LoopState, queue: Any | None) -> None:
    """실시간 조회로 찾아 **실제로 확인한** 논문을 백그라운드 색인에 올린다(설계 §2.6 4단계).

    이것이 "쓸수록 코퍼스가 그쪽으로 자란다"의 구현이다. 없으면 같은 논문을 매 턴 실시간으로
    다시 조회하고 코퍼스는 영원히 자라지 않는다 — 승격(`fetch_paper`)만으로는 본문만 생기고
    색인은 안 된다(U1의 `BUILD_DOC_MODEL`은 "이미 색인된 논문"을 위한 잡이다).

    **확인한 것만 올린다.** 검색 히트를 전부 올리면 질의 한 번에 열 편이 큐로 가고, 그중
    모델이 열어보지도 않은 논문이 대부분이다.

    **한 번에 보낸다.** 논문마다 부르면 확인 논문 수만큼 SQS 왕복이 응답 반환 앞에 얹히고,
    실패하면 botocore 재시도가 메시지마다 돈다 — 이 턴의 답이 기다리지 않아도 되는 일이다.

    실패는 전부 삼킨다 — 색인은 **다음** 질문을 위한 것이라 이 턴의 답에 영향이 없다.
    """
    if queue is None:
        return
    # 코퍼스 논문은 이미 색인돼 있고, 첨부는 사적 문서라 코퍼스에 넣지 않는다.
    paper_ids = [h.paper_id for h in state.papers.values() if h.origin is PaperOrigin.EXTERNAL]
    if not paper_ids:
        return
    try:
        queue.enqueue_index(paper_ids)
    except Exception:  # noqa: BLE001 — 색인 요청 실패가 답을 깨뜨리면 안 된다
        log.warning("evidence: index enqueue failed (%d papers)", len(paper_ids), exc_info=True)


def _effective_scope(request: EvidenceRequest) -> str:
    value = getattr(request, "scope", None)
    return str(getattr(value, "value", value) or "auto")


def _seed_explicit(state: LoopState, request: EvidenceRequest, scope: str) -> None:
    """explicit·mixed scope의 명시 논문은 후보로 미리 올린다(BR-EV-2).

    scope는 v2에서도 **탐색 대상 집합의 제약**으로 남는다 — 질의 문구 설계만
    루프 판단으로 옮겼다.

    `auto`에서는 무시한다 — 계약(`evidence.schema.json`의 paperIds 설명)과
    BR-EV-2가 정한 바다. 씨앗으로 올리면 사용자가 고르지도 않은 논문이 확인
    대상 수치(candidates)에 섞인다.

    호출자가 준 id는 **코퍼스 논문 id로만** 받는다. 업로드 문서 네임스페이스
    (`userdoc:`)는 코퍼스 검색으로 도달할 수 없는 사적 영역이라, 여기로 들어오면
    본인 문서라도 첨부 경로(소유권이 확인되는 경로)를 우회하게 된다.
    """
    if scope == "auto":
        return
    for paper_id in getattr(request, "paperIds", None) or []:
        pid = str(paper_id)
        if _RESERVED_ID_PREFIXES.match(pid):
            log.warning("evidence: rejected reserved-namespace paperId")
            continue
        if state.handle(pid) is None:
            state.discovered[pid] = PaperHandle(
                paper_id=pid, record_ref=pid, origin=PaperOrigin.CORPUS
            )


def _default_budget() -> LoopBudget:
    """`budget_factory`가 안 주어졌을 때의 예산 — **정의는 `EvidenceSettings`에만 있다**.

    종전에는 이 함수가 settings의 아홉 수치를 통째로 복제하고 "함께 바꾼다"는 주석으로
    맞춰뒀다. `cap_fetch_paper`를 3→8로 올릴 때 두 곳을 다 고쳐야 한다는 사실이 주석에만
    있었던 것인데, 주석은 기구가 아니다. 이제 env 오버라이드도 이쪽으로 따라온다.
    """
    from .settings import EvidenceSettings

    return EvidenceSettings.from_env().build_loop_budget()
