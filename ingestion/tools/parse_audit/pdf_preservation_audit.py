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

``--pipeline`` also renders the page crops and judges THOSE (see ``_assets.py``). Everything above
reads the doc-model, and a doc-model is not what the reader looks at: a figure block can carry a
caption, an ``assetRef`` and healthy coverage while its stored image is a fifth of the figure — the
defect that prompted these signals went unseen by every check here until someone opened the page.
The same contract still decides what counts: a crop refused because the region held only the caption
is a DESIGNED outcome (BR-23a) and stays a signal, while a crop the reader was meant to get and did
not is a violation.

Reads the PDF and TEI caches written by ``corpus_sample.py --pdf`` and ``pdf_grobid_audit.py``. No
embedding, no cloud. With the caches populated it needs no network at all; ``--grobid-url`` only
fills TEI the cache is missing, and ``--pipeline`` runs the local recovery stages.

Usage::

    uv run python tools/parse_audit/pdf_preservation_audit.py --cache /tmp/parse-audit \
        --out pdf_preserve.jsonl
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from _assets import asset_signals, merged_cell_tables
from _common import caption_probe, counts, figures_without_assetref, strip_ws, walk_sections
from _pipeline import build_doc, pipeline_builder, tei_for
from _sweep import run_sweep

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.asset_extraction import DESIGNED_REFUSALS
from docsuri_ingestion.full_text_extraction import pdf_to_text

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
# Letter-prefixed float numbering — "Figure A1", "Table S2", "Fig. B.3" — the standard style for
# appendix and supplementary floats. ``_FLOAT_RE`` cannot read these, and it must stay that way
# on the SOURCE side: the letter is invisible to ``_contiguous`` (A1 is not "the float after 12"),
# so admitting it there would re-open the column-seam artefacts that function exists to cut.
# ``_unreadable_labels`` alone reads this pattern — its question is "did GROBID mint this block
# out of junk", and a block named "Figure A1" plainly was not.
_LETTERED_FLOAT_RE = re.compile(
    r"\b(?:fig(?:ure)?|table)\s*\.?\s*(?-i:[A-Z])\.?\s*\d{1,2}\b", re.IGNORECASE
)
# The glyphs an itemize renders into the text layer.
_BULLET_RE = re.compile(r"[•▪‣◦]")
# Past this a float number is too commonly a year/section reference to trust ("Table 2020").
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
            out[_KIND_OF[word.lower()]].add(n)
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
            # A code block carries its listing heading in the text, not a caption.
            named = (
                _floats_in(str(block.get("text") or "")[:120])
                if kind == "code"
                else _floats_in(f"{block.get('anchorLabel') or ''} {block.get('caption') or ''}")
            )
            for k, numbers in named.items():
                out[k] |= numbers
    return out


def _unreadable_labels(doc: dict) -> int:
    """Figure/table blocks whose label and caption together name no float number.

    The masking term in the loss arithmetic. ``lost_figures`` is a COUNT subtraction, so a block
    GROBID minted out of a body paragraph raises the doc-model's tally and cancels a float that
    genuinely went missing — three named and three held reads as clean even when one of the three
    held is junk. Observed directly: blocks labelled ``'-P peaks at d = 2'``, ``'K'`` and ``'?'``.

    Counted rather than turned into a stricter loss test on purpose. Matching float numbers as a
    SET instead of a count is the obvious alternative and it was measured to be worse — GROBID
    files a float's name into labels it never finished splitting, and set-matching reported six
    missing tables for a paper that had three of them sitting right there (see ``_violations``).
    This names the population that causes the cancellation without re-opening that over-report.

    A letter-prefixed name ("Figure A1") counts as readable even though ``_FLOAT_RE`` cannot
    parse it: appendix numbering is a paper's standard style, not GROBID junk, and a violation
    that fires on every paper with an appendix is wrong at baseline — the failure mode this
    directory keeps ``figure_crops_partial`` out of the violations for.
    """
    unreadable = 0
    for section in walk_sections(doc):
        for block in section.get("blocks") or []:
            kind = block.get("type")
            if kind not in ("figure", "table"):
                continue
            name = f"{block.get('anchorLabel') or ''} {block.get('caption') or ''}"
            named = _floats_in(name)
            if not any(named.values()) and not _LETTERED_FLOAT_RE.search(name):
                unreadable += 1
    return unreadable


