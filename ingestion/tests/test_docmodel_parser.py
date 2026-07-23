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


def test_paragraph_inside_a_minipage_is_a_span_and_is_still_kept() -> None:
    """Inside a minipage / inline-sectional block LaTeXML emits the paragraph as
    ``<span class="ltx_p">`` — HTML forbids ``<p>`` there. Requiring the tag name dropped that
    text, leaving titled subsections ("Finding 1:", "Assumption 1:") with no blocks at all."""
    html = """
    <!DOCTYPE html><html><body><article class="ltx_document">
     <section class="ltx_section" id="S1">
      <h2 class="ltx_title ltx_title_section">Results</h2>
      <section class="ltx_paragraph" id="S1.Px1">
       <h5 class="ltx_title ltx_title_paragraph">Finding 1:</h5>
       <span class="ltx_para"><span class="ltx_p">Page views declined slightly.</span></span>
      </section>
     </section>
    </article></body></html>
    """
    doc = _parse(html)
    finding = _body_sections(doc)[0].sections[0]
    assert finding.title == "Finding 1:"
    assert [b.root.text for b in finding.blocks] == ["Page views declined slightly."]


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
    # Multi-panel: src is blanked so the asset extractor page-crops the WHOLE figure (all panels)
    # instead of imaging only the first sub-panel's e-print graphic.
    assert specs[0].src == ""


def test_two_numbered_floats_sharing_one_container_stay_two_figures() -> None:
    """Two figures set side by side share one <figure> container, each panel carrying its own
    numbered caption. Reading the container as one figure dropped the second from the document and
    left the first with no label, so it could not be matched to a page-crop either."""
    panel = (
        '<figure class="ltx_figure ltx_figure_panel"><img src="{src}"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">{tag} </span>{cap}</figcaption>'
        "</figure>"
    )
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure">'
        + panel.format(src="left.png", tag="Figure 7 :", cap="Effect of batch size")
        + panel.format(src="right.png", tag="Figure 8 :", cap="Effect of z loss")
        + "</figure></section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00011", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    figures = [b.root for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)]
    assert [f.anchorLabel for f in figures] == ["Figure 7", "Figure 8"]
    assert [f.caption for f in figures] == ["Effect of batch size", "Effect of z loss"]
    # Each panel is its own float, so each keeps its own e-print graphic rather than being blanked.
    assert [(s.label, s.src) for s in specs] == [
        ("Figure 7", "left.png"),
        ("Figure 8", "right.png"),
    ]


