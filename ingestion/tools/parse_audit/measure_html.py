#!/usr/bin/env python
"""Parse the cached ar5iv HTML with WHATEVER parser is importable, and dump per-paper metrics.

The A/B sweep runs this twice against the same cache — once from this branch, once from a checkout
of the merge base — and ``diff.py`` compares the two dumps. Whatever a paper parses into here is
what a reader would get; a regression is a paper that parses into LESS than the base produced.

Parser only: no network, no assets, no embedding.

Usage::

    # from this branch's checkout
    uv run python tools/parse_audit/measure_html.py --cache /tmp/parse-audit --out after.jsonl
    # from a develop worktree, same cache
    uv run python tools/parse_audit/measure_html.py --cache /tmp/parse-audit --out before.jsonl
    uv run python tools/parse_audit/diff.py before.jsonl after.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _common import counts
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.full_text_extraction import html_to_text

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _measure(paper_id: str, version: int, html: str) -> dict:
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
    result = {"paper_id": paper_id, "version": version, **counts(doc)}
    source = html_to_text(html)
    result["source_chars"] = len(source)
    result["coverage"] = round(result["body_chars"] / len(source), 4) if source else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="cache dir from corpus_sample.py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    targets = json.loads((args.cache / "targets.json").read_text())
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            path = args.cache / "html" / f"{key}.html"
            try:
                row = _measure(
                    target["paper_id"], target["version"], path.read_text(errors="replace")
                )
            except Exception as exc:  # noqa: BLE001 - a crash is the loudest datum here
                row = {**target, "error": f"{type(exc).__name__}: {exc}"}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 25 == 0 or "error" in row:
                print(f"[{i}/{len(targets)}] {key} {row.get('error', '')}", flush=True)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
