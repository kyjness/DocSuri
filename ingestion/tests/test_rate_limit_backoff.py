"""429 backs off far longer than a generic transient failure.

Measured the hard way: a 20-paper run against a source that was already rate-limiting us put
~100 requests through it (5 attempts each on a 1/2/4/8s schedule) and the source stayed shut
afterwards. A 5xx means "the dependency stumbled" and a second or two is right; a 429 means
"you are asking too often", and the fast schedule turns a short block into a long one.

The token bucket cannot prevent this. It paces a steady stream correctly, but a retry storm is
precisely the case where the source has already told us its budget is spent.
"""

from __future__ import annotations

import pytest

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import RetriableIngestionError
from docsuri_ingestion.resilience import (
    _RATE_LIMIT_BACKOFF_MULTIPLIER,
    IngestionResilienceService,
    RetryPolicy,
)


class _Obs:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def emit_metric(self, name, value, tags=None) -> None:
        self.metrics.append((name, value, tags or {}))

    def emit_log(self, entry) -> None:
        pass

    def emit_failure_signal(self, job_id, stage, error) -> None:
        pass


def _service() -> IngestionResilienceService:
    # No jitter so the assertion is on the schedule, not on a random draw.
    return IngestionResilienceService(
        _Obs(),
        retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=1.0, factor=2.0,
                                 jitter_ratio=0.0),
    )


@pytest.mark.parametrize("attempt", [1, 2])
def test_rate_limited_waits_the_multiple_of_a_plain_transient(attempt: int) -> None:
    service = _service()
    throttled = RetriableIngestionError(
        "arXiv returned 429", reason=FailureReason.RATE_LIMITED, stage="fetch_metadata"
    )
    outage = RetriableIngestionError(
        "arXiv returned 503",
        reason=FailureReason.DEPENDENCY_UNAVAILABLE,
        stage="fetch_metadata",
    )
    assert service._retry_delay(attempt, throttled) == pytest.approx(
        service._retry_delay(attempt, outage) * _RATE_LIMIT_BACKOFF_MULTIPLIER
    )


def test_the_rate_limited_schedule_is_minutes_not_seconds() -> None:
    """The point of the multiplier is that a paper's whole attempt chain outlasts a short block."""
    service = _service()
    throttled = RetriableIngestionError(
        "429", reason=FailureReason.RATE_LIMITED, stage="fetch_metadata"
    )
    total = sum(service._retry_delay(a, throttled) for a in (1, 2))
    assert total >= 40.0, f"429 backoff totals only {total:.0f}s — a short block outlasts it"


def test_a_permanent_failure_is_not_retried_at_all() -> None:
    """The multiplier must not turn a non-retriable error into a slow one — it must not be
    reached. A 404 that waited minutes before failing would stall the batch on missing papers."""
    from docsuri_ingestion.domain.errors import PermanentIngestionError

    service = _service()
    calls = []

    def boom():
        calls.append(1)
        raise PermanentIngestionError(
            "arXiv returned 404", reason=FailureReason.FETCH_FAILURE, stage="fetch_metadata"
        )

    with pytest.raises(PermanentIngestionError):
        service.retry("fetch_metadata", boom)
    assert len(calls) == 1
