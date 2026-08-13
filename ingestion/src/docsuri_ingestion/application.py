from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import datetime
from typing import NoReturn
from uuid import uuid4

from docsuri_shared.dtos import DocModel, DocModelResultDTO, SourceTier, SourceUnavailableDTO

from .asset_extraction import AssetExtractor, crop_assets_from_specs
from .config import CORPUS_SLICE_CATEGORIES
from .corpus_sources import (
    POLICY_REJECTIONS,
    CorpusSourceAdapterSet,
    CorpusTextCandidate,
    SourcePaperRecord,
    admission_rejection,
)
from .docmodel import DocModelBuilder
from .docmodel.tei import tei_crop_specs
from .domain.assets import AssetCropSpec, FigureSpec
from .domain.canonical import (
    arxiv_tier_label,
    canonical_key,
    source_priority,
    source_priority_from_tier,
)
from .domain.enums import DedupDecision, FailureClass, FailureReason, JobKind, SourceName
from .domain.errors import IngestionError, PermanentIngestionError
from .domain.models import (
    CanonicalDedupState,
    EmbeddingBatch,
    IngestionJob,
    MetadataRecord,
    ParsedPaper,
    Tombstone,
)
from .full_text_extraction import FullTextExtractionError, pdf_to_text
from .ports import (
    ArxivSourcePort,
    AssetSourcePort,
    AssetStorePort,
    ClockPort,
    ControlPlaneStorePort,
    EmbeddingPort,
    FullTextStorePort,
    GrobidPort,
    ObservabilityPort,
    QueuePort,
    SystemClock,
    UserDocumentSourcePort,
    VectorIndexPort,
    dedup_decision_applies_to_index,
)
from .processors import (
    Chunker,
    DeduplicationGuard,
    FetchParseProcessor,
    IndexRecordAssembler,
    assert_writer_embedding_role,
    detect_withdrawal_text,
    normalize_text,
)
from .resilience import IngestFailureHandler, IngestionResilienceService


