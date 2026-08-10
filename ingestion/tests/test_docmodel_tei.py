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


# --- crop framing: the rendered region is the CONTENT, not the float's caption lines ---
#
# A float's coords is the list of its caption's text LINES plus its content region. Unioning all of
# it put the caption inside the image the reader sees, beside the <figcaption> already rendering
# the same words. These fix which region is actually cropped.


def _figure_crop(tei: str):
    return next(s for s in tei_crop_specs(tei, paper_id="p", version=1) if s.type.value == "figure")


def test_caption_lines_below_a_graphic_are_trimmed_off_the_crop() -> None:
    # Two caption lines under a plot: the crop must be the plot.
    tei = (
        f"<TEI {_NS}><text><body><div><head>S</head></div>"
        '<figure coords="4,50,100,200,120;4,50,230,200,8;4,50,240,140,8">'
        "<head>Figure 1</head><figDesc>A plot.</figDesc>"
        '<graphic coords="4,50,100,200,120" type="bitmap" />'
        "</figure></body></text></TEI>"
    )
    spec = _figure_crop(tei)
    assert spec.bbox == (50.0, 100.0, 250.0, 220.0)
    assert spec.content_coords is True


def test_caption_lines_above_a_graphic_keep_the_floats_own_width() -> None:
    # The caption spans the whole column; the <graphic> covers only ONE of two subfigures. Cropping
    # to the graphic alone would cut the other, so x stays the float's span and only y is trimmed.
    tei = (
        f"<TEI {_NS}><text><body><div><head>S</head></div>"
        '<figure coords="4,72,330,467,8;4,72,340,467,8;4,334,377,164,157">'
        "<head>Figure 1</head><figDesc>Two panels.</figDesc>"
        '<graphic coords="4,334,377,164,157" type="bitmap" />'
        "</figure></body></text></TEI>"
    )
    spec = _figure_crop(tei)
    assert spec.bbox == (72.0, 377.0, 539.0, 534.0)


def test_a_tables_own_coords_decide_the_page_its_crop_comes_from() -> None:
    # GROBID files the caption strip on the page the caption sits on, which is not always the page
    # the table is on. Cropping the float's first region then pictures the wrong page entirely.
    tei = (
        f"<TEI {_NS}><text><body><div><head>S</head></div>"
        '<figure type="table" coords="11,311,247,228,117">'
        "<head>Table 1</head><figDesc>Timings.</figDesc>"
        '<table coords="12,88,135,205,240">'
        "<row><cell>a</cell><cell>b</cell></row></table>"
        "</figure></body></text></TEI>"
    )
    spec = next(s for s in tei_crop_specs(tei, paper_id="p", version=1) if s.type.value == "table")
    assert spec.page == 12
    assert spec.bbox == (88.0, 135.0, 293.0, 375.0)


def test_a_single_region_float_is_cropped_to_its_content_box() -> None:
    # One region covering caption AND body: no line is identifiable as caption, so GROBID's own
    # content box is the only signal left and it is taken as-is.
    tei = (
        f"<TEI {_NS}><text><body><div><head>S</head></div>"
        '<figure type="table" coords="17,111,132,388,208">'
        "<head>Table 5</head><figDesc>Scores.</figDesc>"
        '<table coords="17,126,160,354,65">'
        "<row><cell>a</cell></row></table>"
        "</figure></body></text></TEI>"
    )
    spec = next(s for s in tei_crop_specs(tei, paper_id="p", version=1) if s.type.value == "table")
    assert spec.bbox == (126.0, 160.0, 480.0, 225.0)


# --- crop framing: an algorithm split across <formula> elements is cropped whole ---


def _algorithm_tei(continuation_coords: str) -> str:
    return (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        '<formula coords="2,50,100,200,40">Algorithm 1 Sort 1: for each x 2: swap</formula>'
        f'<formula coords="{continuation_coords}">3: end for 4: return 5: Require: x</formula>'
        "</div></body></text></TEI>"
    )


def _one_code_block(tei: str):
    doc = _parse(tei)
    blocks = [b.root for s in doc.sections for b in s.blocks if b.root.type == "code"]
    assert len(blocks) == 1, f"expected one listing, got {len(blocks)}"
    return blocks[0]


def test_a_listing_continued_in_a_second_formula_is_cropped_whole() -> None:
    # The continuation's text was already being rejoined; without its coordinates the crop pictured
    # only the opening fragment.
    tei = _algorithm_tei("2,50,150,200,60")
    assert "end for" in _one_code_block(tei).text
    spec = next(s for s in tei_crop_specs(tei, paper_id="p", version=1))
    assert spec.bbox == (50.0, 100.0, 250.0, 210.0)


