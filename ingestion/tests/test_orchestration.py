from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from docsuri_shared.dtos import DocModel
from docsuri_shared.vector_spec import DIMENSIONS, IndexRecord

import docsuri_ingestion.worker as worker_module
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
from docsuri_ingestion.config import CORPUS_END, CORPUS_START
from docsuri_ingestion.corpus_sources import CorpusSourceAdapterSet, SourcePaperRecord
from docsuri_ingestion.docmodel.builder import DocModelBuilder
from docsuri_ingestion.domain.canonical import canonical_key
from docsuri_ingestion.domain.enums import DedupDecision, FailureReason, JobKind, SourceName
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.domain.models import CanonicalDedupState, IndexRecordBatch, IngestionJob
from docsuri_ingestion.settings import IngestionSettings
from docsuri_ingestion.worker import job_from_payload, process_message

from .conftest import build_test_pipeline


class _NoHtmlDocModelSource:
    def fetch_html_source(self, arxiv_id: str):
        del arxiv_id
        return None


class _DocModelStore:
    def __init__(self) -> None:
        self.docs: list[DocModel] = []
        self.removed: list[str] = []

    def get(self, paper_id: str, version: int) -> DocModel | None:
        del paper_id, version
        return None

    def put(self, doc: DocModel) -> str:
        self.docs.append(doc)
        return "memory://doc-model"

    def remove(self, paper_id: str) -> None:
        self.removed.append(paper_id)


class _AssetStore:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove_assets(self, paper_id: str) -> None:
        self.removed.append(paper_id)


class _ExternalSource:
    def __init__(self, record: SourcePaperRecord) -> None:
        self.record = record
        self.fetched_pdf_for: SourcePaperRecord | None = None
        self.incremental_calls: list[tuple[datetime, tuple[str, ...], datetime | None]] = []

    def fetch_incremental(self, since, categories, until=None):
        self.incremental_calls.append((since, tuple(categories), until))
        return (self.record,)

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        self.fetched_pdf_for = record
        return b"%PDF"


class _Grobid:
    def __init__(self, text: str = "PDF extracted full text") -> None:
        self.text = text
        self.seen_pdf: bytes | None = None

    def extract_tei(self, pdf: bytes) -> str:
        self.seen_pdf = pdf
        return f"<TEI><text><body><div><p>{self.text}</p></div></body></text></TEI>"


def _external_record() -> SourcePaperRecord:
    return SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id="oa-1",
        title="External PDF Paper",
        abstract="External abstract",
        authors=("Ada Lovelace",),
        categories=("cs.LG",),
        updated_at=datetime(2025, 6, 2, tzinfo=UTC),
        published_at=datetime(2025, 6, 1, tzinfo=UTC),
        pdf_url="https://example.test/paper.pdf",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        doi="10.1000/external",
    )


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
    pipeline = SimpleNamespace(ingest_one=seen.append, is_rebuild_active=lambda: False)
    runtime = SimpleNamespace(pipeline=pipeline, queue=queue, observability=observability)

    process_message(runtime, message)

    assert queue.acked == ["legacy-job"]
    assert queue.dlq == []
    assert seen[0].job_id == "job-1"


def test_worker_main_uses_configured_polling_limits(monkeypatch) -> None:
    class FakeEvent:
        def __init__(self) -> None:
            self.stopped = False
            self.waits: list[float] = []

        def is_set(self) -> bool:
            return self.stopped

        def wait(self, timeout: float) -> None:
            self.waits.append(timeout)
            self.stopped = True

    class FakeQueue:
        def __init__(self) -> None:
            self.calls: list[int] = []

        def receive_messages(self, max_messages: int = 10):
            self.calls.append(max_messages)
            return []

    event = FakeEvent()
    queue = FakeQueue()
    docmodel_queue = FakeQueue()
    settings = IngestionSettings(
        DOCSURI_WORKER_MAX_MESSAGES=25,
        DOCSURI_WORKER_LOOP_DELAY_SECONDS=7.5,
    )
    runtime = SimpleNamespace(queue=queue, docmodel_queue=docmodel_queue)

    monkeypatch.setattr(worker_module, "_shutdown_event", event)
    monkeypatch.setattr(worker_module.IngestionSettings, "from_env", lambda: settings)
    monkeypatch.setattr(worker_module, "build_production_runtime", lambda _settings: runtime)

    assert worker_module.main([]) == 0

    assert docmodel_queue.calls == [10]
    assert queue.calls == [10]
    assert event.waits == [7.5]


