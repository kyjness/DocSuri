"""Golden-fixture regression tests over real papers, across all three parse paths.

Every other parser test in this unit feeds hand-written markup. That verifies the mapping rules
but not the thing deployment used to verify by eye: that a *real* document — with its nesting
depth, subfigure grouping, MathML volume, and GROBID's noisier section segmentation — still comes
out whole. With the deployment retired there is no other place that check can happen.

All three input paths are covered, because they are three separate parsers:

* ``ar5iv``  — LaTeXML HTML, the arXiv doc-model source (``parse_html_to_docmodel``)
* ``grobid`` — TEI from a real PDF, the ONLY path for non-arXiv sources such as Semantic Scholar
  and OpenAlex (``parse_tei_to_docmodel`` / ``tei_crop_specs``)
* ``pdf``    — the PDF itself, for text extraction and bbox page-crop rendering

The digest deliberately stores shapes and content hashes rather than the full DocModel: it stays
a few KB, and any real change to structure, ordering, or text still moves it. Regenerate with
``DOCSURI_UPDATE_FIXTURES=1`` and review the diff — see ``fixtures/SOURCES.md``.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel, tei_crop_specs, tei_to_text
from docsuri_ingestion.full_text_extraction import html_to_text, pdf_to_text

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
FIXTURES = FIXTURE_ROOT / "ar5iv"
_FIXED_TS = datetime(2026, 1, 1, tzinfo=UTC)
_UPDATE = os.environ.get("DOCSURI_UPDATE_FIXTURES") == "1"

# 2305.02531 is the ar5iv "no content" page, exercised separately below.
PAPERS = ["2210.12090", "2112.01799"]
# The one paper carried in all three forms, so the paths can be compared against each other.
TRIPLE = "2210.12090"
# TEI is a separate parser from the HTML one, and the maths-heavy papers are only here: 2210.12090
# has no display maths at all, so without these the TEI formula path had no real-paper coverage.
TEI_PAPERS = ["2210.12090", "2607.16138", "2112.01799"]
# Carried in TEI *and* PDF, so its formula/algorithm crops can actually be rendered.
FORMULA_PAPER = "2607.16138"


def _load(paper_id: str) -> str:
    with gzip.open(FIXTURES / f"{paper_id}.html.gz", "rt", encoding="utf-8") as handle:
        return handle.read()


def _load_tei(paper_id: str = TRIPLE) -> str:
    path = FIXTURE_ROOT / "grobid" / f"{paper_id}.tei.xml.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


def _load_pdf(paper_id: str = TRIPLE) -> bytes:
    return (FIXTURE_ROOT / "pdf" / f"{paper_id}.pdf").read_bytes()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _parse(paper_id: str):
    return parse_html_to_docmodel(
        _load(paper_id),
        paper_id=paper_id,
        version=1,
        title="Fixture Paper",
        abstract=None,
        source_tier=SourceTier.ar5iv,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )


def _block_digest(block) -> dict:
    """Shape plus a content hash — enough that any text or structural change moves the digest."""
    root = block.root
    entry: dict = {"id": root.id, "type": root.type}
    text = getattr(root, "text", None)
    if text is not None:
        entry["textLen"] = len(text)
        entry["textSha"] = _sha(text)
    if root.type == "table":
        entry["rows"] = len(root.rows)
        entry["cols"] = max((len(r.cells) for r in root.rows), default=0)
        entry["caption"] = root.caption[:60] if root.caption else None
        entry["anchorLabel"] = root.anchorLabel
    if root.type == "figure":
        entry["assetRef"] = str(root.assetRef) if root.assetRef else None
        entry["caption"] = root.caption[:60] if root.caption else None
        entry["anchorLabel"] = root.anchorLabel
    if root.type == "formula":
        entry["latexSha"] = _sha(root.latex) if root.latex else None
        entry["display"] = root.display
        entry["anchorLabel"] = root.anchorLabel
    if root.type == "list":
        entry["items"] = len(root.items)
        entry["ordered"] = root.ordered
    if root.type == "code":
        entry["lines"] = len(text.splitlines()) if text else 0
    return entry


def _section_digest(section) -> dict:
    return {
        "id": section.id,
        "title": section.title,
        "blocks": [_block_digest(b) for b in section.blocks],
        "sections": [_section_digest(s) for s in section.sections or []],
    }


def _digest(doc) -> dict:
    return {
        "fullTextLen": len(doc.fullText),
        "fullTextSha": _sha(doc.fullText),
        "sections": [_section_digest(s) for s in doc.sections],
    }


def _assert_matches_recorded(digest: dict, path: Path, label: str) -> None:
    if _UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(digest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not _UPDATE:
            pytest.fail(f"wrote missing digest {path.name}; re-run to verify against it")

    expected = json.loads(path.read_text(encoding="utf-8"))
    assert digest == expected, (
        f"{label}: parsed structure drifted from the recorded digest. If the change is "
        "intended, regenerate with DOCSURI_UPDATE_FIXTURES=1 and review the diff."
    )


@pytest.mark.parametrize("paper_id", PAPERS)
def test_real_paper_parses_to_the_recorded_structure(paper_id: str) -> None:
    _assert_matches_recorded(
        _digest(_parse(paper_id)), FIXTURES / f"{paper_id}.digest.json", paper_id
    )


@pytest.mark.parametrize("paper_id", PAPERS)
def test_real_paper_keeps_its_content(paper_id: str) -> None:
    """A blunt floor under the digest.

    The digest pins whatever the parser does today, including a silent regression if one were
    ever recorded. These bounds are independent of it: a real paper has substantial text, a
    section tree that actually nests, and blocks other than paragraphs.
    """
    doc = _parse(paper_id)

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    sections = list(walk(doc.sections))
    blocks = [b.root for s in sections for b in s.blocks]
    kinds = {b.type for b in blocks}

    assert len(doc.fullText) > 20_000, "a full paper collapsed to a fragment"
    assert len(sections) >= 15, f"section tree flattened: {len(sections)} sections"
    assert any(s.sections for s in doc.sections), "nesting was lost — no section has children"
    assert len(blocks) >= 50, f"blocks dropped: {len(blocks)}"
    assert {"paragraph", "figure"} <= kinds, f"block kinds missing: {kinds}"
    # Reading order must be preserved: every block's text appears in fullText, in order.
    cursor = 0
    for block in blocks:
        text = (getattr(block, "text", None) or "").strip()
        if not text:
            continue
        found = doc.fullText.find(text, cursor)
        assert found >= 0, f"block {block.id} text is missing from fullText or out of order"
        cursor = found


def test_ar5iv_no_content_page_stays_below_the_html_fulltext_floor() -> None:
    """ar5iv answers HTTP 200 with a placeholder when LaTeXML produced nothing.

    ``ArxivHttpSource`` relies on ``_MIN_HTML_FULLTEXT_CHARS`` to notice and fall through to the
    PDF. That guard is only worth its complexity if the real page really does land under it.
    """
    from docsuri_ingestion.adapters.arxiv import _MIN_HTML_FULLTEXT_CHARS

    text = html_to_text(_load("2305.02531"))
    assert len(text) < _MIN_HTML_FULLTEXT_CHARS, (
        "the ar5iv placeholder now exceeds the truncation floor — either ar5iv started rendering "
        "this paper (refetch the fixture, pick another placeholder) or the floor needs revisiting"
    )


# ---------------------------------------------------------------------------------------
# GROBID TEI — the only doc-model path for non-arXiv sources (Semantic Scholar, OpenAlex).
# ---------------------------------------------------------------------------------------


def _parse_tei(paper_id: str = TRIPLE):
    return parse_tei_to_docmodel(
        _load_tei(paper_id),
        paper_id=paper_id,
        version=1,
        title="Fixture Paper",
        abstract=None,
        source_tier=SourceTier.pdf,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )


@pytest.mark.parametrize("paper_id", TEI_PAPERS)
def test_real_tei_parses_to_the_recorded_structure(paper_id: str) -> None:
    _assert_matches_recorded(
        _digest(_parse_tei(paper_id)),
        FIXTURE_ROOT / "grobid" / f"{paper_id}.digest.json",
        f"{paper_id} TEI",
    )


def test_real_tei_keeps_its_content() -> None:
    """Bounds independent of the digest, as for the HTML path.

    GROBID segments far more aggressively than LaTeXML — this paper's numbered "Challenge N."
    subheadings each become their own div — so the section count is high and some heads are
    empty. That is real GROBID output, not a defect, and pinning it here is the point: a parser
    change that started dropping or merging those divs would move these numbers.
    """
    doc = _parse_tei()

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    sections = list(walk(doc.sections))
    blocks = [b.root for s in sections for b in s.blocks]
    kinds = {b.type for b in blocks}

    assert len(doc.fullText) > 20_000, "a full paper collapsed to a fragment"
    assert len(sections) >= 15, f"section tree flattened: {len(sections)} sections"
    assert len(blocks) >= 40, f"blocks dropped: {len(blocks)}"
    assert {"paragraph", "figure", "table"} <= kinds, f"block kinds missing: {kinds}"
    # Tables must survive as DATA, not as a flattened caption string.
    tables = [b for b in blocks if b.type == "table"]
    assert any(len(t.rows) > 1 for t in tables), "no table kept more than one row"
    # This paper carries all six of its tables, including Table 1 — the one GROBID hands over as
    # an empty <table/>. A rowless table is kept for its caption, so what must never happen is a
    # table arriving with neither: that is a block conveying nothing.
    assert len(tables) == 6, f"a table went missing: {len(tables)} of 6"
    assert all(t.rows or t.caption for t in tables), (
        "a table came through with no rows and no caption"
    )
    rowless = [t for t in tables if not t.rows]
    assert len(rowless) == 1 and rowless[0].anchorLabel.startswith("Table 1")
    assert "Major challenges facing clinical development" in doc.fullText


def test_real_tei_crop_specs_stay_inside_their_pages() -> None:
    """Crop specs drive real page renders, so a bad bbox becomes a broken image downstream.

    ``teiCoordinates`` is requested for figures and formulas only (see ``GrobidHttpClient``), so
    what this pins is that GROBID's coordinates survive parsing as 1-based pages with ordered,
    non-degenerate boxes — the shape ``crop_assets_from_specs`` assumes.
    """
    specs = tei_crop_specs(_load_tei(), paper_id=TRIPLE, version=1)
    assert specs, "no crop specs recovered from a TEI that carries coords"

    for spec in specs:
        x0, y0, x1, y1 = spec.bbox
        assert spec.page >= 1, f"{spec.asset_id}: page is 1-based in GROBID coords"
        assert x1 > x0 and y1 > y0, f"{spec.asset_id}: degenerate bbox {spec.bbox}"
        assert x0 >= 0 and y0 >= 0, f"{spec.asset_id}: negative origin {spec.bbox}"

    # Ordinals are what align a rendered image with its doc-model block; duplicates would put
    # the wrong picture on a figure.
    per_type: dict[str, list[int]] = {}
    for spec in specs:
        per_type.setdefault(str(spec.type), []).append(spec.ordinal)
    for asset_type, ordinals in per_type.items():
        assert len(ordinals) == len(set(ordinals)), f"duplicate {asset_type} ordinals: {ordinals}"


def test_tei_text_projection_covers_the_structured_text() -> None:
    """``tei_to_text`` (withdrawal scan) and the doc-model must read the same document.

    They are separate walks over the same TEI, so they can drift apart. The flattened projection
    includes matter the doc-model drops (headers, reference list), hence >= rather than equality.
    """
    flat = tei_to_text(_load_tei())
    doc = _parse_tei()
    assert len(flat) >= len(doc.fullText) > 20_000
    # A distinctive mid-document sentence must appear in both.
    paragraphs = [
        b.root.text
        for s in doc.sections
        for b in s.blocks
        if b.root.type == "paragraph" and len(getattr(b.root, "text", "")) > 200
    ]
    assert paragraphs, "no substantial paragraph to cross-check"
    probe = paragraphs[len(paragraphs) // 2][:80]
    assert probe in flat, "the flattened projection is missing doc-model text"


# ---------------------------------------------------------------------------------------
# PDF — text extraction and bbox page-crop rendering.
# ---------------------------------------------------------------------------------------


def test_real_pdf_extracts_full_text() -> None:
    text = pdf_to_text(_load_pdf())
    assert len(text) > 20_000, f"PDF text extraction collapsed: {len(text)} chars"
    assert "AutoPrognosis" in text, "the title is missing from the extracted text"
    # Reading order: the abstract must precede the references.
    assert text.index("Abstract") < text.rindex("References")


def test_real_pdf_crops_render_for_every_tei_spec() -> None:
    """The TEI coords and the PDF are the two halves of the asset pipeline; test them joined.

    Rendering is best-effort in production (a failure yields no asset rather than an error), so a
    silent regression here would show up only as missing figures on the page. Assert the real
    specs really do render against the real PDF.
    """
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import crop_assets_from_specs

    specs = tei_crop_specs(_load_tei(), paper_id=TRIPLE, version=1)
    assets = crop_assets_from_specs(_load_pdf(), specs, paper_id=TRIPLE, version=1)

    assert len(assets) == len(specs), (
        f"{len(specs) - len(assets)} of {len(specs)} crops failed to render"
    )
    for asset in assets:
        assert asset.image, f"{asset.meta.asset_id}: rendered to empty bytes"
        # WebP is the delivered format (FR-17); the magic bytes are RIFF....WEBP.
        assert asset.image[:4] == b"RIFF" and asset.image[8:12] == b"WEBP", (
            f"{asset.meta.asset_id}: not a WebP image"
        )

    # Every rendered asset id must be referenced by a block, or the image has nowhere to land.
    # Walk the whole tree, not just the top level: the blocks carrying refs sit in subsections.
    doc = _parse_tei()

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    referenced = {
        b.root.assetRef.assetId
        for s in walk(doc.sections)
        for b in s.blocks
        if getattr(b.root, "assetRef", None)
    }
    for asset in assets:
        assert asset.meta.asset_id in referenced, (
            f"{asset.meta.asset_id} rendered but no doc-model block references it"
        )

# GROBID emits a <graphic> only for RASTER figures, so a vector figure arrives with coordinates
# covering nothing but its caption's text lines. Cropping those verbatim yields an image of the
# caption sentence — the figure itself is missing, while every structural assertion still passes.
# Maps asset id -> the caption-strip height (pt) GROBID supplied, measured from the fixture TEI.
_VECTOR_FIGURES = {
    f"{TRIPLE}:v1:figure:1": 44.6,  # p8, Figure 1 — architecture diagram
    f"{TRIPLE}:v1:figure:2": 20.7,  # p15, Figure 2 — decision curve plot
    f"{TRIPLE}:v1:figure:3": 68.5,  # p16, Figure 3 — value-of-information plot
}


def _rendered_bboxes() -> dict[str, tuple]:
    from docsuri_ingestion.asset_extraction import crop_assets_from_specs

    specs = tei_crop_specs(_load_tei(), paper_id=TRIPLE, version=1)
    assets = crop_assets_from_specs(_load_pdf(), specs, paper_id=TRIPLE, version=1)
    return {a.meta.asset_id: a.meta.bbox for a in assets}


def test_vector_figures_recover_the_graphic_grobid_did_not_locate() -> None:
    """A caption-only crop must be widened to the figure the PDF really carries.

    Asserting on the *height* rather than on rendering success is the point: the caption-only
    crops rendered perfectly well and were valid WebP, which is exactly why the existing
    assertions above could not see the defect.
    """
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    boxes = _rendered_bboxes()

    for aid, caption_height in _VECTOR_FIGURES.items():
        assert aid in boxes, f"{aid} produced no asset at all"
        x0, y0, x1, y1 = boxes[aid]
        height = y1 - y0
        assert height > caption_height * 2.5, (
            f"{aid}: crop is {height:.1f}pt tall against a {caption_height}pt caption strip — "
            "the graphic above the caption was not recovered"
        )
        assert 0 <= x0 < x1 and 0 <= y0 < y1, f"{aid}: degenerate bbox after recovery"


def test_figures_grobid_located_and_all_tables_keep_their_coordinates() -> None:
    """The recovery must be inert wherever GROBID's coordinates were already right.

    Figures 4/5 carry a <graphic>; figure 0 is a text block GROBID mislabelled a figure and has no
    graphic object to find; tables get their body coordinates. None may move — a recovery that
    widened these would be swallowing neighbouring page content.
    """
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    specs = {s.asset_id: s.bbox for s in tei_crop_specs(_load_tei(), paper_id=TRIPLE, version=1)}
    boxes = _rendered_bboxes()

    untouched = [aid for aid in specs if aid not in _VECTOR_FIGURES]
    assert len(untouched) == 9, f"fixture drifted: expected 9 untouched specs, got {untouched}"
    for aid in untouched:
        assert boxes[aid] == specs[aid], f"{aid}: bbox changed but GROBID's coordinates were sound"


# ---------------------------------------------------------------------------------------
# Chunking — what actually reaches the search index, fed from the real parsed documents.
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["html", "tei"])
def test_real_document_chunks_into_indexable_pieces(kind: str) -> None:
    """Parsing correctly is not enough: the doc-model still has to chunk.

    Chunking is where a parse regression becomes a *search* regression — a document that parses
    into one giant block, or into blocks whose ids do not resolve, still produces a DocModel but
    ruins retrieval. Synthetic input cannot show that, because it is already chunk-sized.
    """
    from docsuri_ingestion.processors import Chunker

    doc = _parse(TRIPLE) if kind == "html" else _parse_tei()
    chunker = Chunker()
    chunk_set = chunker.chunk_doc_model(doc)
    chunks = chunk_set.chunks

    assert chunks, "a full paper produced no chunks"
    assert len(chunks) <= chunker.max_chunks_per_paper
    # A real paper must not collapse into a couple of chunks, nor shatter into hundreds.
    assert 20 <= len(chunks) <= 100, f"{kind}: implausible chunk count {len(chunks)}"

    for chunk in chunks:
        assert chunk.text.strip(), f"{kind}: empty chunk at ordinal {chunk.ordinal}"
        assert len(chunk.text) <= chunker.max_chunk_chars, (
            f"{kind}: chunk {chunk.ordinal} is {len(chunk.text)} chars, over the embedding cap"
        )

    # Ordinals are the chunk id input, so gaps or repeats would collide ids across a paper.
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert len({c.chunk_id for c in chunks}) == len(chunks), "duplicate chunk ids"

    # Block refs are what lets a search hit anchor back to a place in the document. Every ref
    # must name a block that really exists, or the citation lands nowhere.
    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    real_blocks = {(s.id, b.root.id) for s in walk(doc.sections) for b in s.blocks}
    for chunk in chunks:
        assert chunk.block_refs, f"{kind}: chunk {chunk.ordinal} has no block refs to anchor on"
        for ref in chunk.block_refs:
            assert (ref.section_id, ref.block_id) in real_blocks, (
                f"{kind}: chunk {chunk.ordinal} references unknown block "
                f"{ref.section_id}/{ref.block_id}"
            )

    # Chunks must span the document, not just its opening.
    assert len({c.section for c in chunks}) >= 10, f"{kind}: chunks cover too few sections"


def test_no_cell_grobid_reconstructed_is_lost_in_translation() -> None:
    """We must carry over every cell GROBID gives us, however poor its reconstruction is.

    GROBID 0.8.0 merges and truncates cells on this paper's wider tables — ``Table 2``'s
    "Dimensionality Reduction" header arrives as ``'Dimensionality Fast ICA '`` and ``PCA (1)``
    is swallowed into a neighbour. That damage is in the TEI itself, so it is not ours to repair:
    inventing the split would fabricate numbers, and the crop image exists precisely as the
    last-resort re-read path for it (D8 / TD-11). What IS ours is losing nothing on the way
    across, which is what this pins.
    """
    from xml.etree import ElementTree as ET

    root = ET.fromstring(_load_tei())
    local = lambda tag: tag.rsplit("}", 1)[-1]  # noqa: E731
    tei_cells = [
        [c for c in row if local(c.tag) == "cell"]
        for fig in root.iter()
        if local(fig.tag) == "figure" and (fig.get("type") or "") == "table"
        for table in fig.iter()
        if local(table.tag) == "table"
        for row in table
        if local(row.tag) == "row" and any(local(c.tag) == "cell" for c in row)
    ]

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    doc = _parse_tei()
    tables = [b.root for s in walk(doc.sections) for b in s.blocks if b.root.type == "table"]
    doc_rows = [row.cells for t in tables for row in t.rows]

    assert len(doc_rows) == len(tei_cells), "a row GROBID reconstructed never reached the doc-model"
    for parsed, raw in zip(doc_rows, tei_cells, strict=True):
        assert len(parsed) == len(raw), "cells were dropped while copying a row across"
    # And the damaged text is carried verbatim rather than silently "cleaned" into something else.
    flat = [c.text for cells in doc_rows for c in cells]
    assert "Dimensionality Fast ICA" in " ".join(flat)


# ---------------------------------------------------------------------------------------
# TEI formulas and algorithms — the maths-heavy path 2210.12090 could not reach.
# ---------------------------------------------------------------------------------------


def _tei_blocks(paper_id: str):
    doc = _parse_tei(paper_id)

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    return doc, [b.root for s in walk(doc.sections) for b in s.blocks]


def _section_of(doc, block_id: str):
    """The section holding ``block_id`` — GROBID sometimes puts a listing's heading there."""

    def walk(sections):
        for section in sections:
            yield section
            yield from walk(section.sections or [])

    return next(s for s in walk(doc.sections) if any(b.root.id == block_id for b in s.blocks))


