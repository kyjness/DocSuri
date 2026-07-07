from __future__ import annotations

import logging
import os
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class InMemoryRateLimiter:
    """Process-local sliding-window limiter for local/dev seams.

    Production deployments should use a shared backend such as Redis so limits are enforced
    consistently across workers.

    Per-request cost is O(1): the served key's window is trimmed lazily and over-cap keys are
    evicted in LRU order via ``OrderedDict.popitem`` — no per-request scan of every key (which
    would let a high-cardinality flood degrade admission to O(K)). A full sweep of expired-but-idle
    keys is amortised to roughly once per ``compact_every`` admissions. Under key pressure eviction
    is LRU and may reset a quiescent key's window — a best-effort limit acceptable for this
    in-memory seam (the shared backend is the real fix).
    """

    max_requests: int = 60
    window_seconds: float = 60.0
    max_keys: int = 10000
    compact_every: int = 1024
    clock: Callable[[], float] = time.time
    _events: OrderedDict[str, deque[float]] = field(default_factory=OrderedDict)
    _since_sweep: int = 0

    def allow(self, key: str) -> bool:
        now = self.clock()
        window = self._events.get(key)
        if window is None:
            window = deque()
            self._events[key] = window
        self._events.move_to_end(key)  # mark most-recently-used (LRU recency tracking)
        cutoff = now - self.window_seconds
        while window and window[0] <= cutoff:
            window.popleft()
        allowed = len(window) < self.max_requests
        if allowed:
            window.append(now)
        self._evict_over_cap()
        self._maybe_sweep(now)
        return allowed

    def _evict_over_cap(self) -> None:
        # O(1) LRU eviction bounds the key set under a flood without an O(K) scan. Runs AFTER the
        # current key is inserted/touched, so the cap is exact (not max_keys + 1) and the current
        # key (most-recently-used) is never the one evicted.
        while len(self._events) > self.max_keys:
            self._events.popitem(last=False)

    def _maybe_sweep(self, now: float) -> None:
        # Amortised full sweep: reclaim expired-but-idle keys ~once per `compact_every` admissions
        # rather than on every request (an every-request sweep would be O(K) per admission).
        self._since_sweep += 1
        if self._since_sweep < max(self.compact_every, 1):
            return
        self._since_sweep = 0
        cutoff = now - self.window_seconds
        for key in list(self._events):
            window = self._events[key]
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                del self._events[key]


class InProcessWindowLimiter:
    """Per-call-limit fixed-window limiter (local/dev fallback for the email-sending endpoints).

    Unlike ``InMemoryRateLimiter`` (fixed cap, gateway blanket limiter), each ``allow`` call carries
    its own ``limit``/``window_seconds`` so different endpoints/keys can have different caps. NOT
    shared across workers — production uses ``RedisRateLimiter``.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[int, float]] = {}

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        now = self._clock()
        count, reset = self._buckets.get(key, (0, now + window_seconds))
        if now >= reset:
            count, reset = 0, now + window_seconds
        count += 1
        self._buckets[key] = (count, reset)
        return count <= limit


class RedisRateLimiter:
    """Shared (cross-worker) fixed-window limiter backed by Redis (INCR + EXPIRE).

    Used for the email-sending / account-creating endpoints (password-reset, resend-verification,
    email-change, signup) so per-email/per-IP caps hold across ECS workers (감사 M1/M6 / SEC-11).
    Fail-OPEN on Redis errors: these are non-auth endpoints, so a limiter outage must not take down
    signup/recovery — the gateway per-IP blanket limiter remains a backstop.
    """

    def __init__(
        self, redis_host: str, redis_port: int = 6379, use_tls: bool = False, db: int = 0
    ) -> None:
        import redis.asyncio as aioredis

        pool_kwargs: dict = {
            "host": redis_host,
            "port": redis_port,
            "db": db,
            "socket_timeout": 1.0,
            "socket_connect_timeout": 1.0,
            "max_connections": 20,
            "decode_responses": True,
        }
        if use_tls:
            pool_kwargs["connection_class"] = aioredis.SSLConnection
        self._redis = aioredis.Redis(connection_pool=aioredis.ConnectionPool(**pool_kwargs))

    async def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        full = f"ratelimit:{key}"
        try:
            count = await self._redis.incr(full)
            if count == 1:
                await self._redis.expire(full, window_seconds)
            return count <= limit
        except Exception as e:  # noqa: BLE001 — fail-open for availability (non-auth endpoints)
            logger.warning("RedisRateLimiter unavailable; failing open for key=%s (%s)", key, e)
            return True


@lru_cache(maxsize=1)
def get_shared_limiter():
    """REDIS_HOST 설정 시 워커 간 공유 RedisRateLimiter, 아니면 프로세스 내 폴백(로컬/테스트).

    이메일 레이트리밋(accounts)과 에이전트 쿼터(agent_quota)가 같은 인스턴스를 공유한다.
    """
    host = os.getenv("REDIS_HOST", "").strip()
    if host:
        return RedisRateLimiter(
            redis_host=host,
            redis_port=int(os.getenv("REDIS_PORT") or "6379"),
            use_tls=os.getenv("REDIS_TLS", "").strip().lower() in {"1", "true", "yes", "on"},
        )
    return InProcessWindowLimiter()
