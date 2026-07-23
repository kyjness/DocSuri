#!/usr/bin/env python
"""Preservation audit — does content present in the ORIGINAL ar5iv source reach the doc-model?

Not a bug re-check and not an A/B regression (that is ``measure_html.py`` + ``diff.py``). This is an
*absolute* loss detector: for a cached ar5iv HTML, count the structural signals the source carries
(tabulars, numbered float captions, lists, listings, equations) and verify the current parser lands
a corresponding block. A source signal with no block is content loss — the failure class every past
u1 defect belonged to (dropped span paragraphs, undetected captions, empty tables).

The source-side detectors are written INDEPENDENTLY of ``docmodel/parser.py`` on purpose: an audit
that imported the parser's own class/regex vocabulary would share its blind spots and prove nothing.
They mirror the LaTeXML ``ltx_*`` vocabulary the parser keys on, but decide loss on their own.

Honest scope: this proves the *loss* class only. Order scrambling, wrong crop content, a caption
bound to the wrong float — "broken but not missing" — are correctness defects this cannot see; they
stay with the crop-dump eye-check. assetRef is checked at the PARSING level (did the parser emit a
non-null reference for a graphic-bearing figure); whether the WebP actually renders needs the asset
extraction path and is out of scope here.

Parser only: no network, no assets, no embedding. Reads a cache written by ``corpus_sample.py``.

Usage::

    uv run python tools/parse_audit/preservation_audit.py --cache /tmp/parse-audit --out audit.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from _common import counts, walk_sections
from bs4 import BeautifulSoup, Tag
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.full_text_extraction import html_to_text

_TS = datetime(2026, 1, 1, tzinfo=UTC)

# fullText coverage below this (body chars / source chars) flags a paper as under-covered. The
# residual above 1.0 - threshold is expected and NOT loss: authors/affiliations/References live
# outside the block tree by design, and a math-heavy paper stores display math as compact LaTeX
# where html_to_text renders long unicode — so 0.55-0.75 is normal. The threshold is set to catch
# only GROSS under-coverage (roughly half the readable text gone), calibrated on the dry run where
# healthy math-heavy papers bottomed out around 0.56.
_COVERAGE_MIN = 0.50

# Numbered float caption tags as LaTeXML writes them into an ``ltx_tag`` span: "Figure 7:",
# "Fig. 2", "TABLE III:". Defined here, NOT imported from the parser, so the audit judges the source
# on its own. Roman numerals are covered by the table pattern's ``\b`` + free-form tail.
_FIG_CAPTION_RE = re.compile(r"^\s*(figure|fig\.?)\s*\d+", re.IGNORECASE)
_TABLE_CAPTION_RE = re.compile(r"^\s*table\b", re.IGNORECASE)
# A sub-panel mark ("(a)", "(b)") is NOT a numbered float — the parser folds panels into one figure,
# so counting them would inflate the expected block count and cry loss where there is none.
_PANEL_MARK_RE = re.compile(r"^\s*\(?[a-z]\)?\s*$", re.IGNORECASE)


def _classes(node: Tag) -> set[str]:
    value = node.get("class")
    return set(value) if value else set()


def _standalone(nodes: list[Tag], forbidden: set[str]) -> int:
    """Count nodes the parser reaches as a STANDALONE block — none with a ``forbidden`` ancestor.

    Two things make a source element not its own block: nesting inside another of the same kind (a
    sub-list is part of its parent list), and living inside a paragraph (``ltx_p``) — inline
    ``\\verb`` comes out as ``<code class="ltx_verbatim">`` inside a paragraph, and the parser folds
    it into the paragraph text rather than dispatching a code block. Counting either cries loss.
    """
    return sum(
        1
        for node in nodes
        if not any(isinstance(a, Tag) and (forbidden & _classes(a)) for a in node.parents)
    )


def _source_signals(soup: BeautifulSoup) -> dict:
    """Count what the ORIGINAL source structurally contains, by the LaTeXML ``ltx_*`` vocabulary.

    Only signals that map reliably to a doc-model block become violations (see ``_violations``).
    ``src_tabulars`` and ``src_equations`` are recorded for drill-down context but NOT used to flag
    loss: ``ltx_tabular`` also lays out author lists / aligned math / nested sub-tables, and
    ``ltx_equationgroup`` nests ``ltx_equation`` while the parser splits aligned lines per row — so
    neither element count maps 1:1 to blocks. Table loss is caught by caption + empty-table instead.
    """
    list_marker = {"ltx_itemize", "ltx_enumerate"}
    listing_marker = {"ltx_listing", "ltx_verbatim"}
    tabulars = [n for n in soup.find_all(["table", "span"]) if "ltx_tabular" in _classes(n)]
    lists = [n for n in soup.find_all(["ul", "ol"]) if list_marker & _classes(n)]
    listings = [n for n in soup.find_all(True) if listing_marker & _classes(n)]
    eq_marker = {"ltx_equation", "ltx_equationgroup"}
    equations = [n for n in soup.find_all(True) if eq_marker & _classes(n)]
    fig_captions = 0
    table_captions = 0
    for caption in soup.find_all(class_="ltx_caption"):
        tag = caption.find("span", class_="ltx_tag")
        text = tag.get_text() if tag is not None else ""
        if _PANEL_MARK_RE.match(text):
            continue
        if _FIG_CAPTION_RE.match(text):
            fig_captions += 1
        elif _TABLE_CAPTION_RE.match(text):
            table_captions += 1
    return {
        "src_tabulars": len(tabulars),  # context only
        "src_equations": len(equations),  # context only
        "src_fig_captions": fig_captions,
        "src_table_captions": table_captions,
        "src_lists": _standalone(lists, list_marker | {"ltx_p"}),
        "src_listings": _standalone(listings, listing_marker | {"ltx_p"}),
    }


def _docmodel_signals(doc: dict) -> dict:
    """Count what the parsed doc-model actually landed, per block type."""
    blocks = [b for s in walk_sections(doc) for b in (s.get("blocks") or [])]
    by_type: Counter[str] = Counter(b.get("type") for b in blocks)
    figures = [b for b in blocks if b.get("type") == "figure"]
    tables = [b for b in blocks if b.get("type") == "table"]
    return {
        "doc_tables": by_type.get("table", 0),
        "doc_figures": by_type.get("figure", 0),
        "doc_lists": by_type.get("list", 0),
        "doc_code": by_type.get("code", 0),
        "doc_formulas": by_type.get("formula", 0),
        "doc_tables_with_caption": sum(1 for b in tables if b.get("caption")),
        "doc_empty_tables": sum(1 for b in tables if not (b.get("rows") or [])),
        "doc_figures_no_assetref": sum(1 for b in figures if not b.get("assetRef")),
    }


def _violations(sig: dict) -> list[str]:
    """Defect types this paper exhibits — a source signal that no block accounts for.

    Comparisons are ``source > doc`` shortfalls (loss), kept conservative so parser-intended merges
    (multi-panel figures, sub-tabulars in one float) do not read as loss. Each returned string is a
    defect TYPE; the caller tallies papers per type.
    """
    v: list[str] = []
    # Numbered floats — the reliable 1:1 signal: a "Figure N"/"TABLE III" caption in the source with
    # no block to carry it. This is the class every past caption-loss defect fell into.
    if sig["src_fig_captions"] > sig["doc_figures"]:
        v.append("figure_caption_shortfall")
    if sig["src_table_captions"] > sig["doc_tables_with_caption"]:
        v.append("table_caption_shortfall")
    # A table block emptied of its rows (caption may survive; rows lost).
    if sig["doc_empty_tables"]:
        v.append("empty_table")
    # Lists / listings: top-level source count vs blocks (nested folded out in _top_level).
    if sig["src_lists"] > sig["doc_lists"]:
        v.append("list_shortfall")
    if sig["src_listings"] > sig["doc_code"]:
        v.append("code_shortfall")
    # Structural: a figure block that never got an asset reference.
    if sig["doc_figures_no_assetref"]:
        v.append("figure_missing_assetref")
    # Coverage: body text GROSSLY short of the source's readable text (half or more gone).
    if sig["coverage"] is not None and sig["coverage"] < _COVERAGE_MIN:
        v.append("coverage_low")
    return v


def _audit_one(paper_id: str, version: int, html: str) -> dict:
    doc = parse_html_to_docmodel(
        html,
        paper_id=paper_id,
        version=version,
        title="",
        abstract=None,
        source_tier=SourceTier.ar5iv,
        parser_version="audit",
        schema_version="audit",
        generated_at=_TS,
    ).model_dump(mode="json")
    sig = {**_source_signals(BeautifulSoup(html or "", "lxml")), **_docmodel_signals(doc)}
    sig.update(counts(doc))
    source_chars = len(html_to_text(html))
    sig["source_chars"] = source_chars
    sig["coverage"] = round(sig["body_chars"] / source_chars, 4) if source_chars else None
    return {
        "paper_id": paper_id,
        "version": version,
        "violations": _violations(sig),
        "signals": sig,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="cache dir from corpus_sample.py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    targets = json.loads((args.cache / "targets.json").read_text())
    by_type: Counter[str] = Counter()
    papers = 0
    errors = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            path = args.cache / "html" / f"{key}.html"
            try:
                row = _audit_one(
                    target["paper_id"], target["version"], path.read_text(errors="replace")
                )
            except Exception as exc:  # noqa: BLE001 - a crash is itself a preservation failure
                error = f"{type(exc).__name__}: {exc}"
                row = {**target, "error": error, "violations": ["parse_error"]}
                errors += 1
            for kind in row["violations"]:
                by_type[kind] += 1
            papers += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 50 == 0 or "error" in row:
                print(f"[{i}/{len(targets)}] {key} {row.get('error', '')}", flush=True)

    print(f"\nwrote {args.out}  ({papers} papers, {errors} parse errors)")
    print("\n=== defect types by frequency (papers affected) ===")
    for kind, n in by_type.most_common():
        print(f"  {kind:28s} {n:5d}  ({n / papers:.1%})")
    if not by_type:
        print("  (none — every source signal accounted for)")


if __name__ == "__main__":
    main()
