from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from .asset_extraction import AssetExtractor
from .config import CORPUS_SLICE_CATEGORIES, WITHDRAWAL_MARKERS
from .corpus_sources import CorpusSourceAdapterSet, CorpusTextCandidate, SourcePaperRecord
from .docmodel import DocModelBuilder
from .domain.canonical import canonical_key
from .domain.enums import DedupDecision, FailureClass, FailureReason, JobKind, SourceName
from .domain.errors import IngestionError, PermanentIngestionError
from .domain.models import (
    CanonicalDedupState,
    EmbeddingBatch,
    IngestionJob,
    ParsedPaper,
    Tombstone,
)
from .ports import (
    ArxivSourcePort,
    AssetSourcePort,
    AssetStorePort,
    ClockPort,
    ControlPlaneStorePort,
    EmbeddingPort,
    FullTextStorePort,
    ObservabilityPort,
    QueuePort,
    VectorIndexPort,
    dedup_decision_applies_to_index,
)
from .processors import (
    Chunker,
    DeduplicationGuard,
    FetchParseProcessor,
    IndexRecordAssembler,
    assert_writer_embedding_role,
    normalize_text,
)
from .resilience import IngestFailureHandler, IngestionResilienceService


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class IngestionPipelineService:
    def __init__(
        self,
        *,
        arxiv: ArxivSourcePort,
        full_text_store: FullTextStorePort,
        embedding: EmbeddingPort,
        vector_index: VectorIndexPort,
        control_plane: ControlPlaneStorePort,
        observability: ObservabilityPort,
        resilience: IngestionResilienceService,
        failure_handler: IngestFailureHandler | None = None,
        chunker: Chunker | None = None,
        parser: FetchParseProcessor | None = None,
        assembler: IndexRecordAssembler | None = None,
        clock: ClockPort | None = None,
        asset_extractor: AssetExtractor | None = None,
        asset_store: AssetStorePort | None = None,
        asset_source: AssetSourcePort | None = None,
        doc_model_builder: DocModelBuilder | None = None,
        embedding_v2: EmbeddingPort | None = None,
        vector_index_v2: VectorIndexPort | None = None,
        corpus_sources: CorpusSourceAdapterSet | None = None,
    ) -> None:
        assert_writer_embedding_role()
        self._arxiv = arxiv
        self._full_text_store = full_text_store
        self._embedding = embedding
        self._vector_index = vector_index
        self._control_plane = control_plane
        self._observability = observability
        self._resilience = resilience
        self._failure_handler = failure_handler
        self._chunker = chunker or Chunker()
        self._parser = parser or FetchParseProcessor()
        self._assembler = assembler or IndexRecordAssembler()
        self._clock = clock or SystemClock()
        # FR-17 multimodal assets — enabled only when all three are injected (safe default off).
        self._asset_extractor = asset_extractor
        self._asset_store = asset_store
        self._asset_source = asset_source
        # Doc-model builder (BR-30/D6): eager in the phase-1 Corpus ingest path, lazy for
        # BUILD_DOC_MODEL compatibility/backfill jobs.
        self._doc_model_builder = doc_model_builder
        self._embedding_v2 = embedding_v2
        self._vector_index_v2 = vector_index_v2
        self._corpus_sources = corpus_sources

    def build_doc_model(
        self, job: IngestionJob
    ) -> DocModelResultDTO | SourceUnavailableDTO:
        """Produce (and cache) the structured doc-model for a paper version (BR-30/D6).

        Dispatched as a BUILD_DOC_MODEL queue job by a consumer (U7 viewer/summary) on a cache
        miss — the read side enqueues, this worker produces. Idempotent: the builder serves the
        cached artifact on a hit, so duplicate enqueues are cheap (no rebuild). If rich HTML is
        unavailable, the worker falls back to the same PDF/text DocModel policy as eager ingest;
        transient arXiv metadata/full-text failures raise through resilience (retriable redelivery).
        """
        if self._doc_model_builder is None:
            raise PermanentIngestionError(
                "doc-model builder not configured",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )
        if not job.arxiv_ref:
            raise PermanentIngestionError(
                "build_doc_model requires arxiv_ref",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )
        metadata = self._resilience.dependency_call(
            "arxiv",
            "fetch_metadata",
            lambda: self._arxiv.fetch_metadata(job.arxiv_ref or ""),
        )
        result = self._doc_model_builder.build(metadata)
        status = result.status
        cached = str(getattr(result, "cached", "")).lower()
        if isinstance(result, SourceUnavailableDTO):
            raw_document = self._resilience.dependency_call(
                "arxiv",
                "fetch_full_text",
                lambda: self._arxiv.fetch_full_text(metadata),
            )
            result = self._doc_model_builder.build_from_text(
                metadata, raw_document.text, source_tier=SourceTier.pdf
            )
            status = "pdf_fallback"
            cached = str(result.cached).lower()
        self._observability.emit_metric(
            "ingestion.docmodel.build",
            1.0,
            {"status": status, "cached": cached},
        )
        return result

    def ingest_one(self, job: IngestionJob) -> DedupDecision:
        if not job.arxiv_ref and job.source_record is None:
            raise PermanentIngestionError(
                "ingest_one requires arxiv_ref or source_record",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="dispatch",
            )
        self._observability.emit_log(
            {
                "type": "ingestion_job_started",
                "jobId": job.job_id,
                "kind": job.kind.value,
                "correlationId": job.correlation_id,
            }
        )
        self._control_plane.record_job_started(job)
        try:
            if job.source_record is not None:
                return self._ingest_source_record(job)

            metadata = self._resilience.dependency_call(
                "arxiv",
                "fetch_metadata",
                lambda: self._arxiv.fetch_metadata(job.arxiv_ref or ""),
            )
            return self.ingest_metadata(job, metadata)
        except IngestionError as exc:
            self._control_plane.record_job_finished(
                job.job_id, success=False, detail=exc.public_error()
            )
            if self._failure_handler is not None:
                self._failure_handler.emit_failure_signal(job.job_id, exc)
                if exc.failure_class is FailureClass.PERMANENT:
                    self._failure_handler.send_to_dlq(
                        {
                            **job.to_payload(),
                            "failureStage": exc.stage,
                            "failureReason": exc.public_error(),
                        },
                        reason=exc.public_error(),
                        job_id=job.job_id,
                    )
            raise

    def ingest_metadata(self, job: IngestionJob, metadata) -> DedupDecision:
        raw_document = self._resilience.dependency_call(
            "arxiv",
            "fetch_full_text",
            lambda: self._arxiv.fetch_full_text(metadata),
        )
        paper = self._parser.parse(raw_document)

        doc_model = self._build_doc_model_before_index(metadata, raw_document.text)
        keys = self._canonical_keys_for_metadata(metadata, paper.year)
        existing = self._canonical_state_for_keys(keys)
        decision = self._index_paper(
            job,
            paper,
            doc_model=doc_model,
            watermark_name="arxiv",
            asset_metadata=metadata,
        )
        if decision is not DedupDecision.STALE and not paper.withdrawal_detected:
            self._record_canonical_winner(
                keys,
                paper,
                "ARXIV_PDF" if "/pdf/" in raw_document.source_url else "ARXIV_HTML",
                SourceName.ARXIV,
                existing,
            )
        return decision

    def _ingest_source_record(self, job: IngestionJob) -> DedupDecision:
        if self._corpus_sources is None:
            raise PermanentIngestionError(
                "corpus source adapters are not configured",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="source",
            )
        record = SourcePaperRecord.from_payload(job.source_record or {})
        self._parser.validate_open_access(record.license_url)
        updated = record.updated_at or record.published_at or self._clock.now()
        record_keys = self._canonical_keys_for_record(record, record.year or updated.year)
        key = job.canonical_key or record_keys[0]
        keys = _dedupe_keys(key, *record_keys)
        existing = self._canonical_state_for_keys(keys)
        if existing is not None and not _source_can_replace(
            existing.winning_source_tier, record.source_name
        ):
            self._record_canonical_duplicate(job, existing, record.source_name, keys)
            return DedupDecision.DUPLICATE

        candidate = self._resilience.dependency_call(
            record.source_name.value.lower(),
            "fetch_full_text",
            lambda: self._corpus_sources.extract_record_text(record),
        )
        paper = self._paper_from_source_record(record, candidate, job, key)

        doc_model = self._build_doc_model_from_paper(paper, SourceTier.pdf)
        decision = self._index_paper(
            job,
            paper,
            doc_model=doc_model,
            watermark_name=record.source_name.value.lower(),
            asset_metadata=None,
        )
        if decision is not DedupDecision.STALE and not paper.withdrawal_detected:
            self._record_canonical_winner(
                keys,
                paper,
                candidate.source_tier,
                record.source_name,
                existing,
            )
        return decision

    def _index_paper(
        self,
        job: IngestionJob,
        paper: ParsedPaper,
        *,
        doc_model: DocModel | None,
        watermark_name: str,
        asset_metadata,
    ) -> DedupDecision:
        if paper.withdrawal_detected:
            return self._tombstone(job, paper, watermark_name=watermark_name)

        dedup = DeduplicationGuard(self._control_plane)
        result = dedup.evaluate(paper)
        if result.decision in {DedupDecision.DUPLICATE, DedupDecision.STALE}:
            self._observability.emit_metric(
                "ingestion.short_circuit",
                1.0,
                {"decision": result.decision.value},
            )
            self._control_plane.record_job_finished(job.job_id, success=True, detail="dedup")
            return result.decision

        if not dedup_decision_applies_to_index(result.decision):
            self._control_plane.record_job_finished(job.job_id, success=True, detail="skip")
            return result.decision

        if not dedup.begin_upsert(paper):
            self._control_plane.record_job_finished(job.job_id, success=True, detail="stale")
            return DedupDecision.STALE

        object_ref = self._resilience.dependency_call(
            "s3",
            "put_full_text",
            lambda: self._full_text_store.put_full_text(paper),
        )
        paper = replace(paper, stored_full_text_ref=object_ref)
        chunks = (
            self._chunker.chunk_doc_model(doc_model)
            if doc_model is not None
            else self._chunker.chunk(paper)
        )
        vectors = self._resilience.dependency_call(
            "bedrock",
            "embed",
            lambda: self._embedding.embed_documents(
                [chunk.text for chunk in chunks.chunks],
                correlation_id=job.correlation_id,
            ),
        )
        embeddings = EmbeddingBatch(
            chunk_ids=tuple(chunk.chunk_id for chunk in chunks.chunks),
            vectors=tuple(tuple(vector) for vector in vectors),
        )
        batch = self._assembler.assemble(paper, chunks, embeddings)

        self._resilience.dependency_call(
            "opensearch",
            "bulk_upsert",
            lambda: self._vector_index.bulk_upsert(batch),
        )
        self._resilience.dependency_call(
            "opensearch",
            "delete_stale_chunks",
            lambda: self._vector_index.delete_stale_chunks(
                paper.paper_id,
                {record.chunkId for record in batch.records},
            ),
        )
        if self._embedding_v2 and self._vector_index_v2:
            try:
                vectors_v2 = self._resilience.dependency_call(
                    "bedrock_v2",
                    "embed",
                    lambda: self._embedding_v2.embed_documents(
                        [chunk.text for chunk in chunks.chunks],
                        correlation_id=job.correlation_id,
                    ),
                )
                embeddings_v2 = EmbeddingBatch(
                    chunk_ids=tuple(chunk.chunk_id for chunk in chunks.chunks),
                    vectors=tuple(tuple(vector) for vector in vectors_v2),
                )
                batch_v2 = self._assembler.assemble(paper, chunks, embeddings_v2)
                self._resilience.dependency_call(
                    "opensearch_v2",
                    "bulk_upsert",
                    lambda: self._vector_index_v2.bulk_upsert(batch_v2),
                )
                self._resilience.dependency_call(
                    "opensearch_v2",
                    "delete_stale_chunks",
                    lambda: self._vector_index_v2.delete_stale_chunks(
                        paper.paper_id,
                        {record.chunkId for record in batch_v2.records},
                    ),
                )
            except Exception as e:
                self._observability.emit_log(
                    {"type": "dual_write_v2_failed", "jobId": job.job_id, "error": str(e)}
                )
        dedup.mark_ingested(paper)
        self._control_plane.advance_watermark(watermark_name, paper.updated_at)
        # FR-17 assets: best-effort, AFTER the index commit so it can never block (BR-27).
        if asset_metadata is not None:
            self._store_assets_best_effort(paper, asset_metadata)
        self._control_plane.record_job_finished(job.job_id, success=True)
        self._observability.emit_metric(
            "ingestion.paper.indexed",
            1.0,
            {"kind": job.kind.value, "chunks": str(len(batch.records))},
        )
        return result.decision

    def _paper_from_source_record(
        self,
        record: SourcePaperRecord,
        candidate: CorpusTextCandidate,
        job: IngestionJob,
        key: str,
    ) -> ParsedPaper:
        normalized_text = normalize_text(candidate.text)
        if not normalized_text:
            raise PermanentIngestionError(
                "full text is empty",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="parse",
            )
        timestamp = record.updated_at or record.published_at or self._clock.now()
        published = record.published_at or timestamp
        year = record.year or published.year
        paper_id = job.paper_id or _paper_id_from_canonical_key(key)
        abstract = normalize_text(record.abstract or record.title)
        authors = tuple(normalize_text(author) for author in record.authors) or (
            record.source_name.value,
        )
        categories = record.categories or ()
        source_url = candidate.source_url or record.html_url or record.pdf_url or ""
        return ParsedPaper(
            paper_id=paper_id,
            version=job.version or record.version,
            title=normalize_text(record.title),
            authors=authors,
            abstract=abstract,
            categories=categories,
            updated_at=timestamp,
            year=year,
            arxiv_url=record.html_url or record.pdf_url or source_url,
            full_text=normalized_text,
            license_url=record.license_url or "",
            withdrawal_detected=detect_withdrawal_proxy(record.title, abstract, normalized_text),
            doi=record.doi or "",
            source_arxiv_id=record.arxiv_id or "",
            source_name=record.source_name,
            source_id=record.source_id,
            source_tier=candidate.source_tier,
            source_url=source_url,
            display_arxiv_id=record.arxiv_id or "",
        )

    def _canonical_key_for_record(self, record: SourcePaperRecord, year: int) -> str:
        return self._canonical_keys_for_record(record, year)[0]

    def _canonical_keys_for_metadata(self, metadata, year: int) -> tuple[str, ...]:
        first_author = metadata.authors[0] if metadata.authors else None
        return _dedupe_keys(
            canonical_key(
                title=metadata.title,
                year=year,
                arxiv_id=metadata.identifier.arxiv_id,
                first_author=first_author,
            ),
            canonical_key(
                title=metadata.title,
                year=year,
                first_author=first_author,
            ),
        )

    def _canonical_keys_for_record(
        self, record: SourcePaperRecord, year: int
    ) -> tuple[str, ...]:
        first_author = record.authors[0] if record.authors else None
        return _dedupe_keys(
            canonical_key(
                title=record.title,
                year=year,
                doi=record.doi,
                arxiv_id=record.arxiv_id,
                first_author=first_author,
            ),
            (
                canonical_key(
                    title=record.title,
                    year=year,
                    arxiv_id=record.arxiv_id,
                    first_author=first_author,
                )
                if record.arxiv_id
                else None
            ),
            canonical_key(
                title=record.title,
                year=year,
                first_author=first_author,
            ),
        )

    def _canonical_state_for_keys(
        self, keys: tuple[str, ...]
    ) -> CanonicalDedupState | None:
        states = [
            state
            for key in keys
            if (state := self._control_plane.get_canonical_dedup_state(key)) is not None
        ]
        if not states:
            return None
        return min(states, key=lambda state: _source_priority_from_tier(state.winning_source_tier))

    def _record_canonical_duplicate(
        self,
        job: IngestionJob,
        existing: CanonicalDedupState,
        source_name: SourceName,
        alias_keys: tuple[str, ...],
    ) -> None:
        seen_sources = _append_source(existing.seen_sources, source_name)
        for key in alias_keys:
            self._control_plane.upsert_canonical_dedup_state(
                replace(
                    existing,
                    canonical_key=key,
                    seen_sources=seen_sources,
                )
            )
        self._control_plane.record_job_finished(
            job.job_id, success=True, detail="canonical_duplicate"
        )
        self._observability.emit_metric(
            "ingestion.canonical_duplicate",
            1.0,
            {"source": source_name.value},
        )

    def _record_canonical_winner(
        self,
        alias_keys: tuple[str, ...],
        paper: ParsedPaper,
        source_tier: str,
        source_name: SourceName,
        existing: CanonicalDedupState | None,
    ) -> None:
        old_alias_keys: tuple[str, ...] = ()
        if existing is not None and existing.paper_id != paper.paper_id:
            old_alias_keys = tuple(
                state.canonical_key
                for state in self._control_plane.list_canonical_dedup_states_for_paper(
                    existing.paper_id
                )
            )
            self._remove_canonical_loser(existing)
            self._control_plane.delete_canonical_dedup_state_for_paper(existing.paper_id)
        seen_sources = _append_source(
            existing.seen_sources if existing is not None else (), source_name
        )
        for key in _dedupe_keys(*alias_keys, *old_alias_keys):
            self._control_plane.upsert_canonical_dedup_state(
                CanonicalDedupState(
                    canonical_key=key,
                    paper_id=paper.paper_id,
                    winning_source_tier=source_tier,
                    winning_version=paper.version,
                    fingerprint=paper.fingerprint,
                    seen_sources=seen_sources,
                ),
            )

    def _remove_canonical_loser(self, existing: CanonicalDedupState) -> None:
        tombstone = Tombstone(
            paper_id=existing.paper_id,
            version=existing.winning_version,
            reason="CANONICAL_SOURCE_REPLACED",
        )
        self._resilience.dependency_call(
            "opensearch",
            "tombstone_canonical_loser",
            lambda: self._vector_index.tombstone_paper(tombstone),
        )
        if self._vector_index_v2:
            try:
                self._resilience.dependency_call(
                    "opensearch_v2",
                    "tombstone_canonical_loser",
                    lambda: self._vector_index_v2.tombstone_paper(tombstone),
                )
            except Exception as e:
                self._observability.emit_log(
                    {"type": "dual_write_v2_canonical_loser_failed", "error": str(e)}
                )
        if self._doc_model_builder is not None:
            self._doc_model_builder.invalidate(existing.paper_id)
        self._remove_assets_best_effort(existing.paper_id)

    def _tombstone(
        self, job: IngestionJob, paper, *, watermark_name: str = "arxiv"
    ) -> DedupDecision:
        dedup = DeduplicationGuard(self._control_plane)
        if not dedup.begin_tombstone(paper):
            self._control_plane.record_job_finished(
                job.job_id, success=True, detail="stale_tombstone"
            )
            return DedupDecision.STALE
        tombstone = Tombstone(paper_id=paper.paper_id, version=paper.version)
        self._resilience.dependency_call(
            "opensearch",
            "tombstone",
            lambda: self._vector_index.tombstone_paper(tombstone),
        )
        if self._vector_index_v2:
            try:
                self._resilience.dependency_call(
                    "opensearch_v2",
                    "tombstone",
                    lambda: self._vector_index_v2.tombstone_paper(tombstone),
                )
            except Exception as e:
                self._observability.emit_log(
                    {"type": "dual_write_v2_tombstone_failed", "error": str(e)}
                )
        self._control_plane.advance_watermark(watermark_name, paper.updated_at)
        self._control_plane.delete_canonical_dedup_state_for_paper(paper.paper_id)
        if self._doc_model_builder is not None:
            self._doc_model_builder.invalidate(paper.paper_id)
        self._remove_assets_best_effort(paper.paper_id)
        self._control_plane.record_job_finished(job.job_id, success=True, detail="tombstoned")
        self._observability.emit_metric("ingestion.paper.tombstoned", 1.0, {"kind": job.kind.value})
        return DedupDecision.CHANGED

    def _store_assets_best_effort(self, paper, metadata) -> None:
        """Extract + store figure/table assets (FR-17). Never raises — assets are a
        display-only, non-blocking side path (BR-27); failures are observed, not propagated."""
        if not (self._asset_extractor and self._asset_store and self._asset_source):
            return
        # Classify by where it fails (§7.3): fetch/extract → EXTRACT, persistence → STORE.
        reason = FailureReason.ASSET_EXTRACT_FAILURE
        try:
            eprint = self._asset_source.fetch_eprint(metadata)
            pdf = self._asset_source.fetch_pdf(metadata)
            extracted = self._asset_extractor.extract(
                paper_id=paper.paper_id, version=paper.version, pdf=pdf, eprint=eprint
            )
            reason = FailureReason.ASSET_STORE_FAILURE
            if extracted:
                self._asset_store.store_assets(paper.paper_id, paper.version, extracted)
            self._observability.emit_metric(
                "ingestion.assets.stored", float(len(extracted)), {"paperId": paper.paper_id}
            )
        except Exception as exc:  # noqa: BLE001 - best-effort: never block indexing (BR-27)
            self._observability.emit_log(
                {
                    "type": "asset_pipeline_failure",
                    "reason": reason.value,
                    "paperId": paper.paper_id,
                    "error": str(exc),
                }
            )
            self._observability.emit_metric("ingestion.assets.failed", 1.0, {})

    def _remove_assets_best_effort(self, paper_id: str) -> None:
        if self._asset_store is None:
            return
        try:
            self._asset_store.remove_assets(paper_id)
        except Exception:  # noqa: BLE001 - best-effort cleanup
            self._observability.emit_metric("ingestion.assets.remove_failed", 1.0, {})

    def _build_doc_model_before_index(self, metadata, fallback_text: str) -> DocModel | None:
        """Eagerly build/cache the doc-model before index exposure (phase-1 Corpus)."""
        if self._doc_model_builder is None:
            return None
        result = self._doc_model_builder.build(metadata)
        status = result.status
        cached = str(getattr(result, "cached", "")).lower()
        if isinstance(result, SourceUnavailableDTO):
            result = self._doc_model_builder.build_from_text(
                metadata, fallback_text, source_tier=SourceTier.pdf
            )
            status = "pdf_fallback"
            cached = str(result.cached).lower()
        self._observability.emit_metric(
            "ingestion.docmodel.eager_build",
            1.0,
            {"status": status, "cached": cached},
        )
        return result.docModel

    def _build_doc_model_from_paper(
        self, paper: ParsedPaper, source_tier: SourceTier
    ) -> DocModel | None:
        if self._doc_model_builder is None:
            return None
        result = self._doc_model_builder.build_from_paper(
            paper.paper_id,
            paper.version,
            paper.title,
            paper.abstract,
            paper.full_text,
            source_tier=source_tier,
        )
        self._observability.emit_metric(
            "ingestion.docmodel.eager_build",
            1.0,
            {"status": "pdf_fallback", "cached": str(result.cached).lower()},
        )
        return result.docModel


