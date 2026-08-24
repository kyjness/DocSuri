"""결정론 픽스처 — 게이트를 통과한 뒤의 모양을 그대로 흉내낸다."""

from __future__ import annotations

from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceItem,
    SourceRef,
    SourceScope,
)

from ..domain.models import (
    AgentRunContext,
    BudgetConsumed,
    EvidenceAccumulator,
    LoopBudget,
)
from ..ports.tools import TOOL_CORPUS_SEARCH, TOOL_EXTRACT_EVIDENCE

__all__ = ["accumulator", "evidence_item", "loop_budget", "run_context"]


def evidence_item(
    statement: str = "AlphaFold2 reaches high accuracy",
    *,
    paper_id: str = "p1",
    record_ref: str | None = None,
    anchor: str | None = "s4.tbl1",
    quote: str | None = "AlphaFold2 | 92.4 | 87.0",
    anchor_type: AnchorType | None = AnchorType.table,
    source_scope: SourceScope | None = SourceScope.fulltext,
    conflicting: list[SourceRef] | None = None,
) -> EvidenceItem:
    """게이트를 통과한 근거 한 건. 게이트 자체는 `test_evidence_gate`가 본다."""
    return EvidenceItem(
        statement=statement,
        supporting=[
            SourceRef(
                paperId=paper_id,
                recordRef=record_ref or f"r-{paper_id}",
                anchor=anchor,
                quote=quote,
                anchorType=anchor_type,
                sourceScope=source_scope,
            )
        ],
        conflicting=conflicting or [],
    )


def accumulator(*items: EvidenceItem) -> EvidenceAccumulator:
    return EvidenceAccumulator(items=list(items))


def loop_budget(**overrides: Any) -> LoopBudget:
    """넉넉한 기본 예산. 한도를 보려는 테스트만 그 축을 덮어쓴다.

    생산 기본값(`EvidenceSettings`)을 쓰지 않는 것은 의도다 — 테스트가 env를 따라 흔들리면
    한도 테스트가 무엇을 재는지 알 수 없게 된다.
    """
    base: dict[str, Any] = {
        "max_iterations": 12,
        "max_tool_calls_total": 20,
        "max_tool_calls": {TOOL_CORPUS_SEARCH: 5, TOOL_EXTRACT_EVIDENCE: 8},
        "token_cost_limit_usd": 1.0,
        "consumed": BudgetConsumed(),
    }
    base.update(overrides)
    return LoopBudget(**base)


def run_context(**overrides: Any) -> AgentRunContext:
    base: dict[str, Any] = {"owner_id": "o1", "session_id": "s1", "turn_id": "t1"}
    base.update(overrides)
    return AgentRunContext(**base)
