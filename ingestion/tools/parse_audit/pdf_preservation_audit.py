#!/usr/bin/env python
"""Preservation audit for the PDF/GROBID path — does the PDF's content reach the doc-model?

The companion to ``preservation_audit.py``, which asks the same question of the ar5iv path. That
one can read the source's own structure (LaTeXML's ``ltx_*`` classes) and check a block landed for
each signal. A PDF carries no such markup, so this reads the signals a PDF still spells out in its
text layer: the NUMBER of every float it names ("Figure 3", "TABLE II", "Algorithm 1") and the
bullet glyphs its lists render.

Why not measure against the same paper's ar5iv parse, as ``pdf_grobid_audit.py`` does: ar5iv serves
whatever version it happens to have built, ignoring the ``v5`` suffix in the URL — 4 of 12 papers in
the audit sample turned out to be a DIFFERENT paper on the ar5iv side. An absolute detector reading
the same file the parser read cannot drift that way.

Float numbers, not occurrences: "Figure 1" appears in its caption and again in every sentence that
cites it, so counting occurrences measures prose. The SET of numbers a paper names is the set of
floats it has, and a citation never introduces a new one.

The verdicts follow the ar5iv audit's contract — content reaching ``fullText``, not block typing.
A listing the parser keeps as a paragraph still delivers its words, so it is reported as a structure
signal for drill-down, never as a violation.

Parser only: no network, no GROBID, no embedding. Reads the PDF and TEI caches written by
``corpus_sample.py --pdf`` and ``pdf_grobid_audit.py``.

Usage::

    uv run python tools/parse_audit/pdf_preservation_audit.py --cache /tmp/parse-audit \
        --out pdf_preserve.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from _common import counts, walk_sections
from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.docmodel.tei import parse_tei_to_docmodel
from docsuri_ingestion.full_text_extraction import pdf_to_text

_TS = datetime(2026, 1, 1, tzinfo=UTC)

# Body text this far short of the PDF's own text layer is gross loss. Set well below 1.0 on
# purpose: the denominator includes the title block, authors, affiliations and the whole reference
# list, none of which the doc-model carries by design, and those alone are a fifth of a paper.
# Calibrated in Step 2 against the audit sample rather than inherited from the ar5iv threshold,
# whose denominator is a different extractor.
_COVERAGE_MIN = 0.35

# A float as a paper names it. ``Fig``/``Figure``/``Table``/``Algorithm``/``Listing`` followed by an
# arabic or roman number — IEEE styles number tables in roman ("TABLE III"), everyone else arabic.
_FLOAT_RE = re.compile(
    r"\b(fig(?:ure)?|table|algorithm|listing)\s*\.?\s*"
    r"(\d{1,2}|[IVXL]{1,5})\b",
    re.IGNORECASE,
)
_KIND_OF = {"fig": "figure", "figure": "figure", "table": "table",
            "algorithm": "algorithm", "listing": "algorithm"}
_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50}
# The glyphs an itemize renders into the text layer.
_BULLET_RE = re.compile(r"[•▪‣◦]")
_WS_RE = re.compile(r"\s+")
# Below this a float number is too commonly a year/section reference to trust ("Table 2020").
_MAX_FLOAT_NUMBER = 40


def _roman_to_int(text: str) -> int | None:
    total = prev = 0
    for ch in reversed(text.lower()):
        value = _ROMAN.get(ch)
        if value is None:
            return None
        total += -value if value < prev else value
        prev = max(prev, value)
    return total or None


def _number(raw: str) -> int | None:
    """The float's number as an int, or None when it is not one we can trust."""
    n = int(raw) if raw.isdigit() else _roman_to_int(raw)
    return n if n is not None and 1 <= n <= _MAX_FLOAT_NUMBER else None


def _floats_in(text: str) -> dict[str, set[int]]:
    """Every float the text names, as {kind: {numbers}}. Pure."""
    out: dict[str, set[int]] = {"figure": set(), "table": set(), "algorithm": set()}
    for word, raw in _FLOAT_RE.findall(text or ""):
        n = _number(raw)
        if n is not None:
            out[_KIND_OF[word.lower().rstrip(".")]].add(n)
    return out


def _contiguous(numbers: set[int]) -> set[int]:
    """``{1..N}`` for the largest N the set covers without a gap — the floats a paper really has.

    Reading a two-column PDF concatenates the foot of one column onto the head of the next, which
    manufactures numbers: a paper with two tables reported "Table 11" because "Table 1" ended a
    column and "1" began the next. Papers number their floats from 1 without gaps, so anything
    past the first gap is an artefact of that seam (or a citation of ANOTHER paper's table), and
    counting it invents a loss that never happened.
    """
    kept: set[int] = set()
    n = 1
    while n in numbers:
        kept.add(n)
        n += 1
    return kept


