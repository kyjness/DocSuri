#!/usr/bin/env python
"""What the Docling page cap actually buys, per repair path, on real PDFs.

``DoclingTableExtractor`` re-reads only the first ``_max_pages`` suspect pages of a paper. That cap
is the batch's wall-clock lever — the re-read is the dominant term of ⑧-2 — and it was set without
a measurement of what the pages past it are worth. This measures it, separately for the two paths
that feed the re-read (``_needs_repair``): tables whose cells came out EMPTY and tables whose cells
came out GLUED, since ⑧-2's open item asks whether the empty path deserves its own lower cap.

ONE Docling pass, every cap evaluated offline. The re-read is the expensive part (seconds per
page), so pages are read once at no cap and each candidate cap is then replayed against that same
extraction — ``apply_repairs`` on a fresh copy of the doc, restricted to the pages the cap would
have allowed. So "cap 4 repairs 9 tables" here is what the pipeline would have produced, not a
model of it, and every cap is measured on identical input.

Needs the ``tables`` extra and a cache built by ``corpus_sample.py --pdf`` plus TEI from
``pdf_grobid_audit.py``. Do NOT run this with GROBID up — the two OOM together (⑧-1.10).

Usage::

    uv run --extra tables python tools/parse_audit/docling_page_cap_sweep.py \
        --cache ~/data/parse-audit-82 --out cap_sweep.jsonl
"""

from __future__ import annotations

import argparse
import copy
import json
import time
from pathlib import Path

from _pipeline import build_doc, tei_for

from docsuri_ingestion.adapters.docling_tables import DoclingTableExtractor
from docsuri_ingestion.docmodel.parser import iter_blocks
from docsuri_ingestion.docmodel.table_repair import (
    _cells_of,
    apply_repairs,
    printed_text,
    tables_needing_repair,
)

# Caps to price. 12 is today's default; 0 is "no re-read at all", the floor every other number is
# an improvement over.
CAPS = (0, 1, 2, 3, 4, 6, 8, 12, 16, 24)

# Pages read per paper in the measuring pass. Above any plausible cap — the point is to see what
# the tail holds — but still bounded, since a pathological paper would otherwise stall the sweep.
_SWEEP_MAX_PAGES = 24


def _cells_by_asset(doc: dict) -> dict[str, list[str]]:
    return {
        (block.get("assetRef") or {}).get("assetId", ""): _cells_of(block.get("rows") or [])
        for block in iter_blocks(doc, "table")
    }


def _classify(cells_before: dict[str, list[str]], specs: list) -> dict[str, str]:
    """asset_id -> "empty" | "glued", for the tables the repair path picked up.

    Split exactly as ``_needs_repair`` splits them — on cell TEXT, not on whether rows exist —
    so these are the same two populations the pipeline routes on. Only tables in ``specs`` are
    classified; a healthy table is never re-read and has no path.
    """
    kinds: dict[str, str] = {}
    for spec in specs:
        cells = [cell for cell in cells_before.get(spec.asset_id, []) if cell.strip()]
        kinds[spec.asset_id] = "empty" if not cells else "glued"
    return kinds


def _repairs_by_path(
    cells_before: dict[str, list[str]], after: dict, kinds: dict[str, str]
) -> dict[str, int]:
    """Repairs split by path. ``apply_repairs`` returns a single total, and the whole question
    here is which of the two paths the total came from.

    Judged on the cell list CHANGING, not on gaining cells: a glued table has cells before and
    after, so "now has cells" would score every glued repair as a no-op.
    """
    tally = {"empty": 0, "glued": 0}
    for block in iter_blocks(after, "table"):
        asset_id = (block.get("assetRef") or {}).get("assetId", "")
        kind = kinds.get(asset_id)
        if kind is not None and _cells_of(block.get("rows") or []) != cells_before.get(asset_id):
            tally[kind] += 1
    return tally


def _audit_one(cache: Path, target: dict, extractor: DoclingTableExtractor) -> dict:
    key = f"{target['paper_id']}v{target['version']}"
    pdf = (cache / "pdf" / f"{key}.pdf").read_bytes()
    crops: list = []
    # Parser-only: this measures what the re-read stage adds, so it must not start from a doc the
    # builder has already repaired.
    built = build_doc(
        target["paper_id"], target["version"], tei_for(key, cache, None), pdf, None, crops
    )
    if built is None:
        return {"paper_id": target["paper_id"], "skipped": "no doc-model"}
    # The repair stage works on the JSON doc, not the model — same conversion the sibling audit
    # makes, so both measure the same object the pipeline hands around.
    doc = built.model_dump(mode="json")

    specs = tables_needing_repair(doc, crops)
    cells_before = _cells_by_asset(doc)
    kinds = _classify(cells_before, specs)
    row: dict = {
        "paper_id": target["paper_id"],
        "version": target["version"],
        "candidates": {
            "empty": sum(1 for s in specs if kinds.get(s.asset_id) == "empty"),
            "glued": sum(1 for s in specs if kinds.get(s.asset_id) == "glued"),
        },
    }
    if not specs:
        row["suspect_pages"] = []
        return row

    # Page order is the order the extractor itself uses, so "the first N pages" here means the
    # same set the cap would keep.
    suspect = sorted({spec.page for spec in specs if spec.page and spec.page > 0})
    row["suspect_pages"] = suspect
    row["pages_by_path"] = {
        "empty": sorted({s.page for s in specs if kinds.get(s.asset_id) == "empty"}),
        "glued": sorted({s.page for s in specs if kinds.get(s.asset_id) == "glued"}),
    }

    # The one expensive pass, timed per page so a cap can be priced in seconds as well as repairs.
    read: list = []
    page_seconds: dict[str, float] = {}
    for page in suspect[:_SWEEP_MAX_PAGES]:
        started = time.monotonic()
        read.extend(extractor.extract_tables(pdf, [page]))
        page_seconds[str(page)] = round(time.monotonic() - started, 2)
    row["page_seconds"] = page_seconds

    printed = printed_text(pdf)
    row["by_cap"] = {}
    for cap in CAPS:
        allowed = set(suspect[:cap])
        after = copy.deepcopy(doc)
        apply_repairs(after, crops, [t for t in read if t.page in allowed], printed)
        row["by_cap"][str(cap)] = {
            "repairs": _repairs_by_path(cells_before, after, kinds),
            "seconds": round(sum(page_seconds.get(str(p), 0.0) for p in suspect[:cap]), 2),
        }
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    extractor = DoclingTableExtractor(max_pages=_SWEEP_MAX_PAGES)
    targets = json.loads((args.cache / "targets.json").read_text())
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            try:
                row = _audit_one(args.cache, target, extractor)
            except Exception as exc:  # noqa: BLE001 - a bad paper is data, not the end of the run
                row = {"paper_id": target["paper_id"], "error": f"{type(exc).__name__}: {exc}"}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            # Every paper prints: a pipeline sweep takes minutes per paper and a buffered run is
            # indistinguishable from a hung one.
            print(
                f"[{i}/{len(targets)}] {row.get('paper_id')} {row.get('candidates', row)}",
                flush=True,
            )


if __name__ == "__main__":
    main()
