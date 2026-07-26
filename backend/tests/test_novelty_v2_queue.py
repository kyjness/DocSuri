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


def test_nack_returns_message_to_queue(queue) -> None:
    # ack 생략만으로는 processing 리스트에 방치된다(워커 재시작 전까지 재전달 없음).
    queue.enqueue("job-1", "owner-1")
    job = queue.consume(timeout_seconds=1)
    assert job is not None
    queue.nack(job)
    assert queue.recover_processing() == 0  # processing에 남아 있지 않다
    again = queue.consume(timeout_seconds=1)
    assert again is not None and again.job_id == "job-1"
    queue.ack(again)


def test_nack_puts_message_at_back_of_queue(queue) -> None:
    for i in range(2):
        queue.enqueue(f"job-{i}", "owner-1")
    first = queue.consume(timeout_seconds=1)
    assert first.job_id == "job-0"
    queue.nack(first)
    # 같은 메시지를 즉시 다시 집지 않는다 — 뒤의 메시지가 먼저 처리된다.
    assert queue.consume(timeout_seconds=1).job_id == "job-1"
    assert queue.consume(timeout_seconds=1).job_id == "job-0"


def test_corrupt_payload_is_discarded(queue) -> None:
    import redis

    client = redis.Redis.from_url(_REDIS_URL)
    client.lpush(queue._queue_key, "not-json")  # noqa: SLF001
    assert queue.consume(timeout_seconds=1) is None
    assert queue.recover_processing() == 0
    client.close()


def test_queued_job_kind_defaults_to_loop_for_legacy_payloads(queue) -> None:
    import redis

    from backend.modules.novelty.ports.queue import KIND_LOOP

    client = redis.Redis.from_url(_REDIS_URL)
    # 배포 시점에 큐에 남아 있던 기존 페이로드(kind 키 없음).
    client.lpush(queue._queue_key, '{"job_id": "job-legacy", "owner_id": "owner-1"}')  # noqa: SLF001
    job = queue.consume(timeout_seconds=1)
    assert job is not None and job.kind == KIND_LOOP and job.message_id is None
    queue.ack(job)
    client.close()


def test_turn_message_roundtrips_kind_and_message_id(queue) -> None:
    from backend.modules.novelty.ports.queue import KIND_TURN

    queue.enqueue("job-1", "owner-1", kind=KIND_TURN, message_id="msg-9")
    job = queue.consume(timeout_seconds=1)
    assert job is not None
    assert job.kind == KIND_TURN and job.message_id == "msg-9"
    queue.ack(job)


def test_idle_consume_at_worker_block_duration_returns_none(queue) -> None:
    """워커의 블록 시간(5초)만큼 빈 큐를 기다려도 예외가 아니라 None이어야 한다.

    redis-py 8부터 소켓 읽기 기본 한도가 5초라, 그 시간만큼 블록하면 서버의 nil
    응답보다 클라이언트 데드라인이 먼저 걸려 TimeoutError가 난다. 어댑터가 이를
    정규화하지 않으면 워커가 잡을 하나도 받기 전에 유휴 상태에서 죽는다 —
    로컬 실스택 검증에서 실제로 그랬다. 종전 테스트는 1초 이하만 써서 못 잡았다.
    """
    from backend.modules.novelty.worker import _CONSUME_TIMEOUT_S

    started = time.monotonic()
    assert queue.consume(timeout_seconds=_CONSUME_TIMEOUT_S) is None
    # 즉시 반환이면 블로킹이 아예 안 된 것이므로 회귀 가드가 의미를 잃는다.
    assert time.monotonic() - started >= _CONSUME_TIMEOUT_S - 0.5


def test_connection_failure_still_propagates(queue) -> None:
    """빈 큐 정규화가 진짜 연결 장애까지 삼키면 안 된다 — 그러면 워커가 죽은 redis를
    상대로 '큐가 비었다'고 오해하며 조용히 공회전한다."""
    import redis

    from backend.modules.novelty.adapters.queue_redis import RedisJobQueue

    # 아무도 듣지 않는 포트 — 연결 자체가 실패한다.
    dead = RedisJobQueue(redis.Redis.from_url("redis://localhost:6399/0"))
    with pytest.raises(redis.exceptions.ConnectionError):
        dead.consume(timeout_seconds=0.1)
