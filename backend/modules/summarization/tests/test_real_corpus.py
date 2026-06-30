"""QT-1 held-out numeric corpus (real arXiv result figures) — locks the recalibration finding.

Decision (reviewer/policy): keep ``_NUMERIC_MISMATCH_THRESHOLD = 0.5``. These tests record the
real-figure evidence behind it so a future threshold change surfaces here:
  (a) the confident (stable-label) cases have no leak / no over-abstention at the default 0.5;
  (b) the safe plateau on confident labels is [0.25, 0.51] — 0.5 sits at its strict upper edge,
      and real fabricated cases at 0.60 ungrounded forbid raising it further;
  (c) the only case that would argue for lowering below 0.5 is the policy probe where EXACTLY
      half the figures are unsupported — recorded as the reviewer's call, not asserted as a bug.
"""

from __future__ import annotations

from summarization.eval.grounding_eval import run_grounding_eval, sweep_numeric_threshold
from summarization.eval.real_corpus import REAL_CONFIDENT, REAL_CORPUS


def test_real_confident_clean_at_default() -> None:
    """Every confident real-figure case classifies correctly at the default 0.5 — no fabrication
    leaked, no faithful summary over-abstained."""
    report = run_grounding_eval(REAL_CONFIDENT)
    assert report.total == len(REAL_CONFIDENT)
    assert report.false_pass == 0, "a fabricated real case leaked past the gate"
    assert report.false_abstain == 0, "a faithful real case was over-abstained"
    assert report.correct == report.total


def test_safe_plateau_includes_default_and_has_upper_edge_at_half() -> None:
    """On confident labels the false_pass=false_abstain=0 plateau spans [0.25, 0.51]; 0.5 is at
    its upper edge and 0.60 already leaks a fabrication (real ViT 3/5 case)."""
    points = {p.threshold: p for p in sweep_numeric_threshold(REAL_CONFIDENT, [0.25, 0.5, 0.6])}
    assert points[0.25].false_pass == 0 and points[0.25].false_abstain == 0
    assert points[0.5].false_pass == 0 and points[0.5].false_abstain == 0
    # Raising past the edge leaks a real majority-fabricated case → cannot go higher than ~0.5.
    assert points[0.6].false_pass >= 1


def test_half_unsupported_probe_passes_at_default() -> None:
    """The pivotal policy probe — exactly half the result figures unsupported (2/4 = 0.50) —
    PASSES at 0.5 (0.50 is not > 0.50). Honoring 'half unsupported = fabricated' is what would
    push strict below 0.5; the label stays the reviewer's call (so we keep 0.5)."""
    (probe,) = (c for c in REAL_CORPUS if c.name == "roberta_probe_2of4")
    (result,) = run_grounding_eval([probe]).results
    assert result.outcome == "pass"
    assert result.classification == "false_pass"  # only under the 'fabricated' policy reading


def test_real_sweep_tradeoff_is_monotone() -> None:
    """Recalibration invariant on the real corpus: rising threshold never increases false_abstain
    nor decreases false_pass."""
    points = sweep_numeric_threshold(REAL_CONFIDENT, [0.0, 0.25, 0.5, 0.75, 1.0])
    false_abstain = [p.false_abstain for p in points]
    false_pass = [p.false_pass for p in points]
    assert false_abstain == sorted(false_abstain, reverse=True)  # non-increasing
    assert false_pass == sorted(false_pass)  # non-decreasing
