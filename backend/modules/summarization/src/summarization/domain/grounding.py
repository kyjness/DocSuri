"""GroundingValidator — U7-owned deterministic grounding gate (BR-S7 / Q4 / Q15).

This is NOT the search-shaped U6 ``enforce`` (candidate ↔ retrieved record SET). U7
verifies a structured summary against ONE paper's refined source text — a different kind
of check (document fidelity), so "single grounding authority = U6" is read as *search
grounding only*. Deterministic checks ONLY; no LLM-judge (Q15):

  1. anchor existence  — each anchor's span/label must exist in the refined source
  2. numeric match     — result numbers must appear in the source (normalized: 95.3% ↔ 0.953,
                         thousand-sep 1,200 ↔ 1200, rounding tolerance 95.3 ↔ 95.34)
  3. schema complete   — required §3 fields present
  4. truncation/empty  — non-empty, not cut off

1차 실패 → orchestrator retries once → still failing → abstain (fail-closed, INV-4).
"""

from __future__ import annotations

import re
from dataclasses import replace

from .models import Anchor, AnchorVerdict, GroundingInput, RefinedSource, Violation

# Match plain decimals AND thousand-separated forms ("1,200", "1,234.5") as a single token, so
# "1,200" is not split into "1" + "200" (which would mis-ground). Longest-alternative-first.
_NUM_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# --- anchor location resolution (BR-S7) --------------------------------------
# An anchor points at a doc-model LOCATION (a section / table / figure), not at a verbatim prose
# quote. The summary is Korean, so the model localizes/paraphrases prose; a verbatim substring
# check against the English source rejects almost every real anchor. Instead the model names the
# source location — the prompt asks for the exact section title or "Figure N"/"Table N" in
# ``label`` (see prompts/templates.py), and some models also echo it in ``target`` (``target_hint``)
# — and we resolve THAT against the doc-model's ACTUAL section/table/figure labels. A resolved
# anchor is kept with its label rewritten to the canonical doc-model label (chip jumps to the real
# block). Deterministic, no LLM-judge (Q15). Anti-fabrication stays with the HARD numeric gate — an
# unresolved location is dropped (SOFT), never surfacing a fabricated figure.
#
# Matching is TOKEN-based (a run of consecutive tokens), not raw substring: "Figure 1" must not
# match "Figure 10" (token "1" ≠ "10"), and a short title "Method" must not match "Methodology".
_LABEL_PREFIX_RE = re.compile(r"^\s*(?:section\b|sec\.|§)\s*[:.\-]?\s*", re.IGNORECASE)
_FIGTBL_RE = re.compile(r"\b(figure|fig\.?|table)\s*(\d+)", re.IGNORECASE)


def _label_tokens(text: str) -> list[str]:
    """Casefolded token list: strip a leading 'Section:'/'Sec.'/'§' prefix (``\\b`` so 'Security' is
    not truncated), drop punctuation, split on whitespace. Tokens (not raw substrings) so 'figure 1'
    ≠ 'figure 10' and 'Section: Eliminating Free Riding' still matches the title 'Eliminating Free
    Riding' as a consecutive run."""
    t = _LABEL_PREFIX_RE.sub("", text.strip())
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)  # § : , . / → space
    return t.lower().split()


def _contiguous(needle: list[str], hay: list[str]) -> bool:
    """True when ``needle`` occurs as a run of consecutive tokens in ``hay`` (order preserved)."""
    n = len(needle)
    return 0 < n <= len(hay) and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def _structural_index(refined: RefinedSource) -> list[tuple[str, list[str]]]:
    """(canonical label, key tokens) for every citable doc-model location, most specific first
    (figures/tables before sections) so a compound target resolves to the precise block."""
    index: list[tuple[str, list[str]]] = []
    seen: set[tuple[str, ...]] = set()

    def add(canonical: str, raw_key: str) -> None:
        toks = _label_tokens(raw_key)
        sig = tuple(toks)
        if toks and sig not in seen:
            seen.add(sig)
            index.append((canonical, toks))

    # Figure / Table labels — from caption prefixes ("Figure 1: …") + structured tables.
    for cap in refined.captions:
        m = _FIGTBL_RE.match(cap.strip())
        if m:
            kind = "Table" if m.group(1).lower().startswith("tab") else "Figure"
            add(f"{kind} {m.group(2)}", f"{kind} {m.group(2)}")
    for tbl in refined.tables:
        if tbl.label:
            add(tbl.label, tbl.label)
    # Section titles.
    for sec in refined.sections:
        if sec.label:
            add(sec.label, sec.label)
    return index


