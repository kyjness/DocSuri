"""Seed fidelity cases for the QT-1 grounding harness — SMALL and REVIEW-PENDING.

These are a starter set to exercise the harness and lock current ``GroundingValidator``
behavior, NOT the held-out evaluation corpus (which is OP/team-owned and larger). Labels are a
best-effort first pass; ``confident=False`` cases are threshold/edge probes whose label is the
reviewer's call. Do NOT recalibrate ``_NUMERIC_MISMATCH_THRESHOLD`` from this set alone.

Each case is hand-built to trip exactly one validator path so the label is unambiguous:
empty/truncated/schema are HARD (abstain); anchor-existence is SOFT (drop, summary still passes);
numeric match is HARD but fraction-based (abstain only when >40% of result figures are absent —
recalibrated from the pre-Phase-3 0.5 estimate, US-S6; see ``domain/grounding.py``).
"""

from __future__ import annotations

from ..domain.models import (
    Anchor,
    AnchorTarget,
    GroundingInput,
    RefinedSource,
    Section,
    SummaryDraft,
)
from .grounding_eval import GroundingEvalCase


def _refined(
    body: str, *, sections: tuple[Section, ...] = (), captions: tuple[str, ...] = ()
) -> RefinedSource:
    return RefinedSource(
        body=body, sections=sections, captions=captions, token_count=len(body.split())
    )


def _draft(
    *,
    tldr: str = "A concise summary of the paper's contribution.",
    method: str = "The method is described in full.",
    results: str = "",
    anchors: tuple[Anchor, ...] = (),
    truncated: bool = False,
    reproducibility: dict[str, str] | None = None,
) -> SummaryDraft:
    return SummaryDraft(
        tldr=tldr,
        contributions=("The primary contribution.",),
        method=method,
        results=results,
        limitations="The stated limitations.",
        reproducibility=reproducibility
        if reproducibility is not None
        else {"code": "released", "data": "public"},
        anchors=anchors,
        truncated=truncated,
    )


# 1. Faithful: every reported figure and the anchor exist verbatim in the source → PASS.
_faithful_grounded = GroundingEvalCase(
    name="faithful_grounded",
    gi=GroundingInput(
        draft=_draft(
            results="Accuracy of 95.3 percent, up from 92.1 percent.",
            anchors=(
                Anchor(
                    "results", AnchorTarget.SECTION, span="95.3 percent accuracy", label="Results"
                ),
            ),
        ),
        refined=_refined(
            "We evaluate on the benchmark. Our method reaches 95.3 percent accuracy, "
            "improving over the 92.1 percent baseline.",
            sections=(Section("Results", 0, 0),),
        ),
    ),
    expected="faithful",
    rationale=(
        "95.3 and 92.1 both appear in the body; the anchor span/label resolve. Nothing fabricated."
    ),
    confident=True,
)

# 2. Faithful but the anchor is a paraphrase (not verbatim): the SOFT check DROPS the anchor and
# keeps the grounded summary → PASS. Guards against over-abstaining on re-phrased pointers.
_faithful_paraphrased_anchor = GroundingEvalCase(
    name="faithful_paraphrased_anchor",
    gi=GroundingInput(
        draft=_draft(
            results="An F-score of 0.88 is reported.",
            anchors=(
                Anchor(
                    "results",
                    AnchorTarget.SECTION,
                    span="our approach substantially outperforms prior work",
                    label="",
                ),
            ),
        ),
        refined=_refined("The model achieves an F-score of 0.88 on the held-out set."),
    ),
    expected="faithful",
    rationale=(
        "0.88 is grounded; the non-verbatim anchor is dropped (SOFT), not abstained — "
        "the summary is faithful."
    ),
    confident=True,
)

# 3. Fabricated: the reported figures are absent from the source (all ungrounded > 50%) → ABSTAIN.
_fabricated_numbers = GroundingEvalCase(
    name="fabricated_numbers",
    gi=GroundingInput(
        draft=_draft(
            results="Reported accuracy 99.9 percent, with 88.7 and 77.1 on two transfer tasks.",
        ),
        refined=_refined("We report on a small pilot. The observed value was 50.0 percent."),
    ),
    expected="fabricated",
    rationale=(
        "99.9 / 88.7 / 77.1 appear nowhere in the source (only 50.0 does); "
        "3/3 ungrounded must abstain."
    ),
    confident=True,
)

# 4. Degenerate/fabricated: an empty method section is an unusable draft → ABSTAIN.
_fabricated_empty_method = GroundingEvalCase(
    name="fabricated_empty_method",
    gi=GroundingInput(
        draft=_draft(method="", results="Accuracy of 50.0 percent."),
        refined=_refined("The observed value was 50.0 percent."),
    ),
    expected="fabricated",
    rationale=(
        "Empty method is a HARD violation — the gate must abstain rather than expose a "
        "hollow summary."
    ),
    confident=True,
)

# 5. PROBE (recalibration settled it, US-S6): exactly half the result figures are unverifiable.
# Under the pre-Phase-3 threshold 0.5 this PASSED (0.5 is not > 0.5) — the known false-pass that
# drove the recalibration. At the strict 0.4 the gate ABSTAINS (caught); pinned in
# ``tests/test_grounding_eval.py::test_half_ungrounded_probe_now_caught``.
_probe_half_ungrounded = GroundingEvalCase(
    name="probe_half_ungrounded_numbers",
    gi=GroundingInput(
        draft=_draft(
            results="We obtain 50.0 percent here and 99.9 percent in the appendix.",
        ),
        refined=_refined("The main result was 50.0 percent on the test split."),
    ),
    expected="fabricated",
    rationale=(
        "50.0 grounded, 99.9 not → 1/2 = 0.5 ungrounded. Former false-pass at the 0.5 "
        "threshold; caught (> 0.4) since the US-S6 recalibration."
    ),
    confident=False,
)


# 6. Faithful with a ROUNDED figure: 95.3 is a correct rounding of the source's 95.34 → PASS
# (matcher 정밀화 — rounding tolerance; before precision work this false-abstained).
_faithful_rounded_figure = GroundingEvalCase(
    name="faithful_rounded_figure",
    gi=GroundingInput(
        draft=_draft(results="Accuracy of 95.3 percent."),
        refined=_refined("Our method reaches 95.34 percent accuracy on the test set."),
    ),
    expected="faithful",
    rationale=(
        "95.3 is a correct rounding of the source 95.34 (within half-a-ULP); matcher grounds it."
    ),
    confident=True,
)

# 7. Faithful with a THOUSAND-SEPARATED figure: 1,200 and 1200 are the same number → PASS.
_faithful_thousand_sep = GroundingEvalCase(
    name="faithful_thousand_separator",
    gi=GroundingInput(
        draft=_draft(results="Trained on 1,200 annotated examples."),
        refined=_refined("The training set comprises 1200 annotated examples."),
    ),
    expected="faithful",
    rationale=(
        "1,200 and 1200 are the same figure (thousand separator); matcher normalizes the comma."
    ),
    confident=True,
)


SEED_CASES: tuple[GroundingEvalCase, ...] = (
    _faithful_grounded,
    _faithful_paraphrased_anchor,
    _faithful_rounded_figure,
    _faithful_thousand_sep,
    _fabricated_numbers,
    _fabricated_empty_method,
    _probe_half_ungrounded,
)

CONFIDENT_CASES: tuple[GroundingEvalCase, ...] = tuple(c for c in SEED_CASES if c.confident)
PROBE_CASES: tuple[GroundingEvalCase, ...] = tuple(c for c in SEED_CASES if not c.confident)
