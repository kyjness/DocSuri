"""Novelty v2 포트 페이크 — 루프 코어를 결정론적으로 검증하기 위한 테스트 대역.

nfr-design-patterns §7: 모든 포트에 페이크, 루프 코어는 스크립트 LLM으로 재생.
InMemory 스토어·큐는 어댑터 계약 테스트의 기준 구현이기도 하다(2단계에서
SQL·redis 구현이 같은 계약 클래스에 등록된다).
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from backend.modules.novelty.domain.models import (
    ArtifactRecord,
    NoveltyChatMessage,
    NoveltyJob,
    ToolCallRecord,
)
from backend.modules.novelty.ports.llm import (
    LlmDecision,
    LoopObservation,
)
from backend.modules.novelty.ports.queue import QueuedJob
from backend.modules.novelty.ports.store import DuplicateTraceSeqError
from backend.modules.novelty.ports.tools import ToolContext, ToolResult, ToolSpec


class InMemoryNoveltyStore:
    """NoveltyStorePort 기준 구현 — owner 격리·seq 무결·cascade 삭제를 강제."""

    def __init__(self) -> None:
        self._jobs: dict[str, NoveltyJob] = {}
        self._artifacts: dict[tuple[str, str], ArtifactRecord] = {}
        self._trace: dict[str, list[ToolCallRecord]] = {}
        self._messages: dict[str, list[NoveltyChatMessage]] = {}

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
            start = ids.index(cursor) + 1 if cursor in ids else len(owned)
            owned = owned[start:]
        return [job.model_copy(deep=True) for job in owned[:limit]]

    def update_job(self, job: NoveltyJob) -> None:
        if job.job_id not in self._jobs:
            raise KeyError(job.job_id)
        self._jobs[job.job_id] = job.model_copy(deep=True)

    def delete_job(self, owner_id: str, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return False
        del self._jobs[job_id]
        # cascade — 산출물·트레이스·대화 동반 삭제(BR-NV18 개정).
        for key in [key for key in self._artifacts if key[0] == job_id]:
            del self._artifacts[key]
        self._trace.pop(job_id, None)
        self._messages.pop(job_id, None)
        return True

    def request_cancel(self, owner_id: str, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.owner_id != owner_id:
            return False
        job.cancel_requested = True
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        return bool(job and job.cancel_requested)

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
            start = ids.index(after) + 1 if after in ids else len(messages)
            messages = messages[start:]
        return [message.model_copy(deep=True) for message in messages[:limit]]


class InMemoryJobQueue:
    """JobQueuePort + ExecutionLockPort 기준 구현(리스 TTL 의미론)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._queue: deque[QueuedJob] = deque()
        self._locks: dict[str, float] = {}
        self._clock = clock

    def enqueue(self, job_id: str, owner_id: str) -> None:
        self._queue.append(QueuedJob(job_id=job_id, owner_id=owner_id))

    def consume(self, timeout_seconds: float) -> QueuedJob | None:
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


class ScriptedToolCallingLlm:
    """결정 시퀀스를 재생하는 LLM 페이크 — 루프 코어의 결정론 검증용."""

    def __init__(
        self,
        script: Iterable[LlmDecision | Callable[[LoopObservation], LlmDecision]],
    ) -> None:
        self._script = deque(script)
        self.observations: list[LoopObservation] = []

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        self.observations.append(observation)
        if not self._script:
            raise AssertionError("scripted LLM exhausted — loop asked for more decisions")
        step = self._script.popleft()
        return step(observation) if callable(step) else step


class FakeTool:
    """설정 가능한 도구 페이크."""

    def __init__(
        self,
        name: str,
        results: Iterable[ToolResult] | None = None,
        default: ToolResult | None = None,
    ) -> None:
        self.spec = ToolSpec(name=name, description=f"fake {name}", parameters={"type": "object"})
        self._results = deque(results or ())
        self._default = default or ToolResult(ok=True, result_summary=f"{name} ok")
        self.calls: list[tuple[dict[str, Any], ToolContext]] = []

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append((args, ctx))
        return self._results.popleft() if self._results else self._default
