"""Per-dependency circuit breakers (nfr-design-patterns §1.2 / RES-9 / BR-16).

Timeouts bound ONE slow call; a breaker bounds a SUSTAINED outage. Without it every request
during a Bedrock/OpenSearch outage pays the full timeout(+retry) budget before hitting the
tested fallback — ~7s per request for embedding, ~15s for the store — multiples of the P50<3s
target. Each dependency gets its OWN breaker (embedding failure ≠ store failure: one degrades
to lexical-only, the other fail-closes), matching the design's per-dependency isolation.

The breaker state machine itself is the SHARED implementation
(:mod:`docsuri_shared.resilience` — permit-based: single HALF-OPEN probe, stale-success
ignore, probe-slot expiry; its contract tests live in ``shared/python/tests``). This module
keeps the discovery-specific policy: which errors count as outages vs responses, and the
unavailable-exception each guarded dependency raises. In-process state is deliberate: NFR-S1
(~50 concurrent) allows instance-local circuit state (nfr-design §3.1); a shared store is an
Infra upgrade, not a contract change. Thresholds are the shared defaults; tuning numbers are
Infra's call (DS-1).
"""

from __future__ import annotations

from docsuri_shared.resilience import CircuitBreaker

from ..ports.search_ports import EmbeddingAdapter, EmbeddingUnavailable

__all__ = ["CircuitBreaker", "CircuitGuardedEmbedder"]


class CircuitGuardedEmbedder:
    """EmbeddingAdapter decorator: OPEN circuit → immediate ``EmbeddingUnavailable`` (the
    orchestrator's tested lexical-only fallback) instead of a doomed ~7s Bedrock wait.

    Sits UNDER the ``EmbeddingCache`` (cache → circuit → real adapter): cache hits neither
    consult nor count toward the circuit — only real dependency calls do."""

    def __init__(self, adapter: EmbeddingAdapter, breaker: CircuitBreaker) -> None:
        self._adapter = adapter
        self._breaker = breaker

    def embed_query(self, text: str) -> list[float]:
        # guard(): exiting the block without success() counts as failure — the
        # EmbeddingUnavailable path needs no explicit report.
        with self._breaker.guard() as permit:
            if permit is None:
                raise EmbeddingUnavailable(
                    f"{self._breaker.name} circuit open — degrading fast"
                )
            try:
                vector = self._adapter.embed_query(text)
            except EmbeddingUnavailable:
                raise
            except Exception:
                # A non-transient error (e.g. the loud dimension-mismatch config error) is not an
                # outage, so it must not count as failure — but it is not proof of health either,
                # since the same catch covers unparseable responses from a degraded provider.
                # Complete NEUTRAL: the half-open probe slot is freed and the outage count is
                # preserved. Marking it success would reset that count, so a provider failing in
                # a mixed way could never trip the circuit at all.
                permit.neutral()
                raise
            permit.success()
            return vector
