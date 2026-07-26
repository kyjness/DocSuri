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

from redis.exceptions import TimeoutError as RedisTimeoutError

from ..ports.queue import KIND_LOOP, QueuedJob

__all__ = ["RedisJobQueue"]

_QUEUE_KEY = "novelty:jobs"
_PROCESSING_KEY = "novelty:jobs:processing"
_LOCK_PREFIX = "novelty:lock:"

# 워커의 블록 소비(_CONSUME_TIMEOUT_S=5s)보다 넉넉한 소켓 읽기 한도. redis-py 8이
# 기본을 5초로 바꾸면서 블록 시간과 같아졌고, 그러면 서버의 nil 응답보다 클라이언트
# 데드라인이 먼저 걸려 유휴 폴링이 예외가 된다.
CONSUME_SOCKET_TIMEOUT_S = 30.0


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
        job = QueuedJob(job_id=job_id, owner_id=owner_id, kind=kind, message_id=message_id)
        self._client.lpush(self._queue_key, json.dumps(job.to_payload()))

    def consume(self, timeout_seconds: float) -> QueuedJob | None:
        try:
            raw = self._client.blmove(
                self._queue_key,
                self._processing_key,
                timeout=max(timeout_seconds, 0.001),
                src="RIGHT",
                dest="LEFT",
            )
        except RedisTimeoutError:
            # 블로킹 읽기가 만료됐다 = 큐가 비어 있다. redis-py 8부터 소켓 읽기
            # 기본 한도가 5초라, 그 이상(또는 같게) 블록하면 서버의 nil 응답보다
            # 클라이언트 데드라인이 먼저 걸려 예외로 나온다. 빈 큐를 예외로 돌려주면
            # 워커가 유휴 상태에서 죽으므로 여기서 "메시지 없음"으로 정규화한다.
            # 연결 실패(ConnectionError)는 이 분기에 걸리지 않고 호출자로 올라간다.
            return None
        if raw is None:
            return None
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        try:
            return QueuedJob.from_payload(json.loads(text), receipt=text)
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
