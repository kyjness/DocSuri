"""날조 검사 게이트(C-2, INV-EV-3/6) 단위 테스트 + 불변식(PBT-EV-6/8).

v1 대비 신설된 두 검사가 실제로 막는지를 중심으로 본다:
- 인용문이 앵커 블록 **밖**이면 탈락(v1은 문서 어딘가에 있으면 통과했다)
- 그림 해석 근거의 숫자가 논문 텍스트에 없으면 탈락
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.modules.evidence.domain.gate import (
    MIN_QUOTE_CHARS,
    PaperEvidenceSource,
    RejectReason,
    run_gate,
)
from backend.modules.evidence.domain.projection import (
    block_projection,
    iter_blocks,
    paper_projection,
)
from backend.tests.evidence_fakes import (
    FIGURE_CAPTION,
    INTRO,
    TABLE_ROW,
    doc_model,
)

PAPER = "2107.06xxx"
RECORD = "rec-1"
TITLE = "Highly accurate protein structure prediction with AlphaFold"



def _source(scope: str = "fulltext", *, title: str = TITLE) -> PaperEvidenceSource:
    doc = doc_model()
    blocks = {bid: (kind, text) for bid, kind, text in iter_blocks(doc)}
    return PaperEvidenceSource(
        paper_id=PAPER,
        record_ref=RECORD,
        scope=scope,
        text=paper_projection(doc),
        blocks=blocks,
        title=title,
    )


def _item(**ref: object) -> dict:
    base = {"paperId": PAPER, "sourceScope": "fulltext"}
    return {
        "statement": ref.pop("statement", "AlphaFold2 reaches 92.4 GDT on CASP14"),
        "supporting": [{**base, **ref}],
        "conflicting": [],
    }


# --- 통과 경로 ---------------------------------------------------------------


def test_table_row_quote_is_citable():
    """표 셀 수치 인용이 통과한다 — FR-47 확장의 핵심 사용 사례."""
    outcome = run_gate([_item(anchor="s4.tbl1", quote=TABLE_ROW)], {PAPER: _source()})

    assert len(outcome.items) == 1
    ref = outcome.items[0].supporting[0]
    assert ref.anchorType.value == "table"
    assert ref.sourceScope.value == "fulltext"


def test_caption_quote_is_citable():
    """v1에서 구조적으로 탈락하던 캡션 인용 — 프롬프트 표현과 대조 투영이 같아졌다."""
    outcome = run_gate(
        [_item(statement="Accuracy grows with training set size", anchor="s5.fig3",
               quote=FIGURE_CAPTION)],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1
    assert outcome.items[0].supporting[0].anchorType.value == "figure"


def test_formula_latex_is_citable():
    outcome = run_gate(
        [_item(statement="The loss is cross entropy", anchor="s2.eq1",
               quote="L = -\\sum_i y_i \\log p_i")],
        {PAPER: _source()},
    )
    assert len(outcome.items) == 1


# --- v2 신설 검사 -------------------------------------------------------------


def test_quote_outside_anchor_block_is_rejected():
    """표를 가리키면서 서론 문장을 인용하는 것 — v1은 통과시켰다."""
    outcome = run_gate([_item(anchor="s4.tbl1", quote=INTRO)], {PAPER: _source()})

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.QUOTE_OUTSIDE_ANCHOR] == 1


def test_fulltext_ref_without_anchor_is_rejected():
    """BR-EV-19/PBT-EV-8 — fulltext 출처는 반드시 앵커를 갖는다."""
    outcome = run_gate([_item(quote=TABLE_ROW)], {PAPER: _source()})

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.ANCHOR_MISSING] == 1


def test_unknown_anchor_is_rejected():
    outcome = run_gate([_item(anchor="s99.tbl9", quote=TABLE_ROW)], {PAPER: _source()})

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.ANCHOR_NOT_FOUND] == 1


def test_figure_scope_needs_a_figure_anchor():
    """표를 '그림 해석'이라고 선언해 인용문 검사를 우회하는 길을 막는다."""
    outcome = run_gate(
        [_item(statement="The trend is log-linear", sourceScope="figure", anchor="s4.tbl1")],
        {PAPER: _source()},
    )

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.ANCHOR_TYPE_MISMATCH] == 1


def test_figure_reading_without_quote_is_allowed():
    """그림 해석은 인용문이 없다 — 대신 범위가 표시된다."""
    outcome = run_gate(
        [_item(statement="Accuracy rises log-linearly with scale", sourceScope="figure",
               anchor="s5.fig3")],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1
    ref = outcome.items[0].supporting[0]
    assert ref.sourceScope.value == "figure"
    assert ref.quote is None


def test_figure_number_absent_from_paper_text_is_rejected():
    """차트에서 눈으로 읽은 수치의 날조 — BLM §3 검사 6."""
    outcome = run_gate(
        [_item(statement="The curve peaks at 99.9 accuracy", sourceScope="figure",
               anchor="s5.fig3")],
        {PAPER: _source()},
    )

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.NUMBER_NOT_GROUNDED] == 1


def test_figure_number_present_in_paper_text_is_allowed():
    outcome = run_gate(
        [_item(statement="The best method reaches 92.4", sourceScope="figure", anchor="s5.fig3")],
        {PAPER: _source()},
    )
    assert len(outcome.items) == 1


# --- v1 승계 검사 -------------------------------------------------------------


def test_fabricated_quote_is_rejected():
    outcome = run_gate(
        [_item(anchor="s4.tbl1", quote="AlphaFold2 achieved a perfect score of 100.0")],
        {PAPER: _source()},
    )
    assert outcome.rejections[RejectReason.QUOTE_NOT_VERBATIM] == 1


def test_short_quote_is_rejected():
    outcome = run_gate([_item(anchor="s4.tbl1", quote="92.4")], {PAPER: _source()})
    assert outcome.rejections[RejectReason.QUOTE_TOO_SHORT] == 1


def test_statement_number_absent_from_quotes_is_rejected():
    outcome = run_gate(
        [_item(statement="AlphaFold2 reaches 95.1 GDT", anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )
    assert outcome.rejections[RejectReason.NUMBER_NOT_GROUNDED] == 1


def test_unknown_paper_is_rejected():
    outcome = run_gate(
        [{"statement": "x", "supporting": [{"paperId": "other", "quote": TABLE_ROW}]}],
        {PAPER: _source()},
    )
    assert outcome.rejections[RejectReason.UNKNOWN_PAPER] == 1


# --- 초록 범위 ---------------------------------------------------------------

ABSTRACT = (
    "We present AlphaFold2, which achieves 92.4 GDT on CASP14 targets and "
    "substantially improves over prior methods."
)


def _abstract_source() -> PaperEvidenceSource:
    return PaperEvidenceSource(
        paper_id="arxiv:2401.00001v2",
        record_ref="external:arxiv:2401.00001v2",
        scope="abstract",
        text=ABSTRACT,
    )


def test_abstract_scope_quote_is_citable_without_anchor():
    outcome = run_gate(
        [{
            "statement": "AlphaFold2 achieves 92.4 GDT",
            "supporting": [{
                "paperId": "arxiv:2401.00001v2",
                "sourceScope": "abstract",
                "quote": "achieves 92.4 GDT on CASP14 targets",
            }],
            "conflicting": [],
        }],
        {"arxiv:2401.00001v2": _abstract_source()},
    )

    assert len(outcome.items) == 1
    ref = outcome.items[0].supporting[0]
    assert ref.sourceScope.value == "abstract"
    assert ref.anchor is None


def test_declared_fulltext_is_demoted_when_only_abstract_was_fetched():
    """선언은 의도일 뿐 확보 사실이 권위다 — 앵커 없는 초록 인용으로 강등된다."""
    outcome = run_gate(
        [{
            "statement": "AlphaFold2 achieves 92.4 GDT",
            "supporting": [{
                "paperId": "arxiv:2401.00001v2",
                "sourceScope": "fulltext",
                "quote": "achieves 92.4 GDT on CASP14 targets",
            }],
            "conflicting": [],
        }],
        {"arxiv:2401.00001v2": _abstract_source()},
    )

    assert outcome.items[0].supporting[0].sourceScope.value == "abstract"


def test_anchor_on_abstract_scope_is_rejected():
    """DocModel이 없는데 앵커를 내보내면 FE 이동 링크가 반드시 깨진다."""
    outcome = run_gate(
        [{
            "statement": "AlphaFold2 achieves 92.4 GDT",
            "supporting": [{
                "paperId": "arxiv:2401.00001v2",
                "sourceScope": "abstract",
                "anchor": "s1.p1",
                "quote": "achieves 92.4 GDT on CASP14 targets",
            }],
            "conflicting": [],
        }],
        {"arxiv:2401.00001v2": _abstract_source()},
    )

    assert outcome.rejections[RejectReason.ANCHOR_ON_ABSTRACT] == 1


# --- 투영 정합 ---------------------------------------------------------------


def test_projection_is_shared_between_prompt_and_gate():
    """게이트가 대조하는 문자열은 프롬프트가 싣는 것과 **같은 함수**에서 나온다.

    v1은 캡션을 프롬프트에서 "Figure 3: ...", 투영에서 "Figure 3 ..."로 만들어
    캡션 인용이 구조적으로 탈락했다. 두 표현이 갈라지지 않는지 고정한다.
    """
    doc = doc_model()
    figure = doc.sections[0].blocks[2]

    projected = block_projection(figure)

    assert projected == FIGURE_CAPTION
    assert projected in paper_projection(doc)


# --- 불변식 (PBT-EV-6 / PBT-EV-8) --------------------------------------------


@given(
    statement=st.text(min_size=1, max_size=120),
    quote=st.text(max_size=200),
    anchor=st.sampled_from(["s1.p1", "s4.tbl1", "s5.fig3", "s2.eq1", "s9.zz9", ""]),
    scope=st.sampled_from(["fulltext", "abstract", "figure", "", "bogus"]),
)
def test_pbt_ev6_accepted_refs_always_pass_block_check(statement, quote, anchor, scope):
    """PBT-EV-6 — 어떤 LLM 출력에도 통과한 근거는 앵커 블록 대조를 만족한다."""
    source = _source()
    outcome = run_gate(
        [{
            "statement": statement,
            "supporting": [{
                "paperId": PAPER, "anchor": anchor, "quote": quote, "sourceScope": scope,
            }],
            "conflicting": [],
        }],
        {PAPER: source},
    )

    for item in outcome.items:
        for ref in item.supporting:
            if ref.sourceScope.value == "figure":
                continue
            assert ref.anchor in source.blocks
            _, block_text = source.blocks[ref.anchor]
            assert ref.quote and ref.quote in block_text
            assert len(ref.quote) >= MIN_QUOTE_CHARS


@given(
    scope=st.sampled_from(["fulltext", "abstract", "figure", ""]),
    anchor=st.sampled_from(["s4.tbl1", "s5.fig3", ""]),
)
def test_pbt_ev8_fulltext_refs_always_carry_an_anchor(scope, anchor):
    """PBT-EV-8 — sourceScope=fulltext 출처는 반드시 DocModel 앵커를 갖는다."""
    outcome = run_gate(
        [{
            "statement": "AlphaFold2 reaches 92.4 GDT",
            "supporting": [{
                "paperId": PAPER, "anchor": anchor, "quote": TABLE_ROW, "sourceScope": scope,
            }],
            "conflicting": [],
        }],
        {PAPER: _source()},
    )

    for item in outcome.items:
        for ref in item.supporting:
            if ref.sourceScope.value == "fulltext":
                assert ref.anchor
                assert ref.anchorType is not None


@pytest.mark.parametrize("raw", [[], [{}], [{"statement": "   "}]])
def test_empty_input_never_produces_items(raw):
    assert run_gate(raw, {PAPER: _source()}).items == ()


def test_identifier_digits_are_not_treated_as_measurements():
    """"CASP14"의 14, "AlphaFold2"의 2는 수치가 아니다.

    v1 정규식은 이것들을 수치로 세어, 인용문이 같은 이름을 담고 있지 않으면
    정상 근거를 통째로 버렸다(AI/ML 문장에서 흔한 형태다).
    """
    outcome = run_gate(
        [_item(statement="On CASP14 the AlphaFold2 system reaches 92.4 GDT",
               anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1


def test_real_measurement_still_has_to_be_grounded():
    """식별자 숫자를 뺀다고 측정값 검사가 느슨해지지는 않는다."""
    outcome = run_gate(
        [_item(statement="On CASP14 it reaches 95.1 GDT", anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert outcome.rejections[RejectReason.NUMBER_NOT_GROUNDED] == 1


# --- 숫자 표기 정규화 (u7 grounding 규칙 이식) --------------------------------
#
# 인용문(TABLE_ROW)의 92.4에 대해 statement가 어떤 표기까지 쓸 수 있는가.
# 등가 표기(정확 ×100/÷100)와 같은 스케일의 반올림은 인정하고, 스케일을
# 건너뛴 반올림은 u7의 반례(정수 "20" ↔ 연도 "2020")대로 계속 막는다.


def test_fraction_notation_of_a_quoted_percent_is_grounded():
    """논문이 92.4로 적은 값을 statement가 0.924로 써도 같은 수다."""
    outcome = run_gate(
        [_item(statement="It reaches a GDT fraction of 0.924",
               anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1


def test_percent_sign_variant_of_a_quoted_number_is_grounded():
    outcome = run_gate(
        [_item(statement="It reaches 92.4% on the benchmark",
               anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1


def test_rounding_at_the_statements_own_precision_is_grounded():
    """정수로 쓴 92는 인용문의 92.4에 근거한다(자릿수 기반 허용 폭)."""
    outcome = run_gate(
        [_item(statement="It reaches roughly 92 GDT", anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert len(outcome.items) == 1


def test_cross_scale_rounding_stays_rejected():
    """0.92는 92.4의 ÷100 반올림 — 스케일 교차에 허용 폭을 얹으면 무관한 값이
    우연 매칭되므로(u7 반례: "20" ↔ "2020") 계속 fail-closed다."""
    outcome = run_gate(
        [_item(statement="It reaches a fraction of 0.92", anchor="s4.tbl1", quote=TABLE_ROW)],
        {PAPER: _source()},
    )

    assert outcome.rejections[RejectReason.NUMBER_NOT_GROUNDED] == 1


def test_malformed_refs_are_rejected_not_crashed():
    """모델이 출처를 문자열로 돌려주는 일이 실제로 있다(로컬 실측).

    게이트가 여기서 터지면 턴 전체가 죽는다 — 잘못된 LLM 출력은 예상 입력이다.
    """
    outcome = run_gate(
        [
            {"statement": "s", "supporting": ["2107.06xxx", 42, None], "conflicting": []},
            "이 항목 자체가 문자열",
        ],
        {PAPER: _source()},
    )

    assert outcome.items == ()
    assert outcome.rejections[RejectReason.MALFORMED_REF] >= 3


def test_paper_id_notation_drift_is_absorbed_but_unknown_papers_are_not():
    """접두어·버전 표기가 흔들려도 확보한 논문이면 인용이 산다 — 없는 논문은 여전히 없다."""
    for written in (PAPER, f"arxiv:{PAPER}", f"{PAPER}v3", PAPER.upper()):
        item = _item(anchor="s4.tbl1", quote=TABLE_ROW)
        item["supporting"][0]["paperId"] = written
        accepted = run_gate([item], {PAPER: _source()}).items

        assert len(accepted) == 1, written
        # 표기가 무엇이든 결과는 확보분의 id로 정규화된다.
        assert accepted[0].supporting[0].paperId == PAPER

    ghost = _item(anchor="s4.tbl1", quote=TABLE_ROW)
    ghost["supporting"][0]["paperId"] = "9999.99999"
    assert run_gate([ghost], {PAPER: _source()}).rejections[RejectReason.UNKNOWN_PAPER] == 1


# --- 표시용 제목 -------------------------------------------------------------


def test_passing_ref_carries_the_paper_title_so_the_screen_can_name_the_source() -> None:
    """제목이 없으면 근거 목록에 `arxiv:2106.09685v2` 같은 식별자만 남는다.

    출처를 만드는 자리는 게이트 하나다 — 조립 단계에서 다시 붙이면 핸들 맵을 한 벌 더 들고
    다녀야 하고, 그 맵이 비면 **제목만** 조용히 사라진다(화면에서는 id로 보인다).
    """
    outcome = run_gate([_item(anchor="s4.tbl1", quote=TABLE_ROW)], {PAPER: _source()})

    assert outcome.items
    assert outcome.items[0].supporting[0].title == TITLE


def test_a_paper_without_a_title_carries_none_rather_than_an_empty_string() -> None:
    """빈 문자열을 실으면 화면이 "제목이 있다"로 읽고 빈 링크를 그린다."""
    outcome = run_gate(
        [_item(anchor="s4.tbl1", quote=TABLE_ROW)], {PAPER: _source(title="")}
    )

    assert outcome.items
    assert outcome.items[0].supporting[0].title is None