@pytest.mark.parametrize("paper_id", [FORMULA_PAPER, "2112.01799"])
def test_tei_display_formulas_become_image_backed_blocks(paper_id: str) -> None:
    """On the PDF path a formula is an IMAGE, deliberately, and carries no LaTeX (TD-12/3a).

    That is not an oversight to be "fixed" later: GROBID's own formula text for these papers is
    font-mangled beyond use — equation (1) of 2607.16138 arrives as
    ``'r a " # w a a " 1 w a ´řa´1 i"1 ...'``. Indexing that would poison search and hand U7's
    numeric-match garbage to ground against. The block therefore points at a page-crop and the
    LaTeX stays empty; the ar5iv path is where real LaTeX comes from.
    """
    _doc, blocks = _tei_blocks(paper_id)
    formulas = [b for b in blocks if b.type == "formula"]

    assert len(formulas) >= 20, f"{paper_id}: display maths collapsed to {len(formulas)} blocks"
    for block in formulas:
        assert block.display is True
        assert block.assetRef is not None, "a formula with no image has no representation at all"
        assert block.assetRef.sourceMode.value == "page-crop"
        assert not (block.latex or ""), "TEI formulas must not carry GROBID's mangled text as LaTeX"


def test_tei_formula_crop_specs_are_renderable_regions() -> None:
    specs = [
        s
        for s in tei_crop_specs(_load_tei(FORMULA_PAPER), paper_id=FORMULA_PAPER, version=1)
        if s.type.value == "formula"
    ]
    assert len(specs) >= 20, f"only {len(specs)} formula crop specs"
    for spec in specs:
        x0, y0, x1, y1 = spec.bbox
        assert spec.page >= 1
        assert x1 > x0 and y1 > y0, f"{spec.asset_id}: degenerate bbox {spec.bbox}"
        assert x0 >= 0 and y0 >= 0


