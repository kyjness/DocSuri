"""DocModel parser (BR-30/TD-16, D1): LaTeXML HTML -> validated structured doc-model.

Exercises the deterministic mapping: nested section tree, deterministic block ids, tables as
DATA (rows/cols + colspan + header), formulas as LaTeX, figures linked to FR-17 webp assetIds,
lists, code, inline math, and the span-only fallback. The output is the pydantic ``DocModel``,
so a schema drift would fail these tests at validation time.
"""

from __future__ import annotations

from datetime import UTC, datetime

from docsuri_shared.dtos import (
    CodeBlock,
    FigureBlock,
    FormulaBlock,
    ListBlock,
    ParagraphBlock,
    SourceTier,
    TableBlock,
)

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.domain.assets import asset_id
from docsuri_ingestion.domain.enums import AssetType

_FIXED_TS = datetime(2026, 6, 23, 0, 0, tzinfo=UTC)

# A compact LaTeXML document exercising every block type and one level of nesting.
# (Newlines between tags are insignificant — the parser collapses inter-tag whitespace.)
LATEXML_HTML = """
<!DOCTYPE html><html><body><article class="ltx_document">
 <h1 class="ltx_title ltx_title_document">A Structured Paper</h1>
 <section class="ltx_section" id="S1">
  <h2 class="ltx_title ltx_title_section">
    <span class="ltx_tag ltx_tag_section">1 </span>Introduction</h2>
  <div class="ltx_para"><p class="ltx_p">We study
    <math alttext="x^{2}" class="ltx_Math">x2</math> models.</p></div>
  <div class="ltx_para"><p class="ltx_p">Second paragraph.</p></div>
  <table class="ltx_equation ltx_eqn_table"><tbody><tr>
    <td class="ltx_eqn_cell"><math display="block" alttext="E = mc^{2}">e</math></td>
    <td class="ltx_eqn_cell ltx_eqn_eqno">
      <span class="ltx_tag ltx_tag_equation">(1)</span></td>
  </tr></tbody></table>
  <figure class="ltx_table" id="S1.T1">
    <figcaption class="ltx_caption">
      <span class="ltx_tag ltx_tag_table">Table 1: </span>Main results.</figcaption>
    <table class="ltx_tabular">
      <thead class="ltx_thead"><tr class="ltx_tr">
        <th class="ltx_th" colspan="2">Group</th><th class="ltx_th">Acc</th>
      </tr></thead>
      <tbody class="ltx_tbody"><tr class="ltx_tr">
        <td class="ltx_td">A</td><td class="ltx_td">B</td><td class="ltx_td">0.92</td>
      </tr></tbody>
    </table>
  </figure>
  <section class="ltx_subsection" id="S1.SS1">
   <h3 class="ltx_title ltx_title_subsection"><span class="ltx_tag">1.1 </span>Setup</h3>
   <div class="ltx_para"><p class="ltx_p">Sub paragraph.</p></div>
   <figure class="ltx_figure" id="S1.F1"><img class="ltx_graphics" src="x.png"/>
     <figcaption class="ltx_caption">
       <span class="ltx_tag ltx_tag_figure">Figure 1: </span>A plot.</figcaption>
   </figure>
   <ol class="ltx_enumerate"><li class="ltx_item"><span class="ltx_tag">1. </span>first</li>
     <li class="ltx_item"><span class="ltx_tag">2. </span>second</li></ol>
   <div class="ltx_listing"><div class="ltx_listingline">def f():</div>
     <div class="ltx_listingline">    return 1</div></div>
  </section>
 </section>
 <section class="ltx_section" id="S2">
  <h2 class="ltx_title ltx_title_section">
    <span class="ltx_tag ltx_tag_section">2 </span>Method</h2>
  <div class="ltx_para"><p class="ltx_p">Method text.</p></div>
 </section>
</article></body></html>
"""


def _parse(html: str = LATEXML_HTML):
    return parse_html_to_docmodel(
        html,
        paper_id="2401.00001",
        version=2,
        title="A Structured Paper",
        abstract="An abstract.",
        source_tier=SourceTier.ar5iv,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )


def _blocks(section):
    return [b.root for b in section.blocks]


def test_meta_and_provenance() -> None:
    doc = _parse()
    assert doc.meta.paperId == "2401.00001"
    assert doc.meta.version == 2
    assert doc.meta.abstract == "An abstract."
    assert doc.meta.provenance.sourceTier is SourceTier.ar5iv
    assert doc.meta.provenance.parserVersion == "docmodel-parser@1"


def test_nested_section_tree_and_ids() -> None:
    doc = _parse()
    assert [s.id for s in doc.sections] == ["s1", "s2"]
    assert doc.sections[0].title == "Introduction"
    subs = doc.sections[0].sections
    assert subs is not None and [s.id for s in subs] == ["s1.1"]
    assert subs[0].title == "Setup"


def test_paragraph_blocks_with_inline_math() -> None:
    doc = _parse()
    paras = [b for b in _blocks(doc.sections[0]) if isinstance(b, ParagraphBlock)]
    assert [p.id for p in paras] == ["s1.p1", "s1.p2"]
    assert paras[0].text == "We study \\(x^{2}\\) models."