def test_a_continuation_on_another_page_leaves_the_crop_where_it_was() -> None:
    # A listing running overleaf has no single rectangle; cropping between the two pages would
    # picture neither.
    tei = _algorithm_tei("3,50,150,200,60")
    assert "end for" in _one_code_block(tei).text
    spec = next(s for s in tei_crop_specs(tei, paper_id="p", version=1))
    assert spec.page == 2
    assert spec.bbox == (50.0, 100.0, 250.0, 140.0)


def test_a_continuation_in_the_other_column_leaves_the_crop_where_it_was() -> None:
    # Unioning across the gutter would drag the whole neighbouring column into the image.
    tei = _algorithm_tei("2,320,150,200,60")
    assert "end for" in _one_code_block(tei).text
    spec = next(s for s in tei_crop_specs(tei, paper_id="p", version=1))
    assert spec.bbox == (50.0, 100.0, 250.0, 140.0)


def test_a_float_with_no_content_element_keeps_its_own_coords() -> None:
    # Nothing to trim to. The bbox is unchanged from before this rule existed, and the spec says so
    # — a strip of caption text and a text float both land here, and only the PDF can tell them
    # apart.
    tei = (
        f"<TEI {_NS}><text><body><div><head>S</head></div>"
        '<figure coords="8,111,408,388,11;8,111,420,388,11">'
        "<head>Figure 1</head><figDesc>Overview.</figDesc>"
        "</figure></body></text></TEI>"
    )
    spec = _figure_crop(tei)
    assert spec.bbox == (111.0, 408.0, 499.0, 431.0)
    assert spec.content_coords is False


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


def test_a_listing_headed_in_caps_is_recognised_on_the_formula_path_too() -> None:
    """IEEE styles a float's heading in caps ("ALGORITHM 1"), and the <formula> path used to test
    for it case-sensitively while the <p> path did not.

    Both halves of that gap show here. GROBID promotes an algorithm float's heading to the section
    title and leaves the steps in a headless <formula>, and it is the TITLE match that tells the
    parser those fragments are one listing — so with a caps title the fragments stayed formula
    images. Where the heading survives inside the formula, the split has to see it as well, or two
    listings run together into one block.

    The 50-paper audit sample holds no caps heading, so nothing in the corpus measurements moves;
    this is the only thing keeping the blind spot closed.
    """
    # Two steps and no control-flow vocabulary: too weak for the headless rule on its own, so the
    # section title is the ONLY thing that can promote this — which is the point of the fixture.
    steps = "<formula>1: initialise the running estimate 2: update the factor matrices</formula>"
    titled = (
        f"<TEI {_NS}><text><body><div><head>ALGORITHM 1 Joint SVD</head>"
        f"{steps}</div></body></text></TEI>"
    )
    assert len(_blocks_of(_parse(titled), "code")) == 1
    assert not _blocks_of(_parse(titled), "formula")
    # The same fragment under an ordinary title stays a formula — the title is doing the work.
    plain = f"<TEI {_NS}><text><body><div><head>Method</head>{steps}</div></body></text></TEI>"
    assert not _blocks_of(_parse(plain), "code")

    split = (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        "<formula>ALGORITHM 1 Training 1: init 2: loop end for "
        "ALGORITHM 2 Sampling 1: draw 2: accept end for</formula>"
        "</div></body></text></TEI>"
    )
    codes = _blocks_of(_parse(split), "code")
    assert len(codes) == 2, "two caps-headed listings ran together into one block"
    assert codes[0].text.startswith("ALGORITHM 1")
    assert codes[1].text.startswith("ALGORITHM 2")


def test_a_lowercase_algorithm_mention_does_not_cut_a_listing_in_two() -> None:
    """The split runs unanchored over a formula's whole text, so it must NOT ignore case.

    "algorithm 2" mid-sentence is a cross-reference to another float, not this one's heading.
    Matching it case-insensitively cut a real listing in half at the mention and filed the tail as
    a second listing — observed on 2607.16138 while widening the caps case. A heading is
    capitalised; a mention in running prose is not, and that is the whole distinction.
    """
    tei = (
        f"<TEI {_NS}><text><body><div><head>Method</head>"
        "<formula>Algorithm 1 Training 1: init 2: update the estimate "
        "3: refine as algorithm 2 does 4: return</formula>"
        "</div></body></text></TEI>"
    )
    codes = _blocks_of(_parse(tei), "code")
    assert len(codes) == 1, "a lowercase cross-reference was treated as a heading"
    assert "as algorithm 2 does" in codes[0].text


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


