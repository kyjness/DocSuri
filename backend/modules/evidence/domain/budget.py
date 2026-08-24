"""3중 한도 집행(FR-45, BR-EV-13) — 검사·소비 기록의 유일한 경로.

루프는 act 직전 정확히 한 번 `check_and_consume_tool_call`을 호출한다. 소비는
단조 증가만 한다(PBT-EV-7) — 거부는 소비를 남기지 않고, 성공한 소비는 되돌리지
않는다. **검사는 도구 실행 전**이다: 실행 후 차감은 초과를 이미 지출한 뒤다.

수치는 설정에서 주입된다. 이 모듈은 상수를 갖지 않는다.
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
    """기계 판독 가능한 거부 사유 — `ToolCallRecord.outcome=budget_denied`의 근거."""

    reason: BudgetDenialReason
    detail: str


def begin_iteration(budget: LoopBudget) -> BudgetDenial | None:
    """한 회차(observe→decide→act) 시작 — 비용·반복 한도 검사 후 소비.

    비용을 **여기서도** 본다. 도구 캡 거부가 턴을 끝내지 않고 루프로 돌아오게 되면서,
    캡에 막힌 도구를 계속 제안하는 모델은 유료 decide 호출을 반복 상한까지 쓸 수 있게
    됐다 — `check_and_consume_tool_call`은 캡 검사가 비용 검사보다 앞이라 비용 초과를 못
    보고, decide 자체에는 비용 검사가 없었다.
    """
    consumed = budget.consumed
    if is_cost_exhausted(budget):
        return BudgetDenial(
            BudgetDenialReason.COST_EXHAUSTED,
            f"cost ${consumed.cost_usd:.2f}/${budget.token_cost_limit_usd:.2f}",
        )
    if consumed.iterations >= budget.max_iterations:
        return BudgetDenial(
            BudgetDenialReason.ITERATIONS_EXHAUSTED,
            f"iterations {consumed.iterations}/{budget.max_iterations}",
        )
    consumed.iterations += 1
    return None


def check_and_consume_tool_call(budget: LoopBudget, tool_name: str) -> BudgetDenial | None:
    """act 직전 1회 — 총 상한·도구별 캡·비용 상한 검사 후 호출 수 소비.

    거부 시 어떤 카운터도 증가하지 않는다(도구가 실행되지 않으므로).
    """
    consumed = budget.consumed
    if consumed.tool_calls_total >= budget.max_tool_calls_total:
        return BudgetDenial(
            BudgetDenialReason.TOOL_CALLS_EXHAUSTED,
            f"tool calls {consumed.tool_calls_total}/{budget.max_tool_calls_total}",
        )
    cap = budget.max_tool_calls.get(tool_name)
    if cap is not None:
        used = consumed.tool_calls.get(tool_name, 0)
        if used >= cap:
            # 도구별 캡이 없으면 한 도구가 예산을 독식한다 — novelty 실측에서
            # 검색 캡 소진으로 필수 산출물을 못 채우고 partial 종료한 형태다.
            return BudgetDenial(
                BudgetDenialReason.TOOL_CAP_EXHAUSTED, f"{tool_name} {used}/{cap}"
            )
    if is_cost_exhausted(budget):
        return BudgetDenial(
            BudgetDenialReason.COST_EXHAUSTED,
            f"cost {consumed.cost_usd:.4f}/{budget.token_cost_limit_usd:.4f} USD",
        )
    consumed.tool_calls_total += 1
    consumed.tool_calls[tool_name] = consumed.tool_calls.get(tool_name, 0) + 1
    return None


def record_cost(budget: LoopBudget, cost_usd: float | None) -> None:
    """실행 후 비용 계상 — 음수 금지(단조 증가)."""
    if cost_usd is None:
        return
    if cost_usd < 0:
        raise ValueError("cost_usd must be non-negative")
    budget.consumed.cost_usd += cost_usd


def is_cost_exhausted(budget: LoopBudget) -> bool:
    return budget.consumed.cost_usd >= budget.token_cost_limit_usd