def test_tei_formula_crops_actually_render_from_the_real_pdf() -> None:
    """The half that specs alone cannot prove — that the coordinates hit real ink."""
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import crop_assets_from_specs

    specs = tei_crop_specs(_load_tei(FORMULA_PAPER), paper_id=FORMULA_PAPER, version=1)
    assets = crop_assets_from_specs(
        _load_pdf(FORMULA_PAPER), specs, paper_id=FORMULA_PAPER, version=1
    )
    # One spec is deliberately refused: GROBID made a formula element out of a stray ")" and its
    # 4.4x9.6pt region cannot hold an equation. Everything else must render.
    refused = {f"{FORMULA_PAPER}:v1:formula:23"}
    rendered = {a.meta.asset_id for a in assets}
    assert {s.asset_id for s in specs} - rendered == refused, (
        f"unexpected crops missing: {sorted({s.asset_id for s in specs} - rendered - refused)}"
    )
    formulas = [a for a in assets if a.meta.type.value == "formula"]
    assert len(formulas) >= 20
    for asset in formulas:
        assert asset.image[:4] == b"RIFF" and asset.image[8:12] == b"WEBP"
        # A formula strip is short but never a hairline: a collapsed bbox would still be valid WebP.
        _x0, y0, _x1, y1 = asset.meta.bbox
        assert y1 - y0 >= 8.0, f"{asset.meta.asset_id}: {y1 - y0:.1f}pt tall, likely an empty strip"


