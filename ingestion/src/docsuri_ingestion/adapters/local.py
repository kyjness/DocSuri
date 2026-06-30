from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from docsuri_shared.dtos import DocModel
from docsuri_shared.events import NewArxivEvent
from docsuri_shared.vector_spec import DIMENSIONS, IndexRecord

from docsuri_ingestion.domain.canonical import source_priority_from_tier
from docsuri_ingestion.domain.enums import DedupDecision, DedupStateKind, FailureReason
from docsuri_ingestion.domain.errors import RetriableIngestionError
from docsuri_ingestion.domain.models import (
    CanonicalDedupState,
    CategoryFilter,
    DedupResult,
    DedupState,
    IndexRecordBatch,
    IndexStats,
    IngestionJob,
    MetadataRecord,
    ParsedPaper,
    RawDocument,
    Tombstone,
    Watermark,
)


class FakeArxivSource:
    def __init__(
        self, metadata: list[MetadataRecord], full_text: dict[str, str] | None = None
    ) -> None:
        self._metadata = {record.arxiv_ref: record for record in metadata}
        self._full_text = full_text or {}

    def harvest_seed(self, category_filter: CategoryFilter):
        for record in self._metadata.values():
            if set(record.categories).intersection(category_filter.categories):
                yield record

    def fetch_incremental(self, since: datetime, categories):
        for record in self._metadata.values():
            if record.updated_at > since and set(record.categories).intersection(categories):
                yield record

    def fetch_metadata(self, arxiv_ref: str) -> MetadataRecord:
        return self._metadata[arxiv_ref]

    def fetch_full_text(self, metadata: MetadataRecord) -> RawDocument:
        text = self._full_text.get(metadata.arxiv_ref) or self._full_text.get(metadata.paper_id)
        if text is None:
            text = (
                f"INTRODUCTION\n{metadata.abstract}\nMETHOD\nThis is deterministic local full text."
            )
        return RawDocument(metadata=metadata, text=text, source_url=f"local://{metadata.arxiv_ref}")

    def fetch_html_source(self, arxiv_id: str):
        del arxiv_id
        return None


def _winner_supersedes(new: CanonicalDedupState, old: CanonicalDedupState) -> bool:
    """Whether ``new`` should overwrite ``old`` as canonical winner: higher source priority, or
    same priority and a newer-or-equal version (BR-C3/BR-14)."""
    new_p = source_priority_from_tier(new.winning_source_tier)
    old_p = source_priority_from_tier(old.winning_source_tier)
    if new_p != old_p:
        return new_p < old_p
    return new.winning_version >= old.winning_version


def _merge_seen_sources(old: tuple, new: tuple) -> tuple:
    merged = list(old)
    for source in new:
        if source not in merged:
            merged.append(source)
    return tuple(merged)


