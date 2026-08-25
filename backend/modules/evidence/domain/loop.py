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
불변 조건은 노드 안에 그대로 산다. 채널에는 **JSON만** 싣는다 — 매 super-step의 `snapshot`
(`LoopState.to_snapshot`), 노드 사이를 건너는 `proposal`, 종료 경로가 채우는 `outcome`. 살아
있는 `LoopState`와 `deps`(LLM·도구·예산·트레이스 싱크·취소 신호)는 직렬화할 수 없으므로
`context`(`LoopRun`)로 주입한다 — context는 체크포인트에 실리지 않는다. runner가
`outcome.state`가 아니라 자기 객체를 조립에 넘기므로 in-place 변경은 여전히 보여야 하고,
스냅샷은 그 객체의 투영일 뿐이다.

체크포인터(`compile_loop_graph(checkpointer)`)가 있으면 `thread_id=turn_id`로 super-step마다
저장된다. 이번 단계는 **재개하지 않는다** — 남은 체크포인트는 실행자가 죽은 턴을 부분 답으로
마감하는 데만 쓴다(`load_snapshot`). 그래서 invoke 전에 스레드를 비운다: **완료된 thread는 다시
invoke해도 아예 돌지 않는다**(입력 쓰기조차 반영되지 않는다 — 1.2.x 실측). 재배달된 잡이 조용히
"아무 일도 안 하고 성공"으로 끝나는 것을 막는 유일한 방법이다.

스냅샷은 상태를 **바꾼 노드만** 돌려준다(`act`와 종료 지점). `decide`·`check_floor`가 만지는 것은
예산·이미지·노트뿐이라 마감이 읽는 것에 영향이 없고, LastValue 채널이 직전 값을 유지한다 —
매 노드가 전체 투영을 다시 쓰면 같은 바이트가 체크포인트마다 두 번씩(blob + writes) 쌓인다.

취소·중단은 `deps.should_stop`이 `decide` 진입(super-step 경계)에서 사유를 돌려주는 것으로
표현한다 — 진행 중인 `act`는 끝까지 돌고 그 결과도 부분 답에 들어간다(§2.8). 종료는 `_finish`
호출 지점에서 `outcome`을 채우는 것으로 표현하고, 근거가 있으면 **모든 종료 경로가** `answer`
노드를 지나 판단을 쓴다(§4.2). 마감(`assemble`)은 여전히 runner가 부른다 — 순수 함수라
super-step을 하나 더 쓸 이유가 없고, 고아 마감은 이미 스냅샷에서 같은 함수를 부른다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime
from langsmith import tracing_context

from ..ports.llm import (
    COUNTER_REQUIRED_KINDS,
    QUESTION_KIND_UNKNOWN,
    AnswerEvidenceView,
    AnswerRequest,
    EvidenceAnswerPort,
    EvidenceLlmPort,
    LlmUnavailable,
    LoopObservation,
    PaperView,
    TerminationProposal,
    ToolCallProposal,
    ToolResultView,
)
from ..ports.tools import (
    STANCE_TOOLS,
    STANCES,
    ToolContext,
    ToolRegistry,
    ToolResult,
    counter_probes,
)
from . import budget as budget_rules
from .answer_checks import AnswerRejected, check_answer
from .assembler import comparison_order, fallback_answer
from .budget import BudgetDenialReason
from .models import (
    AgentRunContext,
    LoopBudget,
    LoopState,
    TerminationReason,
    ToolCallOutcome,
    ToolCallRecord,
)

__all__ = ["LoopDeps", "LoopOutcome", "LoopRun", "compile_loop_graph", "load_snapshot", "run_loop"]

log = logging.getLogger("docsuri.evidence.loop")

# 관찰 윈도우 — 최근 몇 건의 도구 결과를 다시 싣는가. 너무 크면 토큰이 새고,
# 너무 작으면 방금 무엇을 했는지 잊고 같은 질의를 반복한다.
_RECENT_WINDOW = 6

_NO_EVIDENCE_NOTE = (
    "아직 검증을 통과한 근거가 0건이다. extract_evidence로 확보한 논문에서 근거를 "
    "추출하거나, 다른 논문을 찾아라. 근거 없이는 종료할 수 없다."
)

