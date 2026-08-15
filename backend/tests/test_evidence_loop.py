"""루프 코어(BLM §1) — 도구 대역 위의 결정론 실행 + 상한 불변식(PBT-EV-7)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceItem,
    SourceRef,
    SourceScope,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from backend.modules.evidence.domain.loop import LoopDeps, run_loop
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

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert len(tool.calls) == 2


def test_budget_denied_is_traced_before_terminating():
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
