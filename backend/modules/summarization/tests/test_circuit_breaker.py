"""LocalCircuitBreaker — Bedrock/OpenAI 격리 (RES-9 / nfr-design §1.1).

HALF-OPEN은 정확히 한 개의 프로브만 허용해야 한다: 워커/코루틴 여럿이 브레이커 하나를
공유하므로, 게이트 없이는 복구 확인 전의 의존성으로 동시 호출이 한꺼번에 몰린다.
"""

from __future__ import annotations

from summarization.adapters.bedrock_llm import LocalCircuitBreaker


def _tripped_breaker() -> LocalCircuitBreaker:
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=0.0)
    assert cb.allow_request()
    cb.record_failure()  # threshold 1 → OPEN
    return cb


def test_half_open_admits_single_probe() -> None:
    cb = _tripped_breaker()
    # recovery_timeout=0 → the next allow_request transitions OPEN → HALF-OPEN.
    assert cb.allow_request() is True  # the one probe
    assert cb.allow_request() is False  # concurrent caller during the probe → rejected
    assert cb.allow_request() is False


def test_probe_success_closes_and_readmits() -> None:
    cb = _tripped_breaker()
    assert cb.allow_request() is True
    cb.record_success()
    assert cb.allow_request() is True  # CLOSED again — traffic flows
    assert cb.allow_request() is True


def test_probe_failure_reopens() -> None:
    cb = LocalCircuitBreaker(failure_threshold=1, recovery_timeout=60.0)
    assert cb.allow_request()
    cb.record_failure()
    # Force the OPEN→HALF-OPEN transition without sleeping.
    cb._last_state_change -= 120.0
    assert cb.allow_request() is True  # probe admitted
    cb.record_failure()  # probe failed → OPEN again
    assert cb.allow_request() is False
