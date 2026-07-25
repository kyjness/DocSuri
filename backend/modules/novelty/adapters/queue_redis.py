"""redis 잡 큐 어댑터(TD-NV2-1, 로컬 1차) — 기존 redis 컨테이너 재사용.

큐 계약은 SQS와 호환되게 유지한다(real_wiring 복원 기준선):
- 소비는 BLMOVE로 processing 리스트에 옮겨 at-least-once를 보장하고,
  ack(LREM)가 SQS delete_message 역할을 한다. 워커 crash 시 processing에 남은
  항목은 recover_processing()이 재적재한다(SQS visibility 만료 재전달의 등가).
- 실행 잠금은 SET NX EX 리스(TTL) — visibility timeout과 같은 만료 회수 계약.
"""

from __future__ import annotations

import json
from typing import Any

from ..ports.queue import KIND_LOOP, QueuedJob

__all__ = ["RedisJobQueue"]

_QUEUE_KEY = "novelty:jobs"
_PROCESSING_KEY = "novelty:jobs:processing"
_LOCK_PREFIX = "novelty:lock:"


class RedisJobQueue:
    """JobQueuePort + ExecutionLockPort 구현. client는 redis.Redis 호환(sync)."""

    def __init__(
        self,
        client: Any,
        *,
        queue_key: str = _QUEUE_KEY,
        processing_key: str = _PROCESSING_KEY,
        lock_prefix: str = _LOCK_PREFIX,
    ) -> None:
        self._client = client
        self._queue_key = queue_key
        self._processing_key = processing_key
        self._lock_prefix = lock_prefix

    # ── 큐 ──
    def enqueue(
        self,
        job_id: str,
        owner_id: str,
        *,
        kind: str = KIND_LOOP,
        message_id: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"job_id": job_id, "owner_id": owner_id}
        # loop은 생략한다 — 배포 시점에 큐에 남아 있던 기존 페이로드와 모양이 같아
        # 인플라이트 메시지가 그대로 소비된다(consume이 부재 시 loop으로 읽는다).
        if kind != KIND_LOOP:
            body["kind"] = kind
        if message_id is not None:
            body["message_id"] = message_id
        self._client.lpush(self._queue_key, json.dumps(body))

    def consume(self, timeout_seconds: float) -> QueuedJob | None:
        raw = self._client.blmove(
            self._queue_key,
            self._processing_key,
            timeout=max(timeout_seconds, 0.001),
            src="RIGHT",
            dest="LEFT",
        )
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        try:
            data = json.loads(text)
            message_id = data.get("message_id")
            return QueuedJob(
                job_id=str(data["job_id"]),
                owner_id=str(data["owner_id"]),
                receipt=text,
                kind=str(data.get("kind") or KIND_LOOP),
                message_id=str(message_id) if message_id is not None else None,
            )
        except (ValueError, KeyError):
            # 손상 payload는 큐에서 제거만 하고 버린다(독약 메시지 방지).
            self._client.lrem(self._processing_key, 1, text)
            return None

    def ack(self, job: QueuedJob) -> None:
        if job.receipt is not None:
            self._client.lrem(self._processing_key, 1, job.receipt)

    def nack(self, job: QueuedJob) -> None:
        """처리하지 않은 메시지를 큐로 반환한다(SQS visibility 0 등가).

        consume이 RIGHT에서 팝하므로 LPUSH는 큐의 끝에 놓는다 — 다른 메시지가
        있으면 그것들이 먼저 처리되고, 없으면 호출자의 backoff가 재시도 간격을
        책임진다. 되돌리지 않으면 recover_processing(워커 재시작)까지 방치된다.
        """
        if job.receipt is None:
            return
        removed = self._client.lrem(self._processing_key, 1, job.receipt)
        if removed:
            self._client.lpush(self._queue_key, job.receipt)

    def recover_processing(self) -> int:
        """워커 기동 시 호출 — crash로 processing에 남은 항목을 재적재한다."""
        moved = 0
        while self._client.lmove(self._processing_key, self._queue_key, "RIGHT", "LEFT"):
            moved += 1
        return moved

    # ── 실행 잠금(리스 TTL) ──
    def acquire(self, job_id: str, ttl_seconds: float) -> bool:
        return bool(
            self._client.set(
                f"{self._lock_prefix}{job_id}", "1", nx=True, ex=max(int(ttl_seconds), 1)
            )
        )

    def renew(self, job_id: str, ttl_seconds: float) -> bool:
        return bool(
            self._client.expire(f"{self._lock_prefix}{job_id}", max(int(ttl_seconds), 1))
        )

    def release(self, job_id: str) -> None:
        self._client.delete(f"{self._lock_prefix}{job_id}")
