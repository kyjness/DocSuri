"""SEC-11 / 감사 M1·M6 — per-call-limit fixed-window limiter for the email-sending endpoints.

Covers the in-process fallback used when REDIS_HOST is unset (local/test). Production swaps in
RedisRateLimiter behind the same async ``allow(key, limit, window_seconds)`` interface.
"""

import pytest

from backend.middleware.rate_limit import InProcessWindowLimiter


@pytest.mark.asyncio
async def test_window_limiter_caps_per_key_and_resets():
    clock = [1000.0]
    limiter = InProcessWindowLimiter(clock=lambda: clock[0])
    key = "signup:email:a@b.com"

    # 한도(3)까지 허용, 4번째 차단.
    assert [await limiter.allow(key, limit=3, window_seconds=60) for _ in range(3)] == [True, True, True]
    assert await limiter.allow(key, limit=3, window_seconds=60) is False

    # 다른 키는 독립적으로 카운트된다(이메일 vs IP, 엔드포인트별 분리).
    assert await limiter.allow("signup:ip:1.2.3.4", limit=3, window_seconds=60) is True

    # 창이 지나면 카운터가 리셋된다.
    clock[0] += 61
    assert await limiter.allow(key, limit=3, window_seconds=60) is True
