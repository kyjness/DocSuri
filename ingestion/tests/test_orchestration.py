from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from docsuri_shared.vector_spec import DIMENSIONS, IndexRecord

from docsuri_ingestion.adapters.aws import OpenSearchVectorIndex
from docsuri_ingestion.adapters.local import (
    FailingEmbeddingPort,
    FakeArxivSource,
    InMemoryControlPlaneStore,
    InMemoryQueue,
    InMemoryVectorIndex,
    sample_metadata,
)
from docsuri_ingestion.application import RefreshOrchestrationService
from docsuri_ingestion.domain.enums import DedupDecision, FailureReason, JobKind
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.domain.models import IndexRecordBatch, IngestionJob
from docsuri_ingestion.worker import job_from_payload, process_message

from .conftest import build_test_pipeline


def test_successful_ingestion_end_to_end_with_fake_adapters() -> None:
    pipeline, control, index, _, _ = build_test_pipeline()
    decision = pipeline.ingest_one(
        IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
    )
    assert decision is DedupDecision.NEW
    assert index.records
    assert control.dedup_states["2401.00001"].fingerprint
    assert control.get_watermark().updated_at == datetime(2024, 1, 1, tzinfo=UTC)


def test_duplicate_redelivery_short_circuits() -> None:
    pipeline, _, index, _, _ = build_test_pipeline()
    job = IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
    assert pipeline.ingest_one(job) is DedupDecision.NEW
    assert (
        pipeline.ingest_one(
            IngestionJob(job_id="job-2", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
        )
        is DedupDecision.DUPLICATE
    )
    assert index.bulk_calls == 1


def test_bulk_partial_failure_does_not_mark_ingested() -> None:
    pipeline, control, _, _, failures = build_test_pipeline(
        vector_index=InMemoryVectorIndex(fail_bulk=True)
    )
    with pytest.raises(RetriableIngestionError):
        pipeline.ingest_one(
            IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
        )
    state = control.dedup_states["2401.00001"]
    assert state.fingerprint is None
    assert failures.failures[-1]["stage"] == "index"


def test_bedrock_retry_recovers_after_429_like_failure() -> None:
    embedding = FailingEmbeddingPort(fail_times=1, reason=FailureReason.RATE_LIMITED)
    pipeline, _, index, _, metrics = build_test_pipeline(embedding=embedding, retry_attempts=2)
    assert (
        pipeline.ingest_one(
            IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
        )
        is DedupDecision.NEW
    )
    assert index.records
    assert any(name == "ingestion.retry" for name, _, _ in metrics.metrics)


class FlakyArxivSource(FakeArxivSource):
    def __init__(self):
        super().__init__([sample_metadata()])
        self.calls = 0

    def fetch_metadata(self, arxiv_ref: str):
        self.calls += 1
        if self.calls == 1:
            raise RetriableIngestionError(
                "temporary arXiv 5xx",
                reason=FailureReason.FETCH_FAILURE,
                stage="fetch_metadata",
            )
        return super().fetch_metadata(arxiv_ref)


class NotFoundArxivSource(FakeArxivSource):
    def __init__(self):
        super().__init__([sample_metadata()])

    def fetch_metadata(self, arxiv_ref: str):
        raise PermanentIngestionError(
            "arXiv 404",
            reason=FailureReason.FETCH_FAILURE,
            stage="fetch_metadata",
        )


def test_arxiv_5xx_retries_then_succeeds() -> None:
    arxiv = FlakyArxivSource()
    pipeline, _, index, _, _ = build_test_pipeline(arxiv=arxiv, retry_attempts=2)
    assert (
        pipeline.ingest_one(
            IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
        )
        is DedupDecision.NEW
    )
    assert arxiv.calls == 2
    assert index.records


def test_arxiv_404_permanent_failure_goes_to_dlq() -> None:
    pipeline, _, _, queue, _ = build_test_pipeline(arxiv=NotFoundArxivSource(), retry_attempts=1)
    with pytest.raises(PermanentIngestionError):
        pipeline.ingest_one(
            IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.99999v1")
        )
    assert queue.dlq[-1]["reason"] == FailureReason.FETCH_FAILURE.value


def test_worker_does_not_duplicate_pipeline_permanent_failure_dlq() -> None:
    pipeline, _, _, queue, observability = build_test_pipeline(
        arxiv=NotFoundArxivSource(), retry_attempts=1
    )
    queue.send_job(IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.99999v1"))
    message = queue.receive_messages(max_messages=1)[0]
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert len(queue.dlq) == 1
    assert queue.acked == [message.message_id]


def test_worker_dispatches_schedule_tick_and_acks() -> None:
    _, _, _, queue, observability = build_test_pipeline()
    refresh = SimpleNamespace(on_schedule_tick=lambda: 2)
    message = SimpleNamespace(
        message_id="tick-1",
        receipt_handle="tick-1",
        body={"type": "schedule_tick"},
    )
    runtime = SimpleNamespace(refresh=refresh, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == ["tick-1"]
    assert queue.dlq == []


def test_worker_dispatches_legacy_schedule_tick_action_and_acks() -> None:
    _, _, _, queue, observability = build_test_pipeline()
    refresh = SimpleNamespace(on_schedule_tick=lambda: 2)
    message = SimpleNamespace(
        message_id="tick-legacy",
        receipt_handle="tick-legacy",
        body={"action": "schedule_tick"},
    )
    runtime = SimpleNamespace(refresh=refresh, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == ["tick-legacy"]
    assert queue.dlq == []


def test_worker_dispatches_legacy_type_less_ingest_job() -> None:
    _, _, _, queue, observability = build_test_pipeline()
    seen: list[IngestionJob] = []
    message = SimpleNamespace(
        message_id="legacy-job",
        receipt_handle="legacy-job",
        body={"jobId": "job-1", "kind": "EVENT", "arxivRef": "2401.00001v1"},
    )
    pipeline = SimpleNamespace(ingest_one=seen.append)
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == ["legacy-job"]
    assert queue.dlq == []
    assert seen[0].job_id == "job-1"


def test_worker_sends_unknown_message_type_to_dlq() -> None:
    _, _, _, queue, observability = build_test_pipeline()
    message = SimpleNamespace(
        message_id="bad-1",
        receipt_handle="bad-1",
        body={"type": "unknown"},
    )
    runtime = SimpleNamespace(queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == ["bad-1"]
    assert queue.dlq[-1]["reason"] == FailureReason.POISON_EVENT.value


class FakeOpenSearchClient:
    def __init__(self) -> None:
        self.bulk_calls = 0

    def bulk(self, body: str):
        self.bulk_calls += 1
        return {"errors": False, "items": []}

    def count(self, *, index: str):
        return {"count": 1}


class FakeStatsCache:
    def __init__(self) -> None:
        self.invalidations = 0

    def invalidate(self) -> None:
        self.invalidations += 1


def test_opensearch_index_stats_reports_last_successful_write_timestamp() -> None:
    index = OpenSearchVectorIndex.__new__(OpenSearchVectorIndex)
    index._client = FakeOpenSearchClient()
    index._index_name = "papers"
    index._stats_cache = FakeStatsCache()
    index._last_write_timestamp = None
    record = IndexRecord(
        chunkId="2401.00001:0000",
        paperId="2401.00001",
        version=1,
        vector=[0.0] * DIMENSIONS,
        section="abstract",
        lexicalTerms="retrieval augmented generation",
        title="A Test Paper",
        authors=["A. Author"],
        year=2024,
        arxivId="2401.00001v1",
        abstract="Abstract",
        abstractSnippet="Abstract",
        arxivUrl="https://arxiv.org/abs/2401.00001",
        categories=["cs.LG"],
    )

    index.bulk_upsert(IndexRecordBatch(paper_id="2401.00001", version=1, records=(record,)))
    stats = index._fetch_stats()

    assert stats.last_write_timestamp is not None


def test_poison_event_payload_becomes_permanent_error_for_dlq_boundary() -> None:
    with pytest.raises(PermanentIngestionError):
        job_from_payload({"kind": "EVENT"})


def test_rebuild_lock_defers_incremental_and_event_paths() -> None:
    control = InMemoryControlPlaneStore()
    queue = InMemoryQueue()
    observability = type(
        "Obs",
        (),
        {
            "metrics": [],
            "emit_metric": lambda self, name, value, tags=None: self.metrics.append(
                (name, value, tags or {})
            ),
            "emit_log": lambda self, entry: None,
            "emit_failure_signal": lambda self, job_id, stage, error: None,
        },
    )()
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
    )
    assert control.acquire_rebuild_lock("test")
    assert service.on_schedule_tick() == 0
    assert not service.on_new_arxiv_event(
        type("Event", (), {"eventId": "e1", "arxivRef": "2401.00001v1"})()
    )
    assert not queue.jobs


def test_changed_version_replaces_stale_chunks() -> None:
    v1_meta = sample_metadata("2401.00001v1")
    v2_meta = sample_metadata("2401.00001v2")

    arxiv = FakeArxivSource(
        metadata=[v1_meta, v2_meta],
        full_text={
            "2401.00001v1": "body v1",
            "2401.00001v2": "body v2",
        },
    )

    pipeline, control, index, _, _ = build_test_pipeline(arxiv=arxiv)

    job1 = IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")
    assert pipeline.ingest_one(job1) is DedupDecision.NEW
    v1_count = len(index.records)
    assert v1_count >= 1
    assert all(record.version == 1 for record in index.records.values())

    job2 = IngestionJob(job_id="job-2", kind=JobKind.EVENT, arxiv_ref="2401.00001v2")
    assert pipeline.ingest_one(job2) is DedupDecision.CHANGED
    # stale v1 chunks are deleted and the new version fully replaces them — no accumulation
    # across versions, and identical body shape yields the same chunk count (not doubled).
    assert all(record.version == 2 for record in index.records.values())
    assert len(index.records) == v1_count
