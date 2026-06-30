"""Pooled PostgreSQL connections for the RDS read adapters.

The glossary/asset readers sit on the warm summarize path — ``glossary_version`` runs on every
request and ``get_user_glossary`` on every cache miss — so a fresh ``psycopg.connect`` per call
adds avoidable per-request connection latency (Part 1 §2, performance). A process-wide
``psycopg_pool.ConnectionPool`` (one per DSN) reuses connections; the object yielded is an
ordinary psycopg connection, so call sites stay unchanged.

Graceful fallback: when ``psycopg_pool`` is not installed (it ships in the ``real`` extra), this
degrades to a direct ``psycopg.connect`` + close — i.e. exactly the prior behavior — so the path
can never regress to worse-than-before. The pool is created lazily on first use (no import-time
or startup cost) and keyed by DSN.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any

_pools: dict[str, Any] = {}
_lock = Lock()


def _pool_for(dsn: str) -> Any | None:
    """Return the cached pool for ``dsn`` (created once), or None when pooling is unavailable."""
    try:
        from psycopg_pool import ConnectionPool
    except ImportError:
        return None
    with _lock:
        pool = _pools.get(dsn)
        if pool is None:
            # min_size keeps a warm connection ready; max_size caps fan-out under load.
            pool = ConnectionPool(dsn, min_size=1, max_size=8, open=True)
            _pools[dsn] = pool
        return pool


@contextmanager
def connection(dsn: str) -> Iterator[Any]:
    """Yield a psycopg connection from the per-DSN pool (returned on exit), or a freshly-opened
    one that is closed on exit when the pool package is absent (prior behavior, no regression)."""
    pool = _pool_for(dsn)
    if pool is None:
        import psycopg

        conn = psycopg.connect(dsn)
        try:
            yield conn
        finally:
            conn.close()
    else:
        with pool.connection() as conn:
            yield conn
