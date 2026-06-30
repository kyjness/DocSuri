"""QT-1 grounding fidelity harness (scaffold).

Locks: (a) the harness classification/counting math (via a forced-outcome fake validator),
(b) that the confident seed cases classify correctly against the real ``GroundingValidator``
(no fabrication leak, no over-abstention), and (c) the current behavior of the threshold probe
so a future ``_NUMERIC_MISMATCH_THRESHOLD`` change surfaces here rather than silently.
"""

from __future__ import annotations

from dataclasses import dataclass

from summarization.domain.models import GroundingInput
from summarization.eval.grounding_eval import (
    GroundingEvalCase,
    run_grounding_eval,
    sweep_numeric_threshold,
)
from summarization.eval.numeric_corpus import NUMERIC_CONFIDENT
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


def test_threshold_probe_current_behavior_is_pass() -> None:
    """The half-ungrounded probe currently PASSES (0.5 is not > 0.5). Recorded so a threshold
    recalibration that flips it is caught here — the probe's label stays the reviewer's call."""
    (probe,) = PROBE_CASES
    (result,) = run_grounding_eval([probe]).results
    assert result.outcome == "pass"
    # Labeled 'fabricated' → today this counts as a false-pass: the recalibration target.
    assert result.classification == "false_pass"


def test_numeric_confident_corpus_clean_at_default() -> None:
    """The stable-label numeric corpus has no leak/over-abstention at the default 0.5 — the
    clear ends do not argue for changing the threshold (only the policy probes do)."""
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
