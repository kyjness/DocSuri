"""소스 재시도의 간격 — 요청속도 거절일 때만 기다린다(NFR-NV2-11 계약의 횟수는 그대로 1회).

계약이 "기계 재시도 1회"를 정한 근거는 **outage 정신**이다. 소스가 죽었으면 곧바로 한 번 더
치는 것이 맞다. 그러나 429·`ThrottlingException`은 outage가 아니라 "너무 빨리 쳤다"이고,
간격 없이 다시 치면 같은 창에서 같은 거절을 한 번 더 받는다 — 재시도가 아무 일도 안 한다.

이 실패는 조용하다. 예외가 위로 안 올라가고 `decide`가 `llm_unavailable`로 기권하므로,
화면에는 "답할 근거가 없다"로 나간다. 2층 심판이 두 번 다 정확히 3문항에서 죽은 것이
그 모양이었다(2026-08-25).
"""

from __future__ import annotations

import pytest

from backend.modules.novelty.adapters.external.base import (
    SourceBreaker,
    SourceUnavailable,
    rate_limited,
)


class _Throttled(RuntimeError):
    def __init__(self) -> None:
        super().__init__("An error occurred (ThrottlingException): Too many requests")


def _breaker(slept: list[float]) -> SourceBreaker:
    return SourceBreaker(retry_backoff_seconds=2.0, sleep=slept.append, jitter=lambda: 0.5)


def test_a_throttled_call_waits_before_its_one_retry():
    slept: list[float] = []
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise _Throttled()
        return "ok"

    assert _breaker(slept).call(fn) == "ok"
    assert slept == [3.0], "스로틀인데 간격 없이 다시 쳤다"
    assert len(calls) == 2, "재시도 횟수는 계약대로 1회다"


def test_an_outage_still_retries_immediately():
    """소스가 죽은 것이라면 기다릴 이유가 없다 — 계약이 든 근거가 그것이다."""
    slept: list[float] = []
    calls = []

    def fn():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("external API unavailable")
        return "ok"

    assert _breaker(slept).call(fn) == "ok"
    assert slept == []
    assert len(calls) == 2


def test_the_retry_count_does_not_grow_when_the_throttle_persists():
    slept: list[float] = []
    calls = []

    def fn():
        calls.append(1)
        raise _Throttled()

    with pytest.raises(SourceUnavailable):
        _breaker(slept).call(fn)

    assert len(calls) == 2, "대기를 붙였다고 재시도가 늘면 계약이 깨진다"
    assert slept == [3.0]


def test_the_wait_carries_jitter_so_parallel_callers_do_not_re_collide():
    """지터가 없으면 병렬 호출들이 같은 순간에 함께 다시 친다 — 스로틀을 부른 그 동시성을
    그대로 재현하는 것이라, 재시도가 서로를 떨어뜨린다."""
    waits = []
    for jitter in (0.0, 1.0):
        slept: list[float] = []
        breaker = SourceBreaker(
            retry_backoff_seconds=2.0, sleep=slept.append, jitter=lambda j=jitter: j
        )
        with pytest.raises(SourceUnavailable):
            breaker.call(_raise_throttled)
        waits.append(slept[0])

    assert waits == [2.0, 4.0], "지터가 대기에 안 실렸다"


def _raise_throttled():
    raise _Throttled()


@pytest.mark.parametrize(
    "error",
    [
        _Throttled(),
        RuntimeError("HTTP 429 Too Many Requests"),
        RuntimeError("Rate limit exceeded"),
    ],
)
def test_rate_limits_are_recognised_across_client_libraries(error):
    """타입으로 가르지 않는다 — botocore·httpx·requests가 각자 다른 예외를 들고 온다."""
    assert rate_limited(error)


def test_a_botocore_style_error_code_is_recognised():
    error = RuntimeError("opaque")
    error.response = {"Error": {"Code": "ThrottlingException"}}  # type: ignore[attr-defined]

    assert rate_limited(error)


def test_a_429_status_code_is_recognised_without_a_message():
    class _Resp:
        status_code = 429

    error = RuntimeError("opaque")
    error.response = _Resp()  # type: ignore[attr-defined]

    assert rate_limited(error)


def test_an_ordinary_failure_is_not_a_rate_limit():
    assert not rate_limited(RuntimeError("external API unavailable"))
    assert not rate_limited(None)
