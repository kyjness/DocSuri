from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Any, TypeVar

from docsuri_shared.events import IngestError, IngestionFailureSignal
from docsuri_shared.resilience import CircuitBreaker

from .domain.enums import FailureClass, FailureReason
from .domain.errors import IngestionError, RetriableIngestionError
from .ports import ObservabilityPort, QueuePort

T = TypeVar("T")

# botocore error codes for transient AWS conditions (Bedrock/OpenSearch throttling + overload)
# that must back off + retry, not go straight to the DLQ.
_BOTOCORE_RETRIABLE_CODES = frozenset(
    {
        "ThrottlingException",
        "Throttling",
        "TooManyRequestsException",
        "ProvisionedThroughputExceededException",
        "RequestLimitExceeded",
        "SlowDown",
        "ServiceUnavailable",
        "ModelTimeoutException",
        "ModelNotReadyException",
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    factor: float = 2.0
    jitter_ratio: float = 0.2

    def delay_for_attempt(self, attempt_index: int) -> float:
        base = self.base_delay_seconds * (self.factor ** max(0, attempt_index - 1))
        jitter = base * self.jitter_ratio * random.random()
        return base + jitter


class TimeoutRunner:
    def __init__(self, timeout_seconds: float) -> None:
        self._timeout_seconds = timeout_seconds

    def run(self, func: Callable[[], T]) -> T:
        # NOT a `with` block: ThreadPoolExecutor.__exit__ joins the worker thread, which would
        # block past the timeout and defeat the wall-clock cap. shutdown(wait=False) returns
        # immediately; the orphaned thread ends on its own I/O timeout (httpx caps at 30s).
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(func)
        try:
            result = future.result(timeout=self._timeout_seconds)
        except FutureTimeoutError as exc:
            executor.shutdown(wait=False)
            raise RetriableIngestionError(
                "operation timed out",
                reason=FailureReason.TIMEOUT,
                stage="timeout",
            ) from exc
        executor.shutdown(wait=False)
        return result


# Consecutive availability failures that trip a dependency, and how long it stays tripped.
# Carried over from the per-unit breaker this replaced.
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_RECOVERY_SECONDS = 60.0


class CircuitOpenError(RetriableIngestionError):
    def __init__(self, dependency: str) -> None:
        super().__init__(
            f"circuit open for dependency: {dependency}",
            reason=FailureReason.DEPENDENCY_UNAVAILABLE,
            stage=dependency,
        )


class TokenBucket:
    def __init__(self, *, rate_per_second: float, capacity: int = 1) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._rate = rate_per_second
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, amount: float = 1.0) -> None:
        remaining = max(amount, 0.0)
        while remaining > 0.0:
            chunk = min(remaining, self._capacity)
            while True:
                with self._lock:
                    self._refill()
                    if self._tokens >= chunk:
                        self._tokens -= chunk
                        remaining -= chunk
                        break
                    wait_seconds = (chunk - self._tokens) / self._rate
                time.sleep(wait_seconds)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)


class IngestFailureHandler:
    def __init__(self, queue: QueuePort, observability: ObservabilityPort) -> None:
        self._queue = queue
        self._observability = observability

    def emit_failure_signal(self, job_id: str, error: IngestionError) -> IngestionFailureSignal:
        signal = IngestionFailureSignal(
            jobId=job_id,
            error=IngestError(stage=error.stage, error=error.public_error()),
        )
        self._observability.emit_failure_signal(
            job_id,
            stage=signal.error.stage,
            error=signal.error.error,
        )
        return signal

    def send_to_dlq(
        self,
        payload: Mapping[str, Any],
        *,
        reason: str,
        job_id: str | None = None,
    ) -> None:
        self._queue.send_to_dlq(payload, reason=reason)
        tags = {"reason": reason}
        if job_id:
            tags["job_id"] = job_id
        self._observability.emit_metric("ingestion.dlq.enqueued", 1.0, tags)


# How much longer a 429 waits than a generic transient failure. With the default policy
# (1s base, factor 2) this turns 1/2/4/8s into 15/30/60/120s — about four minutes of backing off
# across a paper's attempts instead of fifteen seconds of hammering.
_RATE_LIMIT_BACKOFF_MULTIPLIER = 15.0