# 바닥 2(§3.3) — 주장·비교형은 반대 측을 한 번은 찾아야 끝낼 수 있다. 사유를 관찰에 실어
# 다음 판단이 달라지게 한다(`_NO_EVIDENCE_NOTE`와 같은 방식) — 거부만 하면 모델은 같은
# 종료 제안을 반복하고 그 반복이 반복 예산을 태운다.
_NO_COUNTER_NOTE = (
    "이 질문은 {kind}형이라 반대 측을 확인해야 끝낼 수 있다. 아직 stance=\"counter\"로 "
    "표시한 검색·추출이 한 번도 없다. 이 주장에 반하거나 조건을 제한하는 근거를 "
    "corpus_search·live_lookup·extract_evidence 중 하나에 stance=\"counter\"를 붙여 "
    "찾아라. 찾아본 뒤 없으면 그때 종료해도 된다 — 없다는 것도 결과다."
)

_TOOL_CAP_NOTE = (
    "'{tool}'은(는) 이번 턴의 호출 상한을 다 썼다({detail}). 다시 부를 수 없으니 "
    "이미 확보한 논문에서 extract_evidence로 근거를 뽑거나 남은 도구를 써라."
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
    # 협조적 취소·중단 — super-step 경계(decide 진입)마다 묻는다. 사유를 돌려주면 반복을
    # 소모하지 않고 그 자리에서 끝낸다(novelty BR-RA8과 같은 방식).
    should_stop: Callable[[], TerminationReason | None] | None = None
    # 판단 층(§4.2). 구성되지 않으면 `answer` 노드가 통째로 건너뛰고 마감이 결정론
    # 이어붙이기로 떨어진다 — 판단은 얹는 층이지 근거형성의 전제가 아니다.
    answer: EvidenceAnswerPort | None = None


@dataclass(slots=True)
class LoopOutcome:
    reason: TerminationReason
    state: LoopState
    detail: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LoopRun:
    """그래프 context — 살아 있는 상태와 의존성. 체크포인트에 실리지 않는다."""

    state: LoopState
    deps: LoopDeps


def run_loop(
    state: LoopState, deps: LoopDeps, *, graph: CompiledStateGraph | None = None
) -> LoopOutcome:
    """한 턴의 자율 탐색을 종료까지 구동한다.

    `graph`가 없으면 체크포인터 없이 컴파일한다(테스트·포트 경로). 있으면
    `thread_id=deps.ctx.turn_id`로 super-step마다 저장된다.
    """
    if graph is None:
        graph = compile_loop_graph(None)
    config: dict[str, Any] = {"recursion_limit": _recursion_limit(deps.budget)}
    if graph.checkpointer is not None:
        # 재개가 아니라 새 실행이다 — 완료된 thread는 비우지 않으면 재invoke가 무동작으로 끝난다.
        graph.checkpointer.delete_thread(deps.ctx.turn_id)
        config["configurable"] = {"thread_id": deps.ctx.turn_id}
    # langchain-core는 LANGSMITH_TRACING 류 env만 있으면 트레이서를 **자동으로** 붙여 노드
    # 입출력(질문·논문 본문·이미지가 든 LoopState)을 외부로 보낸다. env의 부재에 기대지
    # 않고 여기서 끈다 — 이 루프의 관찰 경로는 on_trace 하나다(SEC-9).
    with tracing_context(enabled=False):
        result = graph.invoke(
            {"snapshot": state.to_snapshot()},
            config=config,
            context=LoopRun(state=state, deps=deps),
        )
    outcome = result["outcome"]
    return LoopOutcome(
        reason=TerminationReason(outcome["reason"]),
        state=state,
        detail=outcome["detail"],
        notes=list(state.notes),
    )


def load_snapshot(graph: CompiledStateGraph, turn_id: str) -> dict[str, Any] | None:
    """마지막 체크포인트의 스냅샷 — 없으면(안 돈 스레드·체크포인터 없음) None."""
    if graph.checkpointer is None:
        return None
    values = graph.get_state({"configurable": {"thread_id": turn_id}}).values
    return values.get("snapshot") if values else None


class _GraphState(TypedDict, total=False):
    # 살아 있는 LoopState의 JSON 투영 — 노드마다 갱신해 체크포인트에 최신이 실리게 한다.
    snapshot: dict[str, Any]
    # decide → check_floor / act 로 넘기는 임시 값. `{"kind": "tool"|"end", ...}`.
    proposal: dict[str, Any] | None
    # 종료 경로(`_finish` 호출 지점)에서만 채워진다. 채워지면 라우터가 END로 보낸다.
    outcome: dict[str, Any] | None


# 반복 하나가 쓰는 최대 스텝 — `decide` + (`act` | `check_floor`). 거부된 종료 제안은
# `decide`로 되돌아가 **새 반복**이 되므로 한 반복이 3스텝이 될 수 없다.
_STEPS_PER_ITERATION = 2
# 반복 상한을 다 쓴 뒤 마지막 `decide`가 예산 검사에서 거부되는 1스텝 + 꼬리의 `answer`
# 1스텝. `answer`는 반복당이 아니라 종료 경로마다 **한 번** 도는 노드다(재생성은 그 안에서
# 일어나므로 스텝을 더 쓰지 않는다).
_TAIL_STEPS = 2


def _recursion_limit(budget: LoopBudget) -> int:
    """그래프 스텝 상한 — 예산에서 유도한다. 기본값(25)에 맡기면 정상 루프가 잘린다.

    최대 스텝 = 반복당 2 × n + 꼬리 1. LangGraph는 N스텝을 돌리려면 `recursion_limit ≥ N+1`을
    요구한다(1.2.x 실측) → 2n+2. `GraphRecursionError`는 잡지 않는다 — 잡아서 예산 소진으로
    바꾸면 현행에 없던 종료 경로가 생기고, 노드를 더하면서 이 상수를 안 고친 실수를 가린다.
    `answer`는 반복당이 아니라 **꼬리** 스텝이라 `_TAIL_STEPS`에 든다(PR 3에서 1 → 2).
    """
    return _STEPS_PER_ITERATION * budget.max_iterations + _TAIL_STEPS + 1


def compile_loop_graph(checkpointer: BaseCheckpointSaver | None) -> CompiledStateGraph:
    """그래프는 deps를 닫지 않으므로 프로세스당 한 번 컴파일하면 된다."""

    def end(run: LoopRun, reason: TerminationReason, detail: str | None) -> dict:
        outcome = _finish(run.state, reason, detail, run.deps)
        return {"outcome": _dump_outcome(outcome), "snapshot": run.state.to_snapshot()}

    def answer(gs: _GraphState, runtime: Runtime[LoopRun]) -> dict:
        """판단 층(§4.2) — 종료가 확정된 뒤 **게이트를 통과한 근거만** 보고 산문을 쓴다.

        루프 안에 두는 이유는 셋이다: 비용이 턴 예산에 계상돼야 하고, super-step 경계라
        체크포인트에 남아야 하며, 실패가 근거형성을 깨서는 안 된다. 어느 실패든 판단만
        비우고 마감으로 보낸다 — 판단이 없으면 마감이 결정론 이어붙이기로 떨어진다.
        """
        run = runtime.context
        _write_answer(run.state, run.deps, (gs.get("outcome") or {}).get("reason"))
        return {"snapshot": run.state.to_snapshot()}

    def decide(gs: _GraphState, runtime: Runtime[LoopRun]) -> dict:
        run = runtime.context
        state, deps = run.state, run.deps
        if deps.should_stop is not None:
            stop = deps.should_stop()
            if stop is not None:
                return end(run, stop, None)

        denial = budget_rules.begin_iteration(deps.budget)
        if denial is not None:
            return end(run, TerminationReason.BUDGET_EXHAUSTED, denial.detail)

        observation = _observe(state, deps)
        try:
            decision = deps.llm.decide(observation, deps.registry.specs())
        except LlmUnavailable as exc:
            # 사유는 `outcome.detail`에만 실리고 마감이 그것을 버린다 — 로그가 없으면
            # 화면에 "분석 불가"가 뜨는데 서버에는 아무 것도 안 남는다(2026-08-24 실측:
            # 골든셋 실행이 조용히 기권했고 DEBUG를 켜도 한 줄이 없었다).
            log.warning("evidence decide: llm unavailable — %s", exc)
            return end(run, TerminationReason.FATAL_ERROR, f"llm_unavailable: {exc}")

        budget_rules.record_cost(deps.budget, decision.cost_estimate_usd)
        # 전달된 이미지는 여기서 소비된다 — 남기면 매 턴 재전송된다.
        _drop_images(state)
        # 스냅샷은 쓰지 않는다 — 이 노드가 바꾸는 것(예산·이미지)은 마감이 읽지 않는다.
        return {"proposal": _dump_proposal(decision.proposal), "outcome": None}

    def check_floor(gs: _GraphState, runtime: Runtime[LoopRun]) -> dict:
        run = runtime.context
        state = run.state
        proposal = gs.get("proposal") or {}
        # 모델이 선언한 질문 유형은 **거부되는 종료 제안에서도** 기록한다 — 선언 자체는
        # 근거 수와 무관하고, 뒤에 예산으로 끝나면 다시 선언할 기회가 없다.
        if proposal.get("question_kind"):
            state.question_kind = proposal["question_kind"]
        # 종료 제안 거부 — 사유를 관찰에 실어 다음 판단이 달라지게 한다(노트는 마감이 안 읽는다).
        if not state.accumulator.items:
            _note(state, _NO_EVIDENCE_NOTE)
            return {"proposal": None, "outcome": None}
        missing = _missing_counter_probe(state, run.deps.budget)
        if missing is not None:
            _note(state, missing)
            return {"proposal": None, "outcome": None}
        return end(run, TerminationReason.SUFFICIENT, proposal.get("note"))

    def act(gs: _GraphState, runtime: Runtime[LoopRun]) -> dict:
        run = runtime.context
        outcome = _act(run.state, run.deps, _load_proposal(gs["proposal"]))
        return {
            "outcome": _dump_outcome(outcome) if outcome is not None else None,
            "snapshot": run.state.to_snapshot(),
        }

    graph = StateGraph(_GraphState, context_schema=LoopRun)
    graph.add_node("decide", decide)
    graph.add_node("check_floor", check_floor)
    graph.add_node("act", act)
    graph.add_node("answer", answer)
    graph.add_edge(START, "decide")
    graph.add_conditional_edges("decide", _route_after_decide)
    graph.add_conditional_edges("check_floor", _route_to_answer_or_back)
    graph.add_conditional_edges("act", _route_to_answer_or_back)
    graph.add_edge("answer", END)
    return graph.compile(checkpointer=checkpointer)


# 라우터 반환형은 Literal이어야 한다 — 그래야 컴파일된 그래프가 자기 간선을 안다
# (`get_graph()`·렌더·트레이스). 맨 str이면 조건부 간선이 전부 빠진 두 노드 그래프로 보인다.
def _route_after_decide(gs: _GraphState) -> Literal["answer", "check_floor", "act", "__end__"]:
    if gs.get("outcome") is not None:
        return _answer_or_end(gs)
    if (gs.get("proposal") or {}).get("kind") == _PROPOSAL_END:
        return "check_floor"
    return "act"


def _route_to_answer_or_back(gs: _GraphState) -> Literal["answer", "decide", "__end__"]:
    return "decide" if gs.get("outcome") is None else _answer_or_end(gs)


def _answer_or_end(gs: _GraphState) -> Literal["answer", "__end__"]:
    """근거가 있으면 **모든 종료 경로가** 판단을 지난다(§3.1 그래프의 꼬리).

    예산 소진·취소·치명 오류도 마찬가지다 — 그때까지 검증된 근거로 부분 답을 만드는 것이
    §2.3·§2.8의 약속이고, 판단 없이 근거만 나열하면 그 약속이 반만 지켜진다. 근거 0건이면
    쓸 것이 없으므로 바로 끝낸다(기권 경로).
    """
    return "answer" if (gs.get("snapshot") or {}).get("items") else END


# 채널에는 JSON만 싣는다 — 제안은 종류 태그를 붙인 dict로, 결과는 사유·상세만.
_PROPOSAL_TOOL = "tool"
_PROPOSAL_END = "end"


def _dump_proposal(proposal: ToolCallProposal | TerminationProposal) -> dict[str, Any]:
    kind = _PROPOSAL_END if isinstance(proposal, TerminationProposal) else _PROPOSAL_TOOL
    return {"kind": kind, **asdict(proposal)}


# 판단 시도 상한 — 최초 1회 + 재생성 1회(§4.3 시작값). 늘리면 거부가 반복될 때 비용이
# 그만큼 늘고, 그 비용도 턴 예산에 계상된다.
_ANSWER_MAX_ATTEMPTS = 2


def _write_answer(state: LoopState, deps: LoopDeps, reason: str | None = None) -> None:
    """§4.2·§4.3 — 판단을 쓰고 검사하고, 안 되면 폴백까지. 예외를 밖으로 내지 않는다.

    `reason`은 이 턴이 **왜** 끝났는지다. LLM이 죽어서 끝난 턴에 판단 LLM을 다시 부르는
    것은 낭비를 넘어 해롭다 — 판단 어댑터는 자기 `SourceBreaker`를 따로 들고 있어 닫힌
    회로에서 시작하므로, 스로틀로 죽은 턴이 쿼터가 문제인 바로 그 순간에 호출을 두 번 더
    쓴다. 어느 쪽이든 결과는 폴백이므로 곧바로 폴백으로 간다.
    """
    if deps.answer is None or not state.accumulator.items:
        return
    ordered = comparison_order(state.accumulator.items)
    reject: str | None = None

    if reason == TerminationReason.FATAL_ERROR.value:
        log.info("evidence answer: 치명 오류로 끝난 턴이라 판단 호출을 건너뛴다")
    else:
        reject = _attempt_answer(state, deps, ordered)
        if state.answer is not None:
            return

    # 재생성도 거부됐거나 판단 LLM을 못 썼다 — 답은 나가되 판단 없이(§4.3, C-2 fail-closed).
    state.answer = fallback_answer(ordered, regenerated=reject is not None)


def _attempt_answer(state: LoopState, deps: LoopDeps, ordered: list) -> str | None:
    """판단 LLM을 최대 `_ANSWER_MAX_ATTEMPTS`회 부른다. 성공하면 `state.answer`를 채운다.

    반환값은 마지막 거부 사유(없으면 None) — 폴백이 "재생성까지 하고 실패한 것"인지
    "애초에 못 부른 것"인지를 호출자가 구분한다.
    """
    views = _answer_views(ordered)
    reject: str | None = None

    for attempt in range(_ANSWER_MAX_ATTEMPTS):
        # `attempt`를 기본인자로 묶는다 — 클로저가 루프 변수를 늦게 읽지 않게.
        def trace(
            outcome: ToolCallOutcome,
            summary: str,
            cost: float | None = None,
            *,
            n: int = attempt + 1,
        ) -> None:
            _record(state, deps, "answer", f"attempt={n}", outcome, summary, cost)

        # 비용을 계상만 하고 확인하지 않으면, 예산이 터져 끝난 턴이 이 턴에서 가장 큰
        # 프롬프트를 한두 번 더 내보낸다. 재생성 쪽이 특히 그렇다.
        if budget_rules.is_cost_exhausted(deps.budget):
            trace(ToolCallOutcome.BUDGET_DENIED, "비용 상한 소진 — 판단 호출을 건너뛴다")
            break
        request = AnswerRequest(
            topic=state.topic,
            question_kind=state.question_kind or QUESTION_KIND_UNKNOWN,
            evidence=views,
            reject_reason=reject,
        )
        try:
            draft = deps.answer.write(request)
        except Exception as exc:  # noqa: BLE001 — 판단 실패가 근거형성을 깨지 않는다
            log.warning("evidence answer failed", exc_info=True)
            trace(ToolCallOutcome.ERROR, str(exc)[:200])
            break
        budget_rules.record_cost(deps.budget, draft.cost_estimate_usd)
        checked = check_answer(draft.sentences, ordered, regenerated=attempt > 0)
        if not isinstance(checked, AnswerRejected):
            state.answer = checked.answer
            demoted = checked.answer.checks.demoted
            if checked.demotion_reasons:
                # **왜** 강등됐는지는 화면 계약에 안 들어간다 — 여기서 안 남기면 문장이
                # 인용 표시를 잃은 이유가 어디에도 안 남는다.
                log.info("evidence answer: 강등 %d건 — %s", demoted, checked.demotion_reasons)
            trace(
                ToolCallOutcome.OK,
                f"문장 {len(checked.answer.segments)}건, 강등 {demoted}건",
                draft.cost_estimate_usd,
            )
            return reject
        reject = f"{checked.code}: {checked.detail}"
        trace(ToolCallOutcome.ERROR, f"거부 — {reject}", draft.cost_estimate_usd)

    return reject


def _answer_views(ordered: list) -> tuple[AnswerEvidenceView, ...]:
    """근거 → 판단 층 입력. 번호는 표시 순서의 1-기반이다(근거표 행 번호와 같은 출처)."""
    by_paper: dict[str, list[int]] = {}
    for number, item in enumerate(ordered, start=1):
        for ref in item.supporting:
            by_paper.setdefault(ref.paperId, []).append(number)
    views = []
    for number, item in enumerate(ordered, start=1):
        # 게이트가 `NO_SUPPORTING`을 이미 떨어뜨렸으므로 지지 출처는 반드시 있다.
        # `if primary else ""`로 감싸면 그 전제가 깨졌을 때 논문 없는 행이 조용히 나간다.
        primary = item.supporting[0]
        # 상충은 "이 명제와 충돌하는 근거의 번호"다 — 상충 출처의 논문이 지지 쪽에 올린
        # 명제를 찾아 그 번호를 준다. 모델이 §2.2대로 조건을 나누려면 어느 근거끼리
        # 갈리는지를 번호로 알아야 한다.
        conflicts = sorted(
            {n for ref in item.conflicting for n in by_paper.get(ref.paperId, []) if n != number}
        )
        views.append(
            AnswerEvidenceView(
                number=number,
                statement=item.statement,
                paper_id=primary.paperId,
                quote=primary.quote or "",
                locator=primary.anchor or "",
                conflicts_with=tuple(conflicts),
            )
        )
    return tuple(views)


def _load_proposal(data: dict[str, Any]) -> ToolCallProposal:
    return ToolCallProposal(
        tool_name=data["tool_name"], args=data["args"], decision_note=data.get("decision_note")
    )


def _dump_outcome(outcome: LoopOutcome) -> dict[str, Any]:
    return {"reason": outcome.reason.value, "detail": outcome.detail}


def _act(state: LoopState, deps: LoopDeps, proposal: ToolCallProposal) -> LoopOutcome | None:
    """도구 1회 실행. 종료해야 하면 LoopOutcome, 계속하면 None."""
    tool = deps.registry.get(proposal.tool_name)
    args_summary = _summarize_args(proposal.args)
    stance = _declared_stance(proposal.tool_name, proposal.args)

    if proposal.decision_note:
        # 한 턴에 도구 호출이 여럿 온 경우 첫 개만 실행되고 나머지는 버려진다. 버려졌다는
        # 사실을 **모델에게** 알려야 다음 턴에 다시 요청할 수 있고(안 알리면 자기가 시킨
        # 일이 그냥 사라진다), 운영자에게도 남겨야 "왜 그 도구가 안 불렸나"를 추적할 수 있다.
        _note(state, f"이번 턴에서 실행되지 않은 호출이 있다 — {proposal.decision_note}")
        log.warning("evidence: %s", proposal.decision_note)

    if tool is None:
        # 어휘 밖 도구를 고른 것은 모델의 오류다 — 예산을 태우지 않고 되돌린다.
        _record(state, deps, proposal.tool_name, args_summary, ToolCallOutcome.ERROR,
                "unknown tool", stance=stance)
        _note(state, f"'{proposal.tool_name}'은(는) 없는 도구다. 제공된 도구 중에서 골라라.")
        return None

    denial = budget_rules.check_and_consume_tool_call(deps.budget, proposal.tool_name)
    if denial is not None:
        _record(state, deps, proposal.tool_name, args_summary, ToolCallOutcome.BUDGET_DENIED,
                denial.detail, stance=stance)
        if denial.reason is BudgetDenialReason.TOOL_CAP_EXHAUSTED:
            # **도구 하나가 상한을 다 쓴 것은 턴의 예산 소진이 아니다.** 다른 도구도, 반복도,
            # 비용도 남아 있다. 여기서 끝내면 이미 확보한 논문을 손에 쥔 채 "근거 부족"으로
            # 기권한다 — 2026-08-24 실측: fetch_paper 3/3에 막혀 논문 3편·256블록을 가지고도
            # extract_evidence를 한 번도 못 부르고 abstain으로 끝났다. 예외도 ERROR 로그도
            # 없어 정상적인 보수적 동작처럼 보인다. 사유를 관찰에 실어 다음 판단이 남은
            # 도구를 고르게 한다(`_NO_EVIDENCE_NOTE`와 같은 방식).
            _note(state, _TOOL_CAP_NOTE.format(tool=proposal.tool_name, detail=denial.detail))
            return None
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
            result.result_summary or (result.error or ""), result.cost_usd, stance=stance)
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
        prior_summary=deps.ctx.prior_summary,
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
    stance: str | None = None,
) -> None:
    record = ToolCallRecord(
        seq=len(state.trace) + 1,
        tool=tool,
        args_summary=args_summary,
        outcome=outcome,
        result_summary=result_summary[:500],
        cost_usd=cost_usd,
        stance=stance,
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


def _missing_counter_probe(state: LoopState, budget: LoopBudget) -> str | None:
    """바닥 2 미달이면 그 사유, 아니면 None(§3.3)."""
    kind = state.question_kind or QUESTION_KIND_UNKNOWN
    if kind not in COUNTER_REQUIRED_KINDS:
        return None
    if counter_probes(state.trace):
        return None
    if not any(budget_rules.can_call(budget, tool) for tool in STANCE_TOOLS):
        # **더 부를 예산이 없으면 바닥을 요구할 수 없다.** 요구하면 종료 제안이 매번 거부되고
        # 그래프가 decide로 되돌아, 근거를 충분히 모은 턴이 남은 반복(최대 12)을 LLM 호출로
        # 태운 뒤 `budget_exhausted`로 끝난다 — 화면에는 "이어서 확인할까요?"가 뜬다.
        # 깨끗이 끝냈어야 할 턴이다.
        log.info("evidence floor: 반대 측 탐색을 더 부를 예산이 없어 종료를 받아들인다")
        return None
    return _NO_COUNTER_NOTE.format(kind="주장" if kind == "claim" else "비교")


def _declared_stance(tool_name: str, args: dict) -> str | None:
    """그 호출의 탐색 방향 선언(§3.2) — **`stance`를 받는 도구에서만** 읽는다.

    `read_paper`에 `stance="counter"`를 달아도 반대 측을 *찾은* 것은 아니다. 어휘 밖 값도
    버린다 — 세는 쪽이 어휘를 넓히면 선언이 검사를 통과시키는 자유 문자열이 된다.
    """
    if tool_name not in STANCE_TOOLS:
        return None
    stance = str((args or {}).get("stance") or "").strip().lower()
    return stance if stance in STANCES else None


def _summarize_args(args: dict) -> str:
    """트레이스·관찰에 싣는 인자 요약. 모델이 쓴 값이므로 렌더 단계에서 무해화된다."""
    parts = []
    for key, value in (args or {}).items():
        text = str(value)
        parts.append(f"{key}={text[:80]}")
    return ", ".join(parts)[:300]


# 근거 0건이어도 사유를 유지하는 종료 — "왜 멈췄는지"가 사용자에게 보여야 하는 것들.
_REASON_KEPT_WITHOUT_EVIDENCE = frozenset(
    {TerminationReason.FATAL_ERROR, TerminationReason.CANCELLED, TerminationReason.INTERRUPTED}
)


def _finish(
    state: LoopState, reason: TerminationReason, detail: str | None, deps: LoopDeps
) -> LoopOutcome:
    if reason not in _REASON_KEPT_WITHOUT_EVIDENCE and not state.accumulator.items:
        # 예산이 끝났든 충분하다고 판단했든, 근거가 없으면 기권이다(INV-EV-2).
        reason = TerminationReason.NO_EVIDENCE
    state.termination_reason = reason
    return LoopOutcome(reason=reason, state=state, detail=detail, notes=list(state.notes))
