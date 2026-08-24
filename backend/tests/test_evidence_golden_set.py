"""§6.2 1층 — 골든셋을 **녹화 LLM**으로 돌려 결정론 지표를 채점한다.

CI에서 매 PR 돈다. 비용이 0이어야 하므로 실모델을 타지 않는다: `decide`·`extract`·`answer`
셋을 대본으로 대체하고, 도구·게이트·루프·검사기는 **실제 코드**를 그대로 지난다. 그래서 이
테스트가 잡는 것은 답변 품질이 아니라 배선과 불변식이다 — 품질은 2층 심판이 본다
(`tools/local/evidence_judge.py`, 수동).

여기서 대본을 쓰는 이유는 하나 더 있다. 골든셋의 값어치는 "이 지표를 재는 배선이 살아
있는가"에 있는데, 실모델을 쓰면 모델이 흔들릴 때마다 CI가 빨개져 그 신호가 묻힌다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest
from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceItem,
    SourceRef,
    SourceScope,
)

from backend.modules.evidence.domain.loop import LoopDeps, run_loop
from backend.modules.evidence.domain.models import (
    AgentRunContext,
    BudgetConsumed,
    EvidenceAccumulator,
    LoopBudget,
    LoopState,
)
from backend.modules.evidence.eval import GOLDEN_CASES, QuestionType, score_turn
from backend.modules.evidence.eval.golden_set import labelled_cases, pending_review
from backend.modules.evidence.eval.layer1 import summarise
from backend.modules.evidence.models import to_turn_result
from backend.modules.evidence.ports.llm import (
    AnswerDraft,
    AnswerSentence,
    LlmDecision,
    TerminationProposal,
)
from backend.modules.evidence.ports.tools import ToolRegistry

# --- 녹화 대역 ----------------------------------------------------------------


@dataclass
class RecordedLlm:
    """`decide` 대역 — 첫 턴에 곧바로 종료를 제안하고 질문 유형만 선언한다.

    탐색 자체는 다른 테스트가 본다. 여기서 필요한 것은 "종료 → 판단 → 마감" 꼬리가
    골든셋 문항마다 같은 모양으로 도는가다.
    """

    question_kind: str | None

    def decide(self, observation, tools) -> LlmDecision:  # noqa: ARG002
        return LlmDecision(
            proposal=TerminationProposal(note="done", question_kind=self.question_kind),
            cost_estimate_usd=0.001,
        )


@dataclass
class RecordedAnswer:
    """`answer` 대역 — 근거 번호를 붙인 문장 하나 + 종합 문장 하나."""

    sentences: tuple[AnswerSentence, ...] | None = None
    calls: list = field(default_factory=list)

    def write(self, request) -> AnswerDraft:
        self.calls.append(request)
        if self.sentences is not None:
            return AnswerDraft(sentences=self.sentences, cost_estimate_usd=0.01)
        numbers = tuple(view.number for view in request.evidence)
        return AnswerDraft(
            sentences=(
                AnswerSentence(text="근거가 이렇게 말한다", refs=numbers[:1]),
                AnswerSentence(text="갈리는 지점은 조건이다"),
            ),
            cost_estimate_usd=0.01,
        )


def _budget() -> LoopBudget:
    return LoopBudget(
        max_iterations=4,
        max_tool_calls_total=8,
        max_tool_calls={},
        token_cost_limit_usd=1.0,
        consumed=BudgetConsumed(),
    )


def _evidence(paper_ids: tuple[str, ...]) -> EvidenceAccumulator:
    """게이트를 통과한 뒤의 상태를 그대로 흉내낸다 — 게이트 자체는 test_evidence_gate가 본다."""
    return EvidenceAccumulator(
        items=[
            EvidenceItem(
                statement=f"{pid}가 그 주장을 뒷받침한다",
                supporting=[
                    SourceRef(
                        paperId=pid,
                        recordRef=f"rec-{pid}",
                        anchor="s1.p1",
                        quote="a verbatim quote from the paper body",
                        sourceScope=SourceScope.fulltext,
                    )
                ],
                conflicting=[],
            )
            for pid in paper_ids
        ]
    )


def _run(case, *, papers: tuple[str, ...], answer=None) -> tuple[Any, LoopState]:
    state = LoopState(topic=case.question)
    if papers:
        state.accumulator = _evidence(papers)
    deps = LoopDeps(
        llm=RecordedLlm(case.expected_kind),
        registry=ToolRegistry(),
        budget=_budget(),
        ctx=AgentRunContext(owner_id="o1", session_id="s1", turn_id="t1"),
        answer=answer or RecordedAnswer(),
    )
    outcome = run_loop(state, deps)
    result = to_turn_result(state, outcome.reason, query_used=case.question)
    return result.outcome, state


# --- 골든셋 자체의 모양 --------------------------------------------------------


def test_the_golden_set_keeps_all_six_question_types():
    """유형 하나가 빠지면 그 유형의 회귀는 영영 안 잡힌다(§6.1 균형)."""
    covered = {case.type for case in GOLDEN_CASES}

    assert covered == set(QuestionType)


def test_no_type_dominates_the_golden_set():
    counts = {t: sum(1 for c in GOLDEN_CASES if c.type is t) for t in QuestionType}

    assert max(counts.values()) <= len(GOLDEN_CASES) // 2, f"한 유형이 절반을 넘었다: {counts}"


def test_case_names_are_unique():
    names = [case.name for case in GOLDEN_CASES]

    assert len(names) == len(set(names))


def test_every_labelled_case_states_why_those_papers():
    """라벨만 남고 근거가 없으면 그것이 판단인지 추측인지 나중에 구분되지 않는다."""
    for case in labelled_cases():
        assert case.note.strip(), f"{case.name}: 정답 논문을 고른 이유가 비어 있다"
        assert case.expected_direction.strip(), f"{case.name}: 기대 판단 방향이 비어 있다"


def test_every_label_has_passed_human_review():
    """검수되지 않은 라벨로 잰 점수는 '내가 정한 정답으로 내가 채점한 값'이다.

    2026-08-24 검수 완료. 문항을 새로 넣으면 `reviewed=False`로 들어와 이 테스트가
    빨개진다 — 그게 의도다. 검수 없이 지표를 읽는 것을 막는 유일한 자리다.
    """
    assert pending_review() == (), (
        "검수되지 않은 라벨: " + ", ".join(c.name for c in pending_review())
    )


# --- 1층 채점 -----------------------------------------------------------------


@pytest.mark.parametrize(
    "case", [c for c in GOLDEN_CASES if c.expected_kind != "out_of_scope"], ids=lambda c: c.name
)
def test_layer1_reports_no_violation_for_a_well_formed_turn(case):
    """배선이 살아 있으면 위반이 0이다 — 이 테스트가 빨개지면 지표가 아니라 배관이 깨진 것이다."""
    papers = case.expected_papers or ("2106.09685",)
    result, state = _run(case, papers=papers)

    report = score_turn(
        case, result, trace=state.trace, rejections=dict(state.accumulator.rejections)
    )

    assert report.violations == []
    assert report.citation_reality == 1.0
    assert report.fallback is False


def test_recall_is_measured_only_where_labels_exist():
    labelled = next(c for c in labelled_cases() if c.type is QuestionType.CLAIM)
    unlabelled = next(
        c
        for c in GOLDEN_CASES
        if not c.expected_papers and c.expected_kind != "out_of_scope"
    )

    with_labels, state_a = _run(labelled, papers=labelled.expected_papers)
    without, state_b = _run(unlabelled, papers=("2106.09685",))

    assert score_turn(labelled, with_labels, trace=state_a.trace).recall_at_k == 1.0
    assert score_turn(unlabelled, without, trace=state_b.trace).recall_at_k is None


def test_recall_falls_when_the_expected_papers_are_missed():
    case = next(c for c in labelled_cases() if len(c.expected_papers) == 3)

    result, state = _run(case, papers=case.expected_papers[:1])

    assert score_turn(case, result, trace=state.trace).recall_at_k == pytest.approx(1 / 3)


def test_an_out_of_scope_question_must_not_search():
    """§2.4 — 비용을 쓰고 나서 '안 하겠다'는 길을 막는다."""
    case = next(c for c in GOLDEN_CASES if c.expected_kind == "out_of_scope")

    result, state = _run(case, papers=())

    report = score_turn(case, result, trace=state.trace)
    assert report.abstained is True
    assert report.searches == 0
    assert report.violations == []


def test_a_synthesis_only_answer_is_caught_as_a_fallback_not_a_pass():
    """검사가 거부한 판단은 폴백으로 떨어진다 — 지표에 그렇게 잡혀야 한다(§4.3)."""
    case = next(c for c in labelled_cases() if c.type is QuestionType.FACT)
    answer = RecordedAnswer(sentences=(AnswerSentence(text="대체로 그렇습니다"),))

    result, state = _run(case, papers=case.expected_papers, answer=answer)

    report = score_turn(case, result, trace=state.trace)
    assert report.fallback is True
    assert report.regenerated is True
    assert report.violations == [], "폴백은 fail-closed의 정상 경로이지 위반이 아니다"


def test_summary_keeps_search_and_answer_metrics_apart():
    """못 찾은 건지 찾고도 틀린 건지가 갈려야 고칠 곳이 보인다(§6.2)."""
    reports = []
    for case in labelled_cases():
        result, state = _run(case, papers=case.expected_papers or ("2106.09685",))
        reports.append(score_turn(case, result, trace=state.trace))

    summary = summarise(reports)

    assert summary["citation_reality"] == 1.0
    assert summary["recall_at_k"] is not None
    assert "violations" in summary and summary["violations"] == []
