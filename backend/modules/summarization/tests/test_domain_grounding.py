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


def test_fabricated_anchor_fails(sample_paper: str, valid_draft: SummaryDraft) -> None:
    bad = replace(
        valid_draft,
        anchors=(Anchor("results", AnchorTarget.TABLE, span="99.9% on CIFAR-100"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert not verdict.ok
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


def test_anchor_label_missing_fails(sample_paper: str, valid_draft: SummaryDraft) -> None:
    from summarization.domain.models import Anchor, AnchorTarget
    bad = replace(
        valid_draft,
        anchors=(
            Anchor(
                field_name="results",
                target=AnchorTarget.SECTION,
                span="95.3% accuracy on ImageNet",
                label="Non Existent Section 9.9"
            ),
        )
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert not verdict.ok
    assert any(v.kind == "anchor_missing" for v in verdict.violations)
