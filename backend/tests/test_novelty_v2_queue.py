"""redis 잡 큐 어댑터 — 실 redis 통합 테스트(env-gated) + 페이크 잠금 계약은
test_novelty_v2_store_contract.py::TestExecutionLockContract가 담당.

CI에는 서비스 컨테이너가 없으므로 NOVELTY_TEST_REDIS_URL 설정 시에만 실행:
NOVELTY_TEST_REDIS_URL=redis://localhost:6379/1 uv run pytest tests/test_novelty_v2_queue.py
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import pytest

_REDIS_URL = os.getenv("NOVELTY_TEST_REDIS_URL")

pytestmark = pytest.mark.skipif(
    not _REDIS_URL, reason="NOVELTY_TEST_REDIS_URL not set (redis integration)"
)


@pytest.fixture()
def queue():
    import redis

    from backend.modules.novelty.adapters.queue_redis import RedisJobQueue

    suffix = uuid4().hex
    client = redis.Redis.from_url(_REDIS_URL)
    q = RedisJobQueue(
        client,
        queue_key=f"test:novelty:jobs:{suffix}",
        processing_key=f"test:novelty:processing:{suffix}",
        lock_prefix=f"test:novelty:lock:{suffix}:",
    )
    yield q
    client.delete(q._queue_key, q._processing_key)  # noqa: SLF001 — 테스트 정리
    client.close()


def test_enqueue_consume_ack_roundtrip(queue) -> None:
    queue.enqueue("job-1", "owner-1")
    job = queue.consume(timeout_seconds=1)
    assert job is not None and job.job_id == "job-1" and job.owner_id == "owner-1"
    # ack 전 crash 가정 — recover가 재적재.
    assert queue.recover_processing() == 1
    again = queue.consume(timeout_seconds=1)
    assert again is not None and again.job_id == "job-1"
    queue.ack(again)
    assert queue.recover_processing() == 0
    assert queue.consume(timeout_seconds=0.1) is None


def test_fifo_order(queue) -> None:
    for i in range(3):
        queue.enqueue(f"job-{i}", "owner-1")
    consumed = [queue.consume(timeout_seconds=1).job_id for _ in range(3)]
    assert consumed == ["job-0", "job-1", "job-2"]


def test_execution_lock_lease(queue) -> None:
    assert queue.acquire("job-9", ttl_seconds=1) is True
    assert queue.acquire("job-9", ttl_seconds=1) is False  # 이중 실행 방지
    assert queue.renew("job-9", ttl_seconds=1) is True
    time.sleep(1.3)  # 리스 만료
    assert queue.acquire("job-9", ttl_seconds=1) is True  # 만료 리스 회수
    queue.release("job-9")
    assert queue.acquire("job-9", ttl_seconds=1) is True


def test_corrupt_payload_is_discarded(queue) -> None:
    import redis

    client = redis.Redis.from_url(_REDIS_URL)
    client.lpush(queue._queue_key, "not-json")  # noqa: SLF001
    assert queue.consume(timeout_seconds=1) is None
    assert queue.recover_processing() == 0
    client.close()