def test_algorithm_floats_grobid_filed_as_formulas_become_searchable_listings() -> None:
    """GROBID has no algorithm concept: it labels an ``algorithm`` float a ``<formula>`` and often
    splits one listing across several of them, so the pseudocode used to arrive as a page-crop
    image like any equation — readable, but invisible to search and unquotable by an agent.

    Unlike equation glyphs the listing's text survives extraction well enough to index, so each
    listing becomes a code block that KEEPS its crop: the text is searchable, the image still
    renders faithfully. This paper carries two listings, and GROBID hands the tail of the first
    one over inside the second float — that tail must rejoin the listing it belongs to.
    """
    doc, blocks = _tei_blocks(FORMULA_PAPER)

    listings = [b for b in blocks if b.type == "code"]
    assert [b.text[:11] for b in listings] == ["Algorithm 1", "Algorithm 2", "1: if algor"]
    assert "end if 12: end if 13:" in listings[0].text, "the split-off tail did not rejoin"
    # The third listing is the one GROBID filed as a SECTION titled "Algorithm 3 …", leaving its
    # steps in headless formulas; those fragments join one block rather than becoming three.
    assert _section_of(doc, listings[2].id).title.startswith("Algorithm 3")
    assert "15:" in listings[2].text
    assert [b.assetRef.assetId for b in listings] == [
        f"{FORMULA_PAPER}:v1:formula:3",  # verified by eye: the "Algorithm 1 Step 2" crop
        f"{FORMULA_PAPER}:v1:formula:5",
        f"{FORMULA_PAPER}:v1:formula:7",
    ]
    # Searchable now: the listing text reaches fullText as its own block, not as caption prose.
    assert "Algorithm 1 Step 2 of IKPLS" in doc.fullText


