"""GroundingValidator — U7-owned deterministic grounding gate (BR-S7 / Q4 / Q15).

This is NOT the search-shaped U6 ``enforce`` (candidate ↔ retrieved record SET). U7
verifies a structured summary against ONE paper's refined source text — a different kind
of check (document fidelity), so "single grounding authority = U6" is read as *search
grounding only*. Deterministic checks ONLY; no LLM-judge (Q15):

  1. anchor existence  — each anchor's span/label must exist in the refined source
  2. numeric match     — result numbers must appear in the source (normalized: 95.3% ↔ 0.953)
  3. schema complete   — required §3 fields present
  4. truncation/empty  — non-empty, not cut off

1차 실패 → orchestrator retries once → still failing → abstain (fail-closed, INV-4).
"""

from __future__ import annotations

import re

from .models import Anchor, AnchorVerdict, GroundingInput, SummaryDraft, Violation

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# A math/formula span (e.g. ``𝓛={1y,1w,…}`` or ``\mathcal{L}``) can't be verbatim-matched against
# the refined source, which stores math as LaTeX/MathML — a different string representation. Such
# spans are EXEMPTED from the anchor-existence check (option B) to avoid false-positive abstains on
# correctly-grounded math; numeric grounding (rule 2) still guards the reported result figures.
# (Alternatives weighed: normalize math on both sides, or steer the prompt off formula anchors —
# see PR discussion. Trade-off: a hallucinated formula anchor would now pass span-existence.)
# NOTE: arrows (U+2190–U+21FF) are deliberately EXCLUDED — ``→`` is common in prose
# ("pretrain → finetune"), so including it would exempt ordinary text spans from the existence
# check and widen the grounding hole. Real formula signal comes from operators / math-alphanumeric
# / LaTeX, which remain below.
_MATH_RE = re.compile(
    r"[∀-⋿⨀-⫿\U0001D400-\U0001D7FF]"  # math unicode (operators/symbols/alphanumerics)
    r"|\\[A-Za-z]+"  # LaTeX command (\mathcal, \sum, …)
    r"|[_^]\{"  # LaTeX sub/superscript group
)


def _is_formula_span(text: str) -> bool:
    return bool(_MATH_RE.search(text))


# Numeric grounding is fraction-based: abstain only when MORE than this share of a draft's result
# figures are absent from the source. Tolerates a few mis-transcribed/rounded values while still
# blocking drafts whose numbers are mostly fabricated (anti-hallucination, INV-4).
_NUMERIC_MISMATCH_THRESHOLD = 0.5


def _normalize_number(token: str) -> set[str]:
    """Return equivalent string forms of a number (95.3% ↔ 0.953 tolerance)."""
    forms = {token}
    try:
        value = float(token)
    except ValueError:
        return forms
    forms.add(f"{value:g}")
    if value > 1:  # percentage ↔ fraction
        forms.add(f"{value / 100:g}")
    else:
        forms.add(f"{value * 100:g}")
    return forms


class GroundingValidator:
    def validate(self, gi: GroundingInput) -> AnchorVerdict:
        draft, refined = gi.draft, gi.refined
        # HARD violations abstain the whole summary (fail-closed, INV-4). The anchor-existence
        # check is SOFT (option D): an anchor whose span isn't verbatim in the source — a table
        # re-rendering, a paraphrase, or LaTeX-vs-unicode math — is DROPPED, not abstained on, so
        # the grounded summary text + the verifiable anchors are still shown. The numeric guard
        # (rule 2) stays HARD, so dropping an unverifiable pointer can never surface a fabricated
        # figure. fail-closed is thus per-anchor here, not whole-summary.
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

        # (1) anchor existence — SOFT: keep verifiable anchors, drop the rest (Step 35)
        haystack = refined.body
        captions = "\n".join(refined.captions)
        # preserved (Appendix/Supplementary, Step 36) is source content too — include it so an
        # anchor into an appendix span/label is not falsely flagged anchor_missing.
        preserved = "\n".join(refined.preserved)
        section_labels = {s.label.strip() for s in refined.sections if s.label.strip()}
        kept: list[Anchor] = []
        for a in draft.anchors:
            span = a.span.strip()
            label = a.label.strip()
            # Verify span — formula spans are exempt (verbatim-unmatchable vs LaTeX source).
            span_ok = (
                not span
                or _is_formula_span(span)
                or (span in haystack or span in captions or span in preserved)
            )
            # Verify label
            label_ok = (
                not label
                or _is_formula_span(label)
                or label in haystack
                or label in captions
                or label in section_labels
                or label in preserved
            )
            if span_ok and label_ok:
                kept.append(a)
            else:
                soft.append(Violation("anchor_missing", a.field_name))

        # (2) numeric match — result figures must appear in the source — HARD, but FRACTION-based:
        # a few stray numbers (a mis-transcribed table cell, a rounded value) shouldn't abstain an
        # otherwise-grounded summary, while a draft whose figures are MOSTLY fabricated still must.
        # Abstain only when the ungrounded share exceeds the threshold (anti-fabrication intact).
        result_nums = _NUM_RE.findall(draft.results)
        if result_nums:
            src_nums = _source_numbers(haystack, captions)
            ungrounded = sum(
                1 for t in result_nums if not (_normalize_number(t) & src_nums)
            )
            if ungrounded / len(result_nums) > _NUMERIC_MISMATCH_THRESHOLD:
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


def is_empty_draft(draft: SummaryDraft) -> bool:
    return not draft.tldr.strip() and not draft.contributions
