"""턴 실행(BLM §0) — 비용 게이트 → 루프 → 조립 → 영속.

도구를 **턴마다 새로 만든다**. 루프 상태를 쥐고 있으므로 재사용하면 세션 간
상태가 섞인다 — 격리를 조립 시점에 강제하는 편이 실행 중 검사보다 안전하다.

비용 게이트는 루프 **시작 전**에 본다(BR-EV-7). 호출을 시작한 뒤 중단하면 이미
지출한 뒤이고, U6가 저하를 알린 이유가 사라지지 않는다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
)

from .adapters.tools import (
    CorpusSearchTool,
    ExternalSearchTool,
    ExtractEvidenceTool,
    FetchPaperTool,
    ReadPaperTool,
    ViewFigureTool,
)
from .domain.assembler import assemble
from .domain.loop import LoopDeps, run_loop
from .domain.models import (
    AgentRunContext,
    BudgetConsumed,
    LoopBudget,
    LoopState,
    PaperHandle,
    PaperOrigin,
    ToolCallRecord,
)
from .models import TurnAbstainResult, TurnResult, TurnSuccessResult
from .ports.tools import ToolRegistry

log = logging.getLogger("docsuri.evidence.runner")

__all__ = ["EvidenceTurnRunner", "RunnerDeps"]

ABSTAIN_COST_DEGRADED = "cost_degraded"


@dataclass(slots=True)
class RunnerDeps:
    """턴 실행에 필요한 바깥 것들. 없는 것은 그 도구가 등록되지 않을 뿐이다."""

    llm: Any
    extractor: Any
    corpus_search: Any | None = None
    external_search: Any | None = None
    doc_models: Any | None = None
    promotion: Any | None = None
    assets: Any | None = None
    cost_guard: Any | None = None
    budget_factory: Callable[[], LoopBudget] | None = None
    max_image_bytes: int = 4_000_000


class EvidenceTurnRunner:
    def __init__(self, deps: RunnerDeps) -> None:
        self._deps = deps

    # -- 비용 -----------------------------------------------------------------
    def _cost_degraded(self, budget_signal: dict | None) -> bool:
        if (budget_signal or {}).get("state", "ok") != "ok":
            return True
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
        budget_signal: dict | None = None,
        attachments: tuple[Any, ...] = (),
        on_trace: Callable[[ToolCallRecord], None] | None = None,
    ) -> TurnResult:
        if self._cost_degraded(budget_signal):
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(
                    state="abstain", abstainReason=ABSTAIN_COST_DEGRADED
                )
            )

        state = LoopState(topic=request.topic)
        _seed_attachments(state, attachments)
        _seed_explicit(state, request)

        budget = (
            self._deps.budget_factory() if self._deps.budget_factory else _default_budget()
        )
        registry = self._build_registry(state)
        outcome = run_loop(
            state,
            LoopDeps(
                llm=self._deps.llm,
                registry=registry,
                budget=budget,
                ctx=ctx,
                on_trace=on_trace,
            ),
        )

        result = assemble(state, outcome.reason, query_used=request.topic)
        if result.state == "ok":
            return TurnSuccessResult(
                outcome=result, resolved_paper_ids=state.accumulator.cited_paper_ids
            )
        return TurnAbstainResult(outcome=result)

    def _build_registry(self, state: LoopState) -> ToolRegistry:
        """설정이 없는 도구는 등록되지 않는다 — 도구 목록이 자연 축소된다."""
        registry = ToolRegistry()
        deps = self._deps

        if deps.corpus_search is not None:
            registry.register(CorpusSearchTool(deps.corpus_search, state))
        if deps.external_search is not None:
            registry.register(ExternalSearchTool(deps.external_search, state))
        if deps.doc_models is not None:
            registry.register(
                FetchPaperTool(
                    doc_models=deps.doc_models, promotion=deps.promotion, state=state
                )
            )
            registry.register(ReadPaperTool(state))
        if deps.assets is not None:
            registry.register(
                ViewFigureTool(deps.assets, state, max_image_bytes=deps.max_image_bytes)
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


def _seed_explicit(state: LoopState, request: EvidenceRequest) -> None:
    """explicit·mixed scope의 명시 논문은 후보로 미리 올린다(BR-EV-2).

    scope는 v2에서도 **탐색 대상 집합의 제약**으로 남는다 — 질의 문구 설계만
    루프 판단으로 옮겼다.
    """
    for paper_id in getattr(request, "paperIds", None) or []:
        pid = str(paper_id)
        if state.handle(pid) is None:
            state.discovered[pid] = PaperHandle(
                paper_id=pid, record_ref=pid, origin=PaperOrigin.CORPUS
            )


def _default_budget() -> LoopBudget:
    """NFR 시작값(nfr-requirements §3). 실측 후 조정하며 변경은 문서 갱신을 동반한다."""
    from .ports.tools import (
        TOOL_CORPUS_SEARCH,
        TOOL_EXTERNAL_SEARCH,
        TOOL_EXTRACT_EVIDENCE,
        TOOL_FETCH_PAPER,
        TOOL_READ_PAPER,
        TOOL_VIEW_FIGURE,
    )

    return LoopBudget(
        max_iterations=12,
        max_tool_calls_total=30,
        max_tool_calls={
            TOOL_CORPUS_SEARCH: 5,
            TOOL_EXTERNAL_SEARCH: 3,
            TOOL_FETCH_PAPER: 3,
            TOOL_READ_PAPER: 8,
            TOOL_VIEW_FIGURE: 6,
            TOOL_EXTRACT_EVIDENCE: 8,
        },
        token_cost_limit_usd=0.50,
        consumed=BudgetConsumed(),
    )
