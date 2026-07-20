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


def _parse_tei():
    return parse_tei_to_docmodel(
        _load_tei(),
        paper_id=TRIPLE,
        version=1,
        title="Fixture Paper",
        abstract=None,
        source_tier=SourceTier.pdf,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=_FIXED_TS,
    )


def test_real_tei_parses_to_the_recorded_structure() -> None:
    _assert_matches_recorded(
        _digest(_parse_tei()), FIXTURE_ROOT / "grobid" / f"{TRIPLE}.digest.json", f"{TRIPLE} TEI"
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
    assert all(t.rows for t in tables), "a table came through with no rows at all"


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