def test_recovery_ignores_decorative_vector_glyphs() -> None:
    """Only a graphic big enough to BE a figure may widen a crop.

    A QED tombstone is drawn as four hairline FORM XObjects (0.5pt thick), and GROBID mislabels
    the "Proposition 3" block above one as a figure. Without a size floor the recovery latched
    onto that glyph and dragged the tail of the preceding proof into the crop — the exact
    "widened into unrelated content" failure the recovery is supposed to refuse. Verified by eye:
    figure:3 is a real heatmap and must still be recovered, figure:0 must not move.
    """
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import crop_assets_from_specs

    specs = tei_crop_specs(_load_tei(FORMULA_PAPER), paper_id=FORMULA_PAPER, version=1)
    by_spec = {s.asset_id: s.bbox for s in specs}
    assets = crop_assets_from_specs(
        _load_pdf(FORMULA_PAPER), specs, paper_id=FORMULA_PAPER, version=1
    )
    widened = {a.meta.asset_id for a in assets if a.meta.bbox != by_spec[a.meta.asset_id]}

    assert widened == {f"{FORMULA_PAPER}:v1:figure:3"}, (
        f"recovery fired on the wrong blocks: {sorted(widened)}"
    )


# ---------------------------------------------------------------------------------------
# e-print LaTeX — the tier between ar5iv and the PDF, and the only source of original-quality
# figure rasters. Synthetic tarballs cannot reproduce what this checks: real member names.
# ---------------------------------------------------------------------------------------

