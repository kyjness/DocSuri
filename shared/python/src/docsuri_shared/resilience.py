"""Shared circuit breaker — the cross-Unit resilience primitive.

Replaces the four per-Unit copies (U2 ``adapters/resilience.py``, U7
``bedrock_llm.LocalCircuitBreaker``, U11 ``extractor._LocalCircuitBreaker``,
U12 ``external/base.SourceBreaker``) with ONE state machine. Unit-specific
policy (retry counts, which errors count as outages, the exception raised on
rejection) stays in the Unit adapters; only the breaker state lives here.

State machine: CLOSED → (``failure_threshold`` consecutive failures) → OPEN →
(``recovery_seconds``) → HALF-OPEN admitting exactly ONE probe → CLOSED on
probe success / OPEN again on probe failure. Guarantees carried over from the
strictest per-Unit variants:

- **Single probe** (U7): concurrent callers arriving during HALF-OPEN are
  rejected; only the probe reaches the (possibly still-down) dependency.
- **Stale success ignored** (U7): a slow call admitted before the trip cannot
  close the circuit under the probe's feet when it returns late.
- **Probe-slot expiry** (U2): a probe holder that never completes its permit
  (crashed mid-call) cannot wedge the circuit OPEN forever — the slot expires
  after one recovery window and a fresh probe is admitted; the dead probe's
  late completion is then ignored (generation token).
- Thread-safe; ``clock`` injectable for tests.

Callers ``acquire()`` a permit (``None`` = rejected → fail fast with the
Unit's own unavailable-exception) and complete it with ``success()`` /
``failure()``. Completion is one-shot and ``failure()`` is idempotent, so
``finally: permit.failure()`` is a safe catch-all release.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

__all__ = ["CircuitBreaker", "CircuitPermit"]

DEFAULT_FAILURE_THRESHOLD = 5
DEFAULT_RECOVERY_SECONDS = 30.0


class CircuitPermit:
    """One-shot completion handle from :meth:`CircuitBreaker.acquire`."""

    __slots__ = ("_breaker", "_done", "_is_probe", "_probe_token")

    def __init__(self, breaker: CircuitBreaker, *, is_probe: bool, probe_token: int = 0) -> None:
        self._breaker = breaker
        self._is_probe = is_probe
        self._probe_token = probe_token
        self._done = False

    def success(self) -> None:
        self._resolve(success=True)

    def failure(self) -> None:
        self._resolve(success=False)

    def _resolve(self, *, success: bool) -> None:
        if self._done:
            return
        self._done = True
        self._breaker._complete(
            is_probe=self._is_probe, success=success, probe_token=self._probe_token
        )


class CircuitBreaker:
    def __init__(
        self,
        name: str = "",
        *,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_seconds: float = DEFAULT_RECOVERY_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self._failure_threshold = failure_threshold
        self._recovery_seconds = recovery_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state = "CLOSED"  # CLOSED | OPEN | HALF-OPEN
        self._failure_count = 0
        self._last_state_change = clock()
        self._probe_in_flight = False
        self._probe_started = 0.0
        self._probe_token = 0

    @contextmanager
    def guard(self) -> Iterator[CircuitPermit | None]:
        """:meth:`acquire`의 컨텍스트 매니저 형태 — permit 완주 계약을 구조로 보장.

        진입 시 permit(거부면 ``None``)을 내주고, 블록 이탈 시 완료되지 않은
        permit을 실패로 마감한다(``failure()`` 멱등 — 성공 완료 후엔 no-op).
        ``finally: permit.failure()``를 소비처마다 손으로 지킬 필요가 없어져
        HALF-OPEN 프로브 슬롯 누수를 놓칠 수 없다. 거부 시 어떤 예외를 던질지,
        어떤 결과를 성공으로 볼지는 호출자 정책으로 남는다(성공은 블록 안에서
        ``permit.success()``로 선언).
        """
        permit = self.acquire()
        try:
            yield permit
        finally:
            if permit is not None:
                permit.failure()

    def acquire(self) -> CircuitPermit | None:
        with self._lock:
            now = self._clock()
            self._check_recovery(now)
            if self._state == "OPEN":
                return None
            if self._state == "HALF-OPEN":
                if (
                    self._probe_in_flight
                    and now - self._probe_started < self._recovery_seconds
                ):
                    return None  # live probe in flight — everyone else fails fast
                # New probe, or an expired (leaked) slot reclaimed.
                self._probe_in_flight = True
                self._probe_started = now
                self._probe_token += 1
                return CircuitPermit(self, is_probe=True, probe_token=self._probe_token)
            return CircuitPermit(self, is_probe=False)

    def _complete(self, *, is_probe: bool, success: bool, probe_token: int) -> None:
        with self._lock:
            now = self._clock()
            if is_probe:
                if probe_token != self._probe_token:
                    return  # late completion of an expired/reclaimed probe — ignore
                self._probe_in_flight = False
                if success:
                    self._state = "CLOSED"
                    self._failure_count = 0
                else:
                    self._state = "OPEN"
                self._last_state_change = now
            elif success:
                if self._state == "CLOSED":
                    self._failure_count = 0
                # Stale success while OPEN/HALF-OPEN: ignored — only the probe recovers.
            else:
                self._failure_count += 1
                if self._state == "CLOSED" and self._failure_count >= self._failure_threshold:
                    self._state = "OPEN"
                    self._last_state_change = now

    def _check_recovery(self, now: float) -> None:
        if self._state == "OPEN" and now - self._last_state_change > self._recovery_seconds:
            self._state = "HALF-OPEN"
            self._probe_in_flight = False
            self._last_state_change = now
