"""QT-1 held-out numeric corpus (real arXiv result figures) — locks the recalibration decision.

Decision (US-S6, 2026-07-10): recalibrate ``_NUMERIC_MISMATCH_THRESHOLD`` 0.5 → 0.4. These
tests record the real-figure evidence behind it so a future threshold change surfaces here:
  (a) the confident (stable-label) cases have no leak / no over-abstention at the 0.4 default;
  (b) honoring ALL labels (probes included) the zero-error plateau is [0.40, 0.50): the old 0.5
      sat just OUTSIDE it — every exactly-half-ungrounded case (e.g. ``roberta_probe_2of4``)
      leaked as a false-pass — and 0.4 is the plateau's STRICT edge;
  (c) 0.4 cannot be lowered further: the faithful ``resnet_probe_2of5`` case (2/5 = 0.40
      ungrounded, exactly on the boundary) passes only via the strict `>`;
  (d) real fabricated cases at 0.60 ungrounded forbid ever raising it past ~0.5 (and C-2
      forbids raising it at all: recalibrations may only go stricter).
"""

from __future__ import annotations

from summarization.eval.grounding_eval import run_grounding_eval, sweep_numeric_threshold
from summarization.eval.real_corpus import REAL_CONFIDENT, REAL_CORPUS


def test_real_confident_clean_at_default() -> None:
    """Every confident real-figure case classifies correctly at the recalibrated 0.4 default —
    no fabrication leaked, no faithful summary over-abstained."""
    report = run_grounding_eval(REAL_CONFIDENT)
    assert report.total == len(REAL_CONFIDENT)
    assert report.false_pass == 0, "a fabricated real case leaked past the gate"
    assert report.false_abstain == 0, "a faithful real case was over-abstained"
    assert report.correct == report.total


def test_full_real_corpus_clean_at_recalibrated_default() -> None:
    """US-S6: honoring ALL labels (probes included) the recalibrated 0.4 is clean on the real
    corpus — in particular the exactly-half-ungrounded ``roberta_probe_2of4`` no longer leaks."""
    report = run_grounding_eval(REAL_CORPUS)
    assert report.false_pass == 0
    assert report.false_abstain == 0
    assert report.correct == report.total == len(REAL_CORPUS)


def test_plateau_edges_old_default_leaked_new_default_clean() -> None:
    """The recalibration curve on ALL real labels: 0.4 is clean; the old 0.5 leaks the
    half-ungrounded probe (the US-S6 false-pass); 0.35 already over-abstains the faithful
    2/5 boundary case — so [0.40, 0.50) is the plateau and 0.4 its strict edge."""
    points = {
        p.threshold: p for p in sweep_numeric_threshold(REAL_CORPUS, [0.35, 0.4, 0.5, 0.6])
    }
    assert points[0.4].false_pass == 0 and points[0.4].false_abstain == 0
    assert points[0.5].false_pass >= 1  # the pre-recalibration leak (roberta_probe_2of4)
    assert points[0.6].false_pass >= 2  # raising further leaks real majority-fabricated cases
    assert points[0.35].false_abstain >= 1  # lowering further over-abstains resnet_probe_2of5


def test_half_unsupported_probe_now_abstains() -> None:
    """US-S6 regression pin on real figures: the pivotal case — exactly half the result figures
    unsupported (2/4 = 0.50) — was a false-pass at the old 0.5 threshold and is now CAUGHT
    (0.50 > 0.4 → abstain). Must never regress to a pass (C-2)."""
    (probe,) = (c for c in REAL_CORPUS if c.name == "roberta_probe_2of4")
    (result,) = run_grounding_eval([probe]).results
    assert result.outcome == "abstain"
    assert result.classification == "true_abstain"


def test_faithful_boundary_case_still_passes() -> None:
    """The strict-edge witness: ``resnet_probe_2of5`` (2/5 = 0.40 ungrounded, faithful) sits
    exactly ON the recalibrated threshold and still passes (0.40 is not > 0.4). Going any
    stricter than 0.4 requires new corpus evidence that this label is wrong."""
    (case,) = (c for c in REAL_CORPUS if c.name == "resnet_probe_2of5")
    (result,) = run_grounding_eval([case]).results
    assert result.outcome == "pass"
    assert result.classification == "true_pass"


def test_real_sweep_tradeoff_is_monotone() -> None:
    """Recalibration invariant on the real corpus: rising threshold never increases false_abstain
    nor decreases false_pass."""
    points = sweep_numeric_threshold(REAL_CONFIDENT, [0.0, 0.25, 0.5, 0.75, 1.0])
    false_abstain = [p.false_abstain for p in points]
    false_pass = [p.false_pass for p in points]
    assert false_abstain == sorted(false_abstain, reverse=True)  # non-increasing
    assert false_pass == sorted(false_pass)  # non-decreasing
