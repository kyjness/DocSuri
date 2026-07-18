"""PBT-RA2 — 3중 예산 invariant: consumed 단조 증가, 한도 초과 시 도구 실행 없음.

설계 근거: business-rules.md BR-RA3, nfr-requirements §3(수치는 주입 — 여기선 임의값).
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from backend.modules.novelty.domain.budget import (
    BudgetDenialReason,
    begin_iteration,
    check_and_consume_tool_call,
    is_cost_exhausted,
    record_cost,
)
from backend.modules.novelty.domain.models import LoopBudget

_TOOLS = ("corpus_search", "github_search", "dataset_search", "form_evidence", "save_artifact")
_CAP_GROUPS = {
    "corpus_search": "search",
    "github_search": "search",
    "dataset_search": "search",
    "form_evidence": "form_evidence",
    "save_artifact": "save_artifact",
}


def _budget(
    max_iterations: int = 24,
    max_total: int = 40,
    caps: dict[str, int] | None = None,
    cost_limit: float = 0.5,
) -> LoopBudget:
    return LoopBudget(
        max_iterations=max_iterations,
        max_tool_calls_total=max_total,
        max_tool_calls=caps if caps is not None else {"search": 12, "form_evidence": 4},
        tool_cap_groups=_CAP_GROUPS,
        token_cost_limit_usd=cost_limit,
    )


def _snapshot(budget: LoopBudget) -> tuple:
    consumed = budget.consumed
    return (
        consumed.iterations,
        consumed.tool_calls_total,
        dict(consumed.tool_calls),
        consumed.cost_usd,
    )


@given(
    ops=st.lists(
        st.one_of(
            st.tuples(st.just("iter")),
            st.tuples(st.just("tool"), st.sampled_from(_TOOLS)),
            st.tuples(st.just("cost"), st.floats(min_value=0.0, max_value=0.2)),
        ),
        max_size=120,
    )
)
def test_pbt_ra2_consumed_monotonic_and_denial_consumes_nothing(ops) -> None:
    budget = _budget(max_iterations=10, max_total=15, cost_limit=0.4)
    previous = _snapshot(budget)
    for op in ops:
        if op[0] == "iter":
            denial = begin_iteration(budget)
        elif op[0] == "tool":
            denial = check_and_consume_tool_call(budget, op[1])
        else:
            record_cost(budget, op[1])
            denial = None
        current = _snapshot(budget)
        # 단조 증가 — 어떤 연산도 카운터를 되돌리지 않는다.
        assert current[0] >= previous[0]
        assert current[1] >= previous[1]
        assert all(current[2].get(k, 0) >= v for k, v in previous[2].items())
        assert current[3] >= previous[3]
        # 거부는 소비를 남기지 않는다.
        if denial is not None:
            assert current == previous
        previous = current
    # 한도 불변식: 소비가 상한을 넘어서 기록되지 않는다(반복·호출 수).
    assert budget.consumed.iterations <= budget.max_iterations
    assert budget.consumed.tool_calls_total <= budget.max_tool_calls_total


@given(seq=st.lists(st.sampled_from(_TOOLS), min_size=1, max_size=80))
def test_pbt_ra2_no_tool_executes_past_group_cap(seq) -> None:
    budget = _budget(max_total=1000, caps={"search": 12, "form_evidence": 4, "save_artifact": 12})
    granted: dict[str, int] = {}
    for tool in seq:
        if check_and_consume_tool_call(budget, tool) is None:
            group = _CAP_GROUPS[tool]
            granted[group] = granted.get(group, 0) + 1
    assert granted.get("search", 0) <= 12
    assert granted.get("form_evidence", 0) <= 4
    assert granted.get("save_artifact", 0) <= 12


def test_search_cap_is_combined_across_search_tools() -> None:
    # NFR §3 — 탐색류(corpus/github/dataset)는 합산 캡.
    budget = _budget(max_total=1000, caps={"search": 3})
    assert check_and_consume_tool_call(budget, "corpus_search") is None
    assert check_and_consume_tool_call(budget, "github_search") is None
    assert check_and_consume_tool_call(budget, "dataset_search") is None
    denial = check_and_consume_tool_call(budget, "corpus_search")
    assert denial is not None and denial.reason is BudgetDenialReason.TOOL_CAP_EXHAUSTED
    # 다른 캡 그룹은 독립.
    assert check_and_consume_tool_call(budget, "form_evidence") is None


def test_cost_exhaustion_denies_before_execution() -> None:
    budget = _budget(cost_limit=0.5)
    assert check_and_consume_tool_call(budget, "corpus_search") is None
    record_cost(budget, 0.5)
    assert is_cost_exhausted(budget)
    denial = check_and_consume_tool_call(budget, "corpus_search")
    assert denial is not None and denial.reason is BudgetDenialReason.COST_EXHAUSTED


def test_iteration_exhaustion_reports_reason() -> None:
    budget = _budget(max_iterations=2)
    assert begin_iteration(budget) is None
    assert begin_iteration(budget) is None
    denial = begin_iteration(budget)
    assert denial is not None and denial.reason is BudgetDenialReason.ITERATIONS_EXHAUSTED
    assert budget.consumed.iterations == 2


def test_uncapped_tool_counts_toward_total_only() -> None:
    budget = _budget(max_total=2, caps={})
    assert check_and_consume_tool_call(budget, "unknown_tool") is None
    assert check_and_consume_tool_call(budget, "unknown_tool") is None
    denial = check_and_consume_tool_call(budget, "unknown_tool")
    assert denial is not None and denial.reason is BudgetDenialReason.TOOL_CALLS_EXHAUSTED