class RefreshOrchestrationService:
    def __init__(
        self,
        *,
        arxiv: ArxivSourcePort,
        control_plane: ControlPlaneStorePort,
        queue: QueuePort,
        observability: ObservabilityPort,
        clock: ClockPort | None = None,
        corpus_sources: CorpusSourceAdapterSet | None = None,
        enabled_sources: tuple[SourceName, ...] = (SourceName.ARXIV,),
    ) -> None:
        self._arxiv = arxiv
        self._control_plane = control_plane
        self._queue = queue
        self._observability = observability
        self._clock = clock or SystemClock()
        self._corpus_sources = corpus_sources
        self._enabled_sources = enabled_sources

    def trigger_full_rebuild(self, owner: str = "u1-worker") -> int:
        if not self._control_plane.acquire_rebuild_lock(owner):
            self._observability.emit_metric("ingestion.rebuild.rejected", 1.0, {"reason": "lock"})
            return 0
        queued = 0
        try:
            from .config import CORPUS_END, CORPUS_START
            from .domain.models import CategoryFilter

            self._control_plane.reset_watermark_for_rebuild("arxiv", CORPUS_START)
            category_filter = CategoryFilter(
                categories=CORPUS_SLICE_CATEGORIES,
                updated_after=CORPUS_START,
                updated_before=CORPUS_END,
            )
            for metadata in self._arxiv.harvest_seed(category_filter):
                self._queue.send_job(
                    IngestionJob(
                        job_id=new_job_id("seed"),
                        kind=JobKind.SEED_REBUILD,
                        arxiv_ref=metadata.arxiv_ref,
                    )
                )
                queued += 1
            for source_name in self._enabled_sources:
                if source_name is SourceName.ARXIV:
                    continue
                self._control_plane.reset_watermark_for_rebuild(
                    source_name.value.lower(), CORPUS_START
                )
                queued += self._queue_external_source(
                    source_name,
                    since=CORPUS_START,
                    until=CORPUS_END,
                    kind=JobKind.SEED_REBUILD,
                )
            self._observability.emit_metric("ingestion.rebuild.queued", float(queued), {})
            return queued
        finally:
            self._control_plane.release_rebuild_lock(owner)

    def on_schedule_tick(self) -> int:
        if self._control_plane.is_rebuild_active():
            self._observability.emit_metric(
                "ingestion.incremental.deferred", 1.0, {"reason": "rebuild"}
            )
            return 0
        queued = 0
        if SourceName.ARXIV in self._enabled_sources:
            watermark = self._control_plane.get_watermark("arxiv")
            for metadata in self._arxiv.fetch_incremental(
                watermark.updated_at, CORPUS_SLICE_CATEGORIES
            ):
                self._queue.send_job(
                    IngestionJob(
                        job_id=new_job_id("incremental"),
                        kind=JobKind.INCREMENTAL,
                        arxiv_ref=metadata.arxiv_ref,
                        source_name=SourceName.ARXIV,
                    )
                )
                queued += 1
        for source_name in self._enabled_sources:
            if source_name is SourceName.ARXIV:
                continue
            queued += self._queue_external_incremental(source_name)
        self._observability.emit_metric("ingestion.incremental.queued", float(queued), {})
        return queued

    def _queue_external_incremental(self, source_name: SourceName) -> int:
        watermark_name = source_name.value.lower()
        watermark = self._control_plane.get_watermark(watermark_name)
        queued = self._queue_external_source(
            source_name, since=watermark.updated_at, kind=JobKind.INCREMENTAL
        )
        self._observability.emit_metric(
            "ingestion.source.incremental.queued",
            float(queued),
            {"source": source_name.value},
        )
        return queued

    def _queue_external_source(
        self,
        source_name: SourceName,
        *,
        since: datetime,
        kind: JobKind,
        until: datetime | None = None,
    ) -> int:
        if self._corpus_sources is None or not self._corpus_sources.is_configured(source_name):
            self._observability.emit_metric(
                "ingestion.source.unconfigured",
                1.0,
                {"source": source_name.value},
            )
            return 0
        queued = 0
        for record in self._corpus_sources.fetch_incremental(
            source_name, since, CORPUS_SLICE_CATEGORIES, until
        ):
            updated = record.updated_at or record.published_at or self._clock.now()
            if updated <= since or (until is not None and updated > until):
                continue
            year = record.year or updated.year
            self._queue.send_job(
                IngestionJob(
                    job_id=new_job_id("seed" if kind is JobKind.SEED_REBUILD else "incremental"),
                    kind=kind,
                    source_name=source_name,
                    source_record=record.to_payload(),
                    canonical_key=canonical_key(
                        title=record.title,
                        year=year,
                        doi=record.doi,
                        arxiv_id=record.arxiv_id,
                        first_author=record.authors[0] if record.authors else None,
                    ),
                )
            )
            queued += 1
        return queued

    def on_new_arxiv_event(self, event) -> bool:
        if self._control_plane.is_rebuild_active():
            self._observability.emit_metric("ingestion.event.deferred", 1.0, {"reason": "rebuild"})
            return False
        self._queue.send_job(
            IngestionJob(
                job_id=new_job_id("event"),
                kind=JobKind.EVENT,
                arxiv_ref=event.arxivRef,
                event_id=event.eventId,
                correlation_id=event.eventId,
            )
        )
        self._observability.emit_metric("ingestion.event.queued", 1.0, {})
        return True