def test_worker_main_docmodel_mode_does_not_poll_bulk_queue(monkeypatch) -> None:
    class FakeEvent:
        def __init__(self) -> None:
            self.stopped = False

        def is_set(self) -> bool:
            return self.stopped

        def wait(self, timeout: float) -> None:
            del timeout
            self.stopped = True

    class FakeQueue:
        def __init__(self, messages=None) -> None:
            self.messages = messages or []
            self.calls: list[int] = []

        def receive_messages(self, max_messages: int = 10):
            self.calls.append(max_messages)
            return self.messages

    event = FakeEvent()
    queue = FakeQueue()
    docmodel_queue = FakeQueue()
    settings = IngestionSettings(
        DOCSURI_WORKER_QUEUE_MODE="docmodel",
        DOCSURI_DOCMODEL_QUEUE_URL="https://sqs.example/docmodel",
    )
    runtime = SimpleNamespace(queue=queue, docmodel_queue=docmodel_queue)

    monkeypatch.setattr(worker_module, "_shutdown_event", event)
    monkeypatch.setattr(worker_module.IngestionSettings, "from_env", lambda: settings)
    monkeypatch.setattr(worker_module, "build_production_runtime", lambda _settings: runtime)

    assert worker_module.main([]) == 0

    assert docmodel_queue.calls == [1]
    assert queue.calls == []


def test_queue_payload_preserves_corpus_retry_metadata() -> None:
    _, _, _, queue, _ = build_test_pipeline()
    source_record = _external_record().to_payload()
    job = IngestionJob(
        job_id="job-meta",
        kind=JobKind.INCREMENTAL,
        arxiv_ref="2401.00001v1",
        source_name=SourceName.OPENALEX,
        failure_stage="grobid",
        canonical_key="doi:10.1000/x",
        paper_id="p1",
        version=3,
        source_record=source_record,
    )
    queue.send_job(job)

    message = queue.receive_messages(max_messages=1)[0]
    parsed = job_from_payload(message.body)

    assert parsed.source_name is SourceName.OPENALEX
    assert parsed.failure_stage == "grobid"
    assert parsed.canonical_key == "doi:10.1000/x"
    assert parsed.paper_id == "p1"
    assert parsed.version == 3
    assert parsed.source_record == source_record


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
        blockRefs=[],
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


class FakeOpenSearchIndices:
    def __init__(self, aliases):
        self.aliases = aliases
        self.update_body = None

    def get_alias(self, *, name: str, ignore=None):
        del name, ignore
        return dict(self.aliases)

    def update_aliases(self, *, body):
        self.update_body = body


class FakeOpenSearchAliasClient:
    def __init__(self, *, count: int = 1, aliases=None) -> None:
        self.indices = FakeOpenSearchIndices(aliases or {"old-index": {}})
        self._count = count

    def count(self, *, index: str):
        del index
        return {"count": self._count}


def test_opensearch_generation_validation_blocks_empty_candidate() -> None:
    index = OpenSearchVectorIndex.__new__(OpenSearchVectorIndex)
    index._client = FakeOpenSearchAliasClient(count=0)
    index._index_name = "candidate-index"
    index._last_write_timestamp = None

    with pytest.raises(PermanentIngestionError):
        index.validate_generation(min_documents=1)


def test_opensearch_switch_alias_cutover_is_separate_from_write() -> None:
    client = FakeOpenSearchAliasClient(aliases={"old-index": {}, "unrelated": {}})
    index = OpenSearchVectorIndex.__new__(OpenSearchVectorIndex)
    index._client = client
    index._index_name = "candidate-index"

    index.switch_alias(
        alias_name="docsuri-corpus", target_index="candidate-index", previous_index="old-index"
    )

    assert client.indices.update_body == {
        "actions": [
            {"remove": {"index": "old-index", "alias": "docsuri-corpus"}},
            {"add": {"index": "candidate-index", "alias": "docsuri-corpus"}},
        ]
    }


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


def test_refresh_wires_configured_external_sources_into_queue() -> None:
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
    record = _external_record()
    provider = _ExternalSource(record)
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.OPENALEX,),
    )

    assert service.on_schedule_tick() == 1

    job = queue.jobs[0]
    assert job.source_name is SourceName.OPENALEX
    assert job.source_record == record.to_payload()
    assert job.canonical_key == "doi:10.1000/external"


