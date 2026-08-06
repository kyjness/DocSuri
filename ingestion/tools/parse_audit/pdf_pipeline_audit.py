#!/usr/bin/env python
"""PDF path audit through the WHOLE builder — TEI parse plus the two recovery stages.

``pdf_grobid_audit.py`` measures ``parse_tei_to_docmodel`` alone, which is what the parser is
responsible for. That is not what a reader receives: ``DocModelBuilder.build_from_tei`` runs table
re-extraction (Docling) and formula OCR (pix2tex) after the parse, and both only exist on this
path. Measuring the parser alone reports their absence as parser defects — a display equation
looks like an empty formula block because its LaTeX arrives one stage later.

So this script builds the same way ingestion does, and the gap between the two dumps is exactly
what the recovery stages contribute. The ar5iv parse of the same paper stays the yardstick.

The readers are resolved through ``runtime._table_extractor`` / ``runtime._formula_reader`` rather
than constructed here, so an environment missing an optional extra degrades in the audit exactly
as it would in ingestion (``auto`` = on wherever installed) instead of silently measuring a
different pipeline.

Needs the cache written by ``corpus_sample.py --html --pdf`` and the TEI cache written by
``pdf_grobid_audit.py``; with both present GROBID does not have to run again. Reads only — the
store is an always-miss fake, so nothing is written to S3 or disk.

Usage::

    uv run --all-extras python tools/parse_audit/pdf_pipeline_audit.py \
        --cache /tmp/parse-audit --out pipeline.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from _common import counts
from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel
from docsuri_ingestion.runtime import _formula_reader, _table_extractor
from docsuri_ingestion.settings import IngestionSettings

_TS = datetime(2026, 1, 1, tzinfo=UTC)


class _NoStore:
    """Always-miss doc-model store. A hit would skip both recovery stages and the parse itself."""

    def get(self, paper_id: str, version: int) -> DocModel | None:  # noqa: ARG002
        return None

    def put(self, doc: DocModel) -> None:
        """Drop it — an audit measures, it does not populate the corpus."""

    def remove(self, paper_id: str) -> None:
        """Never called; present so the object satisfies the store port."""


class _FixedClock:
    def now(self) -> datetime:
        return _TS


def _tei_for(key: str, cache: Path, client: GrobidHttpClient | None) -> str:
    """Cached TEI, extracting it once if ``pdf_grobid_audit.py`` has not already."""
    path = cache / "tei" / f"{key}.tei.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    if client is None:
        raise FileNotFoundError(f"no cached TEI for {key} and no GROBID url given")
    path.parent.mkdir(exist_ok=True)
    tei = client.extract_tei((cache / "pdf" / f"{key}.pdf").read_bytes())
    path.write_text(tei, encoding="utf-8")
    return tei


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--grobid-url",
        default=None,
        help="only needed when the TEI cache is missing entries",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument(
        "--targets",
        default="targets.json",
        help="target list inside --cache; point at a subset to sample the sweep",
    )
    args = parser.parse_args()

    settings = IngestionSettings()
    table_extractor = _table_extractor(settings)
    formula_reader = _formula_reader(settings)
    print(
        f"table_extractor={'on' if table_extractor else 'OFF'} "
        f"formula_reader={'on' if formula_reader else 'OFF'}",
        flush=True,
    )
    builder = DocModelBuilder(
        source=None,  # type: ignore[arg-type]  # build_from_tei never reaches the HTML ladder
        store=_NoStore(),
        table_extractor=table_extractor,
        formula_reader=formula_reader,
        clock=_FixedClock(),
        parser_version="audit",
        schema_version="audit",
    )
    client = (
        GrobidHttpClient(base_url=args.grobid_url, timeout_seconds=args.timeout_seconds)
        if args.grobid_url
        else None
    )

    targets = json.loads((args.cache / args.targets).read_text())
    started = time.monotonic()
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            paper_id, version = target["paper_id"], target["version"]
            key = f"{paper_id}v{version}"
            row: dict[str, Any] = {"paper_id": paper_id, "version": version}
            try:
                pdf = (args.cache / "pdf" / f"{key}.pdf").read_bytes()
                # crops is the parser's out-param; both recovery stages page-crop through it, so
                # passing it is what makes them run at all.
                crops: list = []
                result = builder.build_from_tei(
                    paper_id, version, "", "",
                    _tei_for(key, args.cache, client),
                    "",
                    source_tier=SourceTier.pdf,
                    crops=crops,
                    pdf=pdf,
                )
                doc = result.docModel.model_dump(mode="json")
                row["pipeline"] = counts(doc)
                row["crops"] = len(crops)
                html_path = args.cache / "html" / f"{key}.html"
                if html_path.exists():
                    ar5iv = parse_html_to_docmodel(
                        html_path.read_text(errors="replace"),
                        paper_id=paper_id, version=version, title="", abstract=None,
                        source_tier=SourceTier.ar5iv, parser_version="audit",
                        schema_version="audit", generated_at=_TS,
                    ).model_dump(mode="json")
                    row["ar5iv"] = counts(ar5iv)
            except Exception as exc:  # noqa: BLE001 - a crash is the loudest datum here
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            # Flushed per paper: formula OCR runs a model over every crop, so a paper can take
            # minutes and a buffered run looks indistinguishable from a hung one.
            fh.flush()
            print(
                f"[{i}/{len(targets)}] {key} {time.monotonic() - started:.0f}s "
                f"{row.get('error', '')}",
                flush=True,
            )
            started = time.monotonic()
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