def new_job_id(prefix: str) -> str:
    return f"{prefix}-{uuid4()}"


def _paper_id_from_canonical_key(key: str) -> str:
    return "src-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _dedupe_keys(*keys: str | None) -> tuple[str, ...]:
    result: list[str] = []
    for key in keys:
        if key and key not in result:
            result.append(key)
    return tuple(result)


def _append_source(seen_sources: tuple, source_name) -> tuple:
    if source_name in seen_sources:
        return seen_sources
    return (*seen_sources, source_name)


def _source_can_replace(winning_source_tier: str, candidate: SourceName) -> bool:
    return _source_priority(candidate) < _source_priority_from_tier(winning_source_tier)


def _source_priority(source_name: SourceName) -> int:
    return {
        SourceName.ARXIV: 0,
        SourceName.SEMANTIC_SCHOLAR: 1,
        SourceName.OPENALEX: 2,
    }[source_name]


def _source_priority_from_tier(source_tier: str) -> int:
    normalized = source_tier.upper()
    if "ARXIV" in normalized or source_tier in {"native_html", "ar5iv", "eprint_latex", "pdf"}:
        return _source_priority(SourceName.ARXIV)
    if "SEMANTIC_SCHOLAR" in normalized:
        return _source_priority(SourceName.SEMANTIC_SCHOLAR)
    if "OPENALEX" in normalized:
        return _source_priority(SourceName.OPENALEX)
    return _source_priority(SourceName.OPENALEX)


def detect_withdrawal_proxy(title: str, abstract: str, text: str) -> bool:
    haystack = f"{title} {abstract} {text}".lower()
    return any(marker in haystack for marker in WITHDRAWAL_MARKERS)