@dataclass(frozen=True, slots=True)
class _TeiAssetContext:
    """Asset inputs for an arXiv paper that took the GROBID rung (BR-30 2026-08-10).

    The HTML path hands the asset step FigureSpecs for the e-print extractor; a GROBID build
    instead yields TEI crop specs plus the exact PDF bytes those coordinates were computed on.
    Carrying both here keeps the crop aligned to the same bytes and saves a re-fetch."""

    crops: tuple[AssetCropSpec, ...]
    pdf: bytes


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
        user_document_source: UserDocumentSourcePort | None = None,
        grobid: GrobidPort | None = None,
        doc_model_builder: DocModelBuilder | None = None,
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
        self._user_document_source = user_document_source
        self._grobid = grobid
        # Doc-model builder (BR-30/D6): eager in the phase-1 Corpus ingest path, lazy for
        # BUILD_DOC_MODEL compatibility/backfill jobs.
        self._doc_model_builder = doc_model_builder
        self._corpus_sources = corpus_sources

    def is_rebuild_active(self) -> bool:
        """Whether a SEED_REBUILD holds the single-writer lock (BR-13). The worker fences in-flight
        INCREMENTAL/EVENT jobs out of a rebuild window with this."""
        return self._control_plane.is_rebuild_active()

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
        # Same ladder as the eager path (ar5iv HTML → arXiv PDF→GROBID). Difference: when every
        # rung fails the result STAYS source_unavailable (viewer links out) instead of excluding
        # the paper — this lazy job serves already-indexed papers, so exclusion is the reingest
        # batch's call, not this handler's.
        result, status, cached, asset_extra = self._walk_ladder(metadata)
        if isinstance(asset_extra, _TeiAssetContext) and asset_extra.crops:
            # A FRESH GROBID build on the lazy path must store its crops too. Discarding them
            # left a cached doc-model whose figure blocks reference assets that were never
            # rendered — and every later eager pass hits the cache, sees no crops to derive, and
            # stores nothing, so the gap became permanent.
            self._render_and_store_crops(
                metadata.paper_id, metadata.version, asset_extra.pdf, list(asset_extra.crops)
            )
        self._observability.emit_metric(
            "ingestion.docmodel.build",
            1.0,
            {"status": status, "cached": cached},
        )
        return result

    def build_user_doc_model(self, job: IngestionJob) -> DocModelResultDTO:
        """Produce/cache a doc-model from a user-uploaded PDF already stored in S3.

        Consumer for the frozen ``BUILD_USER_DOC_MODEL`` contract. Uses GROBID for structure
        (sections/tables/figures) when a sidecar is wired via ``DOCSURI_GROBID_URL`` (#13,
        dedicated user-PDF worker); degrades to the pdfplumber flat-text doc-model otherwise, or
        on any GROBID fault.
        """
        if self._doc_model_builder is None:
            raise PermanentIngestionError(
                "doc-model builder not configured",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )
        if self._user_document_source is None:
            raise PermanentIngestionError(
                "user document source not configured",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="docmodel",
            )
        if not job.paper_id or not job.paper_id.startswith("userdoc:"):
            raise PermanentIngestionError(
                "build_user_doc_model requires a userdoc paper_id",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )
        if job.version is None:
            raise PermanentIngestionError(
                "build_user_doc_model requires version",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )
        if not job.object_key:
            raise PermanentIngestionError(
                "build_user_doc_model requires object_key",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="docmodel",
            )

        pdf = self._resilience.dependency_call(
            "s3",
            "get_user_document",
            lambda: self._user_document_source.fetch_pdf(job.object_key or ""),
        )
        try:
            text = normalize_text(pdf_to_text(pdf))
        except FullTextExtractionError as exc:
            raise PermanentIngestionError(
                "user PDF could not be parsed",
                reason=FailureReason.PARSE_FAILURE,
                stage="parse",
            ) from exc
        if not text:
            raise PermanentIngestionError(
                "user PDF extracted no text",
                reason=FailureReason.PARSE_FAILURE,
                stage="parse",
            )

        # GROBID structure extraction when a sidecar is wired (DOCSURI_GROBID_URL); otherwise the
        # TEI stays empty, build_from_tei reports source_unavailable, and the recovery below hands
        # the user the pdfplumber flat-text doc-model. A GROBID timeout/HTTP fault takes the same
        # route — GROBID must never block the user's build.
        tei = ""
        grobid = self._grobid
        if grobid is not None:
            try:
                tei = self._resilience.dependency_call(
                    "grobid",
                    "extract_tei",
                    lambda: grobid.extract_tei(pdf),
                )
            except Exception:  # noqa: BLE001 - GROBID is best-effort; degrade to pdfplumber.
                self._observability.emit_metric(
                    "ingestion.docmodel.user_grobid_unavailable",
                    1.0,
                    {"module": job.module or "unknown"},
                )
                tei = ""

        result = self._doc_model_builder.build_from_tei(
            job.paper_id,
            job.version,
            "User uploaded PDF",
            "",
            tei,
            source_tier=SourceTier.pdf,
            # The crop specs are consumed inside the build (table repair / formula OCR need them
            # to map blocks to page regions); without a list those passes silently skip, leaving
            # uploads the only PDF path without the second readers.
            crops=[],
            pdf=pdf,
        )
        flat_recovery = isinstance(result, SourceUnavailableDTO)
        if flat_recovery:
            # Uploads are the ONE lenient caller (BR-30 2026-08-10): a corpus paper with no
            # structure is excluded, but this document is the user's own and a GROBID hiccup must
            # not take away the only view they have. Stated here, at the call site it applies to,
            # rather than as a default buried in the shared builder.
            result = self._doc_model_builder.build_from_paper(
                job.paper_id, job.version, "User uploaded PDF", "", text,
                source_tier=SourceTier.pdf,
            )
        self._observability.emit_metric(
            "ingestion.docmodel.user_build",
            1.0,
            {
                # Status reports what the user actually RECEIVED. GROBID answering but its TEI
                # parsing to nothing ships flat pdfplumber text — labeling that "grobid" would
                # keep the dashboard at 100% grobid through a systematic TEI regression, exactly
                # when the label matters.
                "status": "grobid" if tei and not flat_recovery else "pdf_fallback",
                "cached": str(result.cached).lower(),
                "module": job.module or "unknown",
            },
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

            if job.arxiv_metadata is not None:
                # Harvest already fetched this via bulk OAI-PMH — skip the per-paper
                # round-trip (arXiv politeness budget) and its breaker exposure.
                metadata = MetadataRecord.from_payload(job.arxiv_metadata)
            else:
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

        keys = self._canonical_keys_for_metadata(metadata, paper.year)
        existing = self._canonical_state_for_keys(keys)
        # Captures whether the build swapped the stored text off the discredited ar5iv page, so
        # the canonical winner below is labeled with the tier the .txt ACTUALLY came from.
        swapped = [False]

        def build() -> tuple:
            built = self._build_doc_model_before_index(
                metadata,
                html_text_stored=raw_document.source_tier is SourceTier.ar5iv,
            )
            swapped[0] = built[2] is not None
            return built

        decision = self._index_paper(
            job,
            paper,
            build_doc_model=build,
            watermark_name="arxiv",
            asset_metadata=metadata,
        )
        if decision is not DedupDecision.STALE and not paper.withdrawal_detected:
            self._record_canonical_winner(
                keys,
                paper,
                arxiv_tier_label(SourceTier.pdf if swapped[0] else raw_document.source_tier),
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
        # Re-asserted at consumption for the same reason the licence check above is, even though
        # the enqueue path already applied it: a job can predate the current rule, and tightening
        # the policy — populating BLOCKED_VENUE_MARKERS from the ⑧-2 harvest, say — would
        # otherwise let the very records it was tightened against through. POLICY reasons only:
        # judging old payloads on data-absence reasons would dead-letter every pre-gate job as
        # `field_unknown` merely for lacking keys that did not exist when it was queued.
        rejection = admission_rejection(record)
        if rejection in POLICY_REJECTIONS:
            raise PermanentIngestionError(
                f"source record refused at admission: {rejection}",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="source",
            )
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

        decision = self._index_paper(
            job,
            paper,
            build_doc_model=lambda: self._build_doc_model_from_record(paper, candidate),
            watermark_name=record.source_name.value.lower(),
            asset_metadata=None,
            record_asset_ctx=(record, candidate),
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
        build_doc_model: Callable[
            [],
            tuple[
                DocModel | None,
                tuple[FigureSpec, ...] | tuple[AssetCropSpec, ...] | _TeiAssetContext | None,
                str | None,
            ],
        ],
        watermark_name: str,
        asset_metadata,
        record_asset_ctx: tuple[SourcePaperRecord, CorpusTextCandidate] | None = None,
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

        # BLM §0.3 order — the doc-model is built only after the dedup short-circuit and the
        # begin_upsert claim, so DUPLICATE/STALE redeliveries and withdrawn papers never pay the
        # build (BR-4/BR-22 zero-cost duplicates); it still lands before index exposure.
        #
        # It also runs BEFORE the full text is stored. Corpus exclusion (BR-30 2026-08-10) means a
        # paper whose every rung failed must leave no full text behind, and never writing beats
        # write-then-delete: the exclusion path costs zero S3 round trips, a flaky GROBID stops
        # multiplying writes by its redelivery count, and — the reason that matters — a re-parse
        # of an ALREADY INDEXED paper can no longer delete the text of a paper whose old chunks
        # are still being served. Nothing between here and the store reads
        # ``stored_full_text_ref``, so the two are free to swap.
        #
        # ``asset_extra`` is pair-typed with the caller's asset context: FigureSpecs or a
        # _TeiAssetContext (GROBID rung) alongside ``asset_metadata`` (arXiv), crop specs
        # (None = cache hit, re-derive) alongside ``record_asset_ctx``. ``full_text_swap`` is the
        # PDF-derived replacement text when the ladder discredited the HTML the full text came
        # from (BR-29/BR-30 2026-08-10) — see _build_doc_model_before_index.
        try:
            doc_model, asset_extra, full_text_swap = build_doc_model()
        except PermanentIngestionError:
            # Metric'd so the reingest batch can watch its exclusion rate, and the begin_upsert
            # claim above — whose version bump already committed — is flipped to EXCLUDED so the
            # ledger does not keep reporting INDEXED for a version that has no chunks, no
            # doc-model, and no full text. Best-effort: the exclusion itself is the story.
            self._observability.emit_metric(
                "ingestion.paper.excluded", 1.0, {"kind": job.kind.value}
            )
            try:
                self._control_plane.mark_excluded(paper.paper_id, paper.version)
            except Exception as exc:  # noqa: BLE001 - ledger cleanup must not mask the exclusion
                self._observability.emit_log(
                    {
                        "type": "exclusion_ledger_failure",
                        "paperId": paper.paper_id,
                        "error": str(exc),
                    }
                )
            raise
        if full_text_swap:
            # The doc-model gate rejected the ar5iv conversion this text was extracted from, but
            # the text cleared its own (length-only) floor. U7 summaries/translations read the
            # stored .txt with no quality signal, so store the PDF text rung's output instead —
            # the same text fetch_full_text would have produced had it known. Chunks are
            # unaffected (they come from the doc-model).
            paper = replace(
                paper, full_text=full_text_swap, source_tier=arxiv_tier_label(SourceTier.pdf)
            )
        object_ref = self._resilience.dependency_call(
            "s3",
            "put_full_text",
            lambda: self._full_text_store.put_full_text(paper),
        )
        paper = replace(paper, stored_full_text_ref=object_ref)
        # ``doc_model is None`` means the builder component is UNWIRED (minimal runtimes/tests),
        # not that a build failed — failures raise above. Only that wiring gap flat-chunks.
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
        dedup.mark_ingested(paper)
        self._control_plane.advance_watermark(watermark_name, paper.updated_at)
        # FR-17 assets: best-effort, AFTER the index commit so it can never block (BR-27).
        if isinstance(asset_extra, _TeiAssetContext):
            # arXiv paper that took the GROBID rung: page-crops against the exact PDF bytes the
            # TEI coordinates were computed on, not the e-print figure extractor. An empty ctx
            # (doc-model cache hit) selects this branch deliberately and does nothing — the crops
            # were stored by the build that populated the cache.
            self._render_and_store_crops(
                paper.paper_id, paper.version, asset_extra.pdf, list(asset_extra.crops)
            )
        elif asset_metadata is not None:
            self._store_assets_best_effort(paper, asset_metadata, asset_extra or ())
        elif record_asset_ctx is not None:
            self._store_record_assets_best_effort(paper, *record_asset_ctx, asset_extra)
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
            withdrawal_detected=detect_withdrawal_text(record.title, abstract, normalized_text),
            doi=record.doi or "",
            source_arxiv_id=record.arxiv_id or "",
            source_name=record.source_name,
            source_id=record.source_id,
            source_tier=candidate.source_tier,
            source_url=source_url,
            display_arxiv_id=record.arxiv_id or "",
        )

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
        return min(states, key=lambda state: source_priority_from_tier(state.winning_source_tier))

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
        self._control_plane.advance_watermark(watermark_name, paper.updated_at)
        self._control_plane.delete_canonical_dedup_state_for_paper(paper.paper_id)
        if self._doc_model_builder is not None:
            self._doc_model_builder.invalidate(paper.paper_id)
        self._remove_assets_best_effort(paper.paper_id)
        self._control_plane.record_job_finished(job.job_id, success=True, detail="tombstoned")
        self._observability.emit_metric("ingestion.paper.tombstoned", 1.0, {"kind": job.kind.value})
        return DedupDecision.CHANGED

    def _store_assets_best_effort(
        self, paper, metadata, figure_specs: tuple[FigureSpec, ...] = ()
    ) -> None:
        """Extract + store figure/table assets (FR-17). Never raises — assets are a
        display-only, non-blocking side path (BR-27); failures are observed, not propagated.

        ``figure_specs`` (the doc-model FigureBlocks, document order) lets the extractor resolve
        each figure's image aligned to its block; empty falls back to the legacy scan."""
        if not (self._asset_extractor and self._asset_store and self._asset_source):
            return
        # Classify by where it fails (§7.3): fetch/extract → EXTRACT, persistence → STORE.
        reason = FailureReason.ASSET_EXTRACT_FAILURE
        try:
            eprint = self._asset_source.fetch_eprint(metadata)
            pdf = self._asset_source.fetch_pdf(metadata)
            extracted = self._asset_extractor.extract(
                paper_id=paper.paper_id,
                version=paper.version,
                pdf=pdf,
                eprint=eprint,
                figure_specs=figure_specs or None,
            )
            reason = FailureReason.ASSET_STORE_FAILURE
            if extracted:
                self._asset_store.store_assets(paper.paper_id, paper.version, extracted)
            self._observability.emit_metric(
                "ingestion.assets.stored", float(len(extracted)), {"paperId": paper.paper_id}
            )
        except Exception as exc:  # noqa: BLE001 - best-effort: never block indexing (BR-27)
            self._report_asset_failure(paper.paper_id, reason, exc)

    def _render_and_store_crops(
        self, paper_id: str, version: int, pdf: bytes, specs: list[AssetCropSpec]
    ) -> None:
        """Render TEI page-crop specs to WebP and persist them (FR-17). The one place that owns
        the crop→store sequence, so every TEI path (arXiv GROBID rung — eager AND lazy — and the
        non-arXiv source record) shares a single failure classification and a single
        ``assets.stored`` contract. Takes bare ids because the lazy BUILD_DOC_MODEL job has no
        ParsedPaper — only metadata.

        Best-effort and never raises (BR-27): assets are a display-only side path, so a failure is
        observed rather than propagated. Classified by WHERE it fails (§7.3): rendering →
        EXTRACT, persistence → STORE."""
        if self._asset_store is None or not specs:
            return
        reason = FailureReason.ASSET_EXTRACT_FAILURE
        refusals: list[tuple[str, str]] = []
        try:
            extracted = crop_assets_from_specs(
                pdf, specs, paper_id=paper_id, version=version, refusals=refusals
            )
            reason = FailureReason.ASSET_STORE_FAILURE
            if extracted:
                self._asset_store.store_assets(paper_id, version, extracted)
            self._observability.emit_metric(
                "ingestion.assets.stored", float(len(extracted)), {"paperId": paper_id}
            )
        except Exception as exc:  # noqa: BLE001 - best-effort: never block indexing (BR-27)
            self._report_asset_failure(paper_id, reason, exc)
        finally:
            # In ``finally``, decoupled from the store on both sides: the refusals were collected
            # by the crop stage and are true whatever happens to storage, and a store failure is
            # exactly when the batch most needs this paper's breakdown. Inside the ``try`` it
            # would also misattribute — an emission error there records ASSET_STORE_FAILURE for
            # assets that stored fine.
            self._emit_asset_refusals(paper_id, refusals)

    def _emit_asset_refusals(self, paper_id: str, refusals: list[tuple[str, str]]) -> None:
        """One counter per reason a spec produced no image (BR-23a). Never raises.

        ``assets.stored`` alone cannot answer the question a reparse batch has to answer: a figure
        with no image shows the viewer's placeholder either way, but ``caption_only`` is the
        DESIGNED outcome (the region held nothing but the caption) while the rest are losses.
        Counted apart so the batch reports its own placeholder rate broken down by cause instead
        of leaving one number that means both.
        """
        by_reason: dict[str, int] = {}
        for _asset_id, why in refusals:
            by_reason[why] = by_reason.get(why, 0) + 1
        try:
            for why, count in sorted(by_reason.items()):
                self._observability.emit_metric(
                    "ingestion.assets.refused", float(count), {"paperId": paper_id, "reason": why}
                )
        except Exception as exc:  # noqa: BLE001 - a broken metrics sink must not cost the asset path
            with suppress(Exception):  # the log rides the same sink that just failed
                self._observability.emit_log(
                    {"type": "asset_refusal_emit_failure", "paperId": paper_id, "error": str(exc)}
                )

    def _store_record_assets_best_effort(
        self,
        paper,
        record: SourcePaperRecord,
        candidate: CorpusTextCandidate,
        crops: tuple[AssetCropSpec, ...] | None = None,
    ) -> None:
        """Coordinate page-crop figure/formula assets for a non-arXiv (TEI) paper (FR-17).

        Renders the TEI crop specs — whose assetIds match the doc-model blocks — to WebP. Reuses
        the crop specs gathered during the doc-model build (``crops``) instead of re-parsing the
        TEI, and the PDF bytes already fetched for GROBID (``candidate.pdf``) instead of
        re-fetching — the latter also keeps the crop aligned to the exact bytes the TEI
        coordinates came from. Falls back to re-parsing / re-fetching only when those are
        unavailable. Gated on the asset store being wired (multimodal enabled); best-effort and
        never raises (BR-27)."""
        if self._asset_store is None or self._corpus_sources is None or not candidate.tei:
            return
        try:
            specs = (
                list(crops)
                if crops is not None
                else tei_crop_specs(
                    candidate.tei, paper_id=paper.paper_id, version=paper.version
                )
            )
            if not specs:
                return
            pdf = (
                candidate.pdf
                if candidate.pdf is not None
                else self._corpus_sources.fetch_record_pdf(record)
            )
        except Exception as exc:  # noqa: BLE001 - resolving the inputs is still the EXTRACT phase
            self._report_asset_failure(paper.paper_id, FailureReason.ASSET_EXTRACT_FAILURE, exc)
            return
        self._render_and_store_crops(paper.paper_id, paper.version, pdf, specs)

    def _report_asset_failure(
        self, paper_id: str, reason: FailureReason, exc: Exception
    ) -> None:
        """Log + count an asset pipeline failure. The asset path is best-effort (BR-27), so this
        is the whole handling — the caller swallows the exception and indexing continues."""
        self._observability.emit_log(
            {
                "type": "asset_pipeline_failure",
                "reason": reason.value,
                "paperId": paper_id,
                "error": str(exc),
            }
        )
        self._observability.emit_metric("ingestion.assets.failed", 1.0, {})

    def _remove_assets_best_effort(self, paper_id: str) -> None:
        if self._asset_store is None:
            return
        try:
            self._asset_store.remove_assets(paper_id)
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            self._observability.emit_log(
                {"type": "asset_remove_failure", "paperId": paper_id, "error": str(exc)}
            )
            self._observability.emit_metric("ingestion.assets.remove_failed", 1.0, {})

    def _grobid_doc_model(
        self, metadata: MetadataRecord
    ) -> tuple[DocModelResultDTO, _TeiAssetContext | None] | None:
        """arXiv PDF → GROBID rung of the Q6 ladder (BR-30 2026-08-10).

        Returns ``None`` when the rung cannot produce a structured doc-model: the sidecar is
        unwired, the PDF is permanently gone, or the TEI parsed to nothing
        (``allow_flat_fallback=False`` — a flat-text doc-model is exactly what this revision
        removed). Transport faults propagate through the resilience taxonomy so a transient GROBID
        blip retries instead of silently excluding the paper. The second element carries the crop
        specs + PDF for the asset step; ``None`` on a cache hit (no parse ran, the asset step
        re-derives).

        The PDF comes from the arXiv source, NOT the FR-17 asset source: same bytes
        ``fetch_full_text`` already pulled for this paper (one memoized download), behind the
        arXiv rate limiter, and inside the failure taxonomy."""
        grobid, builder = self._grobid, self._doc_model_builder
        if grobid is None or builder is None:
            self._observability.emit_metric(
                "ingestion.docmodel.grobid_rung_unwired", 1.0, {}
            )
            return None
        try:
            pdf = self._resilience.dependency_call(
                "arxiv", "fetch_pdf", lambda: self._arxiv.fetch_pdf(metadata)
            )
        except PermanentIngestionError:
            # No HTML rung AND no PDF — the rung genuinely cannot run. Report it as "no structured
            # form" (the caller decides exclude vs. stay-unavailable) rather than letting a fetch
            # error masquerade as a parse failure.
            self._observability.emit_metric("ingestion.docmodel.grobid_rung_no_pdf", 1.0, {})
            return None
        if pdf is None:
            # `only` cache mode with a miss — no bytes, no rung. Not an error.
            self._observability.emit_metric("ingestion.docmodel.grobid_rung_no_pdf", 1.0, {})
            return None
        try:
            tei = self._resilience.dependency_call(
                "grobid", "extract_tei", lambda: grobid.extract_tei(pdf)
            )
        except PermanentIngestionError:
            # GROBID REJECTED this PDF outright (400/415/422 — malformed/oversized/unsupported).
            # That is "the rung cannot produce a doc-model for this paper", not a fault to bubble:
            # the lazy BUILD_DOC_MODEL contract keeps the result source_unavailable (viewer links
            # out), and letting this escape turned every such already-indexed paper into an
            # endless DLQ + failure-signal loop while the viewer polled a build that can never
            # land. Transient GROBID faults (5xx/timeouts) still propagate and retry.
            self._observability.emit_metric("ingestion.docmodel.grobid_rung_rejected", 1.0, {})
            return None
        crops: list[AssetCropSpec] = []
        result = builder.build_from_tei(
            metadata.paper_id,
            metadata.version,
            metadata.title,
            metadata.abstract or "",
            tei,
            source_tier=SourceTier.pdf,
            crops=crops,
            pdf=pdf,
        )
        if isinstance(result, SourceUnavailableDTO):
            return None
        # Skip the context entirely when no asset store is wired: carrying multi-MB PDF bytes
        # across chunking, embedding and the index upsert only to drop them is pure waste.
        if self._asset_store is None:
            return result, None
        if result.cached:
            # A cache hit parsed no TEI, so there are no crops to render — and none needed, the
            # build that filled the cache stored them. Hand back an EMPTY context rather than
            # None: None falls through to the `asset_metadata` branch in _index_paper, whose
            # e-print figure extractor re-downloads the tarball AND the PDF for assets this rung
            # does not use. (pdf=b"" so the bytes are not kept alive through embedding.)
            return result, _TeiAssetContext(crops=(), pdf=b"")
        if not crops:
            # FRESH build whose TEI carried no coordinates (a GROBID deployment can drop
            # teiCoordinates): the crop branch would silently no-op while the doc-model's figure
            # blocks still reference assetIds. Fall back to the e-print extractor branch (None →
            # `asset_metadata` in _index_paper) — the same asset_id scheme, and the path this
            # population used before the GROBID rung existed. Metric'd: dangling figure refs are
            # otherwise invisible in observability.
            self._observability.emit_metric("ingestion.docmodel.grobid_rung_no_coords", 1.0, {})
            return result, None
        return result, _TeiAssetContext(crops=tuple(crops), pdf=pdf)

    def _walk_ladder(
        self, metadata: MetadataRecord, figure_specs: list[FigureSpec] | None = None
    ) -> tuple[
        DocModelResultDTO | SourceUnavailableDTO,
        str,
        str,
        tuple[FigureSpec, ...] | _TeiAssetContext | None,
    ]:
        """Walk the arXiv Q6 ladder once: ar5iv HTML, then arXiv PDF→GROBID (BR-30 2026-08-10).

        The single place that knows the rung ORDER and what each rung reports, so the eager
        ingest path and the lazy BUILD_DOC_MODEL job cannot drift on it (they already had — the
        same rung was reported as "grobid" by one and "grobid_fallback" by the other). Callers
        differ only in what they do with a final ``SourceUnavailableDTO``: exclude, or stay
        unavailable. Returns ``(result, status, cached, asset_extra)``; the metric NAME is the
        caller's, since eager and lazy builds are counted separately.
        """
        builder = self._doc_model_builder
        assert builder is not None  # callers check; keeps the type narrow
        result = builder.build(metadata, figure_specs=figure_specs)
        asset_extra: tuple[FigureSpec, ...] | _TeiAssetContext | None = tuple(figure_specs or ())
        if not isinstance(result, SourceUnavailableDTO):
            return result, result.status, str(result.cached).lower(), asset_extra
        recovered = self._grobid_doc_model(metadata)
        if recovered is None:
            return result, result.status, "false", None
        result, asset_extra = recovered
        return result, "grobid", str(result.cached).lower(), asset_extra

    def _raise_excluded(self, message: str) -> NoReturn:
        """Fail a paper OUT of the corpus (BR-30 2026-08-10). One place so the exclusion metric
        and the failure classification cannot drift between the ladder and the record path."""
        self._observability.emit_metric(
            "ingestion.docmodel.eager_build", 1.0, {"status": "excluded", "cached": "false"}
        )
        raise PermanentIngestionError(
            message, reason=FailureReason.PARSE_FAILURE, stage="docmodel"
        )

    def _build_doc_model_before_index(
        self, metadata, *, html_text_stored: bool = False
    ) -> tuple[DocModel | None, tuple[FigureSpec, ...] | _TeiAssetContext | None, str | None]:
        """Eagerly build/cache the doc-model before index exposure (phase-1 Corpus).

        Returns the doc-model, the asset-step input matching the rung that built it (FigureSpecs
        for the HTML path in document order, a ``_TeiAssetContext`` for the GROBID rung), and a
        full-text replacement (see below). When every rung fails the paper is EXCLUDED from the
        corpus (BR-30 2026-08-10) — this raises instead of returning a flat-text doc-model, and
        ``_index_paper`` never stores its full text.

        ``html_text_stored`` says the caller's full text was extracted from the ar5iv HTML. When
        the ladder then falls past the HTML rung THIS pass (the gate discredited that same page),
        the third element carries the PDF text rung's output so the caller stores that instead —
        otherwise the discredited page's text (which clears its own length-only floor) becomes the
        canonical ``.txt`` that U7 summaries read, labeled with the very tier the viewer just
        refused. The PDF bytes are a memo hit — the GROBID rung just fetched them through the same
        adapter. PDF unavailable/unparseable → ``None``: the fragment beats nothing, matching
        ``fetch_full_text``'s own fallback philosophy."""
        if self._doc_model_builder is None:
            return None, (), None
        figure_specs: list[FigureSpec] = []
        result, status, cached, asset_extra = self._walk_ladder(metadata, figure_specs)
        if isinstance(result, SourceUnavailableDTO):
            self._raise_excluded("no ladder rung produced a structured doc-model — paper excluded")
        self._observability.emit_metric(
            "ingestion.docmodel.eager_build",
            1.0,
            {"status": status, "cached": cached},
        )
        full_text_swap = None
        if html_text_stored and status == "grobid":
            full_text_swap = self._pdf_full_text_best_effort(metadata)
        return result.docModel, asset_extra, full_text_swap

    def _pdf_full_text_best_effort(self, metadata) -> str | None:
        """The PDF text rung's output for a paper whose ar5iv text was discredited (BR-29). Best
        effort — any failure keeps the caller's existing text rather than failing the paper."""
        try:
            pdf = self._resilience.dependency_call(
                "arxiv", "fetch_pdf", lambda: self._arxiv.fetch_pdf(metadata)
            )
            text = normalize_text(pdf_to_text(pdf)) if pdf else ""
        except (PermanentIngestionError, FullTextExtractionError):
            return None
        return text or None

    def _build_doc_model_from_record(
        self, paper: ParsedPaper, candidate: CorpusTextCandidate
    ) -> tuple[DocModel | None, tuple[AssetCropSpec, ...] | None, None]:
        """Structured doc-model for a non-arXiv source record from its GROBID TEI.

        TEI absent or parsed to nothing means the record has no structured form — the paper is
        EXCLUDED from the corpus (BR-30 2026-08-10) rather than indexed as a flat text blob. The
        figure/formula crop specs are gathered during the single TEI parse and returned, so the
        asset step reuses them instead of re-parsing. On a cache hit no parse runs here, so crops
        is returned as None and the asset step re-derives them."""
        if self._doc_model_builder is None:
            return None, None, None
        crops: list[AssetCropSpec] = []
        result = self._doc_model_builder.build_from_tei(
            paper.paper_id,
            paper.version,
            paper.title,
            paper.abstract,
            candidate.tei or "",
            source_tier=SourceTier.pdf,
            crops=crops,
            # The same PDF GROBID read, so a table it mangled can be re-read from the page.
            pdf=candidate.pdf,
        )
        if isinstance(result, SourceUnavailableDTO):
            self._raise_excluded("source record has no parseable TEI — paper excluded")
        self._observability.emit_metric(
            "ingestion.docmodel.eager_build",
            1.0,
            {"status": "tei", "cached": str(result.cached).lower()},
        )
        # A cache hit skips the TEI parse, so an empty list there means "not derived" (not "no
        # crops"); signal None so the asset step parses the TEI itself.
        record_crops = None if result.cached else tuple(crops)
        # No third element to give: the record path's text never came from ar5iv.
        return result.docModel, record_crops, None


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
                        arxiv_metadata=metadata.to_payload(),
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

    def backfill_external_sources(self, since: datetime, until: datetime) -> int:
        """Bounded one-off backfill of the non-arXiv corpus sources (SS/OpenAlex) over an explicit
        [since, until] window — the run-scoped path the daily tick can't cover (its watermark
        starts at now(), so it only harvests forward and queues ~0). arXiv is left untouched: no
        seed re-harvest, no rebuild lock. Enqueues source-record SEED jobs (exempt from the BR-13
        incremental fence) that the worker drains into the index; the per-paper watermark advance
        hands the source off to the daily tick. Idempotent — canonical dedup + chunkId upsert make
        re-runs safe."""
        queued = 0
        for source_name in self._enabled_sources:
            if source_name is SourceName.ARXIV:
                continue
            # Per-source isolation: one source exhausting its retries (e.g. unauthenticated SS
            # rate-limited to abort) must not drop the others — log + skip and carry on, mirroring
            # on_schedule_tick. Each source's paged fetch already retries transient blips, so this
            # only catches a sustained/permanent failure of that whole source.
            # Count through a tally rather than the return value: the source's paged fetch is a
            # generator, so a page failure aborts mid-iteration and `return queued` never runs.
            # The jobs enqueued before that point are real and already in the queue — reporting 0
            # for them makes a partially-successful backfill look like a no-op and invites a re-run.
            tally = [0]
            try:
                self._queue_external_source(
                    source_name,
                    since=since,
                    until=until,
                    kind=JobKind.SEED_REBUILD,
                    tally=tally,
                )
            except Exception as exc:  # noqa: BLE001 — defensive boundary around one source
                self._observability.emit_metric(
                    "ingestion.backfill.external.failed",
                    1.0,
                    {"source": source_name.value, "error": type(exc).__name__},
                )
            finally:
                queued += tally[0]
        self._observability.emit_metric("ingestion.backfill.external.queued", float(queued), {})
        return queued

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
            # Per-source isolation: a single source failing (e.g. an upstream 4xx/timeout)
            # must not abort the whole tick or crash the worker — skip it and carry on.
            try:
                queued += self._queue_external_incremental(source_name)
            except Exception as exc:  # noqa: BLE001 — defensive boundary around one source
                self._observability.emit_metric(
                    "ingestion.source.incremental.failed",
                    1.0,
                    {"source": source_name.value, "error": type(exc).__name__},
                )
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
        tally: list[int] | None = None,
    ) -> int:
        """Enqueue a source-record job per in-window record; return how many were queued.

        ``tally`` mirrors the count as it goes, for callers that must still see the partial
        progress when the source's generator raises part-way through and the return never happens.
        """
        if self._corpus_sources is None or not self._corpus_sources.is_configured(source_name):
            self._observability.emit_metric(
                "ingestion.source.unconfigured",
                1.0,
                {"source": source_name.value},
            )
            return 0
        queued = 0
        rejected: Counter[str] = Counter()
        try:
            yield_from_source = self._corpus_sources.fetch_incremental(
                source_name, since, CORPUS_SLICE_CATEGORIES, until
            )
            for record in yield_from_source:
                updated = record.updated_at or record.published_at or self._clock.now()
                if updated <= since or (until is not None and updated > until):
                    continue
                rejection = admission_rejection(record)
                if rejection is not None:
                    # Counted here, emitted once per reason in the finally. Emitting per record
                    # would flood exactly when it hurts — the gate is fail-closed, so a field
                    # going missing upstream refuses EVERY record, and a widened S2 query has
                    # been measured at 22,039 of them. A count is also the more useful datapoint.
                    rejected[rejection] += 1
                    continue
                year = record.year or updated.year
                prefix = "seed" if kind is JobKind.SEED_REBUILD else "incremental"
                self._queue.send_job(
                    IngestionJob(
                        job_id=new_job_id(prefix),
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
                if tally is not None:
                    tally[0] = queued
        finally:
            # In a finally for the same reason ``tally`` exists: the source generator can raise
            # part-way through a multi-page harvest, and a refusal count that only survives a
            # clean run is missing exactly when something went wrong.
            for reason, count in rejected.items():
                self._observability.emit_metric(
                    "ingestion.source.rejected",
                    float(count),
                    {"source": source_name.value, "reason": reason},
                )
            if rejected and queued == 0:
                # Total collapse is upstream schema drift until proven otherwise (rename of
                # s2FieldsOfStudy / primary_topic), and without this it reads exactly like "the
                # source had nothing new" — return 0, exit 0, nobody looks. The exact zero/some
                # condition needs no invented threshold.
                self._observability.emit_metric(
                    "ingestion.source.rejected_all", 1.0, {"source": source_name.value}
                )
                self._observability.emit_log(
                    {
                        "type": "ingestion_source_rejected_all",
                        "source": source_name.value,
                        "rejected": sum(rejected.values()),
                        "hint": "every harvested record was refused — check upstream field names",
                    }
                )
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
    # source_priority_from_tier is the single source of truth shared with the
    # control-plane guarded upsert (domain.canonical).
    return source_priority(candidate) < source_priority_from_tier(winning_source_tier)


