"""루프 코어(BLM §1) — 도구 대역 위의 결정론 실행 + 상한 불변식(PBT-EV-7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceItem,
    SourceRef,
    SourceScope,
)
from hypothesis import given, settings
from hypothesis import strategies as st
from langgraph.errors import GraphRecursionError

from backend.modules.evidence.domain.loop import (
    _NO_EVIDENCE_NOTE,
    LoopDeps,
    LoopRun,
    _recursion_limit,
    compile_loop_graph,
    run_loop,
)
from backend.modules.evidence.domain.models import (
    AgentRunContext,
    BudgetConsumed,
    EvidenceAccumulator,
    LoopBudget,
    LoopState,
    PaperHandle,
    PaperOrigin,
    TerminationReason,
    ToolCallOutcome,
    ToolCallRecord,
)
from backend.modules.evidence.ports.llm import (
    LlmDecision,
    LlmUnavailable,
    TerminationProposal,
    ToolCallProposal,
)
from backend.modules.evidence.ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_EXTRACT_EVIDENCE,
    ImageAttachment,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)


@dataclass
class FakeTool:
    name: str
    result: ToolResult = field(default_factory=lambda: ToolResult(ok=True, content={"hits": 1}))
    # 호출마다 다른 결과가 필요할 때(예: 첫 호출만 이미지) 순서대로 소비된다.
    results: list[ToolResult] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)
    raises: Exception | None = None

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.name, parameters={"type": "object"})

    def invoke(self, args: dict[str, Any], ctx) -> ToolResult:
        self.calls.append(args)
        if self.raises is not None:
            raise self.raises
        if self.results:
            return self.results.pop(0)
        return self.result


@dataclass
class ScriptedLlm:
    """미리 정한 결정을 순서대로 돌려준다 — 소진되면 종료를 제안한다."""

    script: list[Any]
    observations: list[Any] = field(default_factory=list)
    raises: Exception | None = None

    def decide(self, observation, tools) -> LlmDecision:
        self.observations.append(observation)
        if self.raises is not None:
            raise self.raises
        if not self.script:
            return LlmDecision(proposal=TerminationProposal(note="done"))
        return LlmDecision(proposal=self.script.pop(0), cost_estimate_usd=0.001)


def _budget(**overrides) -> LoopBudget:
    base = {
        "max_iterations": 12,
        "max_tool_calls_total": 20,
        "max_tool_calls": {TOOL_CORPUS_SEARCH: 5, TOOL_EXTRACT_EVIDENCE: 8},
        "token_cost_limit_usd": 1.0,
        "consumed": BudgetConsumed(),
    }
    base.update(overrides)
    return LoopBudget(**base)


def _deps(llm, registry, budget=None, **kwargs) -> LoopDeps:
    return LoopDeps(
        llm=llm,
        registry=registry,
        budget=budget or _budget(),
        ctx=AgentRunContext(owner_id="o1", session_id="s1", turn_id="t1"),
        **kwargs,
    )


def _registry(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _evidence_item() -> EvidenceItem:
    return EvidenceItem(
        statement="AlphaFold2 reaches high accuracy",
        supporting=[
            SourceRef(
                paperId="p1",
                recordRef="r1",
                anchor="s4.tbl1",
                quote="AlphaFold2 | 92.4 | 87.0",
                anchorType=AnchorType.table,
                sourceScope=SourceScope.fulltext,
            )
        ],
        conflicting=[],
    )


def _state_with_evidence(topic="q") -> LoopState:
    """근거가 이미 하나 쌓인 상태 — 종료 제안이 수용될 수 있는 최소 조건."""
    state = LoopState(topic=topic)
    state.accumulator = EvidenceAccumulator(items=[_evidence_item()])
    return state


# --- 종료 판정 ---------------------------------------------------------------


def test_termination_is_rejected_when_no_evidence_was_accumulated():
    """INV-EV-2 — 에이전트가 '충분하다'고 해도 근거 0건이면 정상 종료가 아니다."""
    llm = ScriptedLlm(script=[TerminationProposal(), TerminationProposal()])

    outcome = run_loop(LoopState(topic="q"), _deps(llm, _registry()))

    assert outcome.reason is TerminationReason.NO_EVIDENCE
    # 거부 사유가 관찰에 실려 다음 판단이 달라진다.
    assert any(note for note in outcome.notes if "근거" in note)
    assert len(llm.observations) >= 2


def test_termination_is_accepted_once_evidence_exists():
    llm = ScriptedLlm(script=[TerminationProposal(note="충분")])

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry()))

    assert outcome.reason is TerminationReason.SUFFICIENT


def test_llm_failure_terminates_as_fatal_without_masking_it_as_abstain():
    llm = ScriptedLlm(script=[], raises=LlmUnavailable("boom"))

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry()))

    assert outcome.reason is TerminationReason.FATAL_ERROR
    assert "llm_unavailable" in (outcome.detail or "")


# --- 예산 -------------------------------------------------------------------


def test_iteration_cap_ends_the_loop():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 50)
    budget = _budget(max_iterations=3)

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry(tool), budget))

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert budget.consumed.iterations == 3
    assert len(tool.calls) == 3


def test_a_dropped_parallel_call_reaches_the_model_not_just_the_dataclass():
    """어댑터가 `decision_note`에 폐기 목록을 담아도, 루프가 그걸 읽지 않으면 아무 데도
    안 남는다(설정만 하고 소비처가 없던 상태). 다음 턴 관찰에 실려야 모델이 다시 요청할 수
    있고, 그래야 "모델이 시킨 일이 조용히 사라지는" 상태가 실제로 닫힌다."""
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(
        script=[
            ToolCallProposal(
                TOOL_CORPUS_SEARCH,
                {"query": "q"},
                decision_note="dropped parallel calls: read_paper",
            )
        ]
    )

    run_loop(_state_with_evidence(), _deps(llm, _registry(tool)))

    # 첫 턴의 관찰에는 없고(그때 막 생겼다), 다음 decide의 관찰에 실려야 한다.
    assert len(llm.observations) >= 2
    notes = " ".join(llm.observations[-1].notes)
    assert "read_paper" in notes


def test_per_tool_cap_stops_one_tool_from_eating_the_budget():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 50)
    budget = _budget(max_tool_calls={TOOL_CORPUS_SEARCH: 2})

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry(tool), budget))

    # 상한을 넘겨 부르지 못한다. 끝난 이유는 이 도구의 상한이 아니라 **반복 상한**이다 —
    # 모델이 같은 도구만 계속 고집했기 때문이고, 그래야 다른 도구를 고를 여지가 남는다.
    assert len(tool.calls) == 2
    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert budget.consumed.iterations == budget.max_iterations


def test_tool_cap_denial_leaves_the_other_tools_usable():
    """도구 하나가 상한을 다 쓴 것은 턴의 예산 소진이 아니다.

    2026-08-24 실측 회귀: `fetch_paper` 3/3에 막힌 턴이 논문 3편을 확보한 채
    `extract_evidence`를 한 번도 못 부르고 근거 0건으로 기권했다. 예외도 ERROR 로그도
    없어 정상적인 보수적 동작처럼 보인다 — 그래서 카운터가 아니라 이 테스트로 잡는다.
    """
    capped = FakeTool(TOOL_CORPUS_SEARCH)
    other = FakeTool(TOOL_EXTRACT_EVIDENCE)
    llm = ScriptedLlm(
        script=[
            ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}),
            ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q2"}),  # 거부된다
            ToolCallProposal(TOOL_EXTRACT_EVIDENCE, {"focus": "f"}),
        ]
    )
    budget = _budget(max_tool_calls={TOOL_CORPUS_SEARCH: 1, TOOL_EXTRACT_EVIDENCE: 8})

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry(capped, other), budget))

    assert len(capped.calls) == 1
    assert len(other.calls) == 1, "상한에 막힌 뒤에도 남은 도구는 불릴 수 있어야 한다"
    assert outcome.reason is TerminationReason.SUFFICIENT


def test_tool_cap_denial_tells_the_model_which_tool_is_gone():
    """거부 사실이 관찰에 실려야 모델이 다른 수를 고른다 — 안 실으면 같은 도구를 반복한다."""
    capped = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 3)
    budget = _budget(max_tool_calls={TOOL_CORPUS_SEARCH: 1})

    run_loop(_state_with_evidence(), _deps(llm, _registry(capped), budget))

    notes = [note for obs in llm.observations for note in obs.notes]
    assert any(TOOL_CORPUS_SEARCH in note and "상한" in note for note in notes)


def test_global_tool_budget_still_ends_the_turn():
    """전역 소진은 여전히 종료다 — 상한 하나만 예외로 만든 것이지 예산을 무르지 않았다."""
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 10)
    budget = _budget(max_tool_calls_total=2, max_tool_calls={TOOL_CORPUS_SEARCH: 9})

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry(tool), budget))

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert budget.consumed.iterations < budget.max_iterations, "반복이 아니라 도구 총량이 끊었다"


def test_budget_denied_is_traced():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 5)
    budget = _budget(max_tool_calls={TOOL_CORPUS_SEARCH: 1})
    state = _state_with_evidence()

    run_loop(state, _deps(llm, _registry(tool), budget))

    assert state.trace[-1].outcome is ToolCallOutcome.BUDGET_DENIED
    assert state.trace[-1].tool == TOOL_CORPUS_SEARCH


def test_denied_call_consumes_nothing():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})] * 5)
    budget = _budget(max_tool_calls={TOOL_CORPUS_SEARCH: 1})

    run_loop(_state_with_evidence(), _deps(llm, _registry(tool), budget))

    assert budget.consumed.tool_calls[TOOL_CORPUS_SEARCH] == 1


# --- 트레이스·오류 처리 -------------------------------------------------------


def test_every_executed_call_is_traced_once():
    """BR-EV-16 — 실행된 도구 호출과 트레이스는 1:1."""
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": f"q{i}"})
                              for i in range(3)])
    state = _state_with_evidence()

    run_loop(state, _deps(llm, _registry(tool)))

    executed = [r for r in state.trace if r.outcome is ToolCallOutcome.OK]
    assert len(executed) == len(tool.calls) == 3
    assert [r.seq for r in state.trace] == list(range(1, len(state.trace) + 1))


def test_trace_carries_the_call_arguments():
    """결과만 보이면 모델이 같은 질의를 반복한다(⑤3 실측 교훈)."""
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "protein folding"})])
    state = _state_with_evidence()

    run_loop(state, _deps(llm, _registry(tool)))

    assert "protein folding" in state.trace[0].args_summary


def test_tool_exception_does_not_break_the_turn():
    tool = FakeTool(TOOL_CORPUS_SEARCH, raises=RuntimeError("upstream down"))
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})])
    state = _state_with_evidence()

    outcome = run_loop(state, _deps(llm, _registry(tool)))

    assert outcome.reason is TerminationReason.SUFFICIENT
    assert state.trace[0].outcome is ToolCallOutcome.ERROR


def test_unknown_tool_is_refused_without_consuming_budget():
    llm = ScriptedLlm(script=[ToolCallProposal("delete_everything", {})])
    budget = _budget()
    state = _state_with_evidence()

    run_loop(state, _deps(llm, _registry(), budget))

    assert budget.consumed.tool_calls_total == 0
    assert state.trace[0].outcome is ToolCallOutcome.ERROR


def test_trace_sink_failure_does_not_break_the_loop():
    def explode(_record):
        raise RuntimeError("sink down")

    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})])

    outcome = run_loop(_state_with_evidence(), _deps(llm, _registry(tool), on_trace=explode))

    assert outcome.reason is TerminationReason.SUFFICIENT


# --- 이미지 1회성 -------------------------------------------------------------


def test_images_are_consumed_after_one_decide():
    """BR-EV-17 — 남기면 윈도우에서 밀려날 때까지 매 턴 재전송된다."""
    image = ImageAttachment(media_type="image/webp", data_b64="AAAA", asset_id="fig1")
    tool = FakeTool(
        "view_figure",
        results=[
            ToolResult(ok=True, content={"assetId": "fig1"}, images=(image,)),
            ToolResult(ok=True, content={"assets": []}),
        ],
    )
    llm = ScriptedLlm(script=[
        ToolCallProposal("view_figure", {"record_ref": "r1", "asset_id": "fig1"}),
        ToolCallProposal("view_figure", {"record_ref": "r1"}),
    ])

    run_loop(_state_with_evidence(), _deps(llm, _registry(tool)))

    # 이미지를 실은 관찰은 정확히 1회 — 조회 직후 한 번만 전달되고 소비된다.
    with_images = [
        obs for obs in llm.observations
        if any(view.images for view in obs.recent_results)
    ]
    assert len(with_images) == 1


# --- 상한 불변식 (PBT-EV-7) ---------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(
    proposals=st.lists(
        st.sampled_from([TOOL_CORPUS_SEARCH, TOOL_EXTRACT_EVIDENCE, "unknown_tool"]),
        min_size=0,
        max_size=40,
    ),
    iteration_cap=st.integers(min_value=1, max_value=8),
    tool_cap=st.integers(min_value=1, max_value=5),
)
def test_pbt_ev7_tool_calls_never_exceed_caps(proposals, iteration_cap, tool_cap):
    """PBT-EV-7 — 어떤 제안 열에도 실행 수가 캡을 넘지 않는다."""
    tools = [FakeTool(TOOL_CORPUS_SEARCH), FakeTool(TOOL_EXTRACT_EVIDENCE)]
    budget = _budget(
        max_iterations=iteration_cap,
        max_tool_calls_total=iteration_cap * 2,
        max_tool_calls={TOOL_CORPUS_SEARCH: tool_cap, TOOL_EXTRACT_EVIDENCE: tool_cap},
    )
    llm = ScriptedLlm(script=[ToolCallProposal(name, {"query": "q"}) for name in proposals])

    run_loop(_state_with_evidence(), _deps(llm, _registry(*tools), budget))

    assert budget.consumed.iterations <= iteration_cap
    assert budget.consumed.tool_calls_total <= budget.max_tool_calls_total
    for tool in tools:
        assert len(tool.calls) <= tool_cap


# --- 관찰 내용 ---------------------------------------------------------------


def test_observation_reports_progress_for_the_depth_judgement():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})])
    state = _state_with_evidence()
    state.papers["p1"] = PaperHandle(
        paper_id="p1", record_ref="r1", origin=PaperOrigin.CORPUS, abstract_text="abs"
    )

    run_loop(state, _deps(llm, _registry(tool)))

    first = llm.observations[0]
    assert first.evidence_count == 1
    assert first.papers[0].scope == "abstract"
    assert first.iterations_left >= 0


# --- 실행 계약 — 그래프 이전 전후로 같아야 하는 것 ------------------------------


def test_other_llm_errors_propagate_unwrapped():
    """`LlmUnavailable`만 기권으로 흡수한다 — 그 밖의 예외는 **원형 그대로** 밖으로 나간다.

    service.py의 catch-all이 그 예외를 받아 턴을 error로 닫으므로, 여기서 래핑되면
    (ExceptionGroup 등) 상위 진단이 달라진다.
    """
    llm = ScriptedLlm(script=[], raises=RuntimeError("boom"))
    state = _state_with_evidence()

    with pytest.raises(RuntimeError) as exc_info:
        run_loop(state, _deps(llm, _registry()))

    assert type(exc_info.value) is RuntimeError
    assert exc_info.value.args == ("boom",)
    assert state.termination_reason is None


def test_loop_mutates_the_callers_state_in_place():
    """runner는 `outcome.state`가 아니라 **자기 state 객체**를 조립에 넘긴다 — 복사가
    끼어들면 트레이스·근거가 조용히 사라진다. 동일성(`is`)으로 잡는다."""
    seen: list = []
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})])
    state = _state_with_evidence()

    outcome = run_loop(state, _deps(llm, _registry(tool), on_trace=seen.append))

    assert outcome.state is state
    assert state.termination_reason is outcome.reason
    assert len(seen) == 1 and seen[0] is state.trace[0]


# --- 그래프 상한 (recursion_limit) --------------------------------------------
#
# LangGraph 기본 상한은 25스텝이고 기본 예산(12회)은 2·12+2=26으로 우연히 그 근처다.
# 아래는 전부 반복 상한을 20으로 두어, config를 안 넘기면 반드시 실패하게 한다.
# 두 최악 경로 — 도구 연속 / 종료 거부 연속 — 모두 반복당 2스텝을 쓴다.


def _wide_budget(max_iterations: int) -> LoopBudget:
    return _budget(
        max_iterations=max_iterations,
        max_tool_calls_total=100,
        max_tool_calls={TOOL_CORPUS_SEARCH: 100},
    )


def _tool_storm(max_iterations: int) -> tuple[LoopState, LoopDeps, FakeTool, ScriptedLlm]:
    """도구만 계속 부르는 경로 — 근거는 있어 종료 제안만 오면 끝날 수 있지만 오지 않는다."""
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(
        script=[ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": f"q{i}"}) for i in range(50)]
    )
    return (
        _state_with_evidence(),
        _deps(llm, _registry(tool), _wide_budget(max_iterations)),
        tool,
        llm,
    )


def _termination_storm(max_iterations: int) -> tuple[LoopState, LoopDeps, None, ScriptedLlm]:
    """근거 없이 종료만 제안하는 경로 — 거부마다 반복 1회를 태우고 트레이스는 남지 않는다."""
    llm = ScriptedLlm(script=[])
    return LoopState(topic="q"), _deps(llm, _registry(), _wide_budget(max_iterations)), None, llm


def test_full_budget_run_ends_by_budget_not_by_graph_recursion():
    state, deps, tool, llm = _tool_storm(20)

    outcome = run_loop(state, deps)

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert outcome.detail == "iterations 20/20"
    assert deps.budget.consumed.iterations == 20
    assert len(tool.calls) == 20
    # 21번째 decide는 관찰 전에 예산 검사에서 거부된다.
    assert len(llm.observations) == 20


def test_rejected_termination_storm_ends_at_the_iteration_cap():
    state, deps, _, llm = _termination_storm(20)

    outcome = run_loop(state, deps)

    assert outcome.reason is TerminationReason.NO_EVIDENCE
    assert outcome.detail == "iterations 20/20"
    assert deps.budget.consumed.iterations == 20
    assert len(llm.observations) == 20
    assert state.trace == []
    assert outcome.notes.count(_NO_EVIDENCE_NOTE) == 1


def test_recursion_limit_formula():
    assert _recursion_limit(_budget(max_iterations=12)) == 26


@pytest.mark.parametrize("storm", [_tool_storm, _termination_storm], ids=["tool", "termination"])
def test_recursion_limit_is_exactly_the_loop_bound(storm):
    """공식을 양쪽에서 고정한다 — 하나 작으면 터지고, 정확히 그 값이면 완주한다."""
    state, deps, _, _ = storm(3)
    with pytest.raises(GraphRecursionError):
        compile_loop_graph(None).invoke(
            {"snapshot": state.to_snapshot()},
            config={"recursion_limit": _recursion_limit(deps.budget) - 1},
            context=LoopRun(state=state, deps=deps),
        )

    state, deps, _, _ = storm(3)
    run_loop(state, deps)  # 정확히 상한으로 돈다
    assert deps.budget.consumed.iterations == 3


def test_langsmith_env_does_not_attach_a_tracer(monkeypatch):
    """env만으로 켜지는 외부 트레이싱을 루프가 막는다 — 노드 입출력에 논문 본문이 실린다."""
    from langsmith import run_helpers

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    seen: list = []

    class Spy:
        def decide(self, observation, tools):
            seen.append(run_helpers.get_tracing_context().get("enabled"))
            return LlmDecision(proposal=TerminationProposal(note="done"))

    run_loop(_state_with_evidence(), _deps(Spy(), _registry()))

    assert seen == [False]


# --- 체크포인트 · 스냅샷 · 협조적 취소 ---


def _snapshot_roundtrip(state: LoopState) -> LoopState:
    import json

    return LoopState.from_snapshot(json.loads(json.dumps(state.to_snapshot())))


def json_dumps(value) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def test_snapshot_roundtrip_preserves_what_assemble_reads():
    from backend.modules.evidence.domain.assembler import assemble

    state = _state_with_evidence()
    state.discovered["d1"] = PaperHandle(
        "d1", "r-d1", PaperOrigin.CORPUS, title="D", abstract_text="a"
    )
    state.examine(PaperHandle("p1", "r1", PaperOrigin.CORPUS, doc_model=object()))
    state.candidates_seen.add("x9")
    state.notes.append("n")
    state.trace.append(
        ToolCallRecord(seq=1, tool="t", args_summary="a", outcome=ToolCallOutcome.OK)
    )
    state.termination_reason = TerminationReason.SUFFICIENT

    restored = _snapshot_roundtrip(state)

    assert restored.papers["p1"].doc_model is None
    assert restored.papers["p1"].scope == "fulltext"  # 본문 확보 사실은 남는다
    assert restored.discovered["d1"].scope == "abstract"
    assert (restored.examined, restored.candidates) == (state.examined, state.candidates)
    assert restored.accumulator.cited_paper_ids == state.accumulator.cited_paper_ids
    assert restored.accumulator.has_conflicts == state.accumulator.has_conflicts
    assert restored.trace == state.trace
    assert restored.notes == state.notes
    assert restored.termination_reason is TerminationReason.SUFFICIENT
    assert assemble(restored, TerminationReason.SUFFICIENT, query_used="q") == assemble(
        state, TerminationReason.SUFFICIENT, query_used="q"
    )


def test_snapshot_carries_only_what_the_finalizer_reads():
    """체크포인트 크기를 정하는 규칙 — 마감(assemble)이 읽지 않는 것은 싣지 않는다."""
    image = ImageAttachment(media_type="image/png", data_b64="AAAA", asset_id="f1")
    tool = FakeTool(TOOL_CORPUS_SEARCH, result=ToolResult(ok=True, content={"big": "x" * 5000},
                                                          images=(image,)))
    llm = ScriptedLlm(script=[ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"})])
    state = _state_with_evidence()
    state.discovered["d1"] = PaperHandle(
        "d1", "r-d1", PaperOrigin.CORPUS, title="D", abstract_text="x" * 900
    )
    run_loop(state, _deps(llm, _registry(tool)))

    snap = state.to_snapshot()
    # 도구 결과 관찰 윈도우·소모 예산은 되읽는 소비자가 없다.
    assert "recent_results" not in snap and "consumed" not in snap
    # 후보는 개수로만 쓰이므로 초록 본문을 싣지 않는다 — 스냅샷의 절반이던 자리.
    assert "abstract_text" not in snap["discovered"][0]
    assert snap["discovered"][0]["title"] == "D"
    # 확인한 논문은 그대로(초록이 근거 범위의 재료다).
    state.examine(PaperHandle("p9", "r9", PaperOrigin.CORPUS, abstract_text="kept"))
    snap = state.to_snapshot()
    assert "abstract_text" in snap["papers"][0]
    assert "x" * 900 not in json_dumps(snap)


def test_checkpointer_sees_the_latest_snapshot_every_super_step():
    from langgraph.checkpoint.memory import InMemorySaver

    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(
        script=[
            ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"}),
            ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "b"}),
        ]
    )
    saver = InMemorySaver()
    graph = compile_loop_graph(saver)
    state = _state_with_evidence()
    deps = _deps(llm, _registry(tool))
    outcome = run_loop(state, deps, graph=graph)

    assert outcome.reason is TerminationReason.SUFFICIENT
    cfg = {"configurable": {"thread_id": "t1"}}
    history = list(graph.get_state_history(cfg))
    # 입력 + decide/act 쌍 ×2 + 마지막 decide + check_floor — 노드마다 체크포인트 하나
    snapshots = [h.values.get("snapshot") for h in history if h.values.get("snapshot")]
    trace_lengths = [len(s["trace"]) for s in snapshots]
    assert max(trace_lengths) == 2
    assert snapshots[0]["termination_reason"] == "sufficient"  # 최신이 먼저
    # 복원은 assemble이 읽는 것만 살린다
    restored = LoopState.from_snapshot(snapshots[0])
    assert len(restored.trace) == 2 and restored.accumulator.items


def test_load_snapshot_returns_none_for_an_unknown_thread():
    from langgraph.checkpoint.memory import InMemorySaver

    from backend.modules.evidence.domain.loop import load_snapshot

    graph = compile_loop_graph(InMemorySaver())
    assert load_snapshot(graph, "never-ran") is None
    assert load_snapshot(compile_loop_graph(None), "t1") is None


def test_rerunning_the_same_thread_starts_over_instead_of_short_circuiting():
    """SQS 재배달 경로 — 남은 outcome이 라우터를 END로 보내면 두 번째 실행이 빈손으로 끝난다."""
    from langgraph.checkpoint.memory import InMemorySaver

    graph = compile_loop_graph(InMemorySaver())
    for _ in range(2):
        tool = FakeTool(TOOL_CORPUS_SEARCH)
        llm = ScriptedLlm(script=[ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"})])
        state = _state_with_evidence()
        outcome = run_loop(state, _deps(llm, _registry(tool)), graph=graph)
        assert outcome.reason is TerminationReason.SUFFICIENT
        assert len(tool.calls) == 1
        assert len(llm.observations) == 2


def test_should_stop_ends_at_the_decide_boundary_without_spending_an_iteration():
    tool = FakeTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(
        script=[
            ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": str(i)}) for i in range(5)
        ]
    )
    stops = iter([None, None, TerminationReason.CANCELLED])
    state = _state_with_evidence()
    deps = _deps(llm, _registry(tool), should_stop=lambda: next(stops))
    outcome = run_loop(state, deps)

    assert outcome.reason is TerminationReason.CANCELLED
    assert state.termination_reason is TerminationReason.CANCELLED
    # 두 반복이 돌았고(도구 2회), 세 번째 decide 진입에서 멈췄다 — 반복·트레이스 미소모
    assert len(tool.calls) == 2
    assert deps.budget.consumed.iterations == 2
    assert [r.seq for r in state.trace] == [1, 2]
    assert len(llm.observations) == 2


def test_should_stop_lets_the_running_act_finish_and_keeps_its_result():
    """취소는 하던 단계가 끝난 뒤다(§2.8) — act 중 들어온 취소도 그 결과를 부분 답에 싣는다."""
    flag = {"cancel": False}

    @dataclass
    class CancellingTool(FakeTool):
        def invoke(self, args, ctx):
            flag["cancel"] = True  # 도구 실행 중 취소 요청이 들어온다
            return super().invoke(args, ctx)

    tool = CancellingTool(TOOL_CORPUS_SEARCH)
    llm = ScriptedLlm(script=[ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"})])
    state = _state_with_evidence()
    deps = _deps(llm, _registry(tool),
                 should_stop=lambda: TerminationReason.CANCELLED if flag["cancel"] else None)
    outcome = run_loop(state, deps)

    assert outcome.reason is TerminationReason.CANCELLED
    assert len(tool.calls) == 1
    assert state.trace[-1].outcome is ToolCallOutcome.OK


@pytest.mark.parametrize("reason", [TerminationReason.CANCELLED, TerminationReason.INTERRUPTED])
def test_stop_reasons_survive_an_empty_accumulator(reason):
    """근거 0건이어도 '왜 멈췄는지'는 NO_EVIDENCE로 뭉개지지 않는다."""
    llm = ScriptedLlm(script=[ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"})])
    state = LoopState(topic="q")
    outcome = run_loop(state, _deps(llm, _registry(FakeTool(TOOL_CORPUS_SEARCH)),
                                    should_stop=lambda: reason))
    assert outcome.reason is reason
    assert state.trace == [] and llm.observations == []
