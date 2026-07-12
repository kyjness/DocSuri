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
    # Option D: an anchor that resolves to no real location (no label, no target_hint) is DROPPED,
    # not abstained on — the summary still passes, the anchor is excluded from kept_anchors, and a
    # soft anchor_missing violation is recorded (telemetry). Fabricated *figures* stay blocked by
    # the HARD numeric gate.
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
    # A label that matches no real section (and no target_hint) resolves to nothing → dropped
    # (option D), not whole-summary abstain.
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


def test_anchor_resolves_by_target_hint_localized_label_kept(
    sample_paper: str, valid_draft: SummaryDraft
) -> None:
    # THE production regression: the model writes a Korean, source-absent ``label`` but puts the
    # real location in its raw ``target`` (target_hint). The anchor must resolve via target_hint
    # to the real section and be KEPT, with its label rewritten to the canonical doc-model label.
    bad = replace(
        valid_draft,
        anchors=(
            Anchor(
                field_name="results",
                target=AnchorTarget.SECTION,
                span=r"\mathcal{L}=\{1y,1w,1d\}",  # a formula span — no longer needs verbatim match
                label="정확도 결과 섹션",  # Korean, absent from the English source
                target_hint="Section: 5.2 Results",
            ),
        ),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "5.2 Results"  # rewritten to canonical
    assert not any(v.kind == "anchor_missing" for v in verdict.violations)


def test_anchor_caption_target_resolves(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # A figure/table target resolves against caption-derived labels ("Table 1: …" → "Table 1").
    bad = replace(
        valid_draft,
        anchors=(Anchor("results", AnchorTarget.TABLE, span="", label="정확도 표",
                        target_hint="Table 1"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Table 1"


def test_anchor_unresolvable_target_dropped(sample_paper: str, valid_draft: SummaryDraft) -> None:
    # A target that resolves to no real doc-model location is dropped (SOFT) — the summary still
    # passes and a fabricated pointer never surfaces. Anti-fabrication of *figures* stays with the
    # HARD numeric gate.
    bad = replace(
        valid_draft,
        anchors=(Anchor("method", AnchorTarget.SECTION, span="", label="없는 섹션",
                        target_hint="Section: Nonexistent Section 9.9"),),
    )
    verdict = GroundingValidator().validate(_gi(bad, sample_paper))
    assert verdict.ok and verdict.kept_anchors == ()
    assert any(v.kind == "anchor_missing" for v in verdict.violations)


def _draft_with_anchor(anchor: Anchor) -> SummaryDraft:
    return SummaryDraft(
        tldr="t", contributions=("c",), method="m", results="r", limitations="l",
        reproducibility={"code": "", "data": ""}, anchors=(anchor,),
    )


def test_anchor_resolves_by_label_location_field() -> None:
    # New prompt contract: the model puts the exact source location in ``label`` (target is the
    # coarse enum). The anchor resolves via ``label`` even when target_hint is just "section".
    from summarization.domain.models import RefinedSource, Section

    refined = RefinedSource(body="b", sections=(Section("Eliminating Free Riding", 0, 1),))
    draft = _draft_with_anchor(
        Anchor("method", AnchorTarget.SECTION, span="", label="Eliminating Free Riding",
               target_hint="section")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Eliminating Free Riding"


def test_anchor_duplicate_chips_collapsed() -> None:
    # Several claims in one field routinely cite the SAME section; after canonicalization they'd
    # render as identical repeated "출처: Introduction" chips. One chip per (field, label) survives.
    from summarization.domain.models import RefinedSource, Section

    refined = RefinedSource(body="b", sections=(Section("Introduction", 0, 1),))
    draft = SummaryDraft(
        tldr="t", contributions=("c",), method="m", results="r", limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(
            Anchor("method", AnchorTarget.SECTION, span="a", label="Introduction",
                   target_hint="section"),
            Anchor("method", AnchorTarget.SECTION, span="b", label="Introduction",
                   target_hint="section"),
            Anchor("method", AnchorTarget.SECTION, span="c", label="Introduction",
                   target_hint="section"),
        ),
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Introduction"


def test_anchor_figure_number_no_prefix_collision() -> None:
    # "Figure 1" must NOT resolve to "Figure 10" — token match ('1' ≠ '10'), not raw substring.
    from summarization.domain.models import RefinedSource

    refined = RefinedSource(body="b", captions=("Figure 10: later.", "Figure 1: first."))
    draft = _draft_with_anchor(
        Anchor("results", AnchorTarget.FIGURE, span="", label="Figure 1", target_hint="Figure 1")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Figure 1"


def test_anchor_section_prefix_does_not_truncate_title() -> None:
    # 'Security Analysis' must not have 'Sec' stripped (→ 'urity analysis'), which would drop a
    # valid anchor. The prefix strip requires a word boundary / 'Sec.' abbreviation dot.
    from summarization.domain.models import RefinedSource, Section

    refined = RefinedSource(body="b", sections=(Section("Security Analysis", 0, 1),))
    draft = _draft_with_anchor(
        Anchor("method", AnchorTarget.SECTION, span="", label="Security Analysis",
               target_hint="Section: Security Analysis")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Security Analysis"


def test_anchor_enum_only_target_does_not_over_resolve() -> None:
    # A bare enum target ("table") + Korean label must NOT collapse to the first table (the old
    # substring rule did); it drops instead of mislabeling the chip.
    from summarization.domain.models import RefinedSource

    refined = RefinedSource(body="b", captions=("Table 1: acc.",))
    draft = _draft_with_anchor(
        Anchor("results", AnchorTarget.TABLE, span="", label="정확도 표", target_hint="table")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.kept_anchors == ()
    assert any(v.kind == "anchor_missing" for v in verdict.violations)


def test_anchor_empty_structure_keeps_chips_verbatim() -> None:
    # #352 edge 1: a pure-abstract / heading-less .txt source has no sections/captions/tables, so
    # the structural index is empty. Chips are kept verbatim rather than all dropped as
    # anchor_missing (the numeric HARD gate stays independent, so nothing fabricated leaks).
    from summarization.domain.models import RefinedSource

    refined = RefinedSource(body="abstract-only body with no headings")
    draft = _draft_with_anchor(
        Anchor("method", AnchorTarget.SECTION, span="", label="초록 인용", target_hint="abstract")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.ok
    assert verdict.kept_anchors == draft.anchors  # kept unchanged, label not rewritten
    assert not any(v.kind == "anchor_missing" for v in verdict.violations)


def test_anchor_longest_contiguous_match_wins() -> None:
    # #352 edge 2: when a short generic section title ("Method") and a longer specific one
    # ("Method and Results") both match the anchor as a token run, the LONGEST wins — the old
    # first-match rule would mislabel the chip to "Method".
    from summarization.domain.models import RefinedSource, Section

    refined = RefinedSource(
        body="b",
        sections=(Section("Method", 0, 1), Section("Method and Results", 0, 1)),
    )
    draft = _draft_with_anchor(
        Anchor("method", AnchorTarget.SECTION, span="",
               label="Method and Results section", target_hint="section")
    )
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert len(verdict.kept_anchors) == 1
    assert verdict.kept_anchors[0].label == "Method and Results"


def test_numeric_minority_mismatch_tolerated() -> None:
    # A few stray figures (1 of 4 absent = 25% ≤ 50%) shouldn't abstain an otherwise-grounded draft.
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="MAPE 1.27, 1.29 and 1.30 vs baseline 9.99",  # 9.99 absent, rest present
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="results: 1.27 1.29 1.30 across horizons", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.ok
    assert not any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_rounding_tolerance_grounds_figure() -> None:
    # matcher 정밀화: 95.3 is a correct rounding of the source's 95.34 → grounded (no mismatch).
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="accuracy of 95.3 percent",
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="we report 95.34 percent on the test set", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.ok
    assert not any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_thousand_separator_grounds_figure() -> None:
    # matcher 정밀화: "1,200" and "1200" are the same figure (comma normalized) → grounded.
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="trained on 1,200 examples",
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="the dataset has 1200 examples", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert verdict.ok
    assert not any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_integer_figure_not_grounded_by_scaled_source_year() -> None:
    # Regression: a fabricated integer figure must NOT false-ground against an unrelated source
    # value ~100× it. The old ×100/÷100 tolerance band grounded "20" against a year "2020"
    # (2020/100 = 20.2, within the integer band 0.5) → the figure slipped past the HARD
    # anti-fabrication gate. Cross-scale equivalence is now exact-normalized-form only.
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="we obtain a score of 20",
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="published in 2020 with no other figures", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert not verdict.ok
    assert any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_rounding_tolerance_is_bounded() -> None:
    # The band is half-a-ULP at the draft's precision, NOT loose: 95.3 vs 95.9 (diff 0.6) must
    # still mismatch — matcher precision must not turn the numeric guard off.
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="accuracy of 95.3 percent",
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="we report 95.9 percent and nothing else", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert not verdict.ok
    assert any(v.kind == "numeric_mismatch" for v in verdict.violations)


def test_numeric_majority_mismatch_abstains() -> None:
    # Mostly-fabricated figures (3 of 4 absent = 75% > 50%) still abstain (anti-hallucination).
    from summarization.domain.models import RefinedSource

    draft = SummaryDraft(
        tldr="t",
        contributions=("c",),
        method="m",
        results="reports 8.1, 8.2, 8.3 and 1.27",  # only 1.27 present
        limitations="l",
        reproducibility={"code": "", "data": ""},
        anchors=(),
    )
    refined = RefinedSource(body="results: 1.27 across horizons", captions=())
    verdict = GroundingValidator().validate(GroundingInput(draft=draft, refined=refined))
    assert not verdict.ok
    assert any(v.kind == "numeric_mismatch" for v in verdict.violations)