class InMemoryControlPlaneStore:
    def __init__(self) -> None:
        self._dedup: dict[str, DedupState] = {}
        self._canonical: dict[str, CanonicalDedupState] = {}
        self._watermarks: dict[str, Watermark] = {}
        self._jobs: dict[str, dict[str, Any]] = {}
        self._rebuild_owner: str | None = None
        self._lock = threading.Lock()

    @property
    def dedup_states(self) -> dict[str, DedupState]:
        return dict(self._dedup)

    def get_watermark(self, name: str = "arxiv") -> Watermark:
        return self._watermarks.get(name, Watermark.epoch(name))

    def advance_watermark(self, name: str, candidate: datetime) -> Watermark:
        with self._lock:
            current = self.get_watermark(name)
            advanced = current.advance(candidate)
            self._watermarks[name] = advanced
            return advanced

    def reset_watermark_for_rebuild(self, name: str, value: datetime) -> Watermark:
        with self._lock:
            watermark = Watermark(name=name, updated_at=value)
            self._watermarks[name] = watermark
            return watermark

    def evaluate_dedup(self, paper_id: str, version: int, fingerprint: str) -> DedupResult:
        state = self._dedup.get(paper_id)
        if state is None:
            return DedupResult(DedupDecision.NEW)
        if version < state.current_version:
            return DedupResult(DedupDecision.STALE, state)
        if (
            version == state.current_version
            and state.fingerprint == fingerprint
            and state.state is DedupStateKind.INDEXED
        ):
            return DedupResult(DedupDecision.DUPLICATE, state)
        return DedupResult(DedupDecision.CHANGED, state)

    def try_claim_upsert(self, paper_id: str, version: int, fingerprint: str) -> bool:
        del fingerprint
        with self._lock:
            current = self._dedup.get(paper_id)
            if current is not None and current.current_version > version:
                return False
            self._dedup[paper_id] = DedupState(
                paper_id=paper_id,
                current_version=version,
                fingerprint=None,
                state=DedupStateKind.INDEXED,
            )
            return True

    def mark_ingested(self, paper_id: str, version: int, fingerprint: str) -> None:
        with self._lock:
            current = self._dedup.get(paper_id)
            if current is None or current.current_version != version:
                return
            self._dedup[paper_id] = DedupState(
                paper_id=paper_id,
                current_version=version,
                fingerprint=fingerprint,
                state=DedupStateKind.INDEXED,
                ingested_at=datetime.now(UTC),
            )

    def try_claim_tombstone(self, paper_id: str, version: int) -> bool:
        with self._lock:
            current = self._dedup.get(paper_id)
            if current is not None and current.current_version > version:
                return False
            self._dedup[paper_id] = DedupState(
                paper_id=paper_id,
                current_version=version,
                fingerprint=None,
                state=DedupStateKind.TOMBSTONED,
                ingested_at=datetime.now(UTC),
            )
            return True

    def get_canonical_dedup_state(self, canonical_key: str) -> CanonicalDedupState | None:
        return self._canonical.get(canonical_key)

    def list_canonical_dedup_states_for_paper(
        self, paper_id: str
    ) -> tuple[CanonicalDedupState, ...]:
        return tuple(state for state in self._canonical.values() if state.paper_id == paper_id)

    def upsert_canonical_dedup_state(self, state: CanonicalDedupState) -> None:
        # Guarded, monotonic upsert (BR-C3/BR-14): keep the higher-priority/newer winner and
        # always merge seen_sources, so two sources racing on one canonical_key can't lost-update
        # each other. Mirrors the Postgres ON CONFLICT guard.
        with self._lock:
            existing = self._canonical.get(state.canonical_key)
            merged = _merge_seen_sources(
                existing.seen_sources if existing else (), state.seen_sources
            )
            supersedes = existing is None or _winner_supersedes(state, existing)
            winner = state if supersedes else existing
            self._canonical[state.canonical_key] = replace(winner, seen_sources=merged)

    def delete_canonical_dedup_state_for_paper(self, paper_id: str) -> None:
        with self._lock:
            for key in [
                key for key, state in self._canonical.items() if state.paper_id == paper_id
            ]:
                del self._canonical[key]

    def acquire_rebuild_lock(self, owner: str) -> bool:
        with self._lock:
            if self._rebuild_owner is not None:
                return False
            self._rebuild_owner = owner
            return True

    def release_rebuild_lock(self, owner: str) -> None:
        with self._lock:
            if self._rebuild_owner == owner:
                self._rebuild_owner = None

    def is_rebuild_active(self) -> bool:
        return self._rebuild_owner is not None

    def record_job_started(self, job: IngestionJob) -> None:
        self._jobs[job.job_id] = {"kind": job.kind.value, "status": "STARTED"}

    def record_job_finished(self, job_id: str, *, success: bool, detail: str | None = None) -> None:
        self._jobs[job_id] = {
            **self._jobs.get(job_id, {}),
            "status": "SUCCEEDED" if success else "FAILED",
            "detail": detail,
        }


class FakeEmbeddingPort:
    def embed_documents(self, texts, *, correlation_id: str | None = None) -> list[list[float]]:
        del correlation_id
        return [deterministic_vector(text) for text in texts]


class InMemoryVectorIndex:
    def __init__(self, *, fail_bulk: bool = False) -> None:
        self.records: dict[str, IndexRecord] = {}
        self.tombstones: list[Tombstone] = []
        self.fail_bulk = fail_bulk
        self.bulk_calls = 0

    def bulk_upsert(self, batch: IndexRecordBatch) -> None:
        self.bulk_calls += 1
        if self.fail_bulk:
            raise RetriableIngestionError(
                "injected bulk failure",
                reason=FailureReason.BULK_INDEX_PARTIAL_FAILURE,
                stage="index",
            )
        for record in batch.records:
            self.records[record.chunkId] = record

    def tombstone_paper(self, tombstone: Tombstone) -> None:
        self.tombstones.append(tombstone)
        for chunk_id in [
            chunk_id
            for chunk_id, record in self.records.items()
            if record.paperId == tombstone.paper_id
        ]:
            del self.records[chunk_id]

    def delete_stale_chunks(self, paper_id: str, keep_chunk_ids: set[str]) -> None:
        for chunk_id in [
            chunk_id
            for chunk_id, record in self.records.items()
            if record.paperId == paper_id and chunk_id not in keep_chunk_ids
        ]:
            del self.records[chunk_id]

    def index_stats(self) -> IndexStats:
        now = datetime.now(UTC)
        return IndexStats(
            status="HEALTHY",
            timestamp=now,
            index_name="memory",
            total_documents=len(self.records),
            vector_count=len(self.records),
            last_write_timestamp=now if self.records else None,
            dependencies={"opensearch": "UP"},
        )