def test_schedule_tick_isolates_a_failing_external_source() -> None:
    # A single external source raising must NOT abort the tick or crash the worker — it should
    # be caught, emit a failure metric, and let the tick finish. Regression for the SS 400 that
    # propagated to worker.main -> SystemExit.
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

    class _RaisingExternalSource:
        def fetch_incremental(self, since, categories, until=None):
            raise PermanentIngestionError(
                "boom", reason=FailureReason.FETCH_FAILURE, stage="source"
            )

        def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
            raise AssertionError("fetch_pdf should not be called")

    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=_RaisingExternalSource(),
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.ARXIV, SourceName.OPENALEX),
    )

    service.on_schedule_tick()  # must not raise

    names = [name for name, _, _ in observability.metrics]
    assert "ingestion.source.incremental.failed" in names  # the bad source was isolated
    assert "ingestion.incremental.queued" in names  # the tick still reached completion
    failed_tags = [
        tags for name, _, tags in observability.metrics
        if name == "ingestion.source.incremental.failed"
    ]
    assert failed_tags[0]["source"] == "OPENALEX"


def test_full_rebuild_wires_configured_external_sources_as_seed_jobs() -> None:
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
    record = _external_record()
    provider = _ExternalSource(record)
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.ARXIV, SourceName.OPENALEX),
    )

    assert service.trigger_full_rebuild(owner="test") == 2

    external_job = next(job for job in queue.jobs if job.source_name is SourceName.OPENALEX)
    assert external_job.kind is JobKind.SEED_REBUILD
    assert external_job.source_record == record.to_payload()
    assert external_job.canonical_key == "doi:10.1000/external"
    assert CORPUS_END - CORPUS_START <= timedelta(days=366)
    assert control.get_watermark("openalex").updated_at == CORPUS_START
    assert provider.incremental_calls[0][0] == CORPUS_START
    assert provider.incremental_calls[0][2] == CORPUS_END


def test_full_rebuild_skips_external_records_outside_corpus_window() -> None:
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
    provider = _ExternalSource(
        replace(
            _external_record(),
            source_id="oa-late",
            updated_at=CORPUS_END + timedelta(days=1),
            doi="10.1000/late",
        )
    )
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([]),
        openalex=provider,
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.OPENALEX,),
    )

    assert service.trigger_full_rebuild(owner="test") == 0
    assert queue.jobs == []


def test_backfill_external_sources_enqueues_only_external_seed_jobs_in_window() -> None:
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
    record = _external_record()  # updated_at 2025-06-02, inside the window below
    provider = _ExternalSource(record)
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.ARXIV, SourceName.OPENALEX),
    )

    since = datetime(2025, 1, 1, tzinfo=UTC)
    until = datetime(2025, 12, 31, tzinfo=UTC)
    assert service.backfill_external_sources(since, until) == 1

    # arXiv is NOT re-harvested — only the external source is enqueued, and as a SEED job.
    assert len(queue.jobs) == 1
    job = queue.jobs[0]
    assert job.source_name is SourceName.OPENALEX
    assert job.kind is JobKind.SEED_REBUILD
    # The run-scoped window is passed straight through to the source adapter.
    assert provider.incremental_calls[0][0] == since
    assert provider.incremental_calls[0][2] == until


def test_backfill_external_sources_isolates_a_failing_source() -> None:
    # One source exhausting its retries (raises) must NOT abort the backfill or drop the others.
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

    class _RaisingExternalSource:
        def fetch_incremental(self, since, categories, until=None):
            raise RetriableIngestionError(
                "rate limited", reason=FailureReason.RATE_LIMITED, stage="semantic_scholar"
            )

        def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
            raise AssertionError("fetch_pdf should not be called")

    good = _ExternalSource(_external_record())
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        semantic_scholar=_RaisingExternalSource(),
        openalex=good,
        grobid=_Grobid(),
    )
    service = RefreshOrchestrationService(
        arxiv=FakeArxivSource([sample_metadata()]),
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=(SourceName.ARXIV, SourceName.SEMANTIC_SCHOLAR, SourceName.OPENALEX),
    )

    queued = service.backfill_external_sources(
        datetime(2025, 1, 1, tzinfo=UTC), datetime(2025, 12, 31, tzinfo=UTC)
    )  # must not raise despite SS failing

    assert queued == 1  # OpenAlex still enqueued
    assert queue.jobs[0].source_name is SourceName.OPENALEX
    failed = [
        tags for name, _, tags in observability.metrics
        if name == "ingestion.backfill.external.failed"
    ]
    assert failed and failed[0]["source"] == "SEMANTIC_SCHOLAR"


