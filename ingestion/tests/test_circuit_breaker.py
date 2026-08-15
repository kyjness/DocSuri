"""Dependency circuit behaviour for the ingestion worker.

The unit dropped its own breaker for ``docsuri_shared.resilience.CircuitBreaker`` — the last
per-unit copy. That copy had no test at all, and the shared one recovers more strictly (a single
half-open probe instead of reopening the gate to everyone), so the policy the worker depends on
is pinned here: outages trip the circuit, permanent errors never do, and a tripped dependency
fails fast instead of stalling the worker.
"""

from __future__ import annotations

import pytest
from docsuri_shared.resilience import CircuitBreaker

from docsuri_ingestion.adapters.local import CapturingObservabilityHub
from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.resilience import (
    CircuitOpenError,
    IngestionResilienceService,
    RetryPolicy,
    is_retriable,
)

_THRESHOLD = 5
_RECOVERY_SECONDS = 60.0


class _FakeClock:
    """Monotonic clock under test control — the breaker takes seconds, not datetimes."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _service_with_clock(clock: _FakeClock) -> IngestionResilienceService:
    # One attempt per call so the retry ladder does not fold several breaker calls into one
    # dependency_call; the retry/breaker interaction is asserted separately below.
    service = IngestionResilienceService(
        CapturingObservabilityHub(), retry_policy=RetryPolicy(max_attempts=1), timeout_seconds=5.0
    )
    service._circuits["arxiv"] = CircuitBreaker(  # noqa: SLF001 - seed a controllable clock
        "arxiv", failure_threshold=_THRESHOLD, recovery_seconds=_RECOVERY_SECONDS, clock=clock
    )
    return service


def _outage() -> None:
    raise RetriableIngestionError(
        "arXiv unavailable", reason=FailureReason.DEPENDENCY_UNAVAILABLE, stage="fetch"
    )


def _not_found() -> None:
    raise PermanentIngestionError(
        "arXiv resource not found", reason=FailureReason.FETCH_FAILURE, stage="fetch"
    )


def test_repeated_outages_trip_the_circuit_and_then_fail_fast() -> None:
    clock = _FakeClock()
    service = _service_with_clock(clock)

    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    # Tripped: the dependency is no longer called at all.
    calls = 0

    def _should_not_run() -> str:
        nonlocal calls
        calls += 1
        return "unreachable"

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", _should_not_run)
    assert calls == 0, "a tripped circuit still reached the dependency"


def test_permanent_errors_never_trip_a_healthy_dependency() -> None:
    # A run of withdrawn or missing papers is not an outage. If 404s tripped the circuit, one bad
    # stretch of the corpus would stall ingestion of the good papers behind it.
    clock = _FakeClock()
    service = _service_with_clock(clock)

    for _ in range(_THRESHOLD * 3):
        with pytest.raises(PermanentIngestionError):
            service.dependency_call("arxiv", "fetch", _not_found)

    assert service.dependency_call("arxiv", "fetch", lambda: "healthy") == "healthy"


def test_recovery_admits_one_probe_and_closes_on_success() -> None:
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    # Still inside the recovery window — everyone fails fast.
    clock.advance(_RECOVERY_SECONDS - 1)
    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", lambda: "probe")

    # Past it, one call is admitted and its success closes the circuit.
    clock.advance(2)
    assert service.dependency_call("arxiv", "fetch", lambda: "probe") == "probe"
    assert service.dependency_call("arxiv", "fetch", lambda: "again") == "again"


def test_a_failed_probe_reopens_the_circuit_rather_than_letting_traffic_back_in() -> None:
    # This is the behaviour the replaced per-unit breaker lacked: it reopened the gate to every
    # caller once the window elapsed, so a still-down dependency got a full traffic burst.
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    clock.advance(_RECOVERY_SECONDS + 1)
    with pytest.raises(RetriableIngestionError):
        service.dependency_call("arxiv", "fetch", _outage)  # the probe fails

    calls = 0

    def _count() -> str:
        nonlocal calls
        calls += 1
        return "unreachable"

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", _count)
    assert calls == 0, "a failed probe let traffic back through"


def test_circuits_are_isolated_per_dependency() -> None:
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    # A tripped arXiv must not fail embedding or indexing calls.
    assert service.dependency_call("bedrock", "embed", lambda: "vector") == "vector"


def test_one_dependency_call_can_trip_the_circuit_through_its_own_retries() -> None:
    # dependency_call retries inside the breaker, so each attempt is its own breaker call. With
    # the default policy a persistently failing dependency trips within a single call — that is
    # intended (the retries ARE the consecutive failures), and worth pinning so a policy change
    # does not silently alter how fast the worker gives up on an outage.
    clock = _FakeClock()
    service = IngestionResilienceService(
        CapturingObservabilityHub(),
        retry_policy=RetryPolicy(max_attempts=_THRESHOLD, base_delay_seconds=0.0, jitter_ratio=0.0),
        timeout_seconds=5.0,
    )
    service._circuits["arxiv"] = CircuitBreaker(  # noqa: SLF001
        "arxiv", failure_threshold=_THRESHOLD, recovery_seconds=_RECOVERY_SECONDS, clock=clock
    )

    with pytest.raises(RetriableIngestionError):
        service.dependency_call("arxiv", "fetch", _outage)

    calls = 0

    def _count() -> str:
        nonlocal calls
        calls += 1
        return "unreachable"

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", _count)
    assert calls == 0


def test_only_one_probe_reaches_a_recovering_dependency() -> None:
    """The guarantee the replaced breaker did not have.

    The old per-unit breaker let every caller through the moment the recovery window elapsed, so
    a still-down dependency took the full worker burst at once. Sequential calls cannot tell the
    two apart — the probe completes before the next call — so hold a probe permit open and check
    that traffic arriving alongside it is rejected.
    """
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    clock.advance(_RECOVERY_SECONDS + 1)
    circuit = service._circuits["arxiv"]  # noqa: SLF001

    probe = circuit.acquire()  # the one caller admitted into HALF-OPEN
    assert probe is not None

    calls = 0

    def _count() -> str:
        nonlocal calls
        calls += 1
        return "unreachable"

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", _count)
    assert calls == 0, "a second caller reached the dependency while a probe was in flight"

    # The probe reports success, and only then does normal traffic resume.
    probe.success()
    assert service.dependency_call("arxiv", "fetch", lambda: "recovered") == "recovered"


def test_a_probe_that_never_completes_cannot_wedge_the_circuit_shut() -> None:
    # A worker killed mid-probe must not leave the dependency permanently unreachable: the slot
    # expires after one recovery window and a fresh probe is admitted.
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    clock.advance(_RECOVERY_SECONDS + 1)
    abandoned = service._circuits["arxiv"].acquire()  # noqa: SLF001 - never completed
    assert abandoned is not None

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", lambda: "blocked")

    clock.advance(_RECOVERY_SECONDS + 1)
    assert service.dependency_call("arxiv", "fetch", lambda: "reclaimed") == "reclaimed"


# ---------------------------------------------------------------------------------------
# botocore error classification — the Bedrock/S3 adapters raise these RAW.
# ---------------------------------------------------------------------------------------


class _FakeClientError(Exception):
    """Shaped like botocore's ClientError, which ``is_retriable`` duck-types rather than imports."""

    def __init__(self, code: str = "", status: int | None = None) -> None:
        super().__init__(code or str(status))
        error: dict = {"Code": code} if code else {}
        metadata: dict = {"HTTPStatusCode": status} if status is not None else {}
        self.response = {"Error": error, "ResponseMetadata": metadata}