def test_uncaptioned_logo_strip_makes_no_figure_block() -> None:
    """A float with several images and NO caption is decoration (a funder/logo strip). Nothing
    could ever image it — no caption number for a page-crop, no single src for the e-print — so
    emitting a block only mints an assetRef that must dangle."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Intro</h2>'
        '<figure class="ltx_figure"><img src="funder_a.png"/><img src="funder_b.png"/></figure>'
        "</section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00012", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    assert [b for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)] == []
    assert specs == []


def _parse_custom(html: str, specs: list | None = None):
    return parse_html_to_docmodel(
        html, paper_id="2401.00099", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs if specs is not None else [],
    )


def test_captioned_figure_outside_any_section_is_recovered() -> None:
    """LaTeXML hoists a teaser figure above the first section, directly under ltx_document. The
    section-only walk dropped it whole — caption, number and graphic — so it is collected into a
    lead section ahead of the body it precedes, and the body sections number after it."""
    html = (
        '<html><body><div class="ltx_document">'
        '<figure class="ltx_figure"><img src="teaser.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">Figure 1: </span>'
        "Teaser overview</figcaption></figure>"
        '<section class="ltx_section"><h2>1 Intro</h2>'
        '<div class="ltx_para"><p class="ltx_p">Body text.</p></div></section>'
        "</div></body></html>"
    )
    specs: list = []
    doc = _parse_custom(html, specs)
    figures = [b.root for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)]
    assert [(f.anchorLabel, f.caption) for f in figures] == [("Figure 1", "Teaser overview")]
    assert [s.label for s in specs] == ["Figure 1"]
    # the recovered float leads; the body section follows it
    body = _body_sections(doc)
    assert body[0].id == "s1" and not body[0].title  # lead section holding the teaser
    assert body[1].id == "s2" and body[1].title == "1 Intro"


def test_caption_of_graphicless_float_outside_section_reaches_full_text() -> None:
    """An orphan float whose \\includegraphics LaTeXML could not render (no <img>) still carries a
    caption; recovering it preserves that text even though no figure block/assetRef is minted."""
    html = (
        '<html><body><div class="ltx_document">'
        '<figure class="ltx_figure">'
        '<figcaption class="ltx_caption"><span class="ltx_tag">Figure 1: </span>'
        "We visualize edits made by our model</figcaption></figure>"
        '<section class="ltx_section"><h2>1 Intro</h2>'
        '<div class="ltx_para"><p class="ltx_p">Body text.</p></div></section>'
        "</div></body></html>"
    )
    doc = _parse_custom(html)
    assert "We visualize edits made by our model" in doc.fullText


def test_uncaptioned_float_outside_section_is_not_recovered() -> None:
    """A stray image with no caption of its own outside every section is decoration — there is no
    number to reference it, so it is left dropped and the body keeps its s1.. numbering."""
    html = (
        '<html><body><div class="ltx_document">'
        '<figure class="ltx_figure"><img src="logo.png"/></figure>'
        '<section class="ltx_section"><h2>1 Intro</h2>'
        '<div class="ltx_para"><p class="ltx_p">Body text.</p></div></section>'
        "</div></body></html>"
    )
    doc = _parse_custom(html)
    body = _body_sections(doc)
    assert [s.id for s in body] == ["s1"]
    assert body[0].title == "1 Intro"  # no lead section was inserted


def test_panel_group_whose_number_sits_in_a_sibling_float_is_kept() -> None:
    """LaTeXML can wrap a numbered figure's panels in an outer float and leave the "Figure 5:"
    caption in a sibling float (arXiv:2510.23156). The group then has no caption of its own and
    reads exactly like a logo strip — but its panels are captioned, and dropping it deletes a real
    figure, which is the one outcome the strip rule exists to avoid causing."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure">'
        '<figure class="ltx_figure ltx_figure_panel"><img src="ps.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">(a) </span>PS</figcaption></figure>'
        '<figure class="ltx_figure ltx_figure_panel"><img src="loso.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">(b) </span>LOSO</figcaption>'
        "</figure>"
        '</figure>'
        "</section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00013", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    figures = [b for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)]
    assert len(figures) == 1


def test_mixed_float_decomposes_into_table_and_figure() -> None:
    """One caption-less ltx_figure can pack a TABLE minipage, a panel group and the group's
    caption-only "Figure 5" float (arXiv:2510.23156, S4.SS2.fig3). Read as a single figure it
    became one unlabeled block: the table's rows and caption vanished and the figure number was
    lost, so its page-crop could never be matched. The float must decompose into flat siblings.
    The table minipage's caption tag carries class ltx_tag_figure — LaTeXML mislabels it, so the
    tag TEXT ("TABLE III") is the signal."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>4 Results</h2>'
        '<figure class="ltx_figure">'
        '<figure class="ltx_figure ltx_minipage">'
        '<figcaption class="ltx_caption"><span class="ltx_tag ltx_tag_figure">TABLE III: </span>'
        "Selected model configurations.</figcaption>"
        '<table class="ltx_tabular">'
        '<tr class="ltx_tr"><th class="ltx_th">Model</th>'
        '<th class="ltx_th"><table class="ltx_tabular">'
        '<tr class="ltx_tr"><td class="ltx_td">Acc</td></tr>'
        '<tr class="ltx_tr"><td class="ltx_td">up</td></tr></table></th></tr>'
        '<tr class="ltx_tr"><td class="ltx_td">CNN</td><td class="ltx_td">0.91</td></tr>'
        "</table></figure>"
        '<figure class="ltx_figure ltx_minipage">'
        '<figure class="ltx_figure ltx_figure_panel"><img src="x6.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">(a) </span>PS</figcaption></figure>'
        '<figure class="ltx_figure"><img src="x8.png"/>'  # sf3 carries no ltx_figure_panel class
        '<figcaption class="ltx_caption"><span class="ltx_tag">(c) </span>LOSO</figcaption>'
        "</figure>"
        '<figure class="ltx_figure"><figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 5: </span>Confusion matrices.</figcaption></figure>'
        "</figure>"
        "</figure></section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2510.23156", version=2, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    section = doc.sections[-1]
    typed = [b.root for b in section.blocks]
    assert [type(b) for b in typed] == [TableBlock, FigureBlock]
    table, figure = typed
    assert table.anchorLabel == "TABLE III"
    assert "Selected model configurations." in (table.caption or "")
    assert len(table.rows) == 2  # header + data — nested header mini-table stays filtered
    assert "Acc" in table.rows[0].cells[1].text
    assert figure.anchorLabel == "Figure 5"
    assert figure.caption == "Confusion matrices."
    assert [(s.src, s.label) for s in specs] == [("", "Figure 5")]  # multi-panel: src blanked
    assert doc.fullText.count("Confusion matrices.") == 1  # adopted caption is not re-emitted


def test_declared_table_float_inside_figure_outer_decomposes_too() -> None:
    """The decomposition also fires when the table child is a DECLARED ``figure.ltx_table`` (not
    a mislabelled minipage): a caption-less ltx_figure outer sharing a table float and a captioned
    figure must yield one TableBlock and one FigureBlock, not one unlabeled figure."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure">'
        '<figure class="ltx_table">'
        '<figcaption class="ltx_caption"><span class="ltx_tag ltx_tag_table">Table 2: </span>'
        "Latency.</figcaption>"
        '<table class="ltx_tabular"><tr class="ltx_tr"><td class="ltx_td">1ms</td></tr></table>'
        "</figure>"
        '<figure class="ltx_figure"><img src="plot.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">Figure 3: </span>A plot'
        "</figcaption></figure>"
        "</figure>"
        "</section></div></body></html>"
    )
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00014", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )
    typed = [b.root for s in doc.sections for b in s.blocks]
    assert [type(b) for b in typed] == [TableBlock, FigureBlock]
    assert typed[0].anchorLabel == "Table 2"
    assert typed[1].anchorLabel == "Figure 3"