def _caption_text_dropped(doc: dict, full_text: str) -> int:
    """Captions the doc-model holds that never reached ``fullText`` — a projection loss.

    The probe rule is the ar5iv audit's, taken from ``_common`` rather than restated: the two
    numbers are compared against each other, so they have to be measured to the same threshold.
    What differs here is only where the captions are read from — the doc-model's own blocks,
    there being no source markup on this path to read them out of.
    """
    ft = strip_ws(full_text)
    dropped = 0
    for section in walk_sections(doc):
        for block in section.get("blocks") or []:
            if block.get("type") not in ("figure", "table"):
                continue
            probe = caption_probe(str(block.get("caption") or ""))
            if probe and probe not in ft:
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
    # Asset-stage types — present only on a --pipeline run, since only that renders the crops.
    # The same contract decides which of them count: a LOSS of content is a violation, a designed
    # outcome is not. Which reasons are designed is the CROP STAGE's fact, decided where each
    # reason is minted — ``DESIGNED_REFUSALS`` lives beside that code, and everything outside the
    # set counts as a loss here, so a reason added there without a classification fails loud
    # instead of reading as designed. (A local list did the opposite, and also mis-drew the line
    # once already: counting ``not_renderable`` — by DEFINITION under ``_MIN_CROP_AREA_PT2``,
    # measured 46pt² median over all 57, 50 of them caption-less formula fragments — put this
    # type at 60% of papers when the real figure is 0%.)
    if sum(
        n for why, n in (sig.get("crops_refused") or {}).items() if why not in DESIGNED_REFUSALS
    ):
        v.append("crop_missing")
    # Conservation: every spec must be stored or refused. A mid-loop failure in the crop stage
    # returns nothing for specs it never reached — no image, no refusal — and without this check
    # a paper that lost EVERY image reads as "a few designed placeholders".
    if "crop_specs" in sig and sig["crop_specs"] != sig.get("crops_stored", 0) + sum(
        (sig.get("crops_refused") or {}).values()
    ):
        v.append("crop_unaccounted")
    # A dead measurement must not read as a clean one: the geometry keys exist (as zeros) even
    # when the pass died, and this is what says they were never measured.
    if sig.get("crop_geometry_error"):
        v.append("crop_geometry_error")
    # ``figure_crops_partial`` is deliberately NOT here. It catches the regression it was built
    # for (0.197 on the broken crop, 0 once fixed), but on 30 corpus papers it fires 7 times and
    # every one examined was a sound crop — its cluster rule cannot tell two stacked floats apart.
    # A violation type that is wrong at baseline teaches everyone to ignore the histogram, so it
    # stays a signal to compare between runs. See ``_assets._graphic_cluster``.
    if sig.get("crop_duplicates"):
        v.append("crop_duplicate")
    if sig.get("table_cells_merged"):
        v.append("table_cells_merged")
    if sig.get("float_label_unreadable"):
        v.append("float_label_unreadable")
    return v


def _audit_one(
    paper_id: str, version: int, tei: str, pdf: bytes, builder: object | None = None
) -> dict:
    crops: list = []
    model = build_doc(paper_id, version, tei, pdf, builder, crops)
    if model is None:
        # BR-30 2026-08-10: real ingestion EXCLUDES this paper (TEI parsed to no structure), so
        # there is nothing to measure preservation against — the loss is the source's.
        return {"excluded": True, "violations": []}
    doc = model.model_dump(mode="json")
    source = pdf_to_text(pdf)
    src = {kind: _contiguous(nums) for kind, nums in _floats_in(source).items()}
    got = _doc_floats(doc)
    sig = dict(counts(doc))
    # A code block is where an algorithm listing lands; a figure block also stands in for a float
    # GROBID could not classify, so both count toward what the doc-model holds.
    kinds = sig["kinds"]
    sig.update(
        {
            "src_figures": len(src["figure"]),
            "src_tables": len(src["table"]),
            "src_algorithms": len(src["algorithm"]),
            "src_bullets": len(_BULLET_RE.findall(source)),
            "lost_figures": max(0, len(src["figure"]) - kinds.get("figure", 0)),
            "lost_tables": max(0, len(src["table"]) - kinds.get("table", 0)),
            "lost_algorithms": max(0, len(src["algorithm"]) - kinds.get("code", 0)),
            "unmatched_figures": sorted(src["figure"] - got["figure"]),
            "unmatched_tables": sorted(src["table"] - got["table"]),
            "unmatched_algorithms": sorted(src["algorithm"] - got["algorithm"]),
            **figures_without_assetref(doc),
            "source_chars": len(source),
            "caption_text_dropped": _caption_text_dropped(doc, model.fullText),
        }
    )
    sig["coverage"] = (
        round(sig["body_chars"] / sig["source_chars"], 4) if sig["source_chars"] else None
    )
    sig["float_label_unreadable"] = _unreadable_labels(doc)
    if builder is not None:
        # Asset signals only on the pipeline run: they render the crops, which is the artifact a
        # reader receives, and there is no point measuring it against a parser-only doc-model.
        sig.update(asset_signals(paper_id, version, pdf, crops))
        sig["table_cells_merged"] = merged_cell_tables(doc, crops)
    return {
        "paper_id": paper_id,
        "version": version,
        "violations": _violations(sig),
        "signals": sig,
    }


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
        help="judge the WHOLE builder (table re-read + formula OCR) AND render the page crops, "
             "not the parser alone — slower by minutes per paper, but this is what a reader "
             "actually receives, images included",
    )
    args = parser.parse_args()

    client = (
        GrobidHttpClient(base_url=args.grobid_url, timeout_seconds=args.timeout_seconds)
        if args.grobid_url
        else None
    )
    builder = pipeline_builder() if args.pipeline else None
    print(f"judging: {'whole pipeline' if builder else 'parser only'}", flush=True)

    run_sweep(
        args.cache / args.targets,
        args.out,
        lambda target, key: _audit_one(
            target["paper_id"],
            target["version"],
            tei_for(key, args.cache, client),
            (args.cache / "pdf" / f"{key}.pdf").read_bytes(),
            builder,
        ),
    )


if __name__ == "__main__":
    main()
