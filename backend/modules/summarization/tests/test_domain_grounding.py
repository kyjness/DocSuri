"""GroundingValidator — BR-S7 / Q4 / Q15: deterministic anchor/numeric/schema checks."""

from __future__ import annotations

from dataclasses import replace

from summarization.domain.grounding import GroundingValidator
from summarization.domain.models import Anchor, AnchorTarget, GroundingInput, SummaryDraft
from summarization.domain.refiner import InputRefiner


def _gi(draft: SummaryDraft, paper: str) -> GroundingInput:
    return GroundingInput(draft=draft, refined=InputRefiner().refine(paper))


def test_valid_draft_passes(sample_paper: str, valid_draft: SummaryDraft) -> None:
    verdict = GroundingValidator().validate(_gi(valid_draft, sample_paper))
    assert verdict.ok
    assert verdict.outcome == "pass"


def test_fabricated_anchor_dropped(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # Option D: a fabricated anchor (span absent from the source) is DROPPED, not abstained on —
    # the summary still passes, the anchor is excluded from kept_anchors, and a soft anchor_missing
    # violation is recorded (telemetry). The numeric guard still blocks fabricated *figures*.
    bad = replace(
        valid_draft,
        anchors=(Anchor("results", AnchorTarget.TABLE, span="99.9% on CIFAR-100"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and verdict.outcome == "pass"
    assert verdict.kept_anchors == ()  # fabricated anchor dropped
    assert any(v.kind == "anchor_missing" for v in verdict.violations)


def test_numeric_mismatch_fails(sample_paper: str, valid_draft: SummaryDraft) -> None:
    bad = replace(valid_draft, results="achieves 42.7% accuracy")
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert not verdict.ok
    assert any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_schema_incomplete_fails(sample_paper: str, valid_draft: SummaryDraft) -> None:
    bad = replace(valid_draft, reproducibility={"code": ""})
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert not verdict.ok
    assert any(v.kind == "schema_incomplete" for v in verdict.violations)


def test_truncated_fails(sample_paper: str, valid_draft: SummaryDraft) -> None:
    bad = replace(valid_draft, truncated=True)
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert not verdict.ok
    assert any(v.kind == "truncated" for v in verdict.violations)


def test_anchor_label_missing_dropped(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # A missing label makes the anchor unverifiable → dropped (option D), not whole-summary abstain.
    bad = replace(
        valid_draft,
        anchors=(
            Anchor(
                field_name="results",
                target=AnchorTarget.SECTION,
                span="95.3% accuracy on ImageNet",
                label="Non Existent Section 9.9",
            ),
        ),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and verdict.kept_anchors == ()
    assert any(v.kind == "anchor_missing" for v in verdict.violations)


def test_formula_anchor_exempt_from_existence(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # A math/formula span can't be verbatim-matched (LaTeX vs unicode) → exempt → KEPT, no violation.
    bad = replace(
        valid_draft,
        anchors=(Anchor("method", AnchorTarget.SECTION, span=r"\mathcal{L}=\{1y,1w,1d\}"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and len(verdict.kept_anchors) == 1
    assert not any(v.kind == "anchor_missing" for v in verdict.violations)


def test_prose_arrow_span_not_exempt(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # A ``→`` is common in prose, not just formulas. An absent arrow span must NOT be exempted as
    # a formula — it stays subject to the existence check and is dropped (regression for the
    # widened grounding hole when arrows were in _MATH_RE).
    bad = replace(
        valid_draft,
        anchors=(Anchor("method", AnchorTarget.SECTION, span="pretrain → finetune on FakeSet-999"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and verdict.kept_anchors == ()  # dropped, not exempted
    assert any(v.kind == "anchor_missing" for v in verdict.violations)


def test_numeric_minority_mismatch_tolerated() -> None:
    # A few stray figures (1 of 4 absent = 25% ≤ 50%) shouldn't abstain an otherwise-grounded draft.
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t", contributions=("c",), method="m",
        results="MAPE 1.27, 1.29 and 1.30 vs baseline 9.99",  # 9.99 absent, rest present
        limitations="l", reproducibility={"code": "", "data": ""}, anchors=(),
    )
    refined = RefinedSource(body="results: 1.27 1.29 1.30 across horizons", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.ok
    assert not any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_numeric_majority_mismatch_abstains() -> None:
    # Mostly-fabricated figures (3 of 4 absent = 75% > 50%) still abstain (anti-hallucination intact).
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t", contributions=("c",), method="m",
        results="reports 8.1, 8.2, 8.3 and 1.27",  # only 1.27 present
        limitations="l", reproducibility={"code": "", "data": ""}, anchors=(),
    )
    refined = RefinedSource(body="results: 1.27 across horizons", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert not verdict.ok
    assert any(v.kind == "numeric_mismatch" for v in verdict.violations)