def test_source_record_ingest_uses_grobid_docmodel_and_source_watermark() -> None:
    record = _external_record()
    provider = _ExternalSource(record)
    grobid = _Grobid("GROBID text with equations and tables")
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
        grobid=grobid,
    )
    store = _DocModelStore()
    builder = DocModelBuilder(source=_NoHtmlDocModelSource(), store=store)
    pipeline, control, index, _, _ = build_test_pipeline(
        doc_model_builder=builder,
        corpus_sources=corpus_sources,
    )

    result = pipeline.ingest_one(
        IngestionJob(
            job_id="openalex-1",
            kind=JobKind.INCREMENTAL,
            source_name=SourceName.OPENALEX,
            source_record=record.to_payload(),
            canonical_key="doi:10.1000/external",
        )
    )

    assert result is DedupDecision.NEW
    assert provider.fetched_pdf_for == record
    assert grobid.seen_pdf == b"%PDF"
    assert store.docs
    assert "External abstract" in store.docs[0].fullText
    assert "GROBID text with equations and tables" in store.docs[0].fullText
    assert index.records
    assert any(
        any(ref.blockId == "s1.p1" for ref in record.blockRefs)
        for record in index.records.values()
    )
    indexed = next(iter(index.records.values()))
    assert indexed.doi == "10.1000/external"
    assert indexed.sourceArxivId is None
    assert indexed.sourceProvenance is not None
    assert indexed.sourceProvenance.sourceName == "OPENALEX"
    assert indexed.sourceProvenance.sourceId == "oa-1"
    assert indexed.sourceProvenance.sourceTier == "OPENALEX_GROBID"
    assert indexed.sourceProvenance.sourceUrl == "https://example.test/paper.pdf"
    assert control.get_watermark("openalex").updated_at == record.updated_at
    assert control.get_canonical_dedup_state("doi:10.1000/external") is not None


def test_arxiv_replaces_doi_only_external_winner_through_title_alias() -> None:
    published = datetime(2025, 6, 1, tzinfo=UTC)
    external = replace(
        _external_record(),
        title="Shared Canonical Paper",
        abstract="Shared abstract",
        authors=("Ada Lovelace",),
        published_at=published,
        updated_at=published,
        arxiv_id=None,
        doi="10.1000/shared",
    )
    arxiv_metadata = replace(
        sample_metadata("2506.00001v1"),
        title=external.title,
        abstract=external.abstract,
        authors=external.authors,
        published_at=published,
        updated_at=published,
    )
    provider = _ExternalSource(external)
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([arxiv_metadata]),
        openalex=provider,
        grobid=_Grobid("External lower-priority text"),
    )
    arxiv = FakeArxivSource(
        [arxiv_metadata],
        full_text={"2506.00001v1": "INTRODUCTION\nArXiv higher-priority text"},
    )
    pipeline, control, index, _, _ = build_test_pipeline(
        arxiv=arxiv,
        corpus_sources=corpus_sources,
    )
    doi_key = "doi:10.1000/shared"
    title_key = canonical_key(
        title=external.title,
        year=2025,
        first_author=external.authors[0],
    )

    assert (
        pipeline.ingest_one(
            IngestionJob(
                job_id="openalex-shared",
                kind=JobKind.INCREMENTAL,
                source_name=SourceName.OPENALEX,
                source_record=external.to_payload(),
                canonical_key=doi_key,
            )
        )
        is DedupDecision.NEW
    )
    old_state = control.get_canonical_dedup_state(doi_key)
    assert old_state is not None
    old_paper_id = old_state.paper_id
    assert control.get_canonical_dedup_state(title_key).paper_id == old_paper_id

    result = pipeline.ingest_one(
        IngestionJob(job_id="arxiv-shared", kind=JobKind.INCREMENTAL, arxiv_ref="2506.00001v1")
    )

    assert result is DedupDecision.NEW
    for key in (doi_key, title_key, "arxiv:2506.00001"):
        state = control.get_canonical_dedup_state(key)
        assert state is not None
        assert state.paper_id == "2506.00001"
        assert state.winning_source_tier == "ARXIV_HTML"
    assert all(record.paperId != old_paper_id for record in index.records.values())
    assert index.tombstones[-1].paper_id == old_paper_id
    assert index.tombstones[-1].reason == "CANONICAL_SOURCE_REPLACED"


