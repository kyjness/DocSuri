"""The loop both preservation sweeps run: per paper, audit -> row -> tally -> summary.

Split out because the two sweeps are read SIDE BY SIDE — PDF-path preservation against ar5iv-path
preservation — and had already drifted while looking identical. One flushed every row and the other
printed every fiftieth; one reported rates over every paper and the other over the papers it had
actually audited. Neither difference was intended, neither failed anything, and both make the two
percentages mean different things under the same heading.

Like ``_common.py`` this imports nothing from ``docsuri_ingestion``: the scripts bring their own
audit function, and only the bookkeeping around it lives here.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path


def run_sweep(
    targets_path: Path,
    out: Path,
    audit_one: Callable[[dict, str], dict],
    *,
    excluded_note: str = "",
) -> Counter[str]:
    """Audit every target, write one JSON row each, print the defect tally. Returns the tally.

    ``audit_one`` receives the target dict and its ``{paper_id}v{version}`` cache key and returns a
    row carrying ``violations``. Raising is a legitimate outcome — a crash IS a preservation
    failure — and becomes a ``parse_error`` row rather than ending the sweep.

    A row may set ``source_unavailable`` to say the source never existed to preserve, which is not
    a parser defect: those papers are counted, reported under ``excluded_note``, and left out of
    the denominator. A sweep whose sources are always present simply never sets the flag.

    Rows are written AND FLUSHED as they are produced, and every paper prints. A pipeline audit can
    take minutes per paper, and a buffered run is indistinguishable from a hung one — which cost a
    43-minute sweep here before anyone could tell it was alive.
    """
    targets = json.loads(targets_path.read_text())
    by_type: Counter[str] = Counter()
    papers = errors = unavailable = 0
    with out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            try:
                row = audit_one(target, key)
            except Exception as exc:  # noqa: BLE001 - a crash is itself a preservation failure
                row = {**target, "error": f"{type(exc).__name__}: {exc}",
                       "violations": ["parse_error"]}
                errors += 1
            papers += 1
            if row.get("source_unavailable"):
                unavailable += 1
            for kind in row["violations"]:
                by_type[kind] += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i}/{len(targets)}] {key} {row.get('error', '')}", flush=True)

    audited = papers - unavailable
    print(f"\nwrote {out}  ({papers} papers, {errors} parse errors)")
    if unavailable:
        print(f"{excluded_note or 'source unavailable'} (excluded): {unavailable}")
        print(f"audited: {audited}")
    print("\n=== defect types by frequency (papers affected, of audited) ===")
    for kind, n in by_type.most_common():
        pct = f"{n / audited:.1%}" if audited else "n/a"
        print(f"  {kind:28s} {n:5d}  ({pct})")
    if not by_type:
        print("  (none — every source signal accounted for)")
    return by_type