class InMemoryFullTextStore:
    def __init__(self) -> None:
        self.objects: dict[str, str] = {}

    def put_full_text(self, paper: ParsedPaper) -> str:
        ref = f"memory://full-text/{paper.paper_id}/v{paper.version}.txt"
        self.objects[ref] = paper.full_text
        return ref


class InMemoryDocModelStore:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, int], DocModel] = {}

    def get(self, paper_id: str, version: int) -> DocModel | None:
        return self.objects.get((paper_id, version))

    def put(self, doc: DocModel) -> str:
        key = (doc.meta.paperId, doc.meta.version)
        self.objects[key] = doc
        return f"memory://doc-model/{doc.meta.paperId}/v{doc.meta.version}.json"

    def remove(self, paper_id: str) -> None:
        for key in [key for key in self.objects if key[0] == paper_id]:
            del self.objects[key]


@dataclass(frozen=True, slots=True)
class InMemoryQueueMessage:
    message_id: str
    receipt_handle: str
    body: dict[str, Any]


class InMemoryQueue:
    def __init__(self) -> None:
        self.jobs: list[IngestionJob] = []
        self.dlq: list[dict[str, Any]] = []
        self.acked: list[str] = []

    def send_job(self, job: IngestionJob) -> None:
        self.jobs.append(job)

    def receive_messages(self, max_messages: int = 10) -> list[InMemoryQueueMessage]:
        messages: list[InMemoryQueueMessage] = []
        for job in self.jobs[:max_messages]:
            messages.append(
                InMemoryQueueMessage(
                    message_id=job.job_id,
                    receipt_handle=job.job_id,
                    body={"type": "ingest_paper", **job.to_payload()},
                )
            )
        self.jobs = self.jobs[max_messages:]
        return messages

    def ack(self, message: InMemoryQueueMessage) -> None:
        self.acked.append(message.message_id)

    def send_to_dlq(self, payload: dict[str, Any], *, reason: str) -> None:
        self.dlq.append({"payload": payload, "reason": reason})

    def parse_new_arxiv_event(self, payload: dict[str, Any]) -> NewArxivEvent:
        return NewArxivEvent.model_validate(payload)


class CapturingObservabilityHub:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict[str, str]]] = []
        self.logs: list[dict[str, Any]] = []
        self.failures: list[dict[str, str]] = []

    def emit_metric(self, name: str, value: float, tags=None) -> None:
        self.metrics.append((name, value, dict(tags or {})))

    def emit_log(self, entry) -> None:
        self.logs.append(dict(entry))

    def emit_failure_signal(self, job_id: str, *, stage: str, error: str) -> None:
        self.failures.append({"job_id": job_id, "stage": stage, "error": error})


class FailingEmbeddingPort:
    def __init__(
        self, *, fail_times: int, reason: FailureReason = FailureReason.RATE_LIMITED
    ) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.reason = reason

    def embed_documents(self, texts, *, correlation_id: str | None = None) -> list[list[float]]:
        del correlation_id
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RetriableIngestionError(
                "injected embedding failure", reason=self.reason, stage="embed"
            )
        return [deterministic_vector(text) for text in texts]


def deterministic_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values = []
    for index in range(DIMENSIONS):
        byte = digest[index % len(digest)]
        values.append((byte / 255.0) * 2.0 - 1.0)
    return values


def sample_metadata(arxiv_ref: str = "2401.00001v1") -> MetadataRecord:
    now = datetime(2024, 1, 1, tzinfo=UTC)
    return MetadataRecord(
        arxiv_ref=arxiv_ref,
        title="A Local Test Paper",
        authors=("Ada Lovelace", "Grace Hopper"),
        abstract="This paper studies deterministic ingestion for retrieval systems.",
        categories=("cs.LG",),
        updated_at=now,
        published_at=now,
        license_url="https://creativecommons.org/licenses/by/4.0/",
        primary_category="cs.LG",
    )
