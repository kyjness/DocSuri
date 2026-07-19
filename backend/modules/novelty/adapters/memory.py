"""InMemory 스토어·큐 — 포트 기준 구현(어댑터).

테스트 페이크의 기준 구현이자, postgres/redis 미구성 환경에서 API가 항상
마운트되기 위한 폴백(제로 서비스 부팅 — /readyz 필수 모듈 유지)이다.
SQL·redis 구현과 같은 계약 테스트를 공유한다(nfr-design-patterns §7).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from ..domain.models import (
    TERMINAL_STATES,
    ArtifactRecord,
    InvalidTransitionError,
    JobState,
    NotionConnection,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    ToolCallRecord,
)
from ..ports.queue import QueuedJob
from ..ports.store import DuplicateTraceSeqError

__all__ = ["InMemoryJobQueue", "InMemoryNoveltyStore"]

class InMemoryNoveltyStore:
    """NoveltyStorePort 기준 구현 — owner 격리·seq 무결·cascade 삭제를 강제."""

    def __init__(self) -> None:
        self._jobs: dict[str, NoveltyJob] = {}
        self._artifacts: dict[tuple[str, str], ArtifactRecord] = {}
        self._trace: dict[str, list[ToolCallRecord]] = {}
        self._messages: dict[str, list[NoveltyChatMessage]] = {}
        self._exports: dict[str, NotionExport] = {}
        self._connections: dict[str, NotionConnection] = {}

    # ── 잡 ──
    def create_job(self, job: NoveltyJob) -> None:
        self._jobs[job.job_id] = job.model_copy(deep=True)

    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob | None:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return None
        return job.model_copy(deep=True)

    def get_job_for_worker(self, job_id: str) -> NoveltyJob | None:
        job = self._jobs.get(job_id)
        return None if job is None else job.model_copy(deep=True)

    def list_jobs(self, owner_id: str, *, cursor: str | None, limit: int) -> list[NoveltyJob]:
        owned = sorted(
            (job for job in self._jobs.values() if job.owner_id == owner_id),
            key=lambda job: (job.created_at, job.job_id),
            reverse=True,
        )
        if cursor is not None:
            ids = [job.job_id for job in owned]
            if cursor not in ids:
                raise KeyError(f"unknown cursor: {cursor}")
            owned = owned[ids.index(cursor) + 1 :]
        return [job.model_copy(deep=True) for job in owned[:limit]]

    def update_job(self, job: NoveltyJob) -> None:
        existing = self._jobs.get(job.job_id)
        if existing is None:
            raise KeyError(job.job_id)
        updated = job.model_copy(deep=True)
        # 취소 플래그는 단방향 래치 — 워커의 낡은 스냅샷이 동시 취소 요청을 덮지 못한다.
        updated.cancel_requested = updated.cancel_requested or existing.cancel_requested
        # 종단 상태 재진입 금지(BR-RA5)를 저장 수준에서도 강제 — 최초 종단 기록이 승리.
        if existing.state in TERMINAL_STATES and updated.state is not existing.state:
            raise InvalidTransitionError(f"job is terminal: {existing.state}")
        self._jobs[job.job_id] = updated

    def delete_job(self, owner_id: str, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return False
        del self._jobs[job_id]
        # cascade — 산출물·트레이스·대화·export 동반 삭제(BR-NV18 개정).
        for key in [key for key in self._artifacts if key[0] == job_id]:
            del self._artifacts[key]
        self._trace.pop(job_id, None)
        self._messages.pop(job_id, None)
        self._exports.pop(job_id, None)
        return True

    # ── Notion export·연결 ──
    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None:
        export = self._exports.get(job_id)
        if export is None or export.owner_id != owner_id:
            return None
        return export.model_copy(deep=True)

    def save_export(self, export: NotionExport) -> None:
        self._exports[export.job_id] = export.model_copy(deep=True)

    def get_notion_connection(self, owner_id: str) -> NotionConnection | None:
        connection = self._connections.get(owner_id)
        return None if connection is None else connection.model_copy(deep=True)

    def save_notion_connection(self, connection: NotionConnection) -> None:
        self._connections[connection.owner_id] = connection.model_copy(deep=True)

    def delete_notion_connection(self, owner_id: str) -> None:
        self._connections.pop(owner_id, None)

    def delete_all_jobs(self, owner_id: str) -> int:
        """소유 잡 전부 벌크 삭제(전체 초기화 — SEC-14 계열) — cascade 동일."""
        deleted = 0
        for job_id in [j.job_id for j in self._jobs.values() if j.owner_id == owner_id]:
            if self.delete_job(owner_id, job_id):
                deleted += 1
        return deleted

    def request_cancel(self, owner_id: str, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return False
        job.cancel_requested = True
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        return bool(job and job.cancel_requested)

    def list_stale_active(self, *, updated_before, limit: int) -> list[NoveltyJob]:
        """오래 방치된 활성 잡 — 실행 중(investigating/reporting)과 미픽업(received,
        큐 메시지 유실 잔재) 모두 stale 감지 입력이다."""
        stale = [
            job
            for job in self._jobs.values()
            if job.state in (JobState.RECEIVED, JobState.INVESTIGATING, JobState.REPORTING)
            and job.updated_at < updated_before
        ]
        stale.sort(key=lambda job: job.updated_at)
        return [job.model_copy(deep=True) for job in stale[:limit]]

    # ── 산출물 ──
    def save_artifact(self, record: ArtifactRecord) -> None:
        # 종류별 최신 검증본만 유지(domain-entities: artifacts 참조 목록).
        self._artifacts[(record.job_id, record.kind.value)] = record.model_copy(deep=True)

    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRecord]:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return []
        records = [rec for (jid, _), rec in self._artifacts.items() if jid == job_id]
        return [rec.model_copy(deep=True) for rec in sorted(records, key=lambda r: r.created_at)]

    # ── 트레이스 ──
    def next_trace_seq(self, job_id: str) -> int:
        records = self._trace.get(job_id, [])
        return records[-1].seq + 1 if records else 1

    def append_trace(self, record: ToolCallRecord) -> None:
        records = self._trace.setdefault(record.job_id, [])
        if any(existing.seq == record.seq for existing in records):
            raise DuplicateTraceSeqError(f"{record.job_id}:{record.seq}")
        records.append(record.model_copy(deep=True))
        records.sort(key=lambda existing: existing.seq)

    def list_trace(
        self, owner_id: str, job_id: str, *, after_seq: int, limit: int
    ) -> list[ToolCallRecord]:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return []
        records = [rec for rec in self._trace.get(job_id, []) if rec.seq > after_seq]
        return [rec.model_copy(deep=True) for rec in records[:limit]]

    # ── 대화 ──
    def append_message(self, message: NoveltyChatMessage) -> None:
        self._messages.setdefault(message.job_id, []).append(message.model_copy(deep=True))

    def list_messages(
        self, owner_id: str, job_id: str, *, after: str | None, limit: int
    ) -> list[NoveltyChatMessage]:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return []
        messages = self._messages.get(job_id, [])
        if after is not None:
            ids = [message.message_id for message in messages]
            if after not in ids:
                raise KeyError(f"unknown cursor: {after}")
            messages = messages[ids.index(after) + 1 :]
        return [message.model_copy(deep=True) for message in messages[:limit]]


class InMemoryJobQueue:
    """JobQueuePort + ExecutionLockPort 기준 구현(리스 TTL 의미론)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._queue: deque[QueuedJob] = deque()
        self._locks: dict[str, float] = {}
        self._clock = clock
        # consume 블로킹 대기(redis BLMOVE 등가 계약) — 폴백 워커의 busy-spin 방지.
        self._not_empty = threading.Condition()

    def enqueue(self, job_id: str, owner_id: str) -> None:
        with self._not_empty:
            self._queue.append(QueuedJob(job_id=job_id, owner_id=owner_id))
            self._not_empty.notify()

    def consume(self, timeout_seconds: float) -> QueuedJob | None:
        with self._not_empty:
            self._not_empty.wait_for(
                lambda: bool(self._queue), timeout=max(timeout_seconds, 0.0)
            )
            return self._queue.popleft() if self._queue else None

    def ack(self, job: QueuedJob) -> None:
        return None

    # 실행 잠금 — 만료된 리스는 회수 가능해야 한다(stale 잡 감지의 전제).
    def acquire(self, job_id: str, ttl_seconds: float) -> bool:
        now = self._clock()
        expiry = self._locks.get(job_id)
        if expiry is not None and expiry > now:
            return False
        self._locks[job_id] = now + ttl_seconds
        return True

    def renew(self, job_id: str, ttl_seconds: float) -> bool:
        if job_id not in self._locks:
            return False
        self._locks[job_id] = self._clock() + ttl_seconds
        return True

    def release(self, job_id: str) -> None:
        self._locks.pop(job_id, None)