def _resolve_location(anchor: Anchor, index: list[tuple[str, list[str]]]) -> str | None:
    """Canonical doc-model label the anchor points at, or None if it resolves to nothing real.
    Resolves against ``label`` (the prompt's location field) OR ``target_hint`` (raw ``target``);
    a location's key tokens must appear as a consecutive run in one of them."""
    hint = _label_tokens(anchor.target_hint)
    lbl = _label_tokens(anchor.label)
    if not hint and not lbl:
        return None
    # Exact token match first — prefer the precise block over a shorter sub-phrase (so
    # "Additional Experimental Results" resolves to itself, not to "Experimental Results").
    for canonical, key in index:
        if key == hint or key == lbl:
            return canonical
    # Contiguous fallback: pick the LONGEST (most specific) matching key, not the first (#352).
    # A short generic title (e.g. "Method") that happens to be a sub-run of the anchor's label
    # must not win over a longer, more specific title that also matches. Index order
    # (most-specific-first) breaks length ties — only a strictly longer key replaces the best.
    best_canonical: str | None = None
    best_len = 0
    for canonical, key in index:
        if len(key) > best_len and (_contiguous(key, hint) or _contiguous(key, lbl)):
            best_canonical, best_len = canonical, len(key)
    return best_canonical


# Numeric grounding is fraction-based: abstain only when MORE than this share of a draft's result
# figures are absent from the source. Tolerates a few mis-transcribed/rounded values while still
# blocking drafts whose numbers are mostly fabricated (anti-hallucination, INV-4).
#
# RECALIBRATED 0.5 → 0.4 (US-S6, 2026-07-10) from the QT-1 eval corpora (seed + numeric spectrum
# + real-figure held-out set, 32 labeled cases): the pre-Phase-3 synthetic estimate 0.5 let every
# exactly-half-ungrounded draft PASS (0.50 is not > 0.50 — 3 false-passes: probe_half_ungrounded_
# numbers, num_ungrounded_2of4, roberta_probe_2of4). The zero-error plateau (false_pass = 0 AND
# false_abstain = 0 across all 32 cases) is [0.40, 0.50); 0.4 is its STRICT edge — the largest
# faithful ungrounded share in the corpora is 2/5 (resnet_probe_2of5), which still passes via the
# strict `>`. Changes here must only go stricter (lower), never looser (C-2: no fabricated
# content); `tests/test_grounding_eval.py` / `tests/test_real_corpus.py` pin both edges.
_NUMERIC_MISMATCH_THRESHOLD = 0.4


def _to_float(token: str) -> float | None:
    """Parse a numeric token (thousand separators stripped) to float, or None."""
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def _decimals(token: str) -> int:
    """Decimal places a token is written to (drives the rounding tolerance band)."""
    _, _, frac = token.partition(".")
    return len(frac)


def _normalize_number(token: str) -> set[str]:
    """Return equivalent string forms of a number (thousand-sep stripped, 95.3% ↔ 0.953)."""
    forms = {token}
    value = _to_float(token)
    if value is None:
        return forms
    forms.add(f"{value:g}")
    if value > 1:  # percentage ↔ fraction
        forms.add(f"{value / 100:g}")
    else:
        forms.add(f"{value * 100:g}")
    return forms


def _number_grounded(token: str, src_values: list[float], src_forms: set[str]) -> bool:
    """A draft figure is grounded if it matches a source figure by exact normalized form OR
    within a **rounding-tolerance band** at the draft's own precision (95.3 grounds 95.34, since
    95.34 rounds to 95.3).

    Cross-scale equivalence (percentage↔fraction, 95.3% = 0.953) is matched ONLY via the exact
    normalized forms above — the rounding band is applied at the SAME scale, never to ×100/÷100
    rescalings. Rescaling inside the tolerant band would let a coarse (e.g. integer) draft figure
    false-ground an unrelated source value that happens to be ~100× it: draft "20" vs a year
    "2020" (2020/100 = 20.2, within the integer band 0.5) — fabricated figure passes the HARD
    anti-fabrication gate (INV-4). Rounded cross-scale (a percent draft vs a fraction written to
    more decimals) is therefore given up on purpose: it fails closed (false-abstain), the safe
    direction for a fabrication gate."""
    if _normalize_number(token) & src_forms:
        return True
    draft = _to_float(token)
    if draft is None:
        return False
    band = 0.5 * 10 ** (-_decimals(token)) + 1e-9
    return any(abs(s - draft) <= band for s in src_values)


