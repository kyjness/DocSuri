"""QT-1 grounding fidelity harness.

Locks: (a) the harness classification/counting math (via a forced-outcome fake validator),
(b) that the confident seed cases classify correctly against the real ``GroundingValidator``
(no fabrication leak, no over-abstention), and (c) the US-S6 recalibration of
``_NUMERIC_MISMATCH_THRESHOLD`` (0.5 → 0.4): the formerly-false-passing half-ungrounded probe
is now CAUGHT, every faithful-labeled case still passes, and the constant may only ever move
stricter (lower) — a loosening change surfaces here rather than silently.
"""

from __future__ import annotations

from dataclasses import dataclass

from summarization.domain.grounding import _NUMERIC_MISMATCH_THRESHOLD
from summarization.domain.models import GroundingInput
from summarization.eval.grounding_eval import (
    GroundingEvalCase,
    run_grounding_eval,
    sweep_numeric_threshold,
)
from summarization.eval.numeric_corpus import NUMERIC_CONFIDENT, NUMERIC_CORPUS
from summarization.eval.real_corpus import REAL_CORPUS
from summarization.eval.seed_cases import CONFIDENT_CASES, PROBE_CASES, SEED_CASES


@dataclass
class _Verdict:
    outcome: str


class _FakeValidator:
    """Returns a fixed outcome regardless of input — isolates the harness math from the gate."""

    def __init__(self, outcome: str) -> None:
        self._outcome = outcome

    def validate(self, gi: GroundingInput) -> _Verdict:  # noqa: ARG002
        return _Verdict(self._outcome)


def _case(name: str, expected: str) -> GroundingEvalCase:
    # The gi is unused by the fake validator; reuse a real seed case's gi to satisfy the type.
    return GroundingEvalCase(name=name, gi=SEED_CASES[0].gi, expected=expected, rationale="t")


def test_counts_false_pass_when_fabricated_leaks() -> None:
    report = run_grounding_eval([_case("x", "fabricated")], validator=_FakeValidator("pass"))
    assert report.false_pass == 1
    assert report.false_abstain == 0
    assert report.correct == 0


def test_counts_false_abstain_when_faithful_blocked() -> None:
    report = run_grounding_eval([_case("x", "faithful")], validator=_FakeValidator("abstain"))
    assert report.false_abstain == 1
    assert report.false_pass == 0


def test_counts_correct_cells() -> None:
    pass_report = run_grounding_eval([_case("x", "faithful")], validator=_FakeValidator("pass"))
    assert (
        pass_report.false_pass == 0 and pass_report.false_abstain == 0 and pass_report.correct == 1
    )
    abstain_report = run_grounding_eval(
        [_case("x", "fabricated")], validator=_FakeValidator("abstain")
    )
    assert abstain_report.correct == 1


def test_confident_seed_cases_have_no_leak_or_overabstention() -> None:
    """Real GroundingValidator: every confident-labeled case classifies correctly."""
    report = run_grounding_eval(CONFIDENT_CASES)
    assert report.total == len(CONFIDENT_CASES)
    assert report.false_pass == 0, "a fabricated seed case leaked past the gate"
    assert report.false_abstain == 0, "a faithful seed case was over-abstained"
    assert report.correct == report.total


def test_half_ungrounded_probe_now_caught() -> None:
    """US-S6 regression pin: the half-ungrounded probe was a KNOWN FALSE-PASS at the
    pre-Phase-3 threshold 0.5 (1/2 = 0.5 is not > 0.5 → fabricated figure leaked). Since the
    recalibration to 0.4 the gate ABSTAINS — the fabrication is caught. This must never
    regress to a pass (C-2: no fabricated content)."""
    (probe,) = PROBE_CASES
    (result,) = run_grounding_eval([probe]).results
    assert result.outcome == "abstain"
    assert result.classification == "true_abstain"


def test_half_ungrounded_probe_leaked_at_old_threshold() -> None:
    """Evidence pin for the recalibration: the SAME probe run at the old 0.5 leaks (false-pass)
    and at the new 0.4 is caught — the exact false-pass → caught flip US-S6 required."""
    (probe,) = PROBE_CASES
    old, new = sweep_numeric_threshold([probe], [0.5, 0.4])[0:2]
    assert old.threshold == 0.5 and old.false_pass == 1  # pre-recalibration leak
    assert new.threshold == 0.4 and new.false_pass == 0 and new.false_abstain == 0


def test_default_threshold_pinned_strict() -> None:
    """The production default is the recalibrated 0.4 — the strict edge of the zero-error
    plateau [0.40, 0.50) on the QT-1 corpora. Grounding is C-2-sensitive: any future change
    may only LOWER this value (stricter, catches more fabrication), never raise it."""
    assert _NUMERIC_MISMATCH_THRESHOLD == 0.4


def test_all_faithful_cases_still_pass_at_recalibrated_default() -> None:
    """US-S6 regression pin (the other side): recalibrating stricter must not over-abstain —
    every faithful-labeled case across ALL corpora (seed + numeric spectrum + real figures,
    probes included) still passes at the 0.4 default."""
    faithful = [c for c in (*SEED_CASES, *NUMERIC_CORPUS, *REAL_CORPUS) if c.expected == "faithful"]
    report = run_grounding_eval(faithful)
    assert report.total == len(faithful) > 0
    assert report.false_abstain == 0, "recalibration over-abstained a faithful case"


def test_no_fabrication_leak_across_all_corpora_at_default() -> None:
    """At the recalibrated 0.4, no fabricated-labeled case in ANY corpus leaks past the gate —
    including the three exactly-half-ungrounded cases that leaked at 0.5."""
    report = run_grounding_eval((*SEED_CASES, *NUMERIC_CORPUS, *REAL_CORPUS))
    assert report.false_pass == 0, "a fabricated case leaked past the recalibrated gate"
    assert report.false_abstain == 0
    assert report.correct == report.total == len(SEED_CASES) + len(NUMERIC_CORPUS) + len(
        REAL_CORPUS
    )


def test_numeric_confident_corpus_clean_at_default() -> None:
    """The stable-label numeric corpus has no leak/over-abstention at the recalibrated 0.4
    default — the clear ends (≤ 0.25 and ≥ 0.75 ungrounded) sit well off the new boundary."""
    report = run_grounding_eval(NUMERIC_CONFIDENT)
    assert report.false_pass == 0
    assert report.false_abstain == 0


def test_sweep_tradeoff_is_monotone() -> None:
    """Recalibration invariant: as the threshold rises, false-abstain never increases and
    false-pass never decreases (a looser gate blocks fewer faithful, passes more fabricated)."""
    points = sweep_numeric_threshold(NUMERIC_CONFIDENT, [0.0, 0.25, 0.5, 0.99])
    assert [p.threshold for p in points] == [0.0, 0.25, 0.5, 0.99]
    false_abstain = [p.false_abstain for p in points]
    false_pass = [p.false_pass for p in points]
    assert false_abstain == sorted(false_abstain, reverse=True)  # non-increasing
    assert false_pass == sorted(false_pass)  # non-decreasing
