"""Per-dependency circuit breakers (nfr-design-patterns §1.2 / RES-9 / BR-16).

The breaker state machine is the SHARED implementation and its contract
(consecutive-failure trip, single HALF-OPEN probe, stale-success ignore,
probe-slot expiry) is verified by ``shared/python/tests/test_resilience.py``.
This file keeps the discovery-specific integration: the embedding decorator
(open → immediate ``EmbeddingUnavailable`` → the orchestrator's tested
lexical-only fallback) and the OpenSearch adapter (open → immediate
``IndexUnavailable`` without a store call; only outage-class errors trip).
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


def _breaker(clock: _Clock, threshold: int = 3, recovery_seconds: float = 30.0) -> CircuitBreaker:
    return CircuitBreaker(
        "test", failure_threshold=threshold, recovery_seconds=recovery_seconds, clock=clock
    )


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
    clock.now = 31.0
    with pytest.raises(EmbeddingUnavailable):
        guarded.embed_query("q")  # half-open probe reaches the adapter again
    assert inner.calls == 4


def test_guarded_embedder_passes_non_transient_errors_through_without_tripping() -> None:
    breaker = _breaker(_Clock(), threshold=1)
    inner = _FlakyEmbedder(error=ValueError("dimension mismatch"))
    guarded = CircuitGuardedEmbedder(inner, breaker)
    with pytest.raises(ValueError, match="dimension mismatch"):
        guarded.embed_query("q")
    # A config error is a RESPONSE, not an outage — the circuit stays closed.
    assert breaker.acquire() is not None


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
    assert breaker.acquire() is not None  # still CLOSED
    assert client.calls == 5  # every request reached the store (no fast-fail)


class _MixedFailureClient:
    """Alternates outage-class and client-class failures, as a degraded store really does."""

    def __init__(self) -> None:
        self.calls = 0
        self.searches = 0

    def search(self, *, index, body, request_timeout=None):  # noqa: ARG002
        self.calls += 1
        error = RuntimeError("store failure")
        # Odd searches look like an outage, even ones like a client error.
        error.status_code = "N/A" if self.searches % 2 == 0 else 400
        raise error


def test_non_transient_errors_do_not_forgive_accumulated_outages(monkeypatch) -> None:
    """A client-class error is circuit-NEUTRAL, not circuit-success.

    Counting it as success clears the consecutive-outage count, so a store degraded into a MIX of
    connection failures and malformed responses never reaches the threshold. The breaker then
    never opens and every read pays the full retry ladder against a store that is effectively
    down — the latency wall the breaker exists to prevent on a read path.
    """
    monkeypatch.setattr("discovery.adapters.opensearch_index.time.sleep", lambda _s: None)
    breaker = _breaker(_Clock(), threshold=2)
    client = _MixedFailureClient()
    adapter = OpenSearchLexicalIndexAdapter(client, "idx", breaker)

    for _ in range(3):  # outage, client error, outage
        with pytest.raises(IndexUnavailable):
            adapter.bm25_search(("q",), 5)
        client.searches += 1

    with pytest.raises(IndexUnavailable, match="circuit open"):
        adapter.bm25_search(("q",), 5)


def test_a_config_error_does_not_forgive_accumulated_embedding_outages() -> None:
    """Same rule on the embedding path: the config error must not reset the outage count."""
    breaker = _breaker(_Clock(), threshold=2)
    # EmbeddingUnavailable is the decorator's outage signal: it re-raises without completing the
    # permit, so guard()'s finally records the failure. Anything else is the non-outage branch.
    down = _FlakyEmbedder(error=EmbeddingUnavailable("provider down"))
    outage = CircuitGuardedEmbedder(down, breaker)
    config = CircuitGuardedEmbedder(_FlakyEmbedder(error=ValueError("dimension mismatch")), breaker)

    with pytest.raises(EmbeddingUnavailable):
        outage.embed_query("q")
    with pytest.raises(ValueError):
        config.embed_query("q")  # neutral — neither trips nor forgives
    with pytest.raises(EmbeddingUnavailable):
        outage.embed_query("q")  # the second outage reaches the threshold

    assert breaker.acquire() is None, "the config error wiped the outage count"
