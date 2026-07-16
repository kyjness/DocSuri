"""EmbeddingCache — read-through query-embedding cache (TD-U2-7; NFR-P1/C1).

Decorates an ``EmbeddingAdapter``: on a hit within TTL it skips the Bedrock call (latency
and cost). A finite TTL is MANDATORY (no never-expiring keys — caching rule). In-memory
here (mock-first); a shared cache for horizontal scaling is an Infra decision (Q5).

Key = the normalized query (BR-2 NFC determinism) — the caller passes ``query.text``.
Embedding failures are NOT cached (``EmbeddingUnavailable`` propagates so the orchestrator
can fall back to lexical-only).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..ports.search_ports import EmbeddingAdapter


class EmbeddingCache:
    """Implements ``EmbeddingAdapter`` (so it can wrap a real/mock adapter transparently)."""

    def __init__(
        self,
        adapter: EmbeddingAdapter,
        *,
        ttl_seconds: float,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0 (no never-expiring cache keys)")
        self._adapter = adapter
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._store: dict[str, tuple[float, list[float]]] = {}
        # The sync search route runs on a threadpool: the evict-then-insert sequence must be
        # atomic, or two threads at cache-full can race next(iter())/pop into a KeyError /
        # "dict changed size during iteration" that surfaces as a search 500. The adapter call
        # stays OUTSIDE the lock — only the cheap dict bookkeeping is serialized.
        self._lock = threading.Lock()

    def embed_query(self, text: str) -> list[float]:
        now = self._clock()
        cached = self._store.get(text)  # atomic dict read — no lock needed
        if cached is not None and (now - cached[0]) < self._ttl:
            return cached[1]
        value = self._adapter.embed_query(text)  # EmbeddingUnavailable propagates (not cached)
        with self._lock:
            self._evict_if_full()
            self._store[text] = (now, value)
        return value

    def _evict_if_full(self) -> None:
        # Simple bound: drop the oldest entry by insertion order (dict preserves it).
        # Caller holds the lock.
        if len(self._store) >= self._max_entries:
            oldest_key = next(iter(self._store))
            self._store.pop(oldest_key, None)
