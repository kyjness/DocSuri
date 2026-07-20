"""NoveltyStorePort 공유 계약 테스트 — 구현이 늘어나면 여기 등록한다.

InMemory(페이크 기준 구현)와 SQL 스토어(⑤ 어댑터 단계)가 같은 계약을 만족해야
real_wiring 복원 시 회귀를 막는다(nfr-design-patterns §7). PBT-NV6(owner 격리 —
트레이스·대화 포함)·seq 무결(PBT-RA3의 저장 측)·cascade 삭제(BR-NV18 개정)를 다룬다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.modules.novelty.domain.models import (
    ArtifactKind,
    ArtifactRecord,
    ChatKind,
    ChatRole,
    InputType,
    NoveltyChatMessage,
    NoveltyJob,
    NoveltyJobRequest,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
)
from backend.modules.novelty.ports.store import DuplicateTraceSeqError

from .novelty_v2_fakes import InMemoryNoveltyStore

# owner 격리 검증용 제3자 — SQL 스토어의 UUID 컬럼과 호환되도록 UUID 문자열.
_OTHER_OWNER = str(uuid4())


def _job(owner_id: str | None = None) -> NoveltyJob:
    return NoveltyJob(
        owner_id=owner_id or str(uuid4()),
        request=NoveltyJobRequest(
            input_type=InputType.NATURAL_LANGUAGE,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
        ),
    )


def _sql_store():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from backend.modules.novelty.adapters.store_sql import NoveltyV2Base, SqlNoveltyStore

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    NoveltyV2Base.metadata.create_all(engine)
    return SqlNoveltyStore(sessionmaker(bind=engine))


def _trace(job_id: str, seq: int) -> ToolCallRecord:
    now = utc_now()
    return ToolCallRecord(
        job_id=job_id,
        seq=seq,
        tool_name="corpus_search",
        args_summary="query='privacy rag'",
        result_summary="3 findings",
        outcome=ToolOutcome.OK,
        started_at=now,
        finished_at=now,
    )


@pytest.fixture(params=["memory", "sql"])
def store(request):
    # 같은 계약을 InMemory(페이크 기준)와 SQL 구현이 함께 만족해야 한다.
    if request.param == "sql":
        return _sql_store()
    return InMemoryNoveltyStore()


class TestNoveltyStoreContract:
    def test_job_roundtrip_and_owner_isolation(self, store) -> None:
        job = _job()
        store.create_job(job)
        assert store.get_job(job.owner_id, job.job_id) is not None
        assert store.get_job(_OTHER_OWNER, job.job_id) is None
        assert store.get_job_for_worker(job.job_id) is not None
        assert store.list_jobs(_OTHER_OWNER, cursor=None, limit=10) == []

    def test_list_jobs_cursor_pagination(self, store) -> None:
        owner = str(uuid4())
        jobs = [_job(owner) for _ in range(3)]
        for job in jobs:
            store.create_job(job)
        first_page = store.list_jobs(owner, cursor=None, limit=2)
        assert len(first_page) == 2
        second_page = store.list_jobs(owner, cursor=first_page[-1].job_id, limit=2)
        assert len(second_page) == 1
        assert {j.job_id for j in first_page} | {j.job_id for j in second_page} == {
            j.job_id for j in jobs
        }

    def test_trace_seq_uniqueness_enforced(self, store) -> None:
        job = _job()
        store.create_job(job)
        assert store.next_trace_seq(job.job_id) == 1
        store.append_trace(_trace(job.job_id, 1))
        store.append_trace(_trace(job.job_id, 2))
        assert store.next_trace_seq(job.job_id) == 3
        with pytest.raises(DuplicateTraceSeqError):
            store.append_trace(_trace(job.job_id, 2))

    def test_trace_cursor_feed_ordering(self, store) -> None:
        job = _job()
        store.create_job(job)
        for seq in range(1, 6):
            store.append_trace(_trace(job.job_id, seq))
        page = store.list_trace(job.owner_id, job.job_id, after_seq=2, limit=2)
        assert [rec.seq for rec in page] == [3, 4]
        # owner 격리(PBT-NV6 — 트레이스 포함).
        assert store.list_trace(_OTHER_OWNER, job.job_id, after_seq=0, limit=10) == []

    def test_artifact_latest_per_kind(self, store) -> None:
        job = _job()
        store.create_job(job)
        first = ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id, kind=ArtifactKind.GAP_ANALYSIS,
            payload={"items": [1]},
        )
        second = ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id, kind=ArtifactKind.GAP_ANALYSIS,
            payload={"items": [1, 2]},
        )
        store.save_artifact(first)
        store.save_artifact(second)
        records = store.list_artifacts(job.owner_id, job.job_id)
        assert len(records) == 1
        assert records[0].payload == {"items": [1, 2]}
        assert store.list_artifacts(_OTHER_OWNER, job.job_id) == []

    def test_messages_owner_scoped_cursor(self, store) -> None:
        job = _job()
        store.create_job(job)
        messages = [
            NoveltyChatMessage(
                job_id=job.job_id, owner_id=job.owner_id, role=ChatRole.USER,
                kind=ChatKind.STEERING, content=f"m{i}",
            )
            for i in range(3)
        ]
        for message in messages:
            store.append_message(message)
        page = store.list_messages(job.owner_id, job.job_id, after=None, limit=2)
        assert [m.content for m in page] == ["m0", "m1"]
        rest = store.list_messages(job.owner_id, job.job_id, after=page[-1].message_id, limit=5)
        assert [m.content for m in rest] == ["m2"]
        assert store.list_messages(_OTHER_OWNER, job.job_id, after=None, limit=5) == []
        # 비소유자는 유효 커서를 들고 와도 KeyError가 아니라 빈 페이지 — 존재 비노출.
        assert (
            store.list_messages(_OTHER_OWNER, job.job_id, after=page[-1].message_id, limit=5)
            == []
        )

    def test_delete_job_cascades_everything(self, store) -> None:
        job = _job()
        store.create_job(job)
        store.append_trace(_trace(job.job_id, 1))
        store.save_artifact(
            ArtifactRecord(
                job_id=job.job_id, owner_id=job.owner_id, kind=ArtifactKind.EVIDENCE,
                payload={"state": "ok"},
            )
        )
        store.append_message(
            NoveltyChatMessage(
                job_id=job.job_id, owner_id=job.owner_id, role=ChatRole.USER,
                kind=ChatKind.STEERING, content="hello",
            )
        )
        assert store.delete_job(_OTHER_OWNER, job.job_id) is False
        assert store.delete_job(job.owner_id, job.job_id) is True
        assert store.get_job_for_worker(job.job_id) is None
        assert store.list_artifacts(job.owner_id, job.job_id) == []
        assert store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=10) == []
        assert store.list_messages(job.owner_id, job.job_id, after=None, limit=10) == []

    def test_cancel_flag_owner_scoped(self, store) -> None:
        job = _job()
        store.create_job(job)
        assert store.request_cancel(_OTHER_OWNER, job.job_id) is False
        assert store.is_cancel_requested(job.job_id) is False
        assert store.request_cancel(job.owner_id, job.job_id) is True
        assert store.is_cancel_requested(job.job_id) is True


class TestExecutionLockContract:
    def test_lock_idempotency_and_lease_expiry(self) -> None:
        from .novelty_v2_fakes import InMemoryJobQueue

        clock = {"now": 0.0}
        queue = InMemoryJobQueue(clock=lambda: clock["now"])
        assert queue.acquire("job-1", ttl_seconds=10) is True
        # 이중 실행 방지 — 유효 리스 중 재획득 불가.
        assert queue.acquire("job-1", ttl_seconds=10) is False
        assert queue.renew("job-1", ttl_seconds=10) is True
        # 만료된 리스는 회수 가능(stale 잡 감지의 전제).
        clock["now"] = 25.0
        assert queue.acquire("job-1", ttl_seconds=10) is True
        queue.release("job-1")
        assert queue.acquire("job-1", ttl_seconds=10) is True

    def test_consume_blocks_until_enqueue_or_timeout(self) -> None:
        # BLMOVE 등가 계약 — 빈 큐에서 timeout까지 대기하고(busy-spin 금지),
        # 대기 중 적재되면 timeout 전에 깨어난다.
        import threading
        import time

        from .novelty_v2_fakes import InMemoryJobQueue

        queue = InMemoryJobQueue()
        started = time.monotonic()
        assert queue.consume(timeout_seconds=0.15) is None
        assert time.monotonic() - started >= 0.1
        timer = threading.Timer(0.05, lambda: queue.enqueue("job-1", "owner-1"))
        started = time.monotonic()
        timer.start()
        job = queue.consume(timeout_seconds=5)
        assert job is not None and job.job_id == "job-1"
        assert time.monotonic() - started < 3.0


class TestStoreLatches:
    """update_job의 단방향 래치 계약 — 취소 플래그·종단 상태(BR-RA5), 양 구현 공통."""

    @pytest.fixture(params=["memory", "sql"])
    def latched_store(self, request):
        return _sql_store() if request.param == "sql" else InMemoryNoveltyStore()

    def test_stale_snapshot_cannot_clear_cancel_flag(self, latched_store) -> None:
        store = latched_store
        job = _job()
        store.create_job(job)
        stale_snapshot = store.get_job(job.owner_id, job.job_id)  # cancel=False 시점 스냅샷
        assert store.request_cancel(job.owner_id, job.job_id) is True
        store.update_job(stale_snapshot)  # 워커의 낡은 전체 덮어쓰기
        assert store.is_cancel_requested(job.job_id) is True  # 래치 유지

    def test_terminal_state_is_write_once(self, latched_store) -> None:
        from backend.modules.novelty.domain.models import InvalidTransitionError, JobState

        store = latched_store
        job = _job()
        store.create_job(job)
        job.state = JobState.INVESTIGATING
        store.update_job(job)
        sweep_view = store.get_job(job.owner_id, job.job_id)
        sweep_view.state = JobState.FAILED
        store.update_job(sweep_view)  # 스윕이 먼저 종단
        job.state = JobState.COMPLETED
        with pytest.raises(InvalidTransitionError):
            store.update_job(job)  # 완주 워커의 후행 종단 기록은 거부
        assert store.get_job(job.owner_id, job.job_id).state is JobState.FAILED

    def test_unknown_cursor_raises_instead_of_truncating(self, latched_store) -> None:
        store = latched_store
        owner = str(uuid4())
        jobs = [_job(owner) for _ in range(2)]
        for job in jobs:
            store.create_job(job)
        page = store.list_jobs(owner, cursor=None, limit=1)
        deleted_cursor = page[0].job_id
        store.delete_job(owner, deleted_cursor)
        with pytest.raises(KeyError):
            store.list_jobs(owner, cursor=deleted_cursor, limit=10)

    def test_unknown_message_cursor_raises(self, latched_store) -> None:
        store = latched_store
        job = _job()
        store.create_job(job)
        with pytest.raises(KeyError):
            store.list_messages(job.owner_id, job.job_id, after=str(uuid4()), limit=5)
