"""Per-dependency circuit breakers (nfr-design-patterns §1.2 / RES-9 / BR-16).

Covers the breaker state machine, the embedding decorator (open → immediate
``EmbeddingUnavailable`` → the orchestrator's tested lexical-only fallback), and the
OpenSearch adapter integration (open → immediate ``IndexUnavailable`` without a store call).
"""

from __future__ import annotations

import pytest

from discovery.adapters.opensearch_index import OpenSearchLexicalIndexAdapter
from discovery.adapters.resilience import CircuitBreaker, CircuitGuardedEmbedder
from discovery.ports.search_ports import EmbeddingUnavailable, IndexUnavailable


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _breaker(clock: _Clock, threshold: int = 3, open_seconds: float = 30.0) -> CircuitBreaker:
    return CircuitBreaker(
        "test", failure_threshold=threshold, open_seconds=open_seconds, clock=clock
    )


def test_breaker_opens_after_consecutive_failures_and_recovers_via_probe() -> None:
    clock = _Clock()
    breaker = _breaker(clock)
    for _ in range(3):
        assert breaker.allow() is True
        breaker.record_failure()
    assert breaker.allow() is False  # OPEN — fail fast

    clock.now = 31.0
    assert breaker.allow() is True  # half-open probe slot
    assert breaker.allow() is False  # only ONE probe per window
    breaker.record_success()
    assert breaker.allow() is True  # CLOSED again


def test_breaker_failed_probe_reopens_a_fresh_window() -> None:
    clock = _Clock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31.0
    assert breaker.allow() is True  # probe
    breaker.record_failure()  # probe failed → re-open
    clock.now = 60.0  # inside the NEW window (opened at 31.0)
    assert breaker.allow() is False
    clock.now = 62.0
    assert breaker.allow() is True  # next probe


def test_breaker_success_resets_consecutive_count() -> None:
    breaker = _breaker(_Clock())
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow() is True  # never reached 3 consecutive


class _FlakyEmbedder:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def embed_query(self, text: str) -> list[float]:  # noqa: ARG002
        self.calls += 1
        if self.error is not None:
            raise self.error
        return [1.0]


def test_guarded_embedder_fails_fast_when_open_without_calling_adapter() -> None:
    clock = _Clock()
    breaker = _breaker(clock)
    inner = _FlakyEmbedder(error=EmbeddingUnavailable("down"))
    guarded = CircuitGuardedEmbedder(inner, breaker)
    for _ in range(3):
        with pytest.raises(EmbeddingUnavailable):
            guarded.embed_query("q")
    assert inner.calls == 3
    with pytest.raises(EmbeddingUnavailable):
        guarded.embed_query("q")  # circuit open → no adapter call
    assert inner.calls == 3


def test_guarded_embedder_passes_non_transient_errors_through_without_tripping() -> None:
    breaker = _breaker(_Clock(), threshold=1)
    inner = _FlakyEmbedder(error=ValueError("dimension mismatch"))
    guarded = CircuitGuardedEmbedder(inner, breaker)
    with pytest.raises(ValueError, match="dimension mismatch"):
        guarded.embed_query("q")
    # A config error is a RESPONSE, not an outage — the circuit stays closed.
    assert breaker.allow() is True


class _AlwaysFailingClient:
    """Duck-typed opensearch client failing every call with the given store status."""

    def __init__(self, status_code: int | str = "N/A") -> None:
        self.calls = 0
        self.status_code = status_code

    def search(self, *, index, body, request_timeout=None):  # noqa: ARG002
        self.calls += 1
        error = RuntimeError("store failure")
        error.status_code = self.status_code
        raise error


def test_store_breaker_opens_on_outages_and_skips_the_store(monkeypatch) -> None:
    monkeypatch.setattr("discovery.adapters.opensearch_index.time.sleep", lambda _s: None)
    clock = _Clock()
    breaker = _breaker(clock, threshold=2)
    client = _AlwaysFailingClient(status_code="N/A")  # connection error → outage class
    adapter = OpenSearchLexicalIndexAdapter(client, "idx", breaker)
    for _ in range(2):
        with pytest.raises(IndexUnavailable):
            adapter.bm25_search(("q",), 5)
    calls_when_opened = client.calls  # 2 searches × 3 transient attempts
    with pytest.raises(IndexUnavailable, match="circuit open"):
        adapter.bm25_search(("q",), 5)  # OPEN → immediate, no store call
    assert client.calls == calls_when_opened
    clock.now = 31.0
    with pytest.raises(IndexUnavailable):
        adapter.bm25_search(("q",), 5)  # half-open probe reaches the store again
    assert client.calls > calls_when_opened


def test_store_breaker_ignores_non_transient_client_errors() -> None:
    # A 4xx means the store RESPONDED (bad query / misconfig) — per-request fail-closed, but a
    # healthy store must never become a fast-fail 503 wall for every adapter on the breaker.
    breaker = _breaker(_Clock(), threshold=2)
    client = _AlwaysFailingClient(status_code=400)
    adapter = OpenSearchLexicalIndexAdapter(client, "idx", breaker)
    for _ in range(5):
        with pytest.raises(IndexUnavailable):
            adapter.bm25_search(("q",), 5)
    assert breaker.allow() is True  # still CLOSED
    assert client.calls == 5  # every request reached the store (no fast-fail)


def test_breaker_leaked_probe_slot_self_heals() -> None:
    # A probe holder that never reports an outcome (crashed) must not wedge the circuit OPEN
    # forever: the slot expires after one cooldown window and a new probe is admitted.
    clock = _Clock()
    breaker = _breaker(clock)
    for _ in range(3):
        breaker.record_failure()
    clock.now = 31.0
    assert breaker.allow() is True  # probe taken… and its holder dies silently
    clock.now = 40.0
    assert breaker.allow() is False  # slot still live inside the window
    clock.now = 62.0
    assert breaker.allow() is True  # expired slot reclaimed