def test_prose_grobid_swept_into_a_table_element_stays_prose() -> None:
    """GROBID files stretches of running text as ``<figure type="table">`` with no cells and no
    head. Keeping those as tables gave the reader a phantom empty table whose "caption" was the
    paragraph itself, plus a page crop picturing prose — 17 of them in a 50-paper sweep, every one
    a references tail, an acknowledgements note, a bulleted item or a sentence citing a table."""
    prose = (
        "NK was supported by a research grant from a foundation, partly funded by the national "
        "programme, and the authors thank the reviewers for their comments on an earlier draft."
    )
    tei = (
        f"<TEI {_NS}><text><body><div><head>Results</head>"
        f'<figure type="table" coords="2,10,20,100,50"><figDesc>{prose}</figDesc></figure>'
        "</div></body></text></TEI>"
    )
    doc = _parse(tei)
    assert not _blocks_of(doc, "table"), "prose with no cells and no head stayed a table"
    paragraphs = _blocks_of(doc, "paragraph")
    assert len(paragraphs) == 1
    assert paragraphs[0].text == prose
    # The text is what mattered — it still reaches the searchable projection.
    assert "thank the reviewers" in doc.fullText


def test_a_headed_table_with_no_cells_is_still_a_table() -> None:
    """The distinction is the head, not the length: a table GROBID named but could not reconstruct
    keeps its block, its caption and its crop (BR-S3). Real captions here run to 1,142 chars, so
    caption length cannot tell the two apart."""
    tei = (
        f"<TEI {_NS}><text><body><div><head>Results</head>"
        '<figure type="table" coords="2,10,20,100,50"><head>Table 4</head>'
        "<figDesc>Ablation over the three encoders, averaged across five seeds and reported "
        "with standard deviations for every configuration we evaluated in this study.</figDesc>"
        "<table /></figure></div></body></text></TEI>"
    )
    doc = _parse(tei)
    tables = _blocks_of(doc, "table")
    assert len(tables) == 1
    assert tables[0].anchorLabel == "Table 4"
    assert tables[0].rows == []
    assert tables[0].assetRef is not None


# --- body-level float placement (GROBID files every figure after every div) ----------------

_PLACED_TEI = f"""
<TEI {_NS}>
  <text><body>
    <div>
      <head coords="1,10,100,300,10">1. Introduction</head>
      <p>We follow the pipeline of Figure 2 throughout.</p>
    </div>
    <div>
      <head coords="4,10,100,300,10">2. Results</head>
      <p>Scores are reported per split.</p>
    </div>
    <figure coords="4,10,300,200,80">
      <head>Figure 2</head><figDesc>The pipeline.</figDesc>
    </figure>
    <figure type="table" coords="4,10,400,200,80">
      <head>Table 9</head><figDesc>Per-split scores.</figDesc>
      <table><row><cell>split</cell><cell>score</cell></row></table>
    </figure>
  </body></text>
</TEI>
"""
# Both floats print on page 4, so coordinates alone would file BOTH under "2. Results". Only the
# citation pulls Figure 2 back to the introduction — which is what makes the two tests below
# distinguish the signals instead of both passing on the coordinate path.


def _float_labels(section) -> list[str]:
    return [b.root.anchorLabel for b in section.blocks if b.root.type in ("figure", "table")]


def test_a_float_the_text_cites_lands_next_to_the_sentence_that_cites_it() -> None:
    """A float whose number a paragraph names belongs beside that paragraph, not in a dump at the
    end. Figure 2 is cited from the introduction while sitting on page 1, and it reads there."""
    body = [s for s in _parse(_PLACED_TEI).sections if s.id != "s0"]
    intro = next(s for s in body if s.title.startswith("1."))
    assert _float_labels(intro) == ["Figure 2"]
    # Right after the citing paragraph, and carrying that section's id.
    assert [b.root.type for b in intro.blocks] == ["paragraph", "figure"]
    assert intro.blocks[1].root.id.startswith(f"{intro.id}.")


def test_an_uncited_float_falls_to_the_section_its_page_position_sits_in() -> None:
    """Nothing names Table 9, so its coordinates decide: page 4 puts it under the head that last
    precedes it. Coarser than a citation — it lands at the section's end — but it reads in place."""
    body = [s for s in _parse(_PLACED_TEI).sections if s.id != "s0"]
    results = next(s for s in body if s.title.startswith("2."))
    assert _float_labels(results) == ["Table 9"]
    assert [b.root.type for b in results.blocks] == ["paragraph", "table"]
    assert not any(s.title == "그림 및 표" for s in body)


