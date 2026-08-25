"""§4.3 판단 문장 검사 — 강등 2종·거부 3종.

`answer`가 LLM 출력이 되면서 `assemble()`이 잃은 결정론이 이 모듈로 옮겨왔다(§4.4).
그래서 회귀 픽스처도 PBT도 여기 건다 — 답변 품질은 골든셋(§6)이 보고, 여기서는
"같은 답변·같은 근거면 같은 판정"만 본다.
"""

from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import (
    AnswerSegmentKind,
    AnswerSegmentRole,
    EvidenceItem,
)
from hypothesis import given
from hypothesis import strategies as st

from backend.modules.evidence.domain.answer_checks import (
    REJECT_NO_CITED_SENTENCE,
    REJECT_SYNTHESIS_RATIO,
    REJECT_UNKNOWN_PAPER,
    AnswerRejected,
    CheckedAnswer,
    check_answer,
)
from backend.modules.evidence.ports.llm import AnswerSentence
from backend.modules.evidence.testing import evidence_item


def _claim(statement: str, *, paper_id: str = "2310.11511", quote: str = "") -> EvidenceItem:
    return evidence_item(
        statement,
        paper_id=paper_id,
        record_ref=paper_id,
        anchor=None,
        quote=quote or statement,
        anchor_type=None,
    )


def _cited(text: str, *refs: int) -> AnswerSentence:
    return AnswerSentence(text=text, refs=refs)


def _synth(text: str) -> AnswerSentence:
    return AnswerSentence(text=text)


# --- 통과 ---------------------------------------------------------------------


def test_a_cited_sentence_backed_by_a_real_claim_passes():
    result = check_answer([_cited("데이터가 적을 때는 LoRA가 낫다", 1)], [_claim("LoRA wins")])

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 0
    assert result.answer.segments[0].kind is AnswerSegmentKind.cited
    assert result.answer.checks.fallback is False


def test_synthesis_sentences_are_allowed_under_the_ratio():
    result = check_answer(
        [_cited("A", 1), _synth("갈리는 지점은 도메인 거리다")], [_claim("LoRA wins")]
    )

    assert isinstance(result, CheckedAnswer)
    assert [s.kind for s in result.answer.segments] == [
        AnswerSegmentKind.cited,
        AnswerSegmentKind.synthesis,
    ]


# --- 강등(A1·A2) — 문장은 남고 표시만 잃는다 -----------------------------------


def test_a1_an_unknown_ref_number_demotes_the_sentence_not_the_answer():
    result = check_answer(
        [_cited("A", 1), _cited("B", 7)], [_claim("one"), _claim("two")]
    )

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 1
    assert result.answer.segments[1].kind is AnswerSegmentKind.synthesis
    assert result.answer.segments[1].refs == []
    assert result.answer.segments[1].text == "B", "강등은 문장을 지우지 않는다"


def test_kind_is_derived_from_refs_not_declared_by_the_model():
    """모델은 text와 refs만 낸다 — 번호가 없으면 그 자체로 종합 문장이다."""
    result = check_answer([_cited("A", 1), _synth("B")], [_claim("one")])

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 0, "번호를 안 붙인 것은 위반이 아니다"
    assert result.answer.segments[1].kind is AnswerSegmentKind.synthesis


def test_a2_a_number_absent_from_the_cited_claim_demotes_the_sentence():
    result = check_answer(
        [_cited("정확도가 99.9% 올랐다", 1), _cited("A", 1)],
        [_claim("accuracy improved by 2.1%")],
    )

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 1
    assert result.answer.segments[0].kind is AnswerSegmentKind.synthesis
    assert any("99.9" in reason for reason in result.demotion_reasons)


def test_a2_reuses_the_gate_number_equivalence():
    """0.953과 95.3%는 같은 수다 — 게이트가 이미 그렇게 판정한다."""
    result = check_answer(
        [_cited("정확도 95.3%", 1)], [_claim("accuracy reaches 0.953")]
    )

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 0