def test_panel_group_adopts_caption_from_caption_only_sibling_float() -> None:
    """The detached "Figure 5:" caption float inside a caption-less panel group must become the
    group's anchorLabel/caption — with an empty label the FigureSpec could never be matched to
    its page-crop, and the figure asset went missing (arXiv:2510.23156, figure:4)."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure">'
        '<figure class="ltx_figure ltx_figure_panel"><img src="ps.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">(a) </span>PS</figcaption></figure>'
        '<figure class="ltx_figure ltx_figure_panel"><img src="loso.png"/>'
        '<figcaption class="ltx_caption"><span class="ltx_tag">(b) </span>LOSO</figcaption>'
        "</figure>"
        '<figure class="ltx_figure"><figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 5: </span>Confusion matrices.</figcaption></figure>'
        "</figure>"
        "</section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2510.23156", version=2, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    figures = [b.root for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)]
    assert len(figures) == 1
    assert figures[0].anchorLabel == "Figure 5"
    assert figures[0].caption == "Confusion matrices."
    assert [(s.src, s.label) for s in specs] == [("", "Figure 5")]


def test_single_image_figure_keeps_eprint_src() -> None:
    """A single-image figure keeps its <img src> so the asset extractor images the
    original-quality e-print graphic (the blank-src page-crop path is multi-panel only)."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Results</h2>'
        '<figure class="ltx_figure"><img src="plot.png"/>'
        '<figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 1: </span>A plot</figcaption>'
        "</figure></section></div></body></html>"
    )
    specs: list = []
    parse_html_to_docmodel(
        html, paper_id="2401.00010", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    assert specs[0].src == "plot.png"
    assert specs[0].label == "Figure 1"


def test_list_and_code_blocks() -> None:
    doc = _parse()
    sub = _body_sections(doc)[0].sections[0]
    list_block = next(b for b in _blocks(sub) if isinstance(b, ListBlock))
    assert list_block.ordered is True
    assert [i.text for i in list_block.items] == ["first", "second"]
    code_block = next(b for b in _blocks(sub) if isinstance(b, CodeBlock))
    assert code_block.text == "def f():\n    return 1"


def test_algorithm_listing_line_numbers_and_soft_wrap() -> None:
    """An algorithm float's numbered listing lines get their number split off with a space
    (not glued "1:Flow"), and an author soft-wrap inside one numbered step is folded to one line."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Method</h2>'
        '<div class="ltx_float ltx_float_algorithm">'
        '<div class="ltx_listing">'
        '<div class="ltx_listingline">'
        '<span class="ltx_tag ltx_tag_listingline">1:</span>Require model,\nlearning rate</div>'
        '<div class="ltx_listingline">'
        '<span class="ltx_tag ltx_tag_listingline">2:</span> return x</div>'
        "</div></div></section></div></body></html>"
    )
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00011", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )
    code = next(
        b.root for s in doc.sections for b in s.blocks if isinstance(b.root, CodeBlock)
    )
    assert code.text == "1: Require model, learning rate\n2:  return x"


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


def test_colorbox_error_and_leaked_colour_arg_excluded_from_body() -> None:
    """An unexpanded \\Colorbox box macro (arXiv:2410.14706 \\cybertron) surfaces as an ltx_ERROR
    node holding the command token, with its {colour} argument leaking as loose text right after.
    Neither may leak into the sentence; the boxed identifier (a separate span) must survive."""
    html = (
        '<article class="ltx_document">'
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">'
        '<span class="ltx_tag ltx_tag_section">1 </span>Method</h2>'
        '<div class="ltx_para"><p class="ltx_p">For variables with the same identifier '
        '<span class="ltx_ERROR undefined">\\Colorbox</span>mygrayInline'
        '<span class="ltx_text ltx_lst_identifier ltx_lstlisting">a</span>, done.</p></div>'
        "</section></article>"
    )
    doc = _parse(html)
    para = _blocks(_body_sections(doc)[0])[0]
    assert isinstance(para, ParagraphBlock)
    assert para.text == "For variables with the same identifier a, done."
    assert "Colorbox" not in para.text and "mygrayInline" not in para.text


def test_colorbox_leaked_colour_dropped_even_with_whitespace_and_never_eats_prose() -> None:
    """The colour drop tolerates whitespace between the error node and the loose colour token, and a
    box error with NO following colour token must not swallow the next sentence (single-token)."""
    html = (
        '<article class="ltx_document"><section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section"><span class="ltx_tag">1 </span>M</h2>'
        # (a) whitespace between the error node and the loose colour token (its own text node, the
        # boxed content following in a span) — the colour is still dropped.
        '<div class="ltx_para"><p class="ltx_p">alpha '
        '<span class="ltx_ERROR undefined">\\Colorbox</span>\n  mygrayInline'
        '<span class="ltx_text ltx_lst_identifier">beta</span>.</p></div>'
        # (b) a box error whose following text is a full sentence (no lone colour token) must keep
        # that prose intact — the single-token gate prevents eating body text.
        '<div class="ltx_para"><p class="ltx_p">gamma '
        '<span class="ltx_ERROR undefined">\\Colorbox</span> the rest of this sentence.</p></div>'
        "</section></article>"
    )
    doc = _parse(html)
    paras = [b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, ParagraphBlock)]
    assert paras[0].text == "alpha beta."  # colour name gone despite the whitespace
    assert "mygrayInline" not in paras[0].text
    assert paras[1].text == "gamma the rest of this sentence."  # prose not eaten


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


def test_code_block_drops_duplicate_math_annotation() -> None:
    # A <math> inside an algorithm listing carries both presentation MathML (unicode) and a TeX
    # <annotation> LaTeX source. The code text must keep only the readable unicode, not both
    # concatenated (regression: "𝐱←𝗓𝖾𝗋𝗈𝖾𝗌(n)\bm{\mathrm{x}}\leftarrow\mathsf{zeroes}(n)").
    html = (
        '<article class="ltx_document">'
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">Algorithm</h2>'
        '<div class="ltx_listing"><div class="ltx_listingline">1: '
        '<math alttext="\\bm{x}"><semantics><mrow><mi>\U0001d431</mi></mrow>'
        '<annotation encoding="application/x-tex">'
        '\\bm{\\mathrm{x}}\\leftarrow\\mathsf{zeroes}(n)</annotation>'
        '</semantics></math></div></div>'
        '</section></article>'
    )
    doc = _parse(html)
    code = next(b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, CodeBlock))
    assert "\U0001d431" in code.text  # unicode presentation kept (readable)
    assert "\\mathsf{zeroes}" not in code.text  # TeX annotation dropped — no duplication
    assert "\\leftarrow" not in code.text


def test_code_block_drops_content_mathml_annotation() -> None:
    # Besides the TeX <annotation>, LaTeXML attaches <annotation-xml encoding="MathML-Content">
    # (content MathML). A raw get_text() also emits ITS text, so "η_m" tripled into
    # "ηm" + "subscript" + "𝜂𝑚" (presentation glyphs, the <csymbol>subscript</csymbol> name, and
    # the italic-unicode <ci>s). Both annotation kinds must be dropped — content included.
    html = (
        '<article class="ltx_document">'
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">Algorithm</h2>'
        '<div class="ltx_listing"><div class="ltx_listingline">1: rate '
        '<math alttext="\\eta_m"><semantics>'
        '<msub><mi>η</mi><mi>m</mi></msub>'
        '<annotation-xml encoding="MathML-Content">'
        '<apply><csymbol>subscript</csymbol><ci>italic-η</ci><ci>m</ci></apply>'
        '</annotation-xml>'
        '<annotation encoding="application/x-tex">\\eta_m</annotation>'
        '</semantics></math></div></div>'
        '</section></article>'
    )
    doc = _parse(html)
    code = next(b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, CodeBlock))
    assert "subscript" not in code.text  # content-MathML csymbol name dropped
    assert "italic-" not in code.text
    assert "\\eta_m" not in code.text  # TeX annotation dropped
    assert "ηm" in code.text  # readable presentation kept


def test_table_ignores_nested_header_table_rows() -> None:
    # A stacked column header "Relevance Rank / ↑" is a NESTED <table> inside the header cell.
    # The parser must NOT pull the nested rows up as phantom single-cell main rows (which made the
    # column headers spill down the first column). Only the real header + data rows survive.
    html = (
        '<article class="ltx_document">'
        '<section class="ltx_section" id="S1">'
        '<h2 class="ltx_title ltx_title_section">Results</h2>'
        '<figure class="ltx_table"><table class="ltx_tabular">'
        '<tr class="ltx_tr"><th class="ltx_th">Model</th>'
        '<th class="ltx_th"><table class="ltx_tabular">'
        '<tr class="ltx_tr"><td class="ltx_td">Relevance Rank</td></tr>'
        '<tr class="ltx_tr"><td class="ltx_td">up</td></tr></table></th></tr>'
        '<tr class="ltx_tr"><td class="ltx_td">Supervised</td><td class="ltx_td">0.478</td></tr>'
        '</table></figure>'
        '</section></article>'
    )
    doc = _parse(html)
    table = next(b for b in _blocks(_body_sections(doc)[0]) if isinstance(b, TableBlock))
    assert len(table.rows) == 2  # header + data only — no phantom nested rows
    # every row has the full column count (2); no stray single-cell row
    assert all(len(r.cells) == 2 for r in table.rows)
    # nested header content is flattened into the parent header cell
    assert "Relevance Rank" in table.rows[0].cells[1].text


def test_a_table_with_no_parsable_rows_keeps_its_caption() -> None:
    """Same contract as the TEI path: empty rows must not take the caption down with them.

    LaTeXML can emit a figure marked as a table whose body carries no <tr> the parser recognises
    (an image-only table, or markup it does not model). The caption is still real paper text.
    """
    html = (
        "<html><body><section><h2>Results</h2>"
        '<figure class="ltx_table">'
        '<figcaption class="ltx_caption"><span class="ltx_tag">Table 4: </span>'
        "Ablation over depth.</figcaption>"
        '<img src="table4.png" alt="rendered table"/>'
        "</figure>"
        "</section></body></html>"
    )
    doc = _parse(html)
    tables = [b for s in doc.sections for b in _blocks(s) if isinstance(b, TableBlock)]
    assert len(tables) == 1, "a table with no parsable rows was dropped outright"
    assert "Ablation over depth." in (tables[0].caption or "")
    assert tables[0].anchorLabel == "Table 4"
    assert tables[0].rows == []
    assert "Ablation over depth." in doc.fullText


def test_span_tabular_table_reads_rows() -> None:
    """LaTeXML renders a scaled tabular (resizebox) as <span class="ltx_tabular"> with span rows
    and cells — no <table> element at all. A <table>-only reader produced a 0-row TableBlock for
    the whole float (arXiv:2510.23156, TABLE IV, 26 rows lost). Row/col spans there are CLASSES
    (ltx_rowspan_2), not attributes."""
    html = (
        "<html><body><section><h2>Results</h2>"
        '<figure class="ltx_table">'
        '<figcaption class="ltx_caption"><span class="ltx_tag ltx_tag_table">TABLE IV: </span>'
        "Test accuracies.</figcaption>"
        '<span class="ltx_tabular"><span class="ltx_tbody">'
        '<span class="ltx_tr">'
        '<span class="ltx_td ltx_rowspan ltx_rowspan_2">Bits</span>'
        '<span class="ltx_td ltx_colspan ltx_colspan_2">Accuracy</span></span>'
        '<span class="ltx_tr"><span class="ltx_td">8</span>'
        '<span class="ltx_td">0.93 <span class="ltx_tabular"><span class="ltx_tr">'
        '<span class="ltx_td">mini</span></span></span></span>'
        '<span class="ltx_td ltx_colspan ltx_colspan_x">n/a</span></span>'
        "</span></span></figure>"
        "</section></body></html>"
    )
    doc = _parse(html)
    table = next(b for s in doc.sections for b in _blocks(s) if isinstance(b, TableBlock))
    assert table.anchorLabel == "TABLE IV"
    assert len(table.rows) == 2  # top-level rows only — the nested mini-tabular row is filtered
    assert table.rows[0].cells[0].rowspan == 2
    assert table.rows[0].cells[1].colspan == 2
    assert "mini" in table.rows[1].cells[1].text  # nested content flattened into its parent cell
    assert table.rows[1].cells[2].colspan is None  # garbage span class (ltx_colspan_x) -> default


def test_table_merges_stacked_top_level_tabulars() -> None:
    """A float stacking several top-level tabulars (side-by-side subtables) kept only the first —
    every later subtable's rows were silently dropped. They concatenate in document order."""
    html = (
        "<html><body><section><h2>Results</h2>"
        '<figure class="ltx_table">'
        '<figcaption class="ltx_caption"><span class="ltx_tag">Table 7: </span>Split.</figcaption>'
        '<table class="ltx_tabular"><tr class="ltx_tr"><td class="ltx_td">a</td></tr>'
        '<tr class="ltx_tr"><td class="ltx_td">b</td></tr></table>'
        '<table class="ltx_tabular"><tr class="ltx_tr"><td class="ltx_td">c</td></tr></table>'
        "</figure>"
        "</section></body></html>"
    )
    doc = _parse(html)
    table = next(b for s in doc.sections for b in _blocks(s) if isinstance(b, TableBlock))
    assert [r.cells[0].text for r in table.rows] == ["a", "b", "c"]


def test_svg_only_figure_keeps_its_block_for_a_page_crop() -> None:
    """LaTeXML draws a TikZ/pgfplots plot as an inline <svg>, so the float has no <img> at all.
    Requiring one dropped the figure together with its caption and number — yet the number is
    exactly what the PDF page-crop path matches on, so the block is worth keeping."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>5 Experiments</h2>'
        '<figure class="ltx_figure"><span class="ltx_inline-block">'
        '<svg class="ltx_picture" height="10" width="10"></svg></span>'
        '<figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 1: </span>Loss curves</figcaption>'
        "</figure></section></div></body></html>"
    )
    specs: list = []
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00014", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS, figure_specs=specs,
    )
    figures = [b.root for s in doc.sections for b in s.blocks if isinstance(b.root, FigureBlock)]
    assert len(figures) == 1
    assert figures[0].caption == "Loss curves"
    assert figures[0].anchorLabel == "Figure 1"
    assert specs[0].src == ""  # nothing to fetch from the e-print; the page-crop images it


def test_captioned_float_holding_text_keeps_its_text_and_caption() -> None:
    """Authors float prompt transcripts and boxed examples with \\begin{figure} + \\fbox, so the
    float has a "Figure 2:" caption and no image at all. Requiring a graphic dropped the caption
    and the whole transcript, putting it beyond search and beyond quoting."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>3 Prompts</h2>'
        '<figure class="ltx_figure"><span class="ltx_inline-block ltx_framed">'
        "System: You are roleplaying a participant in the card selection task."
        "</span>"
        '<figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 2: </span>The expert prompt.</figcaption>'
        "</figure></section></div></body></html>"
    )
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00015", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )
    assert "Figure 2: The expert prompt." in doc.fullText
    assert "You are roleplaying a participant" in doc.fullText


def test_uncaptioned_logo_strip_is_still_dropped_by_the_text_float_path() -> None:
    """The text-float recovery must not resurrect decoration: a float with images but no caption
    has nothing to say and nothing that could image it."""
    html = (
        '<html><body><div class="ltx_document">'
        '<section class="ltx_section"><h2>1 Intro</h2>'
        '<figure class="ltx_figure"><img src="a.png"/><img src="b.png"/></figure>'
        "</section></div></body></html>"
    )
    doc = parse_html_to_docmodel(
        html, paper_id="2401.00016", version=1, title="T", abstract=None,
        source_tier=SourceTier.ar5iv, parser_version="p", schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )
    assert [b for s in doc.sections for b in s.blocks if s.id != "s0"] == []
