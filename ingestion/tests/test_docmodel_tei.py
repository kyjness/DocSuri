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
