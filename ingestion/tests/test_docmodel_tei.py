"""GROBID TEI -> structured DocModel (BR-30, D1): sections, data tables, image formulas/figures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel, tei_crop_specs

_NS = 'xmlns="http://www.tei-c.org/ns/1.0"'

_TEI = f"""
<TEI {_NS}>
  <text><body>
    <div>
      <head>1. Introduction</head>
      <p>We study diffusion over <ref>protein</ref> structure.</p>
      <formula><label>(1)</label>E = mc^2</formula>
    </div>
    <div>
      <head>2. Method</head>
      <p>The backbone is modelled directly.</p>
    </div>
    <figure type="table" coords="3,10,20,100,50">
      <head>Table 1</head>
      <figDesc>Ablation results.</figDesc>
      <table>
        <row><cell>model</cell><cell>score</cell></row>
        <row><cell>ours</cell><cell>0.92</cell></row>
      </table>
    </figure>
    <figure coords="2,10,40,100,50">
      <head>Figure 1</head>
      <figDesc>The pipeline.</figDesc>
    </figure>
  </body></text>
</TEI>
"""


def _parse(tei: str):
    return parse_tei_to_docmodel(
        tei,
        paper_id="src-abc",
        version=1,
        title="A Paper",
        abstract="An abstract.",
        source_tier=SourceTier.pdf,
        parser_version="pv",
        schema_version="sv",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_sections_and_paragraphs_preserve_order_and_titles() -> None:
    doc = _parse(_TEI)
    titles = [s.title for s in doc.sections]
    # abstract section first, then the two body divs, then the grouped figures/tables section
    assert titles[:3] == ["Abstract", "1. Introduction", "2. Method"]
    intro = doc.sections[1]
    assert intro.blocks[0].root.type == "paragraph"
    assert "diffusion over protein structure" in intro.blocks[0].root.text


def test_block_formula_is_image_fallback_no_latex() -> None:
    doc = _parse(_TEI)
    intro = doc.sections[1]
    formula = next(b.root for b in intro.blocks if b.root.type == "formula")
    # PDF path: no reliable LaTeX -> image assetRef, anchor label from <label>
    assert formula.latex is None
    assert formula.assetRef is not None
    assert formula.assetRef.type.value == "formula"
    assert formula.assetRef.assetId == "src-abc:v1:formula:0"
    assert formula.anchorLabel == "(1)"


def test_table_is_structured_data_not_image() -> None:
    doc = _parse(_TEI)
    figures = doc.sections[-1]  # trailing grouped section
    table = next(b.root for b in figures.blocks if b.root.type == "table")
    assert table.anchorLabel == "Table 1"
    assert table.caption == "Ablation results."
    assert [c.text for c in table.rows[0].cells] == ["model", "score"]
    assert [c.text for c in table.rows[1].cells] == ["ours", "0.92"]


def test_table_with_coords_also_carries_page_crop_fallback() -> None:
    # Rows stay primary, but a coord-bearing table ALSO references a page-crop image fallback,
    # so a later vision reader can re-read numbers GROBID may have garbled.
    doc = _parse(_TEI)
    figures = doc.sections[-1]
    table = next(b.root for b in figures.blocks if b.root.type == "table")
    assert table.assetRef is not None
    assert table.assetRef.type.value == "table"
    assert table.assetRef.assetId == "src-abc:v1:table:0"
    assert table.rows  # data is not displaced by the image


def test_table_without_coords_stays_data_only() -> None:
    # No coordinates -> no image is possible, so no dangling assetRef is attached.
    tei = (
        f"<TEI {_NS}><text><body><figure type=\"table\">"
        "<head>Table 1</head><table><row><cell>a</cell><cell>b</cell></row></table>"
        "</figure></body></text></TEI>"
    )
    doc = parse_tei_to_docmodel(
        tei,
        paper_id="p",
        version=1,
        title="t",
        abstract=None,
        source_tier=SourceTier.pdf,
        parser_version="pv",
        schema_version="sv",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    table = next(
        b.root for s in doc.sections for b in s.blocks if b.root.type == "table"
    )
    assert table.assetRef is None
    assert tei_crop_specs(tei, paper_id="p", version=1) == []


def test_figure_is_image_assetref_with_caption() -> None:
    doc = _parse(_TEI)
    figures = doc.sections[-1]
    figure = next(b.root for b in figures.blocks if b.root.type == "figure")
    assert figure.assetRef.assetId == "src-abc:v1:figure:0"
    assert figure.caption == "The pipeline."
    assert figure.anchorLabel == "Figure 1"


def test_full_text_excludes_image_formula_but_keeps_table_data() -> None:
    doc = _parse(_TEI)
    assert "0.92" in doc.fullText  # table cell data is searchable
    assert "mc^2" not in doc.fullText  # image-only formula contributes no text


def test_deterministic_same_tei_same_docmodel() -> None:
    assert _parse(_TEI).model_dump() == _parse(_TEI).model_dump()


def test_malformed_tei_raises() -> None:
    import xml.etree.ElementTree as ET

    with pytest.raises(ET.ParseError):
        _parse("<TEI>")


# --- coordinate crop specs (#4/#5): ordinal alignment with the doc-model blocks ---


def _block_asset_ids(doc) -> set[str]:
    ids: set[str] = set()
    for section in doc.sections:
        for block in section.blocks:
            ref = getattr(block.root, "assetRef", None)
            if ref is not None:
                ids.add(ref.assetId)
    return ids


def test_crop_specs_asset_ids_align_with_doc_model_blocks() -> None:
    # The alignment guarantee: every crop spec targets an assetId that a doc-model block
    # references, because both are minted in the same TEI walk.
    doc = _parse(_TEI)
    specs = tei_crop_specs(_TEI, paper_id="src-abc", version=1)
    assert specs  # the figure has coords
    for spec in specs:
        assert spec.asset_id in _block_asset_ids(doc)


def test_crop_spec_parses_page_and_bbox_from_coords() -> None:
    specs = tei_crop_specs(_TEI, paper_id="src-abc", version=1)
    figure = next(s for s in specs if s.type.value == "figure")
    assert figure.asset_id == "src-abc:v1:figure:0"
    assert figure.page == 2
    assert figure.bbox == (10.0, 40.0, 110.0, 90.0)
    # the table keeps its structured data AND, having coords, gets a page-crop fallback spec
    table = next(s for s in specs if s.type.value == "table")
    assert table.asset_id == "src-abc:v1:table:0"
    assert table.page == 3
    assert table.bbox == (10.0, 20.0, 110.0, 70.0)


def test_crop_spec_for_formula_with_coords() -> None:
    tei = (
        f"<TEI {_NS}><text><body><div><head>M</head>"
        '<formula coords="1,5,6,30,12"><label>(2)</label>x=y</formula>'
        "</div></body></text></TEI>"
    )
    specs = tei_crop_specs(tei, paper_id="p", version=2)
    assert len(specs) == 1
    assert specs[0].type.value == "formula"
    assert specs[0].asset_id == "p:v2:formula:0"
    assert specs[0].page == 1


def test_crop_specs_empty_on_malformed_tei() -> None:
    assert tei_crop_specs("<TEI", paper_id="p", version=1) == []


def test_a_table_grobid_could_not_reconstruct_keeps_its_caption() -> None:
    """GROBID emits an empty <table/> when its cell reconstruction fails on a real table.

    Dropping the block then loses the CAPTION too, which is text the paper really contains and
    the schema calls out as preserved (BR-S3) — it is a results-number source and the only
    remaining handle on that table. The rows may legitimately be empty; the caption may not
    vanish with them.
    """
    tei = (
        f"<TEI {_NS}><text><body><div><head>R</head>"
        '<figure type="table" coords="2,10,20,100,50">'
        "<head>Table 1</head><figDesc>Major challenges facing development.</figDesc>"
        "<table />"
        "</figure></div></body></text></TEI>"
    )
    doc = _parse(tei)
    tables = [b.root for s in doc.sections for b in s.blocks if b.root.type == "table"]
    assert len(tables) == 1, "a table GROBID could not reconstruct was dropped outright"
    assert tables[0].caption == "Major challenges facing development."
    assert tables[0].anchorLabel == "Table 1"
    assert tables[0].rows == []
    # The caption is what makes the table findable at all once its rows are gone.
    assert "Major challenges facing development." in doc.fullText


def test_an_algorithm_mention_after_a_listing_is_not_dropped() -> None:
    """One <formula> can carry a real listing AND a trailing "Algorithm N" cross-reference GROBID
    swept into the same element. The listing becomes a code block; the mention is still text the
    paper contains, so it is kept (joined to that listing) rather than silently vanishing."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        "<formula>Algorithm 1 Training 1: init 2: loop end for "
        "Algorithm 2 gives the details</formula>"
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    codes = [b.root for s in doc.sections for b in s.blocks if b.root.type == "code"]
    assert len(codes) == 1
    assert "1: init" in codes[0].text
    assert "Algorithm 2 gives the details" in codes[0].text
    assert "Algorithm 2 gives the details" in doc.fullText


