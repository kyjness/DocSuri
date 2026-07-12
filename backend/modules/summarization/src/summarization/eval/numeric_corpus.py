"""Numeric fraction-spectrum corpus for threshold recalibration (QT-1).

Each case fixes a known *ungrounded fraction* of the draft's result figures so a sweep over
``_NUMERIC_MISMATCH_THRESHOLD`` traces the false-pass / false-abstain trade-off. Clear ends
(few or most figures fabricated) are ``confident``; the policy-sensitive middle (⅓ … ⅔
ungrounded) is left as ``confident=False`` probes — whether "half the numbers are unverifiable"
counts as fabricated is a REVIEWER/policy call, not derivable from data.

⚠️ SYNTHETIC — hand-built, not held-out real papers. A sweep here encodes the label policy, so
the 'best' threshold is illustrative on its own. The US-S6 recalibration (0.5 → 0.4) was
committed from this spectrum TOGETHER with the real-figure corpus (``real_corpus.py``), which
settled the 0.50 boundary: exactly-half-unsupported now counts as fabricated (caught at 0.4).
"""

from __future__ import annotations

from ..domain.models import GroundingInput, RefinedSource, SummaryDraft
from .grounding_eval import GroundingEvalCase

# Well-separated values so none collide via rounding tolerance or ×100 percent/fraction scaling.
_GROUNDED_POOL = ("11", "22", "33", "44")
_FABRICATED_POOL = ("70", "80", "90", "60")


def _numeric_case(
    name: str, n_grounded: int, n_fabricated: int, expected: str, *, confident: bool
) -> GroundingEvalCase:
    grounded = _GROUNDED_POOL[:n_grounded]
    fabricated = _FABRICATED_POOL[:n_fabricated]
    figures = ", ".join(f"{x} percent" for x in (*grounded, *fabricated))
    body = "Source measurements: " + " ".join(grounded) + " on the held-out split."
    total = n_grounded + n_fabricated
    frac = n_fabricated / total if total else 0.0
    draft = SummaryDraft(
        tldr="A concise summary.",
        contributions=("The contribution.",),
        method="The method.",
        results=f"Reported figures: {figures}.",
        limitations="The limitations.",
        reproducibility={"code": "released", "data": "public"},
        anchors=(),
    )
    return GroundingEvalCase(
        name=name,
        gi=GroundingInput(draft=draft, refined=RefinedSource(body=body, captions=())),
        expected=expected,
        rationale=f"{n_fabricated}/{total} result figures absent from source (frac={frac:.2f}).",
        confident=confident,
    )


# Clear ends — stable labels (assertable).
_f0 = _numeric_case("num_ungrounded_0of4", 4, 0, "faithful", confident=True)  # 0.00
_f1of4 = _numeric_case("num_ungrounded_1of4", 3, 1, "faithful", confident=True)  # 0.25
_f3of4 = _numeric_case("num_ungrounded_3of4", 1, 3, "fabricated", confident=True)  # 0.75
_f3of3 = _numeric_case("num_ungrounded_3of3", 0, 3, "fabricated", confident=True)  # 1.00

# Policy-sensitive middle — label is the reviewer's call (probes, not asserted).
_p1of3 = _numeric_case("num_ungrounded_1of3", 2, 1, "faithful", confident=False)  # 0.33
_p2of4 = _numeric_case("num_ungrounded_2of4", 2, 2, "fabricated", confident=False)  # 0.50
_p2of3 = _numeric_case("num_ungrounded_2of3", 1, 2, "fabricated", confident=False)  # 0.67


NUMERIC_CORPUS: tuple[GroundingEvalCase, ...] = (
    _f0,
    _f1of4,
    _f3of4,
    _f3of3,
    _p1of3,
    _p2of4,
    _p2of3,
)
NUMERIC_CONFIDENT: tuple[GroundingEvalCase, ...] = tuple(c for c in NUMERIC_CORPUS if c.confident)
NUMERIC_PROBES: tuple[GroundingEvalCase, ...] = tuple(
    c for c in NUMERIC_CORPUS if not c.confident
)