EPRINT_PAPER = TRIPLE


def _load_eprint(paper_id: str = EPRINT_PAPER) -> bytes:
    return (FIXTURE_ROOT / "eprint" / f"{paper_id}.tar.gz").read_bytes()


def _figure_specs(paper_id: str):
    specs: list = []
    parse_html_to_docmodel(
        _load(paper_id),
        paper_id=paper_id,
        version=1,
        title="Fixture Paper",
        abstract=None,
        source_tier=SourceTier.ar5iv,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
        figure_specs=specs,
    )
    return specs


def test_eprint_figures_match_by_stem_only_where_ar5iv_kept_the_authors_filename() -> None:
    """Stem matching against a REAL tarball, which is the whole point of this fixture.

    ar5iv rewrites a figure it rendered itself to ``x1.png``/``x2.png``/``x3.png`` while leaving
    author-supplied rasters under their own names. So only the figures the author shipped as PNGs
    can be found in the e-print, and the rest must fall through to the page-crop path — an
    all-or-nothing rule ("any structured hit disables page-crops") would blank them. The ordinals
    must survive the gap so each assetId still lands on the FigureBlock that references it.
    """
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import AssetExtractor

    specs = _figure_specs(EPRINT_PAPER)
    assert [s.src.rsplit("/", 1)[-1] for s in specs] == [
        "x1.png",
        "x2.png",
        "x3.png",
        "shap_values_ap.png",
        "AP_diabetes_webapp.png",
    ], "the ar5iv fixture's figure sources moved — re-derive what should match"

    candidates = AssetExtractor()._structured_figures(_load_eprint(), specs)
    assert [c.ordinal for c in candidates] == [3, 4], "stem matching picked the wrong figures"
    for candidate in candidates:
        assert candidate.source_mode.value == "structured"
        assert candidate.image, "a matched figure normalized to nothing"