def test_floats_with_neither_signal_keep_the_trailing_section() -> None:
    """TEI predating the ``head`` coordinate request has no anchors and no citations here, so the
    old grouped section must still be produced — an older cache stays parseable, not empty."""
    body = [s for s in _parse(_TEI).sections if s.id != "s0"]
    trailing = body[-1]
    assert trailing.title == "그림 및 표"
    assert sorted(_float_labels(trailing)) == ["Figure 1", "Table 1"]


def test_a_merged_head_is_placed_by_any_of_the_numbers_it_claims() -> None:
    """GROBID fuses adjacent floats into one element whose head claims several numbers
    ("Figure 4 :Figure 5 :"). A citation of either number is a citation of that element."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>The decision regions appear in Figure 5.</p>
        </div>
        <div>
          <head coords="9,10,100,300,10">2. Appendix</head>
          <p>Further material follows.</p>
        </div>
        <figure coords="9,10,300,200,80">
          <head>Figure 4 :Figure 5 :</head><figDesc>Decision regions.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == ["Figure 4 :Figure 5 :"]
    assert not any(s.title == "그림 및 표" for s in body)


def test_a_citation_of_a_longer_number_does_not_claim_the_shorter_float() -> None:
    """"Figure 12" must not read as a citation of Figure 1 — that would drag a float to the first
    paragraph mentioning any number starting with its digits."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>See Figure 12 for the ablation.</p>
        </div>
        <div>
          <head coords="2,10,100,300,10">2. Details</head>
          <p>Figure 1 shows the overview.</p>
        </div>
        <figure coords="1,10,300,200,80">
          <head>Figure 1</head><figDesc>Overview.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == []
    assert _float_labels(body[1]) == ["Figure 1"]


def test_a_roman_numbered_table_is_placed_by_the_text_that_cites_it() -> None:
    """IEEE styling numbers tables "TABLE III" throughout. Reading only arabic numerals lost the
    citation signal for every table in such a paper and dropped the whole style onto the coarser
    coordinate rule — here that would put the table two sections away from the sentence using it.
    """
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>The configurations are listed in Table III.</p>
        </div>
        <div>
          <head coords="7,10,100,300,10">2. Appendix</head>
          <p>Further material follows.</p>
        </div>
        <figure type="table" coords="7,10,300,200,80">
          <head>TABLE III</head><figDesc>Selected model configurations</figDesc>
          <table><row><cell>lr</cell><cell>0.01</cell></row></table>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == ["TABLE III"]
    assert _float_labels(body[1]) == []


