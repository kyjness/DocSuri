#!/usr/bin/env python
"""PDF/GROBID path audit: TEI -> DocModel, measured against the SAME paper's ar5iv doc-model.

The PDF/GROBID path is the only one non-arXiv sources (Semantic Scholar, OpenAlex) and user uploads
ever take, and there is no deployment left to eyeball it. The ar5iv parse of the same paper is the
yardstick — it was verified float-by-float against its source — so anything the PDF path is short of
is what those sources would lose.

Needs a local GROBID (``docker run -d --rm -p 8070:8070 lfoppiano/grobid:0.8.0``). TEI is cached to
disk so the GROBID step runs once. Parser + GROBID only; no embedding, no cloud.

Usage::

    uv run python tools/parse_audit/pdf_grobid_audit.py \
        --cache /tmp/parse-audit --grobid-url http://localhost:8070 --out pdf_audit.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from _common import counts
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _tei_for(key: str, cache: Path, client: GrobidHttpClient) -> str:
    tei_dir = cache / "tei"
    tei_dir.mkdir(exist_ok=True)
    path = tei_dir / f"{key}.tei.xml"
    if not path.exists():
        tei = client.extract_tei((cache / "pdf" / f"{key}.pdf").read_bytes())
        path.write_text(tei, encoding="utf-8")
    return path.read_text(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--grobid-url", default="http://localhost:8070")
    parser.add_argument("--out", type=Path, required=True)
    # Big PDFs (20 MB+) take minutes; the 30s production default would time every one of them out.
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    args = parser.parse_args()

    client = GrobidHttpClient(base_url=args.grobid_url, timeout_seconds=args.timeout_seconds)
    targets = json.loads((args.cache / "targets.json").read_text())
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            row: dict = {"paper_id": target["paper_id"], "version": target["version"]}
            try:
                crops: list = []
                pdf_doc = parse_tei_to_docmodel(
                    _tei_for(key, args.cache, client),
                    paper_id=target["paper_id"], version=target["version"], title="",
                    abstract=None, source_tier=SourceTier.pdf, parser_version="audit",
                    schema_version="audit", generated_at=_TS, crops=crops,
                ).model_dump(mode="json")
                row["pdf"] = counts(pdf_doc)
                row["crops"] = len(crops)
                html = (args.cache / "html" / f"{key}.html").read_text(errors="replace")
                ar5iv_doc = parse_html_to_docmodel(
                    html, paper_id=target["paper_id"], version=target["version"], title="",
                    abstract=None, source_tier=SourceTier.ar5iv, parser_version="audit",
                    schema_version="audit", generated_at=_TS,
                ).model_dump(mode="json")
                row["ar5iv"] = counts(ar5iv_doc)
            except Exception as exc:  # noqa: BLE001 - a crash is the loudest datum here
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"[{i}/{len(targets)}] {key} {row.get('error', '')}", flush=True)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
