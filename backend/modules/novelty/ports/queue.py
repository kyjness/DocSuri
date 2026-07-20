"""잡 큐 포트 — 적재·소비·실행 잠금(NFR-NV2-1~3).

잠금은 리스 기반(TTL) 계약이다: redis SET NX EX와 SQS visibility timeout이
같은 계약을 만족한다 — 만료된 리스는 다른 워커가 회수할 수 있어야 하고(stale
잡 감지), 갱신(renew)으로 장기 실행을 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = ["ExecutionLockPort", "JobQueuePort", "QueuedJob"]


@dataclass(frozen=True, slots=True)
class QueuedJob:
    job_id: str
    owner_id: str
    receipt: str | None = None  # 큐 구현별 ack 핸들(SQS receipt 등)


class JobQueuePort(Protocol):
    def enqueue(self, job_id: str, owner_id: str) -> None: ...

    def consume(self, timeout_seconds: float) -> QueuedJob | None: ...

    def ack(self, job: QueuedJob) -> None: ...


class ExecutionLockPort(Protocol):
    """job_id 단위 실행 잠금 — 이중 실행 방지(멱등)."""

    def acquire(self, job_id: str, ttl_seconds: float) -> bool: ...

    def renew(self, job_id: str, ttl_seconds: float) -> bool: ...

    def release(self, job_id: str) -> None: ...
