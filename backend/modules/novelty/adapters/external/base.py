"""외부 소스 호출 공통부 — 재시도 1회 + 소스별 서킷 브레이커(NFR-NV2-11).

브레이커 상태기계는 공유 구현(docsuri_shared.resilience — 단일 프로브·stale
success 무시·프로브 슬롯 만료)을 쓰고, 여기는 소스 정책만 남긴다: 기계 재시도
1회 후 실패는 오류로 에이전트에 반환된다(BR-NV16 — 대체 경로 판단).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from docsuri_shared.resilience import CircuitBreaker

__all__ = ["SourceBreaker", "SourceUnavailable", "check_response"]


class SourceUnavailable(RuntimeError):
    pass


class SourceBreaker:
    def __init__(
        self,
        *,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._breaker = CircuitBreaker(
            "source",
            failure_threshold=failure_threshold,
            recovery_seconds=cooldown_seconds,
            clock=clock,
        )

    def call(self, fn: Callable[[], Any]) -> Any:
        permit = self._breaker.acquire()
        if permit is None:
            raise SourceUnavailable("circuit open")
        last_error: Exception | None = None
        try:
            for _ in range(2):  # 기계 재시도 1회 — 이후는 에이전트 판단(NFR-NV2-11)
                try:
                    result = fn()
                except Exception as exc:  # noqa: BLE001 — 실패 집계 후 오류로 반환
                    last_error = exc
                    continue
                permit.success()
                return result
        finally:
            permit.failure()  # 멱등 — 성공 완료 후엔 no-op(catch-all 해제)
        raise SourceUnavailable(str(last_error) if last_error else "external source failed")


def check_response(response: Any) -> None:
    """외부 API 응답 공통 검사 — 4xx/5xx는 예외로 승격(소스 실패 집계 대상)."""
    if getattr(response, "status_code", 200) >= 400:
        raise RuntimeError("external API unavailable")
    raise_for_status = getattr(response, "raise_for_status", None)
    if raise_for_status is not None:
        raise_for_status()