def _blocks_of(doc, kind: str) -> list:
    """Body blocks of one kind. ``s0`` is the abstract ``_parse`` synthesises, not parsed TEI."""
    return [
        b.root for s in doc.sections if s.id != "s0" for b in s.blocks if b.root.type == kind
    ]


def test_a_pseudocode_listing_grobid_filed_as_a_paragraph_becomes_code() -> None:
    """GROBID classifies a float as <formula> only when it reads as maths.

    A pseudocode listing usually reads as prose to it and lands in <p> instead — across the audit
    sample that is where 43 of 44 listings arrived. Inspecting formulas alone therefore left
    nearly every listing typed as a paragraph: present in fullText, but indistinguishable from
    surrounding prose for a reader and for anything quoting it.
    """
    listing = (
        "Algorithm 1 Joint SVD for QK Projections Input: pre-conditioning matrix P, "
        "query projection heads Wq, key projection heads Wk, number of heads h, rank r, "
        "iteration count N Initialize: Wq = Wq P for each head i do compute the factorisation "
        "and update the running estimate end for return the factors"
    )
    tei = (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        f"<p>{listing}</p></div></body></text></TEI>"
    )
    doc = _parse(tei)
    codes = _blocks_of(doc, "code")
    assert len(codes) == 1, "a listing GROBID filed as <p> stayed typed as prose"
    assert codes[0].text.startswith("Algorithm 1 Joint SVD")
    assert not _blocks_of(doc, "paragraph")
    # Promotion must not cost the text — it is the same characters under a truer type.
    assert "Initialize: Wq = Wq P" in doc.fullText