def test_source_record_skips_pdf_fetch_when_higher_priority_winner_exists() -> None:
    record = _external_record()
    provider = _ExternalSource(record)
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=FakeArxivSource([sample_metadata()]),
        openalex=provider,
        grobid=_Grobid(),
    )
    pipeline, control, index, _, _ = build_test_pipeline(corpus_sources=corpus_sources)
    control.upsert_canonical_dedup_state(
        CanonicalDedupState(
            canonical_key="doi:10.1000/external",
            paper_id="2401.00001",
            winning_source_tier="ARXIV_HTML",
            winning_version=1,
            fingerprint="fp",
            seen_sources=(SourceName.ARXIV,),
        )
    )

    result = pipeline.ingest_one(
        IngestionJob(
            job_id="openalex-duplicate",
            kind=JobKind.INCREMENTAL,
            source_name=SourceName.OPENALEX,
            source_record=record.to_payload(),
            canonical_key="doi:10.1000/external",
        )
    )

    state = control.get_canonical_dedup_state("doi:10.1000/external")
    assert result is DedupDecision.DUPLICATE
    assert provider.fetched_pdf_for is None
    assert index.records == {}
    assert state is not None
    assert state.seen_sources == (SourceName.ARXIV, SourceName.OPENALEX)


def test_arxiv_replaces_lower_priority_canonical_winner() -> None:
    old_paper_id = "src-old-openalex"
    arxiv_key = "arxiv:2401.00001"
    store = _DocModelStore()
    builder = DocModelBuilder(source=_NoHtmlDocModelSource(), store=store)
    asset_store = _AssetStore()
    pipeline, control, index, _, _ = build_test_pipeline(
        doc_model_builder=builder,
        asset_store=asset_store,
    )
    control.upsert_canonical_dedup_state(
        CanonicalDedupState(
            canonical_key=arxiv_key,
            paper_id=old_paper_id,
            winning_source_tier="OPENALEX_GROBID",
            winning_version=1,
            fingerprint="old-fp",
            seen_sources=(SourceName.OPENALEX,),
        )
    )
    index.records["old-openalex:0000"] = IndexRecord(
        chunkId="old-openalex:0000",
        paperId=old_paper_id,
        version=1,
        vector=[0.0] * DIMENSIONS,
        section="body",
        lexicalTerms="old duplicate",
        blockRefs=[],
        title="Old Duplicate",
        authors=["Old"],
        year=2024,
        arxivId="",
        abstract="old",
        abstractSnippet="old",
        arxivUrl="https://example.test/old",
        categories=["cs.LG"],
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="arxiv-replaces", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
    )

    state = control.get_canonical_dedup_state(arxiv_key)
    assert result is DedupDecision.NEW
    assert state is not None
    assert state.paper_id == "2401.00001"
    assert state.winning_source_tier == "ARXIV_HTML"
    assert state.seen_sources == (SourceName.OPENALEX, SourceName.ARXIV)
    assert all(record.paperId != old_paper_id for record in index.records.values())
    assert index.tombstones[-1].reason == "CANONICAL_SOURCE_REPLACED"
    assert store.removed == [old_paper_id]
    assert asset_store.removed == [old_paper_id]


def test_withdrawn_arxiv_does_not_replace_external_canonical_winner() -> None:
    old_paper_id = "src-old-openalex"
    arxiv_key = "arxiv:2401.00001"
    arxiv = FakeArxivSource(
        [sample_metadata()],
        full_text={"2401.00001v1": "This paper has been withdrawn by the authors."},
    )
    pipeline, control, index, _, _ = build_test_pipeline(arxiv=arxiv)
    control.upsert_canonical_dedup_state(
        CanonicalDedupState(
            canonical_key=arxiv_key,
            paper_id=old_paper_id,
            winning_source_tier="OPENALEX_GROBID",
            winning_version=1,
            fingerprint="old-fp",
            seen_sources=(SourceName.OPENALEX,),
        )
    )
    index.records["old-openalex:0000"] = IndexRecord(
        chunkId="old-openalex:0000",
        paperId=old_paper_id,
        version=1,
        vector=[0.0] * DIMENSIONS,
        section="body",
        lexicalTerms="old duplicate",
        blockRefs=[],
        title="Old Duplicate",
        authors=["Old"],
        year=2024,
        arxivId="",
        abstract="old",
        abstractSnippet="old",
        arxivUrl="https://example.test/old",
        categories=["cs.LG"],
    )

    result = pipeline.ingest_one(
        IngestionJob(job_id="withdrawn-arxiv", kind=JobKind.INCREMENTAL, arxiv_ref="2401.00001v1")
    )

    state = control.get_canonical_dedup_state(arxiv_key)
    assert result is DedupDecision.CHANGED
    assert state is not None
    assert state.paper_id == old_paper_id
    assert any(record.paperId == old_paper_id for record in index.records.values())
    assert all(tombstone.paper_id != old_paper_id for tombstone in index.tombstones)


