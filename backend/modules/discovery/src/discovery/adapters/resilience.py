"""Per-dependency circuit breakers (nfr-design-patterns §1.2 / RES-9 / BR-16).

Timeouts bound ONE slow call; a breaker bounds a SUSTAINED outage. Without it every request
during a Bedrock/OpenSearch outage pays the full timeout(+retry) budget before hitting the
tested fallback — ~7s per request for embedding, ~15s for the store — multiples of the P50<3s
target. Each dependency gets its OWN breaker (embedding failure ≠ store failure: one degrades
to lexical-only, the other fail-closes), matching the design's per-dependency isolation.

In-process state is deliberate: NFR-S1 (~50 concurrent) allows instance-local circuit state
(nfr-design §3.1); a shared store is an Infra upgrade, not a contract change. Thread-safe —
the sync FastAPI route runs on a threadpool. Thresholds are conservative constants below;
tuning numbers are Infra's call (DS-1).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..ports.search_ports import EmbeddingAdapter, EmbeddingUnavailable

# Consecutive failures before the circuit OPENs. High enough that the store adapter's own
# transient retry (3 attempts inside ONE call = one failure here) doesn't trip it on a blip.
FAILURE_THRESHOLD = 5
# Seconds the circuit stays OPEN before allowing one half-open probe call through.
OPEN_SECONDS = 30.0


class CircuitBreaker:
    """Minimal consecutive-failure breaker: CLOSED → (N failures) → OPEN → (cooldown) →
    HALF-OPEN (one probe) → CLOSED on success / OPEN again on failure.

    Callers ask :meth:`allow` before the dependency call and report the outcome via
    :meth:`record_success` / :meth:`record_failure`. ``allow() is False`` means fail
    IMMEDIATELY with the dependency's own unavailable-exception — the caller keeps its
    existing fallback semantics (lexical-only vs fail-closed), the breaker only skips the
    doomed wait."""

    def __init__(
        self,
        name: str,
        *,
        failure_threshold: int = FAILURE_THRESHOLD,
        open_seconds: float = OPEN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._threshold = failure_threshold
        self._open_seconds = open_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_started: float | None = None

    def allow(self) -> bool:
        """Whether the next dependency call may proceed. In OPEN, one probe per cooldown
        window is let through (half-open); everyone else is rejected fast. A probe slot whose
        holder never reported an outcome (crashed between allow() and record_*) expires after
        one cooldown window, so a leaked slot cannot wedge the circuit OPEN forever."""
        with self._lock:
            now = self._clock()
            if self._opened_at is None:
                return True
            if now - self._opened_at < self._open_seconds:
                return False
            if (
                self._probe_started is not None
                and now - self._probe_started < self._open_seconds
            ):
                return False  # another thread holds a live half-open probe slot
            self._probe_started = now
            return True

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_started = None

    def record_failure(self) -> None:
        with self._lock:
            if self._probe_started is not None:
                # Failed half-open probe → re-open a fresh cooldown window.
                self._probe_started = None
                self._opened_at = self._clock()
                return
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._threshold and self._opened_at is None:
                self._opened_at = self._clock()


class CircuitGuardedEmbedder:
    """EmbeddingAdapter decorator: OPEN circuit → immediate ``EmbeddingUnavailable`` (the
    orchestrator's tested lexical-only fallback) instead of a doomed ~7s Bedrock/OpenAI wait.

    Sits UNDER the ``EmbeddingCache`` (cache → circuit → real adapter): cache hits neither
    consult nor count toward the circuit — only real dependency calls do."""

    def __init__(self, adapter: EmbeddingAdapter, breaker: CircuitBreaker) -> None:
        self._adapter = adapter
        self._breaker = breaker

    def embed_query(self, text: str) -> list[float]:
        if not self._breaker.allow():
            raise EmbeddingUnavailable(f"{self._breaker.name} circuit open — degrading fast")
        try:
            vector = self._adapter.embed_query(text)
        except EmbeddingUnavailable:
            self._breaker.record_failure()
            raise
        except Exception:
            # A non-transient error (e.g. the loud dimension-mismatch config error) means the
            # dependency RESPONDED — count it as circuit-success (frees a half-open probe slot)
            # and re-raise: the circuit is for outages, not for masking config bugs.
            self._breaker.record_success()
            raise
        self._breaker.record_success()
        return vector