def test_input_colon_is_pseudocode_vocabulary_even_when_a_space_follows() -> None:
    """``Input:`` is the ordinary spelling; ``Input:x`` is not.

    The vocabulary alternation used to close on a word boundary that applied to every branch, so
    a trailing ``\\b`` after ``Input\\s*:`` demanded a word character immediately after the colon.
    That is exactly what a real listing does NOT write, which silently weakened both this path and
    the headless-formula detector.
    """
    listing = (
        "Algorithm 2 Sampling Input: dataset D, budget B, tolerance eps, seed s, "
        "and the initial estimate theta drawn from the prior over the parameter space "
        "which the routine then refines until the budget is exhausted"
    )
    tei = (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        f"<p>{listing}</p></div></body></text></TEI>"
    )
    assert len(_blocks_of(_parse(tei), "code")) == 1


def test_a_verbatim_listing_caption_promotes_without_pseudocode_vocabulary() -> None:
    """LaTeX's lstlisting float carries neither numbered steps nor control-flow words.

    An RDF/Turtle or config snippet is code all the same, so that family leans on the captioned
    heading ("Listing 6:") anchored at the paragraph start.
    """
    listing = (
        "Listing 6: Example of SGP-based KG wd:Q1968853 wd:P166#1 wd:Q3703462 . "
        "wd:P166#1 :singletonPropertyOf wd:P166 ; wd:P585 wd:Q3703462 . "
        "wd:Q1968853 wd:P166 wd:Q3703462 ."
    )
    tei = (
        f"<TEI {_NS}><text><body><div><head>Data</head>"
        f"<p>{listing}</p></div></body></text></TEI>"
    )
    assert len(_blocks_of(_parse(tei), "code")) == 1


def test_prose_that_merely_cites_an_algorithm_stays_a_paragraph() -> None:
    """The cost of a false positive is real prose retyped as code, which is worse than the
    lossless status quo — so a heading alone never promotes, and a mid-sentence mention never
    matches at all."""
    cites = (
        "Algorithm 1 achieves a tighter regret bound than the baseline, and we discuss below "
        "why the improvement carries over to the misspecified setting studied in Section 4, "
        "where the same argument applies with only minor changes to the constants involved."
    )
    mid = (
        "In the CSV data format used as input for StarE (Listing 10), the qualifier triples are "
        "not represented as entities, so the conversion drops them entirely and the downstream "
        "evaluation compares models over a strictly smaller relation vocabulary than intended."
    )
    tei = (
        f"<TEI {_NS}><text><body><div><head>Results</head>"
        f"<p>{cites}</p><p>{mid}</p></div></body></text></TEI>"
    )
    doc = _parse(tei)
    assert not _blocks_of(doc, "code")
    assert len(_blocks_of(doc, "paragraph")) == 2


