#!/usr/bin/env python
"""Fetch a random sample of the stored corpus to a local cache, for a parse audit.

The stored doc-models were written by older parser generations; this pulls the ORIGINAL sources so
a current parser can be run against them offline. Bytes land on disk so an A/B run parses identical
input twice (once per checkout) and each source is fetched exactly once. ar5iv and arXiv are free,
public, and paced politely — nothing here bills.

Usage::

    uv run python tools/parse_audit/corpus_sample.py \
        --manifest ~/data/docsuri-data/docmodel-manifest.tsv \
        --count 150 --seed 20260721 --cache /tmp/parse-audit --html --pdf

The manifest is a TSV of ``<parser-version>\t<doc-model/PAPER/vN.json>`` rows — the corpus index.
``--html`` caches the ar5iv build (HTML-path audit); ``--pdf`` caches the arXiv PDF (GROBID-path
audit). ``targets.json`` records which papers were successfully cached, for the measure scripts.
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.request
from pathlib import Path

_AR5IV = "https://ar5iv.labs.arxiv.org/html/{key}"
_PDF = "https://arxiv.org/pdf/{key}"


def _sample(manifest: Path, count: int, seed: int) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for line in manifest.read_text().splitlines():
        _, key = line.split("\t", 1)
        _, paper_id, version = key.split("/")
        rows.append((paper_id, int(version.removeprefix("v").removesuffix(".json"))))
    random.Random(seed).shuffle(rows)
    return rows[:count]


def _get(url: str, user_agent: str) -> bytes | None:
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read() if response.status == 200 else None
    except Exception:  # noqa: BLE001 - a miss is data for the audit, not a failure
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="corpus manifest TSV")
    parser.add_argument("--cache", type=Path, required=True, help="output cache directory")
    parser.add_argument("--count", type=int, default=150)
    parser.add_argument("--seed", type=int, default=20260721)
    parser.add_argument("--html", action="store_true", help="cache the ar5iv HTML")
    parser.add_argument("--pdf", action="store_true", help="cache the arXiv PDF")
    parser.add_argument("--email", default="", help="contact for the polite User-Agent")
    parser.add_argument("--pace-seconds", type=float, default=2.0)
    args = parser.parse_args()
    if not (args.html or args.pdf):
        parser.error("pass --html and/or --pdf")

    base_ua = "docsuri-parse-audit/1.0"
    ua = f"{base_ua} (mailto:{args.email})" if args.email else base_ua
    (args.cache / "html").mkdir(parents=True, exist_ok=True)
    (args.cache / "pdf").mkdir(parents=True, exist_ok=True)
    got: list[dict] = []
    targets = _sample(args.manifest, args.count, args.seed)
    pace = args.pace_seconds
    for i, (paper_id, version) in enumerate(targets, start=1):
        key = f"{paper_id}v{version}"
        ok = True
        if args.html:
            ok &= _cache(args.cache / "html" / f"{key}.html", _AR5IV.format(key=key), ua, pace)
        if args.pdf:
            pdf_path = args.cache / "pdf" / f"{key}.pdf"
            ok &= _cache(pdf_path, _PDF.format(key=key), ua, pace, pdf=True)
        if ok:
            got.append({"paper_id": paper_id, "version": version})
        print(f"[{i}/{len(targets)}] {key} {'ok' if ok else 'MISS'}", flush=True)
    (args.cache / "targets.json").write_text(json.dumps(got, indent=1))
    print(f"cached {len(got)}/{len(targets)} -> {args.cache / 'targets.json'}")


def _cache(path: Path, url: str, user_agent: str, pace: float, *, pdf: bool = False) -> bool:
    if path.exists():
        return True
    data = _get(url, user_agent)
    time.sleep(pace)
    if not data or (pdf and not data.startswith(b"%PDF")):
        return False
    path.write_bytes(data)
    return True


if __name__ == "__main__":
    main()