def test_theorem_furniture_does_not_claim_the_number_of_a_real_float() -> None:
    """GROBID files a paper's theorem headings under ``<figure>`` too — "Challenge 1 .",
    "Proposition 3 .". Those name a proposition, not a figure, so reading a number out of them
    hands the element Figure 1's citation and prints it at a sentence that never mentioned it.
    Only a KEYWORD-anchored number counts; anything else falls through to the coordinate rule."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>The overview is given in Figure 1.</p>
        </div>
        <div>
          <head coords="8,10,100,300,10">2. Appendix</head>
          <p>Further material follows.</p>
        </div>
        <figure coords="8,10,300,200,80">
          <head>Challenge 1 .</head><figDesc>Developing powerful ML pipelines.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == []  # not dragged to Figure 1's citation
    assert _float_labels(body[1]) == ["Challenge 1 ."]  # placed by its page-8 coordinates


def test_a_table_captioned_without_a_colon_keeps_its_table_typing() -> None:
    """A rows-less ``<figure type="table">`` is demoted to a paragraph unless its caption NAMES a
    table, because GROBID sweeps stray prose into table elements. IEEE captions carry no colon —
    "TABLE IV RESULTS OF THE ABLATION STUDY" — and a delimiter-only rule read them as prose,
    demoting real tables and taking their crop and repair eligibility with them."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>Body text.</p>
          <figure type="table" coords="1,10,300,200,80">
            <figDesc>TABLE IV RESULTS OF THE ABLATION STUDY</figDesc>
          </figure>
        </div>
      </body></text>
    </TEI>
    """
    section = next(s for s in _parse(tei).sections if s.id != "s0")
    assert [b.root.type for b in section.blocks] == ["paragraph", "table"]


def test_a_caption_that_merely_cites_a_table_is_still_demoted() -> None:
    """The other side of the same rule: GROBID swept a paragraph that CITES Table 1 into a table
    element. A caption punctuates after its label; a sentence runs straight on to a verb, so this
    stays prose rather than becoming a phantom empty table with a page crop picturing it."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,100,300,10">1. Setup</head>
          <p>Body text.</p>
          <figure type="table" coords="1,10,300,200,80">
            <figDesc>Table 1 displays the selected hyperparameters.</figDesc>
          </figure>
        </div>
      </body></text>
    </TEI>
    """
    section = next(s for s in _parse(tei).sections if s.id != "s0")
    assert [b.root.type for b in section.blocks] == ["paragraph", "paragraph"]


def test_a_tei_with_no_body_still_parses_to_an_empty_doc_model() -> None:
    """GROBID can return TEI with no ``<body>`` at all. The builder degrades such a parse to the
    flat-text doc-model, which only works if the parse RETURNS rather than raising — and page
    layout is read on the trailing-section path that a body-less document still reaches."""
    doc = _parse(f"<TEI {_NS}><text></text></TEI>")
    assert [s for s in doc.sections if s.id != "s0"] == []


def test_a_two_column_page_is_ordered_by_column_before_height() -> None:
    """On a two-column page, ``y`` alone is not reading order: a heading opening the RIGHT column
    near the top sorts above a float sitting lower in the LEFT column, so the coordinate rule hands
    that float to the wrong section. Taken from arXiv:2502.11386 page 9 — a left-column float at
    y=347 under "B. QoE Modeling" (left, y=161), with "C. Algorithm Overview" opening the right
    column at y=186. The float is read before anyone reaches column two."""
    tei = f"""
    <TEI {_NS}>
      <facsimile><surface n="9" ulx="0.0" uly="0.0" lrx="612.0" lry="792.0"/></facsimile>
      <text><body>
        <div>
          <head coords="9,48.96,161.38,73.49,8.58">B. QoE Modeling</head>
          <p>Body of the left column.</p>
        </div>
        <div>
          <head coords="9,311.98,185.68,96.04,8.58">C. Algorithm Overview</head>
          <p>Body of the right column.</p>
        </div>
        <figure coords="9,48.96,346.95,251.05,90.00">
          <head>Figure 4</head><figDesc>A left-column float.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == ["Figure 4"]  # B. QoE Modeling, the column it is printed in
    assert _float_labels(body[1]) == []


def test_a_single_column_paper_keeps_its_height_only_ordering() -> None:
    """The column rule must not fire where there is no second column. A single-column paper puts
    every heading at the left margin, and a narrow float indented right of centre is still simply
    below the heading above it — giving it a column would invent an order the page never had."""
    tei = f"""
    <TEI {_NS}>
      <facsimile><surface n="3" ulx="0.0" uly="0.0" lrx="612.0" lry="792.0"/></facsimile>
      <text><body>
        <div>
          <head coords="3,72.00,100.00,120.00,10.00">1. Setup</head>
          <p>Body text.</p>
        </div>
        <div>
          <head coords="3,72.00,500.00,120.00,10.00">2. Results</head>
          <p>More body text.</p>
        </div>
        <figure coords="3,330.00,300.00,120.00,60.00">
          <head>Figure 4</head><figDesc>An indented narrow float.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert _float_labels(body[0]) == ["Figure 4"]  # y=300 is under "1. Setup", not "2. Results"
    assert _float_labels(body[1]) == []


def test_a_teaser_printed_above_the_first_heading_opens_the_first_section() -> None:
    """A float on the title page sits above every heading, so no head precedes it and the
    coordinate rule owns nothing — it was the one shape left stranded in the trailing dump.
    It is the overview figure authors put there, and it reads at the front, not the back."""
    tei = f"""
    <TEI {_NS}>
      <text><body>
        <div>
          <head coords="1,10,400,300,10">1. Introduction</head>
          <p>The method is described below.</p>
        </div>
        <figure coords="1,10,150,200,80">
          <head>Figure 1</head><figDesc>Overview of the system.</figDesc>
        </figure>
      </body></text>
    </TEI>
    """
    body = [s for s in _parse(tei).sections if s.id != "s0"]
    assert not any(s.title == "그림 및 표" for s in body)
    intro = body[0]
    assert [b.root.type for b in intro.blocks] == ["figure", "paragraph"]
    assert intro.blocks[0].root.anchorLabel == "Figure 1"
