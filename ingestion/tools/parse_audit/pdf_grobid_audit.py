#!/usr/bin/env python
"""PDF/GROBID path audit: TEI -> DocModel, measured against the SAME paper's ar5iv doc-model.

The PDF/GROBID path is the only one non-arXiv sources (Semantic Scholar, OpenAlex) and user uploads
ever take, and there is no deployment left to eyeball it. The ar5iv parse of the same paper is the
yardstick — it was verified float-by-float against its source — so anything the PDF path is short of
is what those sources would lose. Cross-source, so read it with ``same_paper``'s caveat in mind:
ar5iv serves whatever version it has built regardless of the ``v5`` in the URL, and a mismatched
pair is dropped rather than compared. ``pdf_preservation_audit.py`` is the absolute counterpart and
the one to reach for first.

``--pipeline`` judges what a READER receives instead of what the parser alone produces: table
re-extraction (Docling) and formula OCR (pix2tex) run after the parse inside
``DocModelBuilder.build_from_tei``, and both exist only on this path, so a parser-only reading
reports their absence as parser defects. It costs minutes per paper, which is why it is a flag.

Needs a local GROBID (``docker run -d --rm -p 8070:8070 lfoppiano/grobid:0.8.0``) unless the TEI
cache is already populated. TEI is cached to disk so the GROBID step runs once.

Usage::

    uv run python tools/parse_audit/pdf_grobid_audit.py \
        --cache /tmp/parse-audit --grobid-url http://localhost:8070 --out pdf_audit.jsonl
    uv run --all-extras python tools/parse_audit/pdf_grobid_audit.py \
        --cache /tmp/parse-audit --out pipeline.jsonl --pipeline
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from _common import counts, same_paper
from _pipeline import TS, build_doc, pipeline_builder, tei_for
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--grobid-url", default=None,
                        help="only needed when the TEI cache is missing entries")
    parser.add_argument("--out", type=Path, required=True)
    # Big PDFs (20 MB+) take minutes; the 30s production default would time every one of them out.
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--targets", default="targets.json",
                        help="target list inside --cache; point at a subset to sample the sweep")
    parser.add_argument(
        "--pipeline",
        action="store_true",
        help="judge the WHOLE builder (table re-read + formula OCR), not the parser alone — "
             "slower by minutes per paper, but this is what a reader actually receives",
    )
    args = parser.parse_args()

    client = (
        GrobidHttpClient(base_url=args.grobid_url, timeout_seconds=args.timeout_seconds)
        if args.grobid_url
        else None
    )
    builder = pipeline_builder() if args.pipeline else None
    print(f"judging: {'whole pipeline' if builder else 'parser only'}", flush=True)

    targets = json.loads((args.cache / args.targets).read_text())
    started = time.monotonic()
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            paper_id, version = target["paper_id"], target["version"]
            key = f"{paper_id}v{version}"
            row: dict[str, Any] = {"paper_id": paper_id, "version": version}
            try:
                tei = tei_for(key, args.cache, client)
                crops: list = []
                pdf_path = args.cache / "pdf" / f"{key}.pdf"
                doc = build_doc(
                    paper_id, version, tei,
                    pdf_path.read_bytes() if builder else b"",
                    builder, crops,
                ).model_dump(mode="json")
                row["pdf"] = counts(doc)
                row["crops"] = len(crops)
                html_path = args.cache / "html" / f"{key}.html"
                html = html_path.read_text(errors="replace") if html_path.exists() else ""
                # Marked, not silent. A cache populated by `corpus_sample.py --pdf` alone has no
                # HTML at all, and an unmarked row is indistinguishable from one where the two
                # sources were compared — a sweep would then average ratios over zero pairs and
                # report a clean-looking result that measured nothing.
                if not html:
                    row["ar5iv_missing"] = True
                # ar5iv built a different version -> its parse is not a yardstick for this PDF.
                elif not same_paper(tei, html):
                    row["version_mismatch"] = True
                    html = ""
                if html:
                    row["ar5iv"] = counts(
                        parse_html_to_docmodel(
                            html,
                            paper_id=paper_id, version=version, title="", abstract=None,
                            source_tier=SourceTier.ar5iv, parser_version="audit",
                            schema_version="audit", generated_at=TS,
                        ).model_dump(mode="json")
                    )
            except Exception as exc:  # noqa: BLE001 - a crash is the loudest datum here
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            # Flushed per paper: under --pipeline formula OCR runs a model over every crop, so a
            # paper can take minutes and a buffered run looks indistinguishable from a hung one.
            fh.flush()
            print(
                f"[{i}/{len(targets)}] {key} {time.monotonic() - started:.0f}s "
                f"{'version mismatch, ar5iv side dropped' if row.get('version_mismatch') else ''}"
                f"{row.get('error', '')}",
                flush=True,
            )
            started = time.monotonic()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
