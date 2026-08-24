"""§6.2 1층 — 골든셋을 **녹화 LLM**으로 돌려 결정론 지표를 채점한다.

CI에서 매 PR 돈다. 비용이 0이어야 하므로 실모델을 타지 않는다: `decide`·`extract`·`answer`
셋을 대본으로 대체하고, 도구·게이트·루프·검사기는 **실제 코드**를 그대로 지난다. 그래서 이
테스트가 잡는 것은 답변 품질이 아니라 배선과 불변식이다 — 품질은 2층 심판이 본다
(`tools/local/evidence_judge.py`, 수동).

여기서 대본을 쓰는 이유는 하나 더 있다. 골든셋의 값어치는 "이 지표를 재는 배선이 살아
있는가"에 있는데, 실모델을 쓰면 모델이 흔들릴 때마다 CI가 빨개져 그 신호가 묻힌다.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from backend.modules.evidence.adapters.tools import CorpusSearchTool
from backend.modules.evidence.domain.loop import LoopDeps, counter_probes, run_loop
from backend.modules.evidence.domain.models import (
    LoopState,
    TerminationReason,
    ToolCallOutcome,
    ToolCallRecord,
)
from backend.modules.evidence.eval import GOLDEN_CASES, QuestionType, score_turn
from backend.modules.evidence.eval.golden_set import labelled_cases, pending_review
from backend.modules.evidence.eval.layer1 import summarise
from backend.modules.evidence.models import to_turn_result
from backend.modules.evidence.ports.llm import AnswerSentence, ToolCallProposal
from backend.modules.evidence.ports.tools import (
    STANCE_COUNTER,
    TOOL_CORPUS_SEARCH,
    ToolRegistry,
)
from backend.modules.evidence.testing import (
    ScriptedAnswer,
    ScriptedLlm,
    accumulator,
    evidence_item,
    loop_budget,
    run_context,
)

# --- 실행 하네스 --------------------------------------------------------------
#
# `decide`·`answer`는 대역(`evidence.testing`)이고 도구·게이트·루프·검사기는 **실제 코드**를
# 그대로 지난다. 그래서 이 파일이 잡는 것은 답변 품질이 아니라 배선과 불변식이다.
# `decide` 대역은 주장·비교형에서 반대 측 탐색 한 번 뒤에 종료를 제안한다 — §3.3 바닥 2가
# 요구하는 최소 모양이다. 그 한 번이 0건이어도 된다("찾아본 뒤 없으면 그때 끝내도 된다").


class _NoHits:
    """검색은 돌지만 결과가 없다. 바닥 2가 묻는 것은 찾았는가가 아니라 찾아봤는가다."""

    def search(self, query, *, phrase=False, years=None):
        return ()


# 반대 측 조건이 붙는 유형(§3.3). 사실형·범위 밖은 면제라 대본도 달라야 한다.
_COUNTER_REQUIRED = {"claim", "comparison"}


def _run(case, *, papers: tuple[str, ...], answer=None) -> tuple[Any, LoopState]:
    state = LoopState(topic=case.question)
    if papers:
        # 게이트를 통과한 뒤의 상태 — 게이트 자체는 test_evidence_gate가 본다.
        state.accumulator = accumulator(
            *(
                evidence_item(f"{pid}가 그 주장을 뒷받침한다", paper_id=pid, anchor="s1.p1",
                              quote="a verbatim quote from the paper body", anchor_type=None)
                for pid in papers
            )
        )
    registry = ToolRegistry()
    registry.register(CorpusSearchTool(_NoHits(), state))
    script: list[Any] = []
    if case.expected_kind in _COUNTER_REQUIRED:
        script.append(
            ToolCallProposal(
                TOOL_CORPUS_SEARCH, {"query": case.question, "stance": STANCE_COUNTER}
            )
        )
    deps = LoopDeps(
        llm=ScriptedLlm(script=script, question_kind=case.expected_kind),
        registry=registry,
        budget=loop_budget(max_iterations=4, max_tool_calls_total=8, max_tool_calls={}),
        ctx=run_context(),
        answer=answer or ScriptedAnswer(),
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
    answer = ScriptedAnswer(script=[(AnswerSentence(text="대체로 그렇습니다"),)])

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


# --- 바닥 2: 반대 측 탐색(§3.3) ------------------------------------------------
#
# 픽스처를 "반대 측을 한 번 찾아보는 턴"으로 고쳤으므로, 그 조건이 **실제로 무는지**를
# 따로 본다. 안 그러면 픽스처만 통과시키고 검사는 아무것도 안 하는 상태로 초록이 된다.


def _claim_case():
    return next(c for c in GOLDEN_CASES if c.expected_kind == "claim")


def test_a_claim_turn_that_never_probed_the_counter_side_is_a_violation():
    case = _claim_case()
    result, state = _run(case, papers=("2106.09685",))
    # 선언을 지운다 = 반대 측을 한 번도 안 찾아본 턴.
    state.trace = [replace(r, stance=None) for r in state.trace]

    report = score_turn(case, result, trace=state.trace)

    assert report.counter_probes == 0
    assert any("counter" in v for v in report.violations)


def test_a_fact_turn_is_exempt_from_the_counter_condition():
    """사실형("X는 몇 년에 나왔어")에 반대 측을 요구하면 없는 대립을 찾게 만든다(§3.3)."""
    case = next(c for c in GOLDEN_CASES if c.expected_kind == "fact")

    result, state = _run(case, papers=("2201.11903",))
    report = score_turn(case, result, trace=state.trace)

    assert report.counter_probes == 0
    assert report.violations == []


def test_the_loop_refuses_to_finish_a_claim_turn_before_probing():
    """루프가 종료 제안을 물린다 — 채점만 위반으로 찍고 답은 나가면 검사가 사후 통보다."""
    case = _claim_case()
    state = LoopState(topic=case.question)
    state.accumulator = accumulator(
        evidence_item("근거", paper_id="2106.09685", anchor="s1.p1", quote="q", anchor_type=None)
    )
    llm = ScriptedLlm(question_kind="claim")  # 대본이 비어 매 회차 종료를 제안한다
    deps = LoopDeps(
        llm=llm,
        registry=ToolRegistry(),
        budget=loop_budget(max_iterations=3, max_tool_calls_total=8, max_tool_calls={}),
        ctx=run_context(),
        answer=ScriptedAnswer(),
    )

    outcome = run_loop(state, deps)

    assert outcome.reason is not TerminationReason.SUFFICIENT, "바닥 2 미달인데 정상 종료했다"
    assert any("counter" in note for note in state.notes), "거부 사유가 관찰에 실리지 않았다"
    # 사유를 안 실으면 모델은 같은 제안을 반복하고 그 반복이 예산을 태운다 — 노트가 그것을
    # 막는 유일한 장치이므로 노트의 존재가 곧 이 규칙의 구현이다.
    assert len(llm.observations) > 1


def test_a_denied_or_unknown_call_does_not_count_as_a_probe():
    """도구가 돌지 않은 호출에 선언만 붙이면 바닥이 열리는 공짜 통로가 된다."""
    case = _claim_case()
    state = LoopState(topic=case.question)
    state.accumulator = accumulator(
        evidence_item("근거", paper_id="2106.09685", anchor="s1.p1", quote="q", anchor_type=None)
    )
    deps = LoopDeps(
        llm=ScriptedLlm(
            script=[ToolCallProposal("no_such_tool", {"stance": STANCE_COUNTER})],
            question_kind="claim",
        ),
        registry=ToolRegistry(),
        budget=loop_budget(max_iterations=3, max_tool_calls_total=8, max_tool_calls={}),
        ctx=run_context(),
        answer=ScriptedAnswer(),
    )

    run_loop(state, deps)

    assert counter_probes(state.trace) == 0


def test_a_stance_on_a_tool_that_does_not_take_one_is_not_a_probe():
    """`read_paper`에 counter를 달아도 반대 측을 **찾은** 것은 아니다."""
    assert (
        counter_probes(
            [
                ToolCallRecord(
                    seq=1,
                    tool="read_paper",
                    args_summary="",
                    outcome=ToolCallOutcome.OK,
                    stance=STANCE_COUNTER,
                )
            ]
        )
        == 0
    )


def test_the_summary_measures_the_counter_rate_only_where_it_applies():
    """사실형·범위 밖을 분모에 넣으면 면제된 문항이 비율을 눌러, 지표가 반대 측 탐색이
    아니라 문항 구성을 반영하게 된다."""
    reports = []
    for case in labelled_cases():
        result, state = _run(case, papers=case.expected_papers or ("2106.09685",))
        reports.append(score_turn(case, result, trace=state.trace))

    summary = summarise(reports)

    assert summary["counter_probe_rate"] == 1.0
