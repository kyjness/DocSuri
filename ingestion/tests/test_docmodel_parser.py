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

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel, parse_text_to_docmodel
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


def _body_sections(doc):
    return [section for section in doc.sections if section.id != "s0"]


def test_meta_and_provenance() -> None:
    doc = _parse()
    assert doc.meta.paperId == "2401.00001"
    assert doc.meta.version == 2
    assert doc.meta.abstract == "An abstract."
    assert doc.meta.provenance.sourceTier is SourceTier.ar5iv
    assert doc.meta.provenance.parserVersion == "docmodel-parser@1"


def test_full_text_projects_all_block_text_in_reading_order() -> None:
    doc = _parse()
    assert doc.fullText.split("\n\n") == [
        "Abstract",
        "An abstract.",
        "Introduction",
        "We study \\(x^{2}\\) models.",
        "Second paragraph.",
        "E = mc^{2}",
        "Table 1 Main results.",
        "Group | Acc",
        "A | B | 0.92",
        "Setup",
        "Sub paragraph.",
        "Figure 1 A plot.",
        "first",
        "second",
        "def f(): return 1",
        "Method",
        "Method text.",
    ]


def test_full_text_excludes_image_and_asset_internals() -> None:
    doc = _parse()
    assert "x.png" not in doc.fullText
    assert "assetId" not in doc.fullText
    assert asset_id("2401.00001", 2, AssetType.FIGURE, 0) not in doc.fullText


def test_nested_section_tree_and_ids() -> None:
    doc = _parse()
    sections = _body_sections(doc)
    assert [s.id for s in doc.sections] == ["s0", "s1", "s2"]
    assert doc.sections[0].title == "Abstract"
    assert doc.sections[0].blocks[0].root.text == "An abstract."
    assert sections[0].title == "Introduction"
    subs = sections[0].sections
    assert subs is not None and [s.id for s in subs] == ["s1.1"]
    assert subs[0].title == "Setup"


def test_html_abstract_section_does_not_duplicate_meta_abstract_embedding_source() -> None:
    html = """
    <html><body><article class="ltx_document">
     <section class="ltx_section"><h2>Abstract</h2>
      <div class="ltx_para"><p class="ltx_p">An abstract.</p></div>
     </section>
     <section class="ltx_section"><h2>Introduction</h2>
      <div class="ltx_para"><p class="ltx_p">Body.</p></div>
     </section>
    </article></body></html>
    """

    doc = _parse(html)

    assert [section.id for section in doc.sections] == ["s0", "s1"]
    assert [section.title for section in doc.sections] == ["Abstract", "Introduction"]
    assert doc.fullText.split("\n\n") == ["Abstract", "An abstract.", "Introduction", "Body."]


def test_paragraph_blocks_with_inline_math() -> None:
    doc = _parse()
    paras = [b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, ParagraphBlock)]
    assert [p.id for p in paras] == ["s1.p1", "s1.p2"]
    assert paras[0].text == "We study \\(x^{2}\\) models."


def test_formula_block_latex_and_anchor() -> None:
    doc = _parse()
    formula = next(b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, FormulaBlock))
    assert formula.id == "s1.eq1"
    assert formula.latex == "E = mc^{2}"
    assert formula.display is True
    assert formula.anchorLabel == "(1)"


def test_table_block_is_structured_data() -> None:
    doc = _parse()
    table = next(b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, TableBlock))
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
    sub = _body_sections(doc)[0].sections[0]
    figure = next(b for b in _blocks(sub) if isinstance(b, FigureBlock))
    assert figure.id == "s1.1.fig1"
    assert figure.anchorLabel == "Figure 1"
    assert figure.caption == "A plot."
    # Deterministic link to the FR-17 asset (re-extraction = 0).
    assert figure.assetRef.assetId == asset_id("2401.00001", 2, AssetType.FIGURE, 0)
    assert figure.assetRef.ordinal == 0


def test_subfigure_uses_own_caption_not_first_panel() -> None:
    """A figure with sub-panels takes its OWN "Figure N" caption, not the first panel's "(a)".

    LaTeXML emits each panel's "(a)/(b)" caption before the figure's own numbered caption; the
    parser must not mislabel the figure "(a)" (which also strips the number used to image it)."""
    panel = (
        '<figure class="ltx_figure"><img src="{src}"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">{tag} </span>{cap}</figcaption>'
        "</figure>"
    )
    own = (
        '<figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 4: </span>Overall result</figcaption>'
    )
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure">'
        + panel.format(src="panel_a.png", tag="(a)", cap="left")
        + panel.format(src="panel_b.png", tag="(b)", cap="right")
        + own
        + "</figure></section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00009", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    figure = next(
        b.root for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)
    )
    assert figure.anchorLabel == "Figure 4"  # NOT "(a)"
    assert figure.caption == "Overall result"
    assert specs[0].label == "Figure 4"  # numbered label flows to the asset extractor


def test_list_and_code_blocks() -> None:
    doc = _parse()
    sub = _body_sections(doc)[0].sections[0]
    list_block = next(b for b in _blocks(sub) if isinstance(b, ListBlock))
    assert list_block.ordered is True
    assert [i.text for i in list_block.items] == ["first", "second"]
    code_block = next(b for b in _blocks(sub) if isinstance(b, CodeBlock))
    assert code_block.text == "def f():\n    return 1"


def test_block_ids_reset_per_section() -> None:
    doc = _parse()
    method_paras = [b for b in _blocks(_body_sections(doc)[1]) if isinstance(b, ParagraphBlock)]
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
    sections = _body_sections(doc)
    assert [s.id for s in doc.sections] == ["s0", "s1", "s2"]
    appendix = sections[1]
    assert appendix.title == "Extra Details"
    assert appendix.sections is not None
    assert [s.title for s in appendix.sections] == ["Setup"]
    assert _blocks(appendix.sections[0])[0].text == "Appendix subsection text."


def test_footnote_excluded_from_paragraph_body() -> None:
    """An inline ltx_note (footnote) must not leak into the sentence text (it would corrupt
    the LLM input and the rich view)."""
    doc = _parse(APPENDIX_HTML)
    para = _blocks(_body_sections(doc)[0])[0]
    assert isinstance(para, ParagraphBlock)
    assert para.text == "We release the code for review."
    assert "example.org" not in para.text


def test_span_only_fallback_when_no_sections() -> None:
    html = '<html><body><div class="ltx_para"><p class="ltx_p">Just a note.</p></div></body></html>'
    doc = _parse(html)
    sections = _body_sections(doc)
    assert [s.id for s in doc.sections] == ["s0", "s1"]
    assert sections[0].title == ""
    para = _blocks(sections[0])[0]
    assert isinstance(para, ParagraphBlock)
    assert para.text == "Just a note."


def test_text_fallback_docmodel_has_stable_paragraph_block_ref() -> None:
    doc = parse_text_to_docmodel(
        "First line.\n\nSecond line.",
        paper_id="src-abc",
        version=1,
        title="PDF Only",
        abstract="PDF abstract.",
        source_tier=SourceTier.pdf,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )

    assert doc.fullText == "Abstract\n\nPDF abstract.\n\nFirst line. Second line."
    abstract_block = doc.sections[0].blocks[0].root
    assert abstract_block.id == "s0.p1"
    assert abstract_block.text == "PDF abstract."
    block = doc.sections[1].blocks[0].root
    assert isinstance(block, ParagraphBlock)
    assert block.id == "s1.p1"
    assert block.text == "First line. Second line."
    assert doc.meta.provenance.sourceTier is SourceTier.pdf