def _doc_floats(doc: dict) -> dict[str, set[int]]:
    """The floats the doc-model actually carries, read from each block's own label and caption.

    A block's label is where GROBID files the float's name, but it splits inconsistently
    ("Fig. 2 .", "TABLE I SETUP", "Table 1"), so the caption is read too — between the two the
    number survives.
    """
    out: dict[str, set[int]] = {"figure": set(), "table": set(), "algorithm": set()}
    for section in walk_sections(doc):
        for block in section.get("blocks") or []:
            kind = block.get("type")
            if kind not in ("figure", "table", "code"):
                continue
            named = _floats_in(f"{block.get('anchorLabel') or ''} {block.get('caption') or ''}")
            # A code block carries its listing heading in the text, not a caption.
            if kind == "code":
                named = _floats_in(str(block.get("text") or "")[:120])
            for k, numbers in named.items():
                out[k] |= numbers
    return out


def _strip_ws(text: str) -> str:
    return _WS_RE.sub("", text).lower()


def _caption_text_dropped(doc: dict, full_text: str) -> int:
    """Captions the doc-model holds that never reached ``fullText`` — a projection loss.

    Mirrors the ar5iv audit's check: content-based, whitespace-stripped so the comparison does not
    trip on the rendering difference between a block field and the projected text.
    """
    ft = _strip_ws(full_text)
    dropped = 0
    for section in walk_sections(doc):
        for block in section.get("blocks") or []:
            if block.get("type") not in ("figure", "table"):
                continue
            probe = _strip_ws(str(block.get("caption") or ""))[:60]
            if len(probe) < 20:
                continue  # too little caption text to judge reliably
            if probe not in ft:
                dropped += 1
    return dropped


def _violations(sig: dict) -> list[str]:
    """Defect types this paper exhibits. Each string is a TYPE; the caller tallies papers.

    Only losses of CONTENT count, exactly as on the ar5iv side. A float the PDF names that the
    doc-model has no block for at all is the whole float gone — caption, rows, crop and all — which
    is why that one IS a violation while "the list came out as a paragraph" is not.

    Loss is judged on COUNTS, not on which numbers matched. GROBID often files a float's name into
    a label it never finished splitting ("TABLE III WORD", "P- 5 :P- 6 :") or drops it entirely, so
    a block can be present and still carry no readable number. Marking those blocks' floats as lost
    reported six missing tables for a paper that had three of them sitting right there. The
    unmatched numbers are still recorded, as context for finding WHICH float went.
    """
    v: list[str] = []
    if sig["lost_figures"]:
        v.append("figure_lost")
    if sig["lost_tables"]:
        v.append("table_lost")
    if sig["caption_text_dropped"]:
        v.append("caption_text_dropped")
    if sig["empty_tables"]:
        v.append("empty_table")
    if sig["doc_figures_no_assetref"]:
        v.append("figure_missing_assetref")
    if sig["coverage"] is not None and sig["coverage"] < _COVERAGE_MIN:
        v.append("coverage_low")
    return v


def _build(paper_id: str, version: int, tei: str, pdf: bytes, builder: object | None):
    """The doc-model to judge — the parser's, or the whole pipeline's when a builder is given.

    They differ, and the difference has fooled this sweep twice: table re-extraction and formula
    OCR run AFTER ``parse_tei_to_docmodel`` inside ``DocModelBuilder.build_from_tei``, so a
    parser-only reading reports their absence as parser defects (it counted six empty tables where
    the pipeline delivers four). Parser-only stays the default because the recovery stages run
    vision models and cost minutes per paper; ``--pipeline`` is what a verdict about what READERS
    receive has to use.
    """
    if builder is None:
        return parse_tei_to_docmodel(
            tei,
            paper_id=paper_id,
            version=version,
            title="",
            abstract=None,
            source_tier=SourceTier.pdf,
            parser_version="audit",
            schema_version="audit",
            generated_at=_TS,
            crops=[],
        )
    return builder.build_from_tei(  # type: ignore[attr-defined]
        paper_id, version, "", "", tei, "",
        source_tier=SourceTier.pdf, crops=[], pdf=pdf,
    ).docModel


