"""외부 소스 호출 공통부 — 재시도 1회 + 소스별 서킷 브레이커(NFR-NV2-11).

u2/u7의 차단기 패턴을 소스 단위로 축소 적용: 연속 실패가 임계에 닿으면 cooldown
동안 호출을 차단하고, 실패는 오류로 에이전트에 반환된다(BR-NV16 — 대체 경로 판단).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

__all__ = ["SourceBreaker", "SourceUnavailable"]


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
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._failures = 0
        self._open_until: float | None = None

    def call(self, fn: Callable[[], Any]) -> Any:
        if self._open_until is not None:
            if self._clock() < self._open_until:
                raise SourceUnavailable("circuit open")
            self._open_until = None
            self._failures = 0
        last_error: Exception | None = None
        for _ in range(2):  # 기계 재시도 1회 — 이후는 에이전트 판단(NFR-NV2-11)
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 — 실패 집계 후 오류로 반환
                last_error = exc
                continue
            self._failures = 0
            return result
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._open_until = self._clock() + self._cooldown_seconds
        raise SourceUnavailable(str(last_error) if last_error else "external source failed")