def test_a2_ignores_numbers_inside_names():
    """CASP14의 14나 AlphaFold2의 2는 수치가 아니다(게이트 `_NUMBER`와 같은 규칙)."""
    result = check_answer(
        [_cited("AlphaFold2는 CASP14에서 앞섰다", 1)], [_claim("the method wins")]
    )

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 0


# --- 거부(A3·A4·A5) — 답변 전체를 물린다 ---------------------------------------


def test_a3_a_paper_id_outside_the_evidence_is_rejected_not_demoted():
    """지어낸 논문은 표시를 낮춘다고 덜 위험해지지 않는다."""
    result = check_answer(
        [_cited("A", 1), _synth("2401.99999도 같은 결론이다")], [_claim("one")]
    )

    assert isinstance(result, AnswerRejected)
    assert result.code == REJECT_UNKNOWN_PAPER


def test_a3_accepts_the_cited_paper_written_without_its_version():
    result = check_answer(
        [_cited("2310.11511이 그렇게 보고한다", 1)],
        [_claim("one", paper_id="2310.11511v3")],
    )

    assert isinstance(result, CheckedAnswer)


def test_a4_an_answer_with_no_cited_sentence_is_rejected():
    result = check_answer([_synth("대체로 그런 편이에요")], [_claim("one")])

    assert isinstance(result, AnswerRejected)
    assert result.code == REJECT_NO_CITED_SENTENCE


def test_a4_fires_when_every_sentence_was_demoted():
    """강등이 쌓여 인용 문장이 0개가 되면 그 답변은 판단이 아니다."""
    result = check_answer([_cited("A", 9), _cited("B", 8)], [_claim("one")])

    assert isinstance(result, AnswerRejected)
    assert result.code == REJECT_NO_CITED_SENTENCE


def test_a5_too_many_synthesis_sentences_is_rejected():
    segments = [_cited("A", 1)] + [_synth(f"S{i}") for i in range(3)]

    result = check_answer(segments, [_claim("one")])

    assert isinstance(result, AnswerRejected)
    assert result.code == REJECT_SYNTHESIS_RATIO


def test_a5_boundary_exactly_at_the_limit_passes():
    """상한은 '넘으면 거부'다 — 정확히 50%는 통과한다."""
    result = check_answer([_cited("A", 1), _synth("S")], [_claim("one")])

    assert isinstance(result, CheckedAnswer)


# --- 결정론 -------------------------------------------------------------------


@given(
    texts=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=6),
    refs=st.lists(st.integers(min_value=-3, max_value=6), max_size=3),
)
def test_pbt_the_checker_is_deterministic(texts, refs):
    """같은 답변·같은 근거면 같은 판정 — 이것이 회귀 픽스처가 성립하는 근거다(§4.4)."""
    segments = [_cited(text, *refs) for text in texts]
    claims = [_claim("one"), _claim("two")]

    first = check_answer(segments, claims)
    second = check_answer(segments, claims)

    if isinstance(first, AnswerRejected):
        assert isinstance(second, AnswerRejected)
        assert (first.code, first.detail) == (second.code, second.detail)
    else:
        assert first.answer == second.answer  # `checks.demoted`까지 이 비교에 든다


@given(refs=st.lists(st.integers(min_value=-5, max_value=9), max_size=4))
def test_pbt_no_segment_ever_keeps_a_ref_outside_the_claim_range(refs):
    """A1의 불변식 — 통과한 답변에는 실재하지 않는 번호가 남지 않는다."""
    claims = [_claim("one"), _claim("two")]

    result = check_answer([_cited("A", *refs), _cited("B", 1)], claims)

    if isinstance(result, CheckedAnswer):
        for segment in result.answer.segments:
            assert all(1 <= n <= len(claims) for n in segment.refs)


# --- A3가 수치를 논문으로 오인하지 않는다 -------------------------------------------