def test_formula_block_latex_and_anchor() -> None:
    doc = _parse()
    formula = next(b for b in _blocks(doc.sections[0]) if isinstance(b, FormulaBlock))
    assert formula.id == "s1.eq1"
    assert formula.latex == "E = mc^{2}"
    assert formula.display is True
    assert formula.anchorLabel == "(1)"


def test_table_block_is_structured_data() -> None:
    doc = _parse()
    table = next(b for b in _blocks(doc.sections[0]) if isinstance(b, TableBlock))
    assert table.id == "s1.tbl1"
    assert table.caption == "Main results."
    assert table.anchorLabel == "Table 1"
    # Header row: spanning header cell preserved, marked isHeader.
    header = table.rows[0].cells
    assert [c.text for c in header] == ["Group", "Acc"]
    assert header[0].isHeader is True
    assert header[0].colspan == 2
    # Data row carries the numbers verbatim (D8 — visible to the LLM, not a crop).
    assert [c.text for c in table.rows[1].cells] == ["A", "B", "0.92"]
    assert table.assetRef is None  # HTML tier: data, no crop image


def test_figure_links_existing_webp_asset_by_ordinal() -> None:
    doc = _parse()
    sub = doc.sections[0].sections[0]
    figure = next(b for b in _blocks(sub) if isinstance(b, FigureBlock))
    assert figure.id == "s1.1.fig1"
    assert figure.anchorLabel == "Figure 1"
    assert figure.caption == "A plot."
    # Deterministic link to the FR-17 asset (re-extraction = 0).
    assert figure.assetRef.assetId == asset_id("2401.00001", 2, AssetType.FIGURE, 0)
    assert figure.assetRef.ordinal == 0


def test_list_and_code_blocks() -> None:
    doc = _parse()
    sub = doc.sections[0].sections[0]
    list_block = next(b for b in _blocks(sub) if isinstance(b, ListBlock))
    assert list_block.ordered is True
    assert [i.text for i in list_block.items] == ["first", "second"]
    code_block = next(b for b in _blocks(sub) if isinstance(b, CodeBlock))
    assert code_block.text == "def f():\n    return 1"


def test_block_ids_reset_per_section() -> None:
    doc = _parse()
    method_paras = [b for b in _blocks(doc.sections[1]) if isinstance(b, ParagraphBlock)]
    assert method_paras[0].id == "s2.p1"  # s2 numbering independent of s1


def test_parse_is_deterministic() -> None:
    a = _parse().model_dump_json()
    b = _parse().model_dump_json()
    assert a == b


# An appendix (ltx_appendix) with a footnote (ltx_note) inlined in a body paragraph —
# mirrors real ar5iv output (e.g. BERT's "Appendix A" + footnote URLs).
APPENDIX_HTML = """
<!DOCTYPE html><html><body><article class="ltx_document">
 <section class="ltx_section" id="S1">
  <h2 class="ltx_title ltx_title_section"><span class="ltx_tag">1 </span>Main</h2>
  <div class="ltx_para"><p class="ltx_p">We release the code<span
    class="ltx_note ltx_role_footnote"><span class="ltx_tag">1</span>https://example.org/code
    </span> for review.</p></div>
 </section>
 <section class="ltx_appendix" id="A1">
  <h2 class="ltx_title ltx_title_appendix">
    <span class="ltx_tag">Appendix A </span>Extra Details</h2>
  <div class="ltx_para"><p class="ltx_p">Appendix intro.</p></div>
  <section class="ltx_subsection" id="A1.SS1">
   <h3 class="ltx_title ltx_title_subsection"><span class="ltx_tag">A.1 </span>Setup</h3>
   <div class="ltx_para"><p class="ltx_p">Appendix subsection text.</p></div>
  </section>
 </section>
</article></body></html>
"""


def test_appendix_is_top_level_section_with_nested_subsections() -> None:
    """ltx_appendix is a section: it stays a top-level node and keeps its subsections nested,
    rather than flattening them up into the body (FD Q2=B — appendices preserved)."""
    doc = _parse(APPENDIX_HTML)
    assert [s.id for s in doc.sections] == ["s1", "s2"]
    appendix = doc.sections[1]
    assert appendix.title == "Extra Details"
    assert appendix.sections is not None
    assert [s.title for s in appendix.sections] == ["Setup"]
    assert _blocks(appendix.sections[0])[0].text == "Appendix subsection text."


def test_footnote_excluded_from_paragraph_body() -> None:
    """An inline ltx_note (footnote) must not leak into the sentence text (it would corrupt
    the LLM input and the rich view)."""
    doc = _parse(APPENDIX_HTML)
    para = _blocks(doc.sections[0])[0]
    assert isinstance(para, ParagraphBlock)
    assert para.text == "We release the code for review."
    assert "example.org" not in para.text


def test_span_only_fallback_when_no_sections() -> None:
    html = '<html><body><div class="ltx_para"><p class="ltx_p">Just a note.</p></div></body></html>'
    doc = _parse(html)
    assert [s.id for s in doc.sections] == ["s1"]
    assert doc.sections[0].title == ""
    para = _blocks(doc.sections[0])[0]
    assert isinstance(para, ParagraphBlock)
    assert para.text == "Just a note."
