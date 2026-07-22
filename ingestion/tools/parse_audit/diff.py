#!/usr/bin/env python
"""Diff two per-paper metric dumps of the same sample — the A/B verdict.

A regression is a paper the second dump parses into LESS than the first: fewer blocks, less covered
body text, a new empty section, a crash. Gains are reported too, but the reason this exists is the
losses — a hole-selected sample can show a defect fixed but never that an unbroken paper stayed
unbroken, so this runs over the RANDOM sample and reports both directions.

Usage::

    uv run python tools/parse_audit/diff.py before.jsonl after.jsonl
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

_WORSE_WHEN_LESS = ("blocks", "coverage", "body_chars", "captions")


def _load(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {f"{r['paper_id']}v{r['version']}": r for r in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()

    before, after = _load(args.before), _load(args.after)
    keys = sorted(set(before) & set(after))
    print(f"papers compared: {len(keys)}")

    new_crashes = [k for k in keys if "error" in after[k] and "error" not in before[k]]
    print(f"new crashes on the after side: {len(new_crashes)}")
    for key in new_crashes:
        print(f"  CRASH {key}: {after[key]['error']}")

    ok = [k for k in keys if "error" not in before[k] and "error" not in after[k]]
    losses: list[tuple[str, str, float, float]] = []
    gains: list[tuple[str, str, float, float]] = []
    for field in _WORSE_WHEN_LESS:
        for key in ok:
            b, a = before[key].get(field), after[key].get(field)
            if b is None or a is None or a == b:
                continue
            (losses if a < b else gains).append((field, key, b, a))
    # empty_sections is the one field where MORE is worse.
    for key in ok:
        b, a = before[key].get("empty_sections"), after[key].get("empty_sections")
        if b is not None and a is not None and a != b:
            (losses if a > b else gains).append(("empty_sections", key, b, a))

    for label, rows in (("LOSSES", losses), ("GAINS", gains)):
        print(f"\n== {label} ==")
        by_field: dict[str, list] = {}
        for field, key, b, a in rows:
            by_field.setdefault(field, []).append((key, b, a))
        for field, items in sorted(by_field.items()):
            print(f"  {field}: {len(items)} papers")
            for key, b, a in sorted(items, key=lambda x: x[2] - x[1])[:8]:
                print(f"    {key}: {b} -> {a}")

    for field in ("coverage", "blocks", "body_chars"):
        bs = [before[k][field] for k in ok if before[k].get(field) is not None]
        as_ = [after[k][field] for k in ok if after[k].get(field) is not None]
        if bs and as_:
            print(f"\n{field}: total {sum(bs):,} -> {sum(as_):,}   median "
                  f"{st.median(bs):.4g} -> {st.median(as_):.4g}")


if __name__ == "__main__":
    main()
