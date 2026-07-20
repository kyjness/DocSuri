"""3중 예산 집행(BR-RA3, FR-45) — 검사·소비 기록의 유일한 경로.

루프는 act 직전 정확히 한 번 `check_and_consume_tool_call`을 호출한다(BLM §2).
consumed는 단조 증가만 한다(PBT-RA2) — 거부는 소비를 남기지 않고, 성공한 소비는
되돌리지 않는다. 수치 한도는 설정에서 주입되며 이 모듈은 상수를 갖지 않는다.
비용 판정의 단일 권위는 U6 get_budget_state()이고 token_cost_limit_usd는
그 배분 내 per-job 상한이다 — novelty 전용 CostGuard를 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .models import LoopBudget

__all__ = [
    "BudgetDenial",
    "BudgetDenialReason",
    "begin_iteration",
    "check_and_consume_tool_call",
    "is_cost_exhausted",
    "record_cost",
]


class BudgetDenialReason(StrEnum):
    ITERATIONS_EXHAUSTED = "iterations_exhausted"
    TOOL_CALLS_EXHAUSTED = "tool_calls_exhausted"
    TOOL_CAP_EXHAUSTED = "tool_cap_exhausted"
    COST_EXHAUSTED = "cost_exhausted"


@dataclass(frozen=True, slots=True)
class BudgetDenial:
    """기계 판독 가능한 거부 사유 — ToolCallRecord.outcome=budget_denied의 근거."""

    reason: BudgetDenialReason
    detail: str


def begin_iteration(budget: LoopBudget) -> BudgetDenial | None:
    """한 턴(observe→decide→act) 시작 — 반복 한도 검사 후 소비."""
    consumed = budget.consumed
    if consumed.iterations >= budget.max_iterations:
        return BudgetDenial(
            BudgetDenialReason.ITERATIONS_EXHAUSTED,
            f"iterations {consumed.iterations}/{budget.max_iterations}",
        )
    consumed.iterations += 1
    return None


def check_and_consume_tool_call(budget: LoopBudget, tool_name: str) -> BudgetDenial | None:
    """act 직전 1회 호출 — 총 상한·캡 그룹 상한·비용 상한 검사 후 호출 수 소비.

    거부 시 어떤 카운터도 증가하지 않는다(도구는 실행되지 않으므로)."""
    consumed = budget.consumed
    if consumed.tool_calls_total >= budget.max_tool_calls_total:
        return BudgetDenial(
            BudgetDenialReason.TOOL_CALLS_EXHAUSTED,
            f"tool calls {consumed.tool_calls_total}/{budget.max_tool_calls_total}",
        )
    cap_group = budget.tool_cap_groups.get(tool_name)
    if cap_group is not None and cap_group in budget.max_tool_calls:
        group_used = sum(
            count
            for tool, count in consumed.tool_calls.items()
            if budget.tool_cap_groups.get(tool) == cap_group
        )
        cap = budget.max_tool_calls[cap_group]
        if group_used >= cap:
            return BudgetDenial(
                BudgetDenialReason.TOOL_CAP_EXHAUSTED,
                f"{cap_group} {group_used}/{cap}",
            )
    if is_cost_exhausted(budget):
        return BudgetDenial(
            BudgetDenialReason.COST_EXHAUSTED,
            f"cost {consumed.cost_usd:.4f}/{budget.token_cost_limit_usd:.4f} USD",
        )
    consumed.tool_calls_total += 1
    consumed.tool_calls[tool_name] = consumed.tool_calls.get(tool_name, 0) + 1
    return None


def record_cost(budget: LoopBudget, cost_usd: float) -> None:
    """실행 후 비용 계상 — 음수 금지(단조 증가)."""
    if cost_usd < 0:
        raise ValueError("cost_usd must be non-negative")
    budget.consumed.cost_usd += cost_usd


def is_cost_exhausted(budget: LoopBudget) -> bool:
    return budget.consumed.cost_usd >= budget.token_cost_limit_usd