def _audit_one(
    paper_id: str, version: int, tei: str, pdf: bytes, builder: object | None = None
) -> dict:
    model = _build(paper_id, version, tei, pdf, builder)
    doc = model.model_dump(mode="json")
    source = pdf_to_text(pdf)
    src = {kind: _contiguous(nums) for kind, nums in _floats_in(source).items()}
    got = _doc_floats(doc)
    blocks = [b for s in walk_sections(doc) for b in (s.get("blocks") or [])]
    kinds = counts(doc)["kinds"]
    # A code block is where an algorithm listing lands; a figure block also stands in for a float
    # GROBID could not classify, so both count toward what the doc-model holds.
    held = {
        "figure": kinds.get("figure", 0),
        "table": kinds.get("table", 0),
        "algorithm": kinds.get("code", 0),
    }
    sig = dict(counts(doc))
    sig.update(
        {
            "src_figures": len(src["figure"]),
            "src_tables": len(src["table"]),
            "src_algorithms": len(src["algorithm"]),
            "src_bullets": len(_BULLET_RE.findall(source)),
            "lost_figures": max(0, len(src["figure"]) - held["figure"]),
            "lost_tables": max(0, len(src["table"]) - held["table"]),
            "lost_algorithms": max(0, len(src["algorithm"]) - held["algorithm"]),
            "unmatched_figures": sorted(src["figure"] - got["figure"]),
            "unmatched_tables": sorted(src["table"] - got["table"]),
            "unmatched_algorithms": sorted(src["algorithm"] - got["algorithm"]),
            "doc_figures_no_assetref": sum(
                1 for b in blocks if b.get("type") == "figure" and not b.get("assetRef")
            ),
            "source_chars": len(source),
            "caption_text_dropped": _caption_text_dropped(doc, model.fullText),
        }
    )
    sig["coverage"] = (
        round(sig["body_chars"] / sig["source_chars"], 4) if sig["source_chars"] else None
    )
    return {
        "paper_id": paper_id,
        "version": version,
        "violations": _violations(sig),
        "signals": sig,
    }


def _tei_for(key: str, cache: Path, client: GrobidHttpClient | None) -> str:
    """Cached TEI, extracting it once when the cache has none and a GROBID is reachable."""
    path = cache / "tei" / f"{key}.tei.xml"
    if path.exists():
        return path.read_text(encoding="utf-8")
    if client is None:
        raise FileNotFoundError(f"no cached TEI for {key} and no --grobid-url given")
    path.parent.mkdir(parents=True, exist_ok=True)
    tei = client.extract_tei((cache / "pdf" / f"{key}.pdf").read_bytes())
    path.write_text(tei, encoding="utf-8")
    return tei


def _pipeline_builder():
    """A builder wired exactly as ingestion wires it, writing nothing.

    The readers come from ``runtime``'s own resolvers so a missing optional extra degrades here the
    way it would in ingestion, and the store always misses so a cache hit cannot skip the very
    stages this mode exists to measure.
    """
    from docsuri_ingestion.docmodel.builder import DocModelBuilder
    from docsuri_ingestion.runtime import _formula_reader, _table_extractor
    from docsuri_ingestion.settings import IngestionSettings

    class _NoStore:
        def get(self, paper_id: str, version: int):  # noqa: ARG002
            return None

        def put(self, doc) -> None:
            """Drop it — an audit measures, it does not populate the corpus."""

        def remove(self, paper_id: str) -> None:
            """Never called; present so the object satisfies the store port."""

    class _FixedClock:
        def now(self):
            return _TS

    settings = IngestionSettings()
    return DocModelBuilder(
        source=None,  # type: ignore[arg-type]  # build_from_tei never reaches the HTML ladder
        store=_NoStore(),
        table_extractor=_table_extractor(settings),
        formula_reader=_formula_reader(settings),
        clock=_FixedClock(),
        parser_version="audit",
        schema_version="audit",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True, help="cache dir from corpus_sample.py")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--targets", default="targets.json")
    parser.add_argument(
        "--grobid-url",
        default=None,
        help="extract any TEI the cache is missing (the sweep is otherwise read-only)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
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
    builder = _pipeline_builder() if args.pipeline else None
    print(f"judging: {'whole pipeline' if builder else 'parser only'}", flush=True)

    targets = json.loads((args.cache / args.targets).read_text())
    by_type: Counter[str] = Counter()
    papers = errors = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for i, target in enumerate(targets, start=1):
            key = f"{target['paper_id']}v{target['version']}"
            try:
                row = _audit_one(
                    target["paper_id"],
                    target["version"],
                    _tei_for(key, args.cache, client),
                    (args.cache / "pdf" / f"{key}.pdf").read_bytes(),
                    builder,
                )
            except Exception as exc:  # noqa: BLE001 - a crash is itself a preservation failure
                row = {**target, "error": f"{type(exc).__name__}: {exc}",
                       "violations": ["parse_error"]}
                errors += 1
            papers += 1
            for kind in row["violations"]:
                by_type[kind] += 1
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i}/{len(targets)}] {key} {row.get('error', '')}", flush=True)

    print(f"\nwrote {args.out}  ({papers} papers, {errors} parse errors)")
    print("\n=== defect types by frequency (papers affected) ===")
    for kind, n in by_type.most_common():
        print(f"  {kind:28s} {n:5d}  ({n / papers:.1%})" if papers else f"  {kind}")
    if not by_type:
        print("  (none — every source signal accounted for)")


if __name__ == "__main__":
    main()