def test_bedrock_throttling_is_retriable() -> None:
    """``BedrockCohereEmbeddingPort._embed_batch`` wraps ``invoke_model`` in no try/except, so a
    throttled embed reaches the resilience layer as a raw botocore error.

    Classification therefore happens here and nowhere else. Getting it wrong is not hypothetical:
    an embedding adapter here had exactly this bug — its 429 classified as permanent, so a
    rate-limited re-index gave up instead of backing off.
    """
    for code in (
        "ThrottlingException",
        "Throttling",
        "TooManyRequestsException",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "SlowDown",
        "ServiceUnavailable",
        "ModelTimeoutException",
        "ModelNotReadyException",
    ):
        assert is_retriable(_FakeClientError(code)), f"{code} must back off, not fail the paper"


def test_botocore_5xx_is_retriable_even_with_an_unknown_code() -> None:
    # AWS adds error codes over time; a 5xx is transient regardless of what it is called.
    assert is_retriable(_FakeClientError("SomeFutureOverloadError", status=503))
    assert is_retriable(_FakeClientError(status=500))


def test_client_side_botocore_errors_are_not_retriable() -> None:
    # Retrying these burns the retry budget and delays the DLQ without any chance of succeeding.
    for code, status in (
        ("ValidationException", 400),
        ("AccessDeniedException", 403),
        ("ResourceNotFoundException", 404),
    ):
        assert not is_retriable(_FakeClientError(code, status=status)), f"{code} must not retry"