def test_a_listing_caption_split_from_its_body_is_not_promoted_alone() -> None:
    """GROBID sometimes emits the caption as its own <p>. A caption is not a listing, and typing
    a bare one as code would put a sentence of prose under a code block."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Data</head>"
        "<p>Listing 10: Example of CSV data for RDR-based WD50K</p>"
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    assert not _blocks_of(doc, "code")
    assert len(_blocks_of(doc, "paragraph")) == 1


def test_consecutive_bulleted_paragraphs_become_one_list() -> None:
    """GROBID emits no <list> or <item> anywhere in the body — a bulleted list arrives as prose
    carrying its bullet glyphs, usually one <p> PER ITEM. The first item cannot know a second is
    coming, so it lands as a paragraph and is reclaimed when the next bullet arrives."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Contributions</head>"
        "<p>We make the following contributions.</p>"
        "<p>• We leverage the time-frequency duality for explanations.</p>"
        "<p>• We show the method transfers to unseen sampling rates.</p>"
        "<p>• We release the benchmark and the evaluation harness.</p>"
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    lists = _blocks_of(doc, "list")
    assert len(lists) == 1, "items split across sibling paragraphs did not rejoin"
    assert [i.text for i in lists[0].items] == [
        "We leverage the time-frequency duality for explanations.",
        "We show the method transfers to unseen sampling rates.",
        "We release the benchmark and the evaluation harness.",
    ]
    # The lead-in is prose and stays one.
    lead = "We make the following contributions."
    assert [b.text for b in _blocks_of(doc, "paragraph")] == [lead]


def test_a_single_paragraph_holding_every_bullet_becomes_one_list() -> None:
    """The other shape the same list arrives in — all items flattened into one <p>."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Inputs</head>"
        "<p>• 3-axis acceleration • 4-axis quaternions • 3-axis angular velocity</p>"
        "</div></body></text></TEI>"
    )
    lists = _blocks_of(_parse(tei), "list")
    assert len(lists) == 1
    assert [i.text for i in lists[0].items] == [
        "3-axis acceleration",
        "4-axis quaternions",
        "3-axis angular velocity",
    ]


def test_a_bullet_used_as_a_maths_placeholder_is_not_a_list() -> None:
    """Papers write "[•] denotes the truncated SVD" and "(•)+ denotes the pseudo inverse".

    An unanchored split tore those into fragments beginning with a bracket, inventing list items
    out of one sentence. Only a paragraph that OPENS with the glyph is an itemised one.
    """
    tei = (
        f"<TEI {_NS}><text><body><div><head>Notation</head>"
        "<p>Here [•] denotes the rank-r truncated SVD and (•)+ denotes the pseudo inverse.</p>"
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    assert not _blocks_of(doc, "list")
    assert len(_blocks_of(doc, "paragraph")) == 1


def test_a_lone_bulleted_paragraph_stays_a_paragraph() -> None:
    """A one-item list is not what the source had, and inventing one is the worse error."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Note</head>"
        "<p>• The dataset is released under CC-BY.</p>"
        "<p>We now turn to the evaluation protocol.</p>"
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    assert not _blocks_of(doc, "list")
    assert len(_blocks_of(doc, "paragraph")) == 2


def test_an_intervening_block_ends_a_list_rather_than_being_swallowed() -> None:
    """A later bullet starts its own list instead of reaching back across unrelated content."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Setup</head>"
        "<p>• first item of the opening list</p>"
        "<p>• second item of the opening list</p>"
        "<p>Prose that separates the two lists entirely.</p>"
        "<p>• first item of the closing list</p>"
        "<p>• second item of the closing list</p>"
        "</div></body></text></TEI>"
    )
    lists = _blocks_of(_parse(tei), "list")
    assert len(lists) == 2, "the two lists were merged across the intervening paragraph"
    assert [i.text for i in lists[0].items] == [
        "first item of the opening list",
        "second item of the opening list",
    ]
    assert [i.text for i in lists[1].items] == [
        "first item of the closing list",
        "second item of the closing list",
    ]
