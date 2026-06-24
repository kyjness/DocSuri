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

from .models import AnchorVerdict, GroundingInput, SummaryDraft, Violation

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


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
        violations: list[Violation] = []

        # (4) empty / truncation (Step 33)
        if not draft.tldr.strip() or not draft.method.strip():
            violations.append(Violation("empty", "tldr/method"))
        if getattr(draft, "truncated", False):
            violations.append(Violation("truncated", "draft"))

        # (3) schema completeness
        if "code" not in draft.reproducibility or "data" not in draft.reproducibility:
            violations.append(Violation("schema_incomplete", "reproducibility"))

        # (1) anchor existence — span (and label, if present) must be in the source (Step 35)
        haystack = refined.body
        captions = "\n".join(refined.captions)
        # preserved (Appendix/Supplementary, Step 36) is source content too — include it so an
        # anchor into an appendix span/label is not falsely flagged anchor_missing.
        preserved = "\n".join(refined.preserved)
        section_labels = {s.label.strip() for s in refined.sections if s.label.strip()}
        for a in draft.anchors:
            span = a.span.strip()
            label = a.label.strip()
            # Verify span
            span_ok = not span or (span in haystack or span in captions or span in preserved)
            # Verify label
            label_ok = not label or (
                label in haystack
                or label in captions
                or label in section_labels
                or label in preserved
            )
            
            if not span_ok or not label_ok:
                violations.append(Violation("anchor_missing", a.field_name))

        # (2) numeric match — result numbers must appear in the source
        for token in _NUM_RE.findall(draft.results):
            if not (_normalize_number(token) & _source_numbers(haystack, captions)):
                violations.append(Violation("numeric_mismatch", "results"))
                break

        if violations:
            return AnchorVerdict(ok=False, violations=tuple(violations), outcome="abstain")
        return AnchorVerdict(ok=True, outcome="pass")


def _source_numbers(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for token in _NUM_RE.findall(t):
            out |= _normalize_number(token)
    return out


def is_empty_draft(draft: SummaryDraft) -> bool:
    return not draft.tldr.strip() and not draft.contributions