class GroundingValidator:
    def __init__(self, *, numeric_mismatch_threshold: float = _NUMERIC_MISMATCH_THRESHOLD) -> None:
        # Injectable so the QT-1 harness can sweep the value for recalibration; production wiring
        # uses the default. abstain when the ungrounded share of result figures EXCEEDS this.
        self._numeric_threshold = numeric_mismatch_threshold

    def validate(self, gi: GroundingInput) -> AnchorVerdict:
        draft, refined = gi.draft, gi.refined
        # HARD violations abstain the whole summary (fail-closed, INV-4). The anchor-location
        # check is SOFT (option D): an anchor that doesn't resolve to a real doc-model section /
        # table / figure is DROPPED, not abstained on, so the grounded summary text + the
        # verifiable anchors are still shown. The numeric guard (rule 2) stays HARD, so dropping an
        # unresolved pointer can never surface a fabricated figure. fail-closed is thus per-anchor
        # here, not whole-summary.
        hard: list[Violation] = []
        soft: list[Violation] = []

        # (4) empty / truncation (Step 33) — HARD
        if not draft.tldr.strip() or not draft.method.strip():
            hard.append(Violation("empty", "tldr/method"))
        if getattr(draft, "truncated", False):
            hard.append(Violation("truncated", "draft"))

        # (3) schema completeness — HARD
        if "code" not in draft.reproducibility or "data" not in draft.reproducibility:
            hard.append(Violation("schema_incomplete", "reproducibility"))

        # (1) anchor location — SOFT: keep anchors that resolve to a REAL doc-model location
        # (section/table/figure), rewriting the label to the canonical one; drop the rest. The
        # model localizes/paraphrases its own ``label`` (Korean), so resolve its raw ``target``
        # against real structure instead of verbatim-matching prose (Step 35 / BR-S7).
        index = _structural_index(refined)
        kept: list[Anchor] = []
        if not index:
            # No doc-model structure to resolve against — pure-abstract fallback or a heading-less
            # legacy .txt whose refiner produced no sections/captions/tables. Keep the anchor chips
            # verbatim instead of dropping every one as anchor_missing (#352): the old verbatim
            # path surfaced abstract-cited anchors, and the numeric HARD gate is independent, so
            # unresolved pointers still cannot leak a fabricated figure.
            kept = list(draft.anchors)
        else:
            for a in draft.anchors:
                canonical = _resolve_location(a, index)
                if canonical is not None:
                    kept.append(replace(a, label=canonical))
                else:
                    soft.append(Violation("anchor_missing", a.field_name))

        # De-duplicate: multiple draft anchors in one field routinely resolve to the SAME
        # canonical location (several claims all cite "Introduction"), which would render as
        # identical repeated "출처" chips. Collapse to one per (field, label), first-seen order.
        seen_chips: set[tuple[str, str]] = set()
        deduped: list[Anchor] = []
        for a in kept:
            key = (a.field_name, a.label)
            if key not in seen_chips:
                seen_chips.add(key)
                deduped.append(a)
        kept = deduped

        # (2) numeric match — result figures must appear in the source — HARD, but FRACTION-based:
        # a few stray numbers (a mis-transcribed table cell, a rounded value) shouldn't abstain an
        # otherwise-grounded summary, while a draft whose figures are MOSTLY fabricated still must.
        # Abstain only when the ungrounded share exceeds the threshold (anti-fabrication intact).
        haystack = refined.body
        captions = "\n".join(refined.captions)
        result_nums = _NUM_RE.findall(draft.results)
        if result_nums:
            src_forms = _source_numbers(haystack, captions)
            src_values = _source_values(haystack, captions)
            ungrounded = sum(
                1 for t in result_nums if not _number_grounded(t, src_values, src_forms)
            )
            if ungrounded / len(result_nums) > self._numeric_threshold:
                hard.append(Violation("numeric_mismatch", "results"))

        if hard:
            return AnchorVerdict(
                ok=False, violations=tuple(hard + soft), outcome="abstain", kept_anchors=tuple(kept)
            )
        return AnchorVerdict(
            ok=True, violations=tuple(soft), outcome="pass", kept_anchors=tuple(kept)
        )


def _source_numbers(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for token in _NUM_RE.findall(t):
            out |= _normalize_number(token)
    return out


def _source_values(*texts: str) -> list[float]:
    """Numeric values of every figure in the source — the basis for rounding-tolerance match."""
    out: list[float] = []
    for t in texts:
        for token in _NUM_RE.findall(t):
            value = _to_float(token)
            if value is not None:
                out.append(value)
    return out