def test_a3_does_not_read_a_four_dot_four_measurement_as_a_paper_id():
    """`1234.5678`은 논문이 아니다 — 신형 id의 앞 넷은 YYMM이라 달이 01~12여야 한다."""
    result = check_answer(
        [_cited("손실이 1234.5678로 떨어졌다", 1)], [_claim("loss drops to 1234.5678")]
    )

    assert isinstance(result, CheckedAnswer), "근거에 있는 수치가 답변째로 거부됐다"
    assert result.answer.checks.demoted == 0


def test_a3_treats_an_id_shaped_number_grounded_in_evidence_as_a_number():
    """`2401.5678`은 모양만으로는 갈리지 않는다 — 근거 수치 풀에 있으면 수치다."""
    result = check_answer(
        [_cited("정확도 2401.5678을 기록했다", 1)], [_claim("reaches 2401.5678")]
    )

    assert isinstance(result, CheckedAnswer)


def test_a3_still_catches_a_stray_id_before_a_sentence_ending_period():
    """가장 흔한 문장 모양 — 마침표가 바로 붙어도 지어낸 논문은 거부된다."""
    result = check_answer(
        [_cited("A", 1), _synth("같은 결론을 낸 것이 2401.99999.")], [_claim("one")]
    )

    assert isinstance(result, AnswerRejected)
    assert result.code == REJECT_UNKNOWN_PAPER


# --- A2가 인용 표기를 수치로 읽지 않는다 --------------------------------------------


def test_a2_ignores_an_inline_citation_marker():
    """`[1]`의 1은 수치가 아니다 — 게이트 숫자 정규식이 뽑는 것을 걷어낸다."""
    result = check_answer([_cited("LoRA가 낫다 [1]", 1)], [_claim("LoRA wins")])

    assert isinstance(result, CheckedAnswer)
    assert result.answer.checks.demoted == 0


def test_role_passes_through_unchecked_and_survives_demotion():
    """§4.2 — 검사 5종은 role을 보지 않는다.

    강등은 "기계가 확인했는가"를 낮추는 것이지 문장이 무엇을 하는지를 바꾸지 않는다.
    강등된 결론은 여전히 결론이고, 화면은 그것을 앞에 세우되 '종합' 배지를 함께 붙인다 —
    여기서 역할을 지우면 **강등된 답변만** 문단 구조를 잃는다.
    """
    checked = check_answer(
        [
            # refs가 없는 번호(A1) → 강등. 역할 선언은 그대로여야 한다.
            AnswerSentence(text="결론이지만 번호가 틀렸다", refs=(9,), role="conclusion"),
            AnswerSentence(text="받치는 근거", refs=(1,), role="evidence"),
            # 번호 붙은 문장을 하나 더 둔다 — 종합 비율이 A5(50%)를 넘으면 답변째로 거부되어
            # 이 테스트가 재는 것(역할 통과)에 닿지도 못한다.
            AnswerSentence(text="또 다른 근거", refs=(1,), role="evidence"),
            AnswerSentence(text="갈리는 지점", refs=(), role="divergence"),
        ],
        [_claim("근거 명제")],
    )

    assert isinstance(checked, CheckedAnswer)
    assert [s.role.value for s in checked.answer.segments] == [
        "conclusion",
        "evidence",
        "evidence",
        "divergence",
    ]
    assert checked.answer.segments[0].kind is AnswerSegmentKind.synthesis
    assert checked.answer.checks.demoted == 1


def test_a_sentence_without_a_role_reads_as_evidence_rather_than_vanishing():
    """선언이 없으면 산문이 평평해질 뿐이다 — 구조를 못 얻는 것과 문장이 사라지는 것은 다르다."""
    checked = check_answer([AnswerSentence(text="역할 없는 문장", refs=(1,))], [_claim("명제")])

    assert isinstance(checked, CheckedAnswer)
    assert checked.answer.segments[0].role is AnswerSegmentRole.evidence