def test_eprint_vector_sources_are_skipped_rather_than_stored_broken() -> None:
    """The tarball's other three figures are ``.pdf``. Without a doc-model to guide it the legacy
    scan takes rasters only, so the vector sources cannot leak in as undecodable bytes."""
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import AssetExtractor

    assert len(AssetExtractor()._structured_figures(_load_eprint())) == 2


def test_eprint_preamble_macros_are_recovered_from_the_real_source() -> None:
    """Doc-model formulas expand author macros, which only exist in the e-print preamble."""
    from docsuri_ingestion.docmodel.macros import extract_macros

    macros = extract_macros(_load_eprint())
    assert macros == {"\\proposed": "{AutoPrognosis}", "\\proposedf": "{AutoPrognosis 2.0}"}


def test_hybrid_extraction_images_every_figure_and_table_on_this_paper() -> None:
    """The full ar5iv + e-print + PDF resolution on real inputs — every figure and table imaged.

    This paper is the reason the caption scan cannot assume a tidy layout, and no synthetic PDF
    reproduces either trap:

    * **Two-column pages merge their captions.** ``extract_text_lines`` joins both columns at the
      same height into one line, so the right column's captions (Figure 3, Figure 4, Table 4) do
      not START their line. They are recovered by their column-start x, while the body
      cross-references on the same pages ("… is provided in Figure 1.") stay rejected.
    * **Table captions are printed on both sides.** Tables 1 and 2 are captioned UNDER the table,
      Tables 3, 5 and 6 above it. A one-sided rule loses whichever half it does not expect.

    The Figure 4 recovery also keeps its page-16 graphic off the Table 5 crop, which used to
    swallow it — hence the bbox assertion below.
    """
    pytest.importorskip("pdfplumber")
    pytest.importorskip("PIL")
    from docsuri_ingestion.asset_extraction import AssetExtractor

    assets = AssetExtractor().extract(
        paper_id=EPRINT_PAPER,
        version=1,
        pdf=_load_pdf(EPRINT_PAPER),
        eprint=_load_eprint(),
        figure_specs=_figure_specs(EPRINT_PAPER),
    )
    by_mode = {a.meta.asset_id: a.meta.source_mode.value for a in assets}

    assert by_mode == {
        f"{EPRINT_PAPER}:v1:figure:0": "page-crop",  # Figure 1
        f"{EPRINT_PAPER}:v1:figure:1": "page-crop",  # Figure 2
        f"{EPRINT_PAPER}:v1:figure:2": "page-crop",  # Figure 3 — right column of a merged line
        f"{EPRINT_PAPER}:v1:figure:3": "structured",  # author raster, original quality
        f"{EPRINT_PAPER}:v1:figure:4": "structured",
        f"{EPRINT_PAPER}:v1:table:0": "page-crop",  # Table 1 — caption printed under the table
        f"{EPRINT_PAPER}:v1:table:1": "page-crop",  # Table 2 — likewise
        f"{EPRINT_PAPER}:v1:table:2": "page-crop",  # Table 3
        f"{EPRINT_PAPER}:v1:table:3": "page-crop",  # Table 4 — right column of a merged line
        f"{EPRINT_PAPER}:v1:table:4": "page-crop",  # Table 5
        f"{EPRINT_PAPER}:v1:table:5": "page-crop",  # Table 6
    }, "every figure and table on this paper must be imaged — do not re-record a regression here"

    table5 = next(a for a in assets if a.meta.asset_id == f"{EPRINT_PAPER}:v1:table:4")
    assert table5.meta.page_ref == 16
    assert table5.meta.bbox[3] < 300, (
        "the Table 5 crop reaches down into Figure 4's graphic again (page 16, top 345-543)"
    )
