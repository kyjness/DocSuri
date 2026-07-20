"""Golden-fixture regression tests over real ar5iv renderings.

Every other parser test in this unit feeds hand-written markup. That verifies the mapping rules
but not the thing deployment used to verify by eye: that a *real* LaTeXML conversion — with its
nesting depth, subfigure grouping, and MathML volume — still comes out whole. With the deployment
retired there is no other place that check can happen, so it happens here.

The digest deliberately stores shapes and content hashes rather than the full DocModel: it stays
a few KB, and any real change to structure, ordering, or text still moves it. Regenerate with
``DOCSURI_UPDATE_FIXTURES=1`` and review the diff — see ``fixtures/ar5iv/SOURCES.md``.
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
from docsuri_ingestion.full_text_extraction import html_to_text

FIXTURES = Path(__file__).parent / "fixtures" / "ar5iv"
_FIXED_TS = datetime(2026, 1, 1, tzinfo=UTC)
_UPDATE = os.environ.get("DOCSURI_UPDATE_FIXTURES") == "1"

# 2305.02531 is the ar5iv "no content" page, exercised separately below.
PAPERS = ["2210.12090", "2112.01799"]


def _load(paper_id: str) -> str:
    with gzip.open(FIXTURES / f"{paper_id}.html.gz", "rt", encoding="utf-8") as handle:
        return handle.read()


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


@pytest.mark.parametrize("paper_id", PAPERS)
def test_real_paper_parses_to_the_recorded_structure(paper_id: str) -> None:
    digest = _digest(_parse(paper_id))
    path = FIXTURES / f"{paper_id}.digest.json"

    if _UPDATE or not path.exists():
        path.write_text(json.dumps(digest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if not _UPDATE:
            pytest.fail(f"wrote missing digest {path.name}; re-run to verify against it")

    expected = json.loads(path.read_text(encoding="utf-8"))
    assert digest == expected, (
        f"{paper_id}: parsed structure drifted from the recorded digest. If the change is "
        "intended, regenerate with DOCSURI_UPDATE_FIXTURES=1 and review the diff."
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
