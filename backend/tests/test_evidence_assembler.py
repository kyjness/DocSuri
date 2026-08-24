"""결과 조립 — 결정론, 빈 성공 금지, 확인 범위 표기."""

from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import (
    AnswerChecks,
    AnswerSegment,
    AnswerSegmentKind,
    EvidenceAnswer,
    EvidenceItem,
    SourceRef,
    SourceScope,
)

from backend.modules.evidence.domain.assembler import (
    ABSTAIN_CANCELLED,
    ABSTAIN_INSUFFICIENT,
    ABSTAIN_LLM_FAILURE,
    ABSTAIN_OUT_OF_CORPUS,
    assemble,
)
from backend.modules.evidence.domain.models import (
    LoopState,
    PaperHandle,
    PaperOrigin,
    TerminationReason,
)


def _item(paper_id="p1", conflicting=False) -> EvidenceItem:
    ref = SourceRef(
        paperId=paper_id,
        recordRef=f"r-{paper_id}",
        quote="AlphaFold2 | 92.4 | 87.0",
        sourceScope=SourceScope.fulltext,
    )
    return EvidenceItem(
        statement=f"claim about {paper_id}",
        supporting=[ref],
        conflicting=[SourceRef(paperId="p2", recordRef="r-p2")] if conflicting else [],
    )


def _state(items=(), examined=0, candidates=0) -> LoopState:
    state = LoopState(topic="q")
    state.accumulator.items.extend(items)
    for i in range(examined):
        pid = f"e{i}"
        state.papers[pid] = PaperHandle(pid, f"r-{pid}", PaperOrigin.CORPUS)
    state.candidates_seen.update(f"c{i}" for i in range(candidates))
    return state


def test_no_evidence_with_no_candidates_is_out_of_corpus():
    result = assemble(_state(), TerminationReason.NO_EVIDENCE)

    assert result.state == "abstain"
    assert result.abstainReason == ABSTAIN_OUT_OF_CORPUS


def test_no_evidence_after_finding_candidates_is_insufficient():
    """후보는 있었는데 근거를 못 뽑은 것 — 사용자에게 다른 행동을 시사한다."""
    result = assemble(_state(candidates=5), TerminationReason.NO_EVIDENCE)

    assert result.abstainReason == ABSTAIN_INSUFFICIENT


def test_fatal_error_abstains_as_llm_unavailable():
    result = assemble(_state(candidates=3), TerminationReason.FATAL_ERROR)

    assert result.abstainReason == ABSTAIN_LLM_FAILURE


def test_success_carries_the_examined_range():
    state = _state(items=[_item()], examined=5, candidates=12)

    result = assemble(state, TerminationReason.BUDGET_EXHAUSTED, query_used="protein")

    assert result.state == "ok"
    assert result.coverage.examined == 5
    assert result.coverage.candidates == 17  # 확인분 + 후보분
    assert result.coverage.stoppedReason.value == "budget_exhausted"
    assert result.coverage.queryUsed == "protein"


def test_terminal_state_stays_ok_when_the_search_was_truncated():
    """저하는 상태가 아니라 필드다 — D5 union을 늘리면 U12·FE 분기가 함께 는다."""
    result = assemble(_state(items=[_item()], examined=1), TerminationReason.BUDGET_EXHAUSTED)

    assert result.state == "ok"


def test_paper_count_counts_cited_papers_not_examined_ones():
    """coverage.paperCount는 '근거로 쓴' 논문 수다 — 열어본 수가 아니다."""
    state = _state(items=[_item("p1"), _item("p1")], examined=9)

    result = assemble(state, TerminationReason.SUFFICIENT)

    assert result.coverage.paperCount == 1


def test_conflicting_claims_come_first():
    state = _state(items=[_item("a"), _item("b", conflicting=True), _item("c")])

    result = assemble(state, TerminationReason.SUFFICIENT)

    assert result.claims[0].conflicting
    # 나머지는 원래 순서를 지킨다(안정 정렬).
    assert [c.statement for c in result.claims[1:]] == ["claim about a", "claim about c"]


def test_assembly_is_deterministic():
    state = _state(items=[_item("a"), _item("b", conflicting=True)], examined=2, candidates=4)

    first = assemble(state, TerminationReason.SUFFICIENT)
    second = assemble(state, TerminationReason.SUFFICIENT)

    assert first.model_dump() == second.model_dump()


def test_answer_falls_back_to_the_deterministic_narrative_without_a_judgement():
    """판단 노드가 안 돈 경로 — 답은 나가되 판단 없이(§4.3 폴백)."""
    state = _state(items=[_item("p1"), _item("p9", conflicting=True)])

    result = assemble(state, TerminationReason.SUFFICIENT)

    text = " ".join(segment.text for segment in result.answer.segments)
    assert "p1에서 확인됨" in text
    assert "다른 결과를 보고합니다" in text
    assert result.answer.checks.fallback is True
    assert all(s.kind is AnswerSegmentKind.synthesis for s in result.answer.segments), (
        "검사를 지나지 않은 문장에 '기계가 확인함' 표시를 줄 수 없다"
    )


def test_a_judgement_from_the_answer_node_wins_over_the_fallback():
    state = _state(items=[_item("p1")])
    state.answer = EvidenceAnswer(
        segments=[AnswerSegment(text="판단", refs=[1], kind=AnswerSegmentKind.cited)],
        checks=AnswerChecks(demoted=0, regenerated=False, fallback=False),
    )

    result = assemble(state, TerminationReason.SUFFICIENT)

    assert result.answer.checks.fallback is False
    assert result.answer.segments[0].text == "판단"


def test_answer_is_absent_when_there_is_nothing_to_summarise():
    result = assemble(_state(candidates=1), TerminationReason.NO_EVIDENCE)

    assert getattr(result, "answer", None) is None


def test_cancelled_with_evidence_is_a_partial_answer_marked_cancelled():
    state = _state(items=[_item()], examined=2, candidates=9)
    result = assemble(state, TerminationReason.CANCELLED)

    assert result.state == "ok"
    assert result.coverage.stoppedReason.value == "cancelled"
    assert (result.coverage.examined, result.coverage.candidates) == (2, 11)  # 확인분 포함


def test_cancelled_before_any_evidence_says_so():
    """취소는 근거 부족이 아니다 — 후보가 있었어도 '취소됨'으로 남는다."""
    result = assemble(_state(candidates=5), TerminationReason.CANCELLED)

    assert result.state == "abstain"
    assert result.abstainReason == ABSTAIN_CANCELLED


def test_interrupted_reads_as_partial_failure_not_cancel():
    ok = assemble(_state(items=[_item()]), TerminationReason.INTERRUPTED)
    assert ok.coverage.stoppedReason.value == "partial_failure"

    empty = assemble(_state(candidates=3), TerminationReason.INTERRUPTED)
    assert empty.abstainReason == ABSTAIN_INSUFFICIENT
