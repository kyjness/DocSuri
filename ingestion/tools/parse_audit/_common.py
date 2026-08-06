"""Shared metric helpers for the parse-audit scripts.

Deliberately self-contained — no import from ``docsuri_ingestion`` beyond the parser entry points
the individual scripts call. The A/B sweep runs the SAME measurement from two checkouts (this branch
and its merge base), so the yardstick must not depend on helpers that exist in only one of them.
"""

from __future__ import annotations

from collections.abc import Iterator


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
        "body_chars": sum(len(block_text(b)) for b in blocks),
        "captions": sum(1 for b in blocks if b.get("caption")),
        "empty_sections": sum(
            1 for s in sections if not (s.get("blocks") or []) and not (s.get("sections") or [])
        ),
        "empty_tables": sum(
            1 for b in blocks if b["type"] == "table" and not (b.get("rows") or [])
        ),
    }