def test_a_plain_exception_is_not_retriable() -> None:
    # The duck-type check must not treat an unrelated exception as an AWS response.
    assert not is_retriable(RuntimeError("boom"))

    class _OddResponse(Exception):
        response = "not-a-dict"

    assert not is_retriable(_OddResponse())


def test_permanent_errors_do_not_reset_an_accumulating_outage_count() -> None:
    """A permanent error is circuit-NEUTRAL, not circuit-success.

    Treating it as success resets the consecutive-failure counter, so a dependency that fails in a
    mixed way — GROBID down behind a proxy serving HTML error pages, which time out sometimes and
    fail TEI parse other times — never accumulates the threshold and the breaker never opens. The
    worker then keeps paying the full timeout against a dead dependency with no fast-fail.
    """
    clock = _FakeClock()
    service = _service_with_clock(clock)

    for _ in range(_THRESHOLD - 1):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    # Interleave one permanent error. It must neither trip the circuit nor forgive the outages.
    with pytest.raises(PermanentIngestionError):
        service.dependency_call("arxiv", "fetch", _not_found)

    with pytest.raises(RetriableIngestionError):
        service.dependency_call("arxiv", "fetch", _outage)  # the THRESHOLD-th outage

    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", lambda: "unreachable")


def test_a_probe_ending_in_a_permanent_error_leaves_the_circuit_shut() -> None:
    """An inconclusive probe must not decide recovery for the next caller.

    Closing on it re-admits full traffic to a dependency that never proved it was back; opening on
    it would burn the whole recovery window on an outcome that was not the dependency's fault.
    Neither — the slot is released and the next caller probes for real.
    """
    clock = _FakeClock()
    service = _service_with_clock(clock)
    for _ in range(_THRESHOLD):
        with pytest.raises(RetriableIngestionError):
            service.dependency_call("arxiv", "fetch", _outage)

    clock.advance(_RECOVERY_SECONDS + 1)
    with pytest.raises(PermanentIngestionError):
        service.dependency_call("arxiv", "fetch", _not_found)  # probe: inconclusive

    # Still HALF-OPEN, so the next caller is the real probe and its single failure re-opens
    # immediately. Had the inconclusive probe closed the circuit, this outage would merely be
    # failure #1 of THRESHOLD and traffic would keep flowing to a dependency that never recovered.
    with pytest.raises(RetriableIngestionError):
        service.dependency_call("arxiv", "fetch", _outage)
    with pytest.raises(CircuitOpenError):
        service.dependency_call("arxiv", "fetch", lambda: "unreachable")

    # And a probe that genuinely succeeds still closes it.
    clock.advance(_RECOVERY_SECONDS + 1)
    assert service.dependency_call("arxiv", "fetch", lambda: "probe") == "probe"
    assert service.dependency_call("arxiv", "fetch", lambda: "again") == "again"
