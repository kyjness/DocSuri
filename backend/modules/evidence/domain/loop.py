"""루프 코어(BLM §1) — observe → decide → act, 그리고 종료 판정.

어댑터를 모른다. 도구·LLM은 포트로만 만나고, 도구가 무엇을 하는지도 모른다 —
루프가 아는 것은 "예산을 검사하고, 호출하고, 기록한다"뿐이다.

불변 조건:
- 예산 검사는 act **직전** 정확히 1회(`domain.budget` 단일 경로). 실행 후 차감은
  초과를 이미 지출한 뒤다.
- 실행된 모든 도구 호출은 `ToolCallRecord` 1:1(BR-EV-16).
- 종료 제안의 판정 권위는 도메인이다 — 누적 근거가 0건이면 정상 종료로 인정하지
  않는다(INV-EV-2).
- 이미지 첨부는 `decide` **직후** 소비하고 폐기한다(BR-EV-17) — 도구 실행 뒤에
  두면 종료 제안이 거부돼 도구 없이 되도는 경로에서 재전송이 남는다.

실행 틀은 LangGraph `StateGraph`다(evidence-agent-v3 설계 §3.1, 아키텍처 Q5=B). 위
불변 조건은 노드 안에 그대로 산다. `deps`(LLM·도구·예산·트레이스 싱크)는 직렬화할 수
없으므로 채널에 넣지 않고 노드 클로저로 묶는다. `LoopState`는 채널에 **참조로** 실린다 —
runner가 `outcome.state`가 아니라 자기 객체를 조립에 넘기므로 in-place 변경이 보여야
한다. 종료는 `_finish` 호출 지점 4곳(노드 3곳 + `_act`)에서 `outcome`을 채우는 것으로
표현한다 — PR 2가 이를 `answer → assemble` 꼬리로 모은다. 체크포인터도 PR 2.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langsmith import tracing_context

from ..ports.llm import (
    EvidenceLlmPort,
    LlmUnavailable,
    LoopObservation,
    PaperView,
    TerminationProposal,
    ToolCallProposal,
    ToolResultView,
)
from ..ports.tools import ToolContext, ToolRegistry, ToolResult
from . import budget as budget_rules
from .models import (
    AgentRunContext,
    LoopBudget,
    LoopState,
    TerminationReason,
    ToolCallOutcome,
    ToolCallRecord,
)

__all__ = ["LoopDeps", "LoopOutcome", "run_loop"]

log = logging.getLogger("docsuri.evidence.loop")

# 관찰 윈도우 — 최근 몇 건의 도구 결과를 다시 싣는가. 너무 크면 토큰이 새고,
# 너무 작으면 방금 무엇을 했는지 잊고 같은 질의를 반복한다.
_RECENT_WINDOW = 6

_NO_EVIDENCE_NOTE = (
    "아직 검증을 통과한 근거가 0건이다. extract_evidence로 확보한 논문에서 근거를 "
    "추출하거나, 다른 논문을 찾아라. 근거 없이는 종료할 수 없다."
)


@dataclass(slots=True)
class LoopDeps:
    llm: EvidenceLlmPort
    registry: ToolRegistry
    budget: LoopBudget
    ctx: AgentRunContext
    # 트레이스 1건이 확정될 때마다 부른다(스트리밍·영속). 실패는 루프를 깨지 않는다 —
    # 진행 표시는 advisory이고 근거형성이 본 경로다(NFR-O1).
    on_trace: Callable[[ToolCallRecord], None] | None = None


@dataclass(slots=True)
class LoopOutcome:
    reason: TerminationReason
    state: LoopState
    detail: str | None = None
    notes: list[str] = field(default_factory=list)


def run_loop(state: LoopState, deps: LoopDeps) -> LoopOutcome:
    """한 턴의 자율 탐색을 종료까지 구동한다."""
    graph = _build_graph(deps)
    # langchain-core는 LANGSMITH_TRACING 류 env만 있으면 트레이서를 **자동으로** 붙여 노드
    # 입출력(질문·논문 본문·이미지가 든 LoopState)을 외부로 보낸다. env의 부재에 기대지
    # 않고 여기서 끈다 — 이 루프의 관찰 경로는 on_trace 하나다(SEC-9).
    with tracing_context(enabled=False):
        result = graph.invoke(
            {"loop": state}, config={"recursion_limit": _recursion_limit(deps.budget)}
        )
    return result["outcome"]


class _GraphState(TypedDict, total=False):
    # 호출자의 LoopState 그 객체 — 복사 없이 참조로 싣는다(체크포인터 없음).
    loop: LoopState
    # decide → check_floor / act 로 넘기는 임시 값. 다음 decide가 덮어쓴다.
    proposal: ToolCallProposal | TerminationProposal
    # 종료 경로(`_finish` 호출 지점)에서만 채워진다. 채워지면 라우터가 END로 보낸다.
    outcome: LoopOutcome | None


# 반복 하나가 쓰는 최대 스텝 — `decide` + (`act` | `check_floor`). 거부된 종료 제안은
# `decide`로 되돌아가 **새 반복**이 되므로 한 반복이 3스텝이 될 수 없다.
_STEPS_PER_ITERATION = 2
# 반복 상한을 다 쓴 뒤 마지막 `decide`가 예산 검사에서 거부되는 1스텝.
_TAIL_STEPS = 1


def _recursion_limit(budget: LoopBudget) -> int:
    """그래프 스텝 상한 — 예산에서 유도한다. 기본값(25)에 맡기면 정상 루프가 잘린다.

    최대 스텝 = 반복당 2 × n + 꼬리 1. LangGraph는 N스텝을 돌리려면 `recursion_limit ≥ N+1`을
    요구한다(1.2.x 실측) → 2n+2. `GraphRecursionError`는 잡지 않는다 — 잡아서 예산 소진으로
    바꾸면 현행에 없던 종료 경로가 생기고, 노드를 더하면서 이 상수를 안 고친 실수를 가린다.
    PR 2의 `answer`·`assemble`은 반복당이 아니라 **꼬리** 스텝이다 — `_TAIL_STEPS`를 올린다.
    """
    return _STEPS_PER_ITERATION * budget.max_iterations + _TAIL_STEPS + 1


def _build_graph(deps: LoopDeps) -> CompiledStateGraph:
    """노드가 deps를 클로저로 닫으므로 턴마다 조립한다(약 3ms).

    PR 2에서 `context_schema=LoopDeps`로 deps를 invoke 인자로 넘기고 그래프는 한 번만
    컴파일한다 — context는 체크포인트에 실리지 않으므로 직렬화 불가인 deps의 제자리다.
    """

    def end(state: LoopState, reason: TerminationReason, detail: str | None) -> dict:
        return {"outcome": _finish(state, reason, detail, deps)}

    def decide(gs: _GraphState) -> dict:
        state = gs["loop"]
        denial = budget_rules.begin_iteration(deps.budget)
        if denial is not None:
            return end(state, TerminationReason.BUDGET_EXHAUSTED, denial.detail)

        observation = _observe(state, deps)
        try:
            decision = deps.llm.decide(observation, deps.registry.specs())
        except LlmUnavailable as exc:
            return end(state, TerminationReason.FATAL_ERROR, f"llm_unavailable: {exc}")

        budget_rules.record_cost(deps.budget, decision.cost_estimate_usd)
        # 전달된 이미지는 여기서 소비된다 — 남기면 매 턴 재전송된다.
        _drop_images(state)
        return {"proposal": decision.proposal}

    def check_floor(gs: _GraphState) -> dict:
        state = gs["loop"]
        if state.accumulator.items:
            return end(state, TerminationReason.SUFFICIENT, gs["proposal"].note)
        # 종료 제안 거부 — 사유를 관찰에 실어 다음 판단이 달라지게 한다.
        _note(state, _NO_EVIDENCE_NOTE)
        return {}

    def act(gs: _GraphState) -> dict:
        return {"outcome": _act(gs["loop"], deps, gs["proposal"])}

    graph = StateGraph(_GraphState)
    graph.add_node("decide", decide)
    graph.add_node("check_floor", check_floor)
    graph.add_node("act", act)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges("decide", _route_after_decide)
    graph.add_conditional_edges("check_floor", _route_back_or_end)
    graph.add_conditional_edges("act", _route_back_or_end)
    return graph.compile()


# 라우터 반환형은 Literal이어야 한다 — 그래야 컴파일된 그래프가 자기 간선을 안다
# (`get_graph()`·렌더·트레이스). 맨 str이면 조건부 간선이 전부 빠진 두 노드 그래프로 보인다.
def _route_after_decide(gs: _GraphState) -> Literal["check_floor", "act", "__end__"]:
    if gs.get("outcome") is not None:
        return END
    if isinstance(gs["proposal"], TerminationProposal):
        return "check_floor"
    return "act"


def _route_back_or_end(gs: _GraphState) -> Literal["decide", "__end__"]:
    return END if gs.get("outcome") is not None else "decide"


def _act(state: LoopState, deps: LoopDeps, proposal: ToolCallProposal) -> LoopOutcome | None:
    """도구 1회 실행. 종료해야 하면 LoopOutcome, 계속하면 None."""
    tool = deps.registry.get(proposal.tool_name)
    args_summary = _summarize_args(proposal.args)

    if proposal.decision_note:
        # 한 턴에 도구 호출이 여럿 온 경우 첫 개만 실행되고 나머지는 버려진다. 버려졌다는
        # 사실을 **모델에게** 알려야 다음 턴에 다시 요청할 수 있고(안 알리면 자기가 시킨
        # 일이 그냥 사라진다), 운영자에게도 남겨야 "왜 그 도구가 안 불렸나"를 추적할 수 있다.
        _note(state, f"이번 턴에서 실행되지 않은 호출이 있다 — {proposal.decision_note}")
        log.warning("evidence: %s", proposal.decision_note)

    if tool is None:
        # 어휘 밖 도구를 고른 것은 모델의 오류다 — 예산을 태우지 않고 되돌린다.
        _record(state, deps, proposal.tool_name, args_summary, ToolCallOutcome.ERROR,
                "unknown tool")
        _note(state, f"'{proposal.tool_name}'은(는) 없는 도구다. 제공된 도구 중에서 골라라.")
        return None

    denial = budget_rules.check_and_consume_tool_call(deps.budget, proposal.tool_name)
    if denial is not None:
        _record(state, deps, proposal.tool_name, args_summary, ToolCallOutcome.BUDGET_DENIED,
                denial.detail)
        return _finish(state, TerminationReason.BUDGET_EXHAUSTED, denial.detail, deps)

    ctx = ToolContext(
        owner_id=deps.ctx.owner_id, session_id=deps.ctx.session_id, turn_id=deps.ctx.turn_id
    )
    try:
        result = tool.invoke(proposal.args, ctx)
    except Exception as exc:  # noqa: BLE001 — 도구 실패가 턴을 깨지 않는다(BR-EV-18)
        log.warning("evidence tool %s raised", proposal.tool_name, exc_info=True)
        result = ToolResult(ok=False, error=f"도구 실행에 실패했다: {exc}"[:300])

    budget_rules.record_cost(deps.budget, result.cost_usd)
    outcome = ToolCallOutcome.OK if result.ok else ToolCallOutcome.ERROR
    if result.ok and not result.content:
        outcome = ToolCallOutcome.EMPTY
    _record(state, deps, proposal.tool_name, args_summary, outcome,
            result.result_summary or (result.error or ""), result.cost_usd)
    _push_result(state, proposal.tool_name, args_summary, result)
    return None


def _paper_view(handle: Any) -> PaperView:
    return PaperView(
        paper_id=handle.paper_id,
        record_ref=handle.record_ref,
        title=handle.title,
        origin=handle.origin.value,
        scope=handle.scope,
    )


def _observe(state: LoopState, deps: LoopDeps) -> LoopObservation:
    consumed = deps.budget.consumed
    return LoopObservation(
        topic=state.topic,
        papers=tuple(_paper_view(handle) for handle in state.papers.values()),
        pending_papers=tuple(_paper_view(handle) for handle in state.discovered.values()),
        recent_results=tuple(state.recent_results),
        evidence_count=len(state.accumulator.items),
        cited_paper_count=len(state.accumulator.cited_paper_ids),
        has_conflicts=state.accumulator.has_conflicts,
        iterations_left=max(0, deps.budget.max_iterations - consumed.iterations),
        tool_calls_left=max(0, deps.budget.max_tool_calls_total - consumed.tool_calls_total),
        cost_left_usd=max(0.0, deps.budget.token_cost_limit_usd - consumed.cost_usd),
        prior_topics=deps.ctx.prior_topics,
        prior_paper_ids=deps.ctx.prior_paper_ids,
        notes=tuple(state.notes),
    )


# 관찰에 싣는 결과 1건의 렌더 상한 — 프롬프트 어댑터가 아니라 여기서 절단하는 이유는
# 렌더형을 1회만 만들기 위해서다(같은 결과가 회차마다 다시 실린다).
_PREVIEW_CHARS = 2000


def _preview(content: dict) -> str:
    import json

    try:
        text = json.dumps(content, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return "(직렬화 불가)"
    return text if len(text) <= _PREVIEW_CHARS else text[:_PREVIEW_CHARS] + " …(생략)"


def _push_result(state: LoopState, tool_name: str, args_summary: str, result: ToolResult) -> None:
    """관찰 윈도우 갱신 — 이미지는 **가장 최근 1건에만** 남긴다."""
    _drop_images(state)
    state.recent_results.append(
        ToolResultView(
            seq=len(state.trace),
            tool_name=tool_name,
            ok=result.ok,
            args_summary=args_summary,
            content=result.content,
            content_preview=_preview(result.content),
            error=result.error,
            images=result.images,
        )
    )
    if len(state.recent_results) > _RECENT_WINDOW:
        del state.recent_results[: len(state.recent_results) - _RECENT_WINDOW]


def _without_images(view: ToolResultView) -> ToolResultView:
    return ToolResultView(
        seq=view.seq,
        tool_name=view.tool_name,
        ok=view.ok,
        args_summary=view.args_summary,
        content=view.content,
        content_preview=view.content_preview,
        error=view.error,
    )


def _drop_images(state: LoopState) -> None:
    state.recent_results = [
        view if not view.images else _without_images(view) for view in state.recent_results
    ]


def _record(
    state: LoopState,
    deps: LoopDeps,
    tool: str,
    args_summary: str,
    outcome: ToolCallOutcome,
    result_summary: str,
    cost_usd: float | None = None,
) -> None:
    record = ToolCallRecord(
        seq=len(state.trace) + 1,
        tool=tool,
        args_summary=args_summary,
        outcome=outcome,
        result_summary=result_summary[:500],
        cost_usd=cost_usd,
    )
    state.trace.append(record)
    if deps.on_trace is None:
        return
    try:
        deps.on_trace(record)
    except Exception:  # noqa: BLE001 — 진행 표시는 advisory(NFR-O1)
        log.warning("evidence trace sink failed (tool=%s)", tool, exc_info=True)


def _note(state: LoopState, text: str) -> None:
    if text not in state.notes:
        state.notes.append(text)


def _summarize_args(args: dict) -> str:
    """트레이스·관찰에 싣는 인자 요약. 모델이 쓴 값이므로 렌더 단계에서 무해화된다."""
    parts = []
    for key, value in (args or {}).items():
        text = str(value)
        parts.append(f"{key}={text[:80]}")
    return ", ".join(parts)[:300]


def _finish(
    state: LoopState, reason: TerminationReason, detail: str | None, deps: LoopDeps
) -> LoopOutcome:
    if reason is not TerminationReason.FATAL_ERROR and not state.accumulator.items:
        # 예산이 끝났든 충분하다고 판단했든, 근거가 없으면 기권이다(INV-EV-2).
        reason = TerminationReason.NO_EVIDENCE
    state.termination_reason = reason
    return LoopOutcome(reason=reason, state=state, detail=detail, notes=list(state.notes))
