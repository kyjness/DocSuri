#!/usr/bin/env python
"""Measure how many merged tables the Docling re-read actually repairs on real PDFs.

Runs the REAL production repair path — ``tables_needing_repair`` -> Docling extract -> verified
``apply_repairs`` — and counts merged/empty tables before and after. A repair is applied only when
every rebuilt number is printed on the page, so a "repaired" count here is verified data, not just a
second reading. Reads the TEI cache ``pdf_grobid_audit.py`` already wrote, and needs the ``tables``
extra installed (``uv pip install .[tables]``).

Usage::

    uv run --extra tables python tools/parse_audit/table_repair_audit.py \
        --cache /tmp/parse-audit --out repair_audit.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _common import walk_sections
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.docling_tables import DoclingTableExtractor
from docsuri_ingestion.docmodel.table_repair import (
    apply_repairs,
    printed_text,
    tables_needing_repair,
)
from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _table_stats(doc: dict) -> tuple[int, int]:
    """(empty tables, tables with rows) — the two states a repair can move a table between."""
    blocks = (b for s in walk_sections(doc) for b in (s.get("blocks") or []))
    tables = [b for b in blocks if b["type"] == "table"]
    empty = sum(1 for t in tables if not (t.get("rows") or []))
    return empty, len(tables) - empty


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    extractor = DoclingTableExtractor()
    targets = json.loads((args.cache / "targets.json").read_text())
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            row: dict = {"paper_id": target["paper_id"], "version": target["version"]}
            try:
                tei = (args.cache / "tei" / f"{key}.tei.xml").read_text()
                pdf = (args.cache / "pdf" / f"{key}.pdf").read_bytes()
                crops: list = []
                doc = parse_tei_to_docmodel(
                    tei, paper_id=target["paper_id"], version=target["version"], title="",
                    abstract=None, source_tier=SourceTier.pdf, parser_version="audit",
                    schema_version="audit", generated_at=_TS, crops=crops,
                ).model_dump(mode="json")
                empty0, filled0 = _table_stats(doc)
                candidates = tables_needing_repair(doc, crops)
                row.update(tables=empty0 + filled0, candidates=len(candidates), repaired=0)
                if candidates:
                    read = extractor.extract_tables(pdf, sorted({c.page for c in candidates}))
                    row["repaired"] = apply_repairs(doc, crops, read, printed_text(pdf))
                    row["empty_after"], row["filled_after"] = _table_stats(doc)
            except Exception as exc:  # noqa: BLE001 - a crash is the loudest datum here
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(targets)}] {key} cand={row.get('candidates')} "
                  f"repaired={row.get('repaired')} {row.get('error', '')}", flush=True)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
