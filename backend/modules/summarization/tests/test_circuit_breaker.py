"""LocalCircuitBreaker — Bedrock/OpenAI isolation (RES-9 / nfr-design §1.1).

HALF-OPEN must admit exactly one probe, and only that probe's outcome may drive the recovery
transition: concurrent workers share one breaker, so without the gate every caller arriving
during HALF-OPEN would hit the (possibly still-down) dependency at once, and a stale success
from a call admitted before the trip could close the circuit under the probe's feet.
"""

from __future__ import annotations

from summarization.adapters.bedrock_llm import LocalCircuitBreaker


def _tripped_breaker() -> LocalCircuitBreaker:
    """OPEN breaker whose recovery window has already elapsed (clock rewound — no sleeping,
    and no reliance on two ``time.time()`` calls returning distinct values)."""
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    permit = cb.acquire()
    assert permit is not None
    permit.failure()  # threshold 1 → OPEN
    cb._last_state_change -= 120.0
    return cb


def test_open_rejects_until_recovery() -> None:
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    permit = cb.acquire()
    assert permit is not None
    permit.failure()
    assert cb.acquire() is None  # OPEN, recovery not elapsed


def test_half_open_admits_single_probe() -> None:
    cb = _tripped_breaker()
    probe = cb.acquire()  # OPEN → HALF-OPEN, admitted as the one probe
    assert probe is not None
    assert cb.acquire() is None  # concurrent caller during the probe → rejected
    assert cb.acquire() is None


def test_probe_success_closes_and_readmits() -> None:
    cb = _tripped_breaker()
    probe = cb.acquire()
    assert probe is not None
    probe.success()
    assert cb.acquire() is not None  # CLOSED again — traffic flows
    assert cb.acquire() is not None


def test_probe_failure_reopens() -> None:
    cb = _tripped_breaker()
    probe = cb.acquire()
    assert probe is not None
    probe.failure()  # probe failed → OPEN again
    assert cb.acquire() is None


def test_stale_success_does_not_close_half_open() -> None:
    # A slow call admitted while CLOSED must not decide recovery when it returns late.
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    stale = cb.acquire()  # admitted while CLOSED
    tripper = cb.acquire()
    assert stale is not None and tripper is not None
    tripper.failure()  # → OPEN
    cb._last_state_change -= 120.0
    probe = cb.acquire()  # the single HALF-OPEN probe
    assert probe is not None
    stale.success()  # pre-trip call returns late
    assert cb.acquire() is None  # circuit must NOT close under the probe
    probe.success()
    assert cb.acquire() is not None  # only the probe's outcome closes it


def test_permit_completion_is_one_shot() -> None:
    # ``finally: permit.failure()`` is the catch-all release — after success() it must be a no-op.
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    permit = cb.acquire()
    assert permit is not None
    permit.success()
    permit.failure()
    assert cb.acquire() is not None  # still CLOSED
