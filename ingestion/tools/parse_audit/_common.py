"""Shared metric helpers for the parse-audit scripts.

Deliberately self-contained — no import from ``docsuri_ingestion`` beyond the parser entry points
the individual scripts call. The A/B sweep runs the SAME measurement from two checkouts (this branch
and its merge base), so the yardstick must not depend on helpers that exist in only one of them.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_HTML_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TEI_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+", re.IGNORECASE)


def _title_key(markup: str, pattern: re.Pattern[str]) -> str:
    match = pattern.search(markup or "")
    if match is None:
        return ""
    text = _TAG_RE.sub(" ", match.group(1))
    # ar5iv prefixes the arXiv id ("[2507.21184] EvoSLD: …"); the id is not part of the title.
    return _NON_ALNUM_RE.sub("", re.sub(r"^\s*\[?\d{4}\.\d{4,5}\]?", "", text)).lower()


def same_paper(tei: str, html: str) -> bool:
    """Whether a TEI and an ar5iv page are the SAME paper, by title.

    ar5iv serves whatever version it has built and ignores the ``v5`` in the requested URL, so a
    cross-source comparison can silently line up two different papers — 4 of 12 in one sweep, where
    the PDF was "CAN LANGUAGE MODELS DISCOVER SCALING LAWS?" and ar5iv "EvoSLD: Automated Neural
    Scaling Law Discovery". Every ratio measured against that pair is noise, and it looks exactly
    like a parser regression. Comparing an opening stretch, since the two renderings disagree about
    subtitles and trailing punctuation.
    """
    a, b = _title_key(tei, _TEI_TITLE_RE), _title_key(html, _HTML_TITLE_RE)
    if not a or not b:
        return True  # cannot tell — do not drop the paper on a missing title
    return a[:30] in b or b[:30] in a


def walk_sections(doc: dict) -> Iterator[dict]:
    """Every section in a doc-model dict, depth-first (top-level walk misses nested subsections)."""
    for section in doc.get("sections") or []:
        yield section
        yield from walk_sections(section)


def block_text(block: dict) -> str:
    """The searchable text a block contributes — the same fields DocModel.fullText projects."""
    kind = block.get("type")
    if kind in ("paragraph", "code"):
        return block.get("text") or ""
    if kind == "formula":
        return block.get("latex") or block.get("latexOcr") or ""
    if kind == "list":
        return " ".join(item.get("text") or "" for item in block.get("items") or [])
    if kind == "table":
        return " ".join(
            cell.get("text") or ""
            for row in block.get("rows") or []
            for cell in row.get("cells") or []
        )
    return block.get("caption") or ""


def counts(doc: dict) -> dict:
    """Per-paper shape a sweep records: block-kind tallies plus projections a regression moves."""
    sections = list(walk_sections(doc))
    blocks = [b for s in sections for b in (s.get("blocks") or [])]
    kinds: dict[str, int] = {}
    # Block COUNT and block TEXT move independently: the PDF path emits the right number of
    # formula blocks while their text is empty, which a kind tally alone reads as healthy. Split
    # body_chars by kind so a sweep names which kind lost the characters.
    chars: dict[str, int] = {}
    for block in blocks:
        kinds[block["type"]] = kinds.get(block["type"], 0) + 1
        chars[block["type"]] = chars.get(block["type"], 0) + len(block_text(block))
    return {
        "sections": len(sections),
        "blocks": len(blocks),
        "kinds": kinds,
        "chars_by_kind": chars,
        # Derived, not re-walked: the loop above already totalled it per kind, and two independent
        # sums of the same thing can only ever disagree by being wrong.
        "body_chars": sum(chars.values()),
        "captions": sum(1 for b in blocks if b.get("caption")),
        "empty_sections": sum(
            1 for s in sections if not (s.get("blocks") or []) and not (s.get("sections") or [])
        ),
        "empty_tables": sum(
            1 for b in blocks if b["type"] == "table" and not (b.get("rows") or [])
        ),
    }


_WS_ONLY_RE = re.compile(r"\s+")
# How much of a caption is compared, and how much is enough to compare at all. Both sweeps judge
# "did this caption reach fullText" the same way, and they are read side by side as PDF-path
# against ar5iv-path preservation — so the yardstick has to be one yardstick. Tuning the probe in
# one file and not the other leaves nothing failing and the comparison quietly wrong.
_CAPTION_PROBE_CHARS = 60
_CAPTION_PROBE_MIN_CHARS = 20


def strip_ws(text: str) -> str:
    """Whitespace removed and lowercased — how both sides of a text-preservation check compare.

    Stripping rather than normalizing, because a block field and the fullText projection disagree
    about where the spaces go; on the stripped forms a preserved caption is an exact substring.
    """
    return _WS_ONLY_RE.sub("", text or "").lower()


def caption_probe(caption: str) -> str:
    """The stripped leading slice used to look a caption up in fullText, or "" if too short.

    A short caption cannot be judged reliably: an eight-character probe finds itself somewhere in
    almost any body text, so it would report every caption preserved.
    """
    probe = strip_ws(caption)[:_CAPTION_PROBE_CHARS]
    return probe if len(probe) >= _CAPTION_PROBE_MIN_CHARS else ""


def figures_without_assetref(doc: dict) -> dict:
    """``{"doc_figures_no_assetref": n}`` — figures the parser landed with no asset reference.

    The one doc-side signal ``counts()`` does not yield and both sweeps' ``_violations`` consume.
    Shared rather than derived twice: the two sweeps publish this number under the same key and it
    is read as PDF-path against ar5iv-path, so one definition of "has a reference" is the point.
    """
    blocks = [b for s in walk_sections(doc) for b in (s.get("blocks") or [])]
    return {
        "doc_figures_no_assetref": sum(
            1 for b in blocks if b.get("type") == "figure" and not b.get("assetRef")
        ),
    }
