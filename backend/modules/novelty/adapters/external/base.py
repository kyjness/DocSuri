"""외부 소스 호출 공통부 — 재시도 1회 + 소스별 서킷 브레이커(NFR-NV2-11).

브레이커 상태기계는 공유 구현(docsuri_shared.resilience — 단일 프로브·stale
success 무시·프로브 슬롯 만료)을 쓰고, 여기는 소스 정책만 남긴다: 기계 재시도
1회 후 실패는 오류로 에이전트에 반환된다(BR-NV16 — 대체 경로 판단).

**요청속도 거절일 때만 기다렸다 재시도한다.** 계약이 정한 것은 재시도 **횟수**(1회)이지
간격이 아니고, 계약이 든 근거는 "outage 정신"이다 — 소스가 죽은 것이라면 곧바로 한 번 더
치는 것이 맞다. 그러나 **429 / `ThrottlingException`은 outage가 아니다.** 간격 없이 다시
치면 같은 창 안에서 같은 거절을 한 번 더 받을 뿐이라 재시도가 아무 일도 하지 않는다.
그 실패는 예외로도 안 드러난다: `decide`가 `llm_unavailable`로 기권하고 사용자에게는
"답할 근거가 없다"로 보인다.

실측(2026-08-25): 2층 심판이 두 번 다 **정확히 3문항 뒤** `ThrottlingException`으로 죽고
회복하지 못했다. 즉시 재시도가 아니라 대기 후 재시도였다면 넘어갔을 자리다.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any

from docsuri_shared.resilience import CircuitBreaker

__all__ = ["SourceBreaker", "SourceUnavailable", "check_response", "rate_limited"]


class SourceUnavailable(RuntimeError):
    pass


class SourceBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        retry_backoff_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._breaker = CircuitBreaker(
            "source",
            failure_threshold=failure_threshold,
            recovery_seconds=cooldown_seconds,
            clock=clock,
        )
        self._backoff = max(0.0, retry_backoff_seconds)
        self._sleep = sleep
        self._jitter = jitter

    def call(self, fn: Callable[[], Any]) -> Any:
        # guard(): success() 없이 블록을 이탈하면 실패로 마감 — 수동 finally 불필요.
        with self._breaker.guard() as permit:
            if permit is None:
                raise SourceUnavailable("circuit open")
            last_error: Exception | None = None
            for attempt in range(2):  # 기계 재시도 1회 — 이후는 에이전트 판단(NFR-NV2-11)
                if attempt and rate_limited(last_error):
                    self._wait_before_retry()
                try:
                    result = fn()
                except Exception as exc:  # noqa: BLE001 — 실패 집계 후 오류로 반환
                    last_error = exc
                    continue
                permit.success()
                return result
            raise SourceUnavailable(
                str(last_error) if last_error else "external source failed"
            )

    def _wait_before_retry(self) -> None:
        """대기 + 지터. 지터가 없으면 병렬 호출들이 **같은 순간에** 함께 다시 친다 —
        스로틀을 부른 그 동시성을 그대로 재현하는 것이라 재시도가 서로를 떨어뜨린다."""
        if not self._backoff:
            return
        self._sleep(self._backoff * (1.0 + self._jitter()))


_RATE_LIMIT_WORDS = ("throttl", "too many requests", "rate limit", "rate exceeded", "429")
_RATE_LIMIT_CODES = frozenset(
    {"Throttling", "ThrottlingException", "TooManyRequestsException", "RequestLimitExceeded"}
)


def rate_limited(error: Exception | None) -> bool:
    """이 실패가 **소스가 죽은 것이 아니라 너무 빨리 친 것**인가.

    타입으로 안 가른다 — botocore·httpx·requests가 각자 다른 예외를 들고 오고, 여기서
    그 셋을 import하면 공통부가 세 클라이언트에 묶인다. 대신 셋이 **공통으로 노출하는
    것**(오류 코드·상태 코드·메시지)을 본다.
    """
    if error is None:
        return False
    response = getattr(error, "response", None)
    if isinstance(response, dict):  # botocore ClientError
        if str(response.get("Error", {}).get("Code", "")) in _RATE_LIMIT_CODES:
            return True
    if getattr(response, "status_code", None) == 429:  # httpx·requests
        return True
    if getattr(error, "status_code", None) == 429:
        return True
    text = str(error).lower()
    return any(word in text for word in _RATE_LIMIT_WORDS)


def check_response(response: Any) -> None:
    """외부 API 응답 공통 검사 — 4xx/5xx는 예외로 승격(소스 실패 집계 대상)."""
    if getattr(response, "status_code", 200) >= 400:
        raise RuntimeError("external API unavailable")
    raise_for_status = getattr(response, "raise_for_status", None)
    if raise_for_status is not None:
        raise_for_status()