class IngestionResilienceService:
    def __init__(
        self,
        observability: ObservabilityPort,
        *,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._observability = observability
        self._retry_policy = retry_policy or RetryPolicy()
        self._timeout_runner = TimeoutRunner(timeout_seconds)
        self._circuits: dict[str, CircuitBreaker] = {}

    def dependency_call(self, dependency: str, stage: str, func: Callable[[], T]) -> T:
        circuit = self._circuits.setdefault(
            dependency,
            CircuitBreaker(
                dependency,
                failure_threshold=_CIRCUIT_FAILURE_THRESHOLD,
                recovery_seconds=_CIRCUIT_RECOVERY_SECONDS,
            ),
        )

        def guarded() -> T:
            # guard(): leaving the block without success() counts as a failure, so an outage
            # needs no explicit report and a half-open probe slot cannot leak.
            with circuit.guard() as permit:
                if permit is None:
                    raise CircuitOpenError(dependency)
                try:
                    result = self._timeout_runner.run(func)
                except Exception as exc:
                    # Only availability failures are a dependency-health signal. A permanent
                    # error (404, a withdrawn paper, a validation violation) must not trip a
                    # healthy dependency — but it is not evidence of health either, since the
                    # same class covers parse failures of a garbage body. Complete NEUTRAL:
                    # marking it success would reset the outage count, so an outage that fails
                    # in a mixed way could never reach the threshold.
                    if not is_retriable(exc):
                        permit.neutral()
                    raise
                permit.success()
                return result

        return self.retry(stage, guarded)

    def _retry_delay(self, attempt: int, exc: Exception) -> float:
        """Backoff for one retry, with 429 held far longer than a plain outage.

        A 5xx means "the dependency stumbled" and coming back in a second or two is right. A 429
        means "you are asking too often", and the fast schedule then makes things worse: measured
        on arXiv, 20 papers x 5 attempts put ~100 requests through a source that was already
        refusing us, and the source stayed shut afterwards. The rate limiter cannot prevent this
        — it paces a steady stream correctly, but a retry storm is the source telling us its
        budget is already spent.

        The multiplier is deliberately large rather than tuned. Waiting too long costs wall-clock
        on a batch that runs unattended; waiting too little costs the whole run, because the
        source extends the block each time it is hit.
        """
        base = self._retry_policy.delay_for_attempt(attempt)
        if isinstance(exc, IngestionError) and exc.reason is FailureReason.RATE_LIMITED:
            return base * _RATE_LIMIT_BACKOFF_MULTIPLIER
        return base

    def retry(self, stage: str, func: Callable[[], T]) -> T:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_policy.max_attempts + 1):
            try:
                result = func()
            except Exception as exc:
                if not is_retriable(exc):
                    raise
                last_error = exc
                self._observability.emit_metric(
                    "ingestion.retry",
                    1.0,
                    {"stage": stage, "attempt": str(attempt)},
                )
                if attempt >= self._retry_policy.max_attempts:
                    break
                time.sleep(self._retry_delay(attempt, exc))
            else:
                if attempt > 1:
                    self._observability.emit_metric(
                        "ingestion.retry.recovered",
                        1.0,
                        {"stage": stage, "attempt": str(attempt)},
                    )
                return result
        if isinstance(last_error, IngestionError):
            raise last_error
        raise RetriableIngestionError(
            f"retry exhausted at stage {stage}",
            reason=FailureReason.DEPENDENCY_UNAVAILABLE,
            stage=stage,
        )


def is_retriable(exc: Exception) -> bool:
    if isinstance(exc, IngestionError):
        return exc.failure_class is FailureClass.RETRIABLE
    if isinstance(exc, ConnectionError | TimeoutError):
        return True
    # Duck-type botocore ClientError (avoid importing botocore here): throttling codes and any
    # 5xx are transient AWS overload — back off + retry instead of failing straight to the DLQ.
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        if response.get("Error", {}).get("Code") in _BOTOCORE_RETRIABLE_CODES:
            return True
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if isinstance(status, int) and status >= 500:
            return True
    return False


def retry_with_policy(
    policy: RetryPolicy,
    func: Callable[[], T],
    *,
    retriable: Callable[[Exception], bool] = is_retriable,
    on_retry: Callable[[int, Exception], None] | None = None,
) -> T:
    """Run ``func``, retrying transient failures on ``policy``'s backoff schedule.

    The final failure propagates unchanged, so the caller keeps the original error taxonomy.
    ``IngestionResilienceService.retry`` is the richer variant for the pipeline path — it also
    emits retry metrics and wraps exhaustion in a stage-tagged RetriableIngestionError.
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            if not retriable(exc) or attempt >= policy.max_attempts:
                raise
            if on_retry is not None:
                on_retry(attempt, exc)
            time.sleep(policy.delay_for_attempt(attempt))
    raise AssertionError("unreachable")  # pragma: no cover
