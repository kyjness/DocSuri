from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docsuri_ops._dedup import BoundedSeen
from docsuri_ops.cost_guard import CostGuardCircuitBreaker
from docsuri_ops.detectors import CostExplosionDetector
from docsuri_ops.domain.enums import CircuitState, DegradeMode, IncidentClass, Severity
from docsuri_ops.domain.models import UsageEvent


def test_cost_guard_warns_at_80_percent() -> None:
    guard = CostGuardCircuitBreaker()

    state = guard.record_spend(UsageEvent(event_id="u1", amount_usd=1280.0, source="bedrock"))

    assert state.threshold_ratio == 0.8
    assert state.degrade_mode == DegradeMode.RERANK_OFF
    assert state.circuit_state == CircuitState.HALF_OPEN
    assert state.tier == "warning"


def test_cost_guard_degrades_before_hard_cap_and_opens_at_cap() -> None:
    guard = CostGuardCircuitBreaker()

    near_cap = guard.record_spend(UsageEvent(event_id="u1", amount_usd=1521.0, source="bedrock"))
    open_state = guard.record_spend(UsageEvent(event_id="u2", amount_usd=79.0, source="bedrock"))

    assert near_cap.degrade_mode == DegradeMode.LEXICAL_ONLY
    assert near_cap.circuit_state == CircuitState.HALF_OPEN
    assert open_state.circuit_state == CircuitState.OPEN
    assert open_state.tier == "hard_cap"


def test_cost_guard_is_idempotent_by_usage_event_id() -> None:
    guard = CostGuardCircuitBreaker()
    event = UsageEvent(event_id="same", amount_usd=10.0, source="embedding")

    guard.record_spend(event)
    state = guard.record_spend(event)

    assert state.spend_usd == 10.0


def test_bounded_seen_dedups_and_evicts_oldest() -> None:
    seen = BoundedSeen(max_size=2)
    seen.add("a")
    seen.add("b")
    assert "a" in seen and "b" in seen
    seen.add("a")  # re-add is a dedup no-op — does not grow or evict
    assert len(seen) == 2
    seen.add("c")  # over cap → oldest ("a") evicted
    assert "a" not in seen
    assert "b" in seen and "c" in seen
    assert len(seen) == 2


def test_cost_explosion_detector_classifies_and_deduplicates() -> None:
    guard = CostGuardCircuitBreaker()
    state = guard.record_spend(UsageEvent(event_id="seed", amount_usd=1300.0, source="bedrock"))
    detector = CostExplosionDetector()
    event = UsageEvent(event_id="usage-1", amount_usd=5.0, source="bedrock", request_id="req-1")

    candidate = detector.evaluate_usage(event, state)
    duplicate = detector.evaluate_usage(event, state)

    assert candidate is not None
    assert candidate.incident_class == IncidentClass.COST_EXPLOSION
    assert candidate.severity == Severity.WARNING
    assert duplicate is None


def test_cost_explosion_detector_flags_rate_limit_spikes() -> None:
    detector = CostExplosionDetector(rate_limit_spike_count=3)

    candidate = detector.evaluate_rate_limit_spike(
        request_id="req-rate", signal_id="rate-1", count=3
    )

    assert candidate is not None
    assert candidate.incident_class == IncidentClass.COST_EXPLOSION
    assert candidate.severity == Severity.WARNING


@given(
    st.lists(
        st.floats(min_value=0.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        max_size=40,
    )
)
def test_cost_guard_spend_is_monotonic(amounts: list[float]) -> None:
    guard = CostGuardCircuitBreaker()
    previous = 0.0

    for index, amount in enumerate(amounts):
        state = guard.record_spend(
            UsageEvent(event_id=f"u-{index}", amount_usd=amount, source="property")
        )
        assert state.spend_usd + 0.000001 >= previous
        previous = state.spend_usd

    assert guard.get_budget_state().spend_usd == pytest.approx(sum(amounts), abs=0.000001)


def test_is_cost_degraded_predicate_matches_guard_tiers() -> None:
    from docsuri_ops.cost_guard import is_cost_critical, is_cost_degraded

    guard = CostGuardCircuitBreaker()
    assert is_cost_degraded(guard.get_budget_state()) is False
    assert is_cost_critical(guard.get_budget_state()) is False

    guard.record_spend(UsageEvent(event_id="u1", amount_usd=1280.0, source="bedrock"))
    # warning(80%) → U7-style soft degradation, but agent hard-gate stays open.
    assert is_cost_degraded(guard.get_budget_state()) is True
    assert is_cost_critical(guard.get_budget_state()) is False

    guard.record_spend(UsageEvent(event_id="u2", amount_usd=240.0, source="bedrock"))
    assert guard.get_budget_state().tier == "critical"
    assert is_cost_critical(guard.get_budget_state()) is True


def test_estimate_bedrock_usd_default_rates_and_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from docsuri_ops.cost_guard import estimate_bedrock_usd

    # 기본 단가: $3/1M input + $15/1M output (Bedrock Claude Sonnet 4.x)
    assert estimate_bedrock_usd(input_tokens=1_000_000, output_tokens=0) == pytest.approx(3.0)
    assert estimate_bedrock_usd(input_tokens=0, output_tokens=1_000_000) == pytest.approx(15.0)
    assert estimate_bedrock_usd(input_tokens=-5, output_tokens=0) == 0.0

    monkeypatch.setenv("DOCSURI_BEDROCK_USD_PER_1M_INPUT", "6.0")
    monkeypatch.setenv("DOCSURI_BEDROCK_USD_PER_1M_OUTPUT", "30.0")
    assert estimate_bedrock_usd(input_tokens=500_000, output_tokens=100_000) == pytest.approx(6.0)