def test_withdrawn_arxiv_clears_itself_as_canonical_winner() -> None:
    arxiv_key = "arxiv:2401.00001"
    arxiv = FakeArxivSource(
        [sample_metadata()],
        full_text={"2401.00001v1": "This paper has been withdrawn by the authors."},
    )
    pipeline, control, _, _, _ = build_test_pipeline(arxiv=arxiv)
    control.upsert_canonical_dedup_state(
        CanonicalDedupState(
            canonical_key=arxiv_key,
            paper_id="2401.00001",
            winning_source_tier="ARXIV_HTML",
            winning_version=1,
            fingerprint="fp",
            seen_sources=(SourceName.ARXIV,),
        )
    )

    result = pipeline.ingest_one(
        IngestionJob(
            job_id="withdrawn-canonical-winner",
            kind=JobKind.INCREMENTAL,
            arxiv_ref="2401.00001v1",
        )
    )

    assert result is DedupDecision.CHANGED
    assert control.get_canonical_dedup_state(arxiv_key) is None


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


# --- patch #2: ingestion-blockage observability + NUL sanitization -----------------

def _sample_index_record() -> IndexRecord:
    return IndexRecord(
        chunkId="2401.00001:0000",
        paperId="2401.00001",
        version=1,
        vector=[0.0] * DIMENSIONS,
        section="abstract",
        lexicalTerms="retrieval augmented generation",
        blockRefs=[],
        title="A Test Paper",
        authors=["A. Author"],
        year=2024,
        arxivId="2401.00001v1",
        abstract="Abstract",
        abstractSnippet="Abstract",
        arxivUrl="https://arxiv.org/abs/2401.00001",
        categories=["cs.LG"],
    )


def test_bulk_failure_summary_keeps_fields_and_truncates_reason() -> None:
    from docsuri_ingestion.adapters.aws import _bulk_failure_summary

    out = _bulk_failure_summary(
        [{"_id": "p:0", "status": 400,
          "error": {"type": "mapper_parsing_exception", "reason": "x" * 500}}]
    )
    assert out[0]["id"] == "p:0"
    assert out[0]["status"] == 400
    assert out[0]["type"] == "mapper_parsing_exception"
    assert out[0]["reason"].endswith("…") and len(out[0]["reason"]) <= 201


def test_bulk_failure_summary_caps_the_list() -> None:
    from docsuri_ingestion.adapters.aws import _bulk_failure_summary

    failures = [{"_id": f"p:{i}", "status": 400, "error": {}} for i in range(20)]
    assert len(_bulk_failure_summary(failures)) == 5


def test_bulk_upsert_logs_rejection_reason_before_raising(caplog) -> None:
    import logging

    from docsuri_ingestion.domain.errors import RetriableIngestionError
    from docsuri_ingestion.domain.models import IndexRecordBatch

    class RejectingClient:
        def bulk(self, body):  # OpenSearch returns HTTP 200 with per-item failures
            return {
                "errors": True,
                "items": [
                    {
                        "index": {
                            "_id": "2401.00001:0000",
                            "status": 400,
                            "error": {
                                "type": "strict_dynamic_mapping_exception",
                                "reason": "mapping set to strict, dynamic introduction not allowed",
                            },
                        }
                    }
                ],
            }

    index = OpenSearchVectorIndex.__new__(OpenSearchVectorIndex)
    index._client = RejectingClient()
    index._index_name = "papers"
    index._stats_cache = FakeStatsCache()
    index._last_write_timestamp = None

    batch = IndexRecordBatch(
        paper_id="2401.00001", version=1, records=(_sample_index_record(),)
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(RetriableIngestionError):
            index.bulk_upsert(batch)
    # The previously-discarded per-item reason is now visible for diagnosis.
    assert "strict_dynamic_mapping_exception" in caplog.text


def test_no_nul_strips_nul_bytes_for_postgres_text() -> None:
    from docsuri_ingestion.adapters.assets import _no_nul

    assert _no_nul("Figure 1\x00 caption") == "Figure 1 caption"
    assert _no_nul("") == ""
    assert _no_nul(None) is None
