from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from .adapters.arxiv import ArxivHttpSource
from .adapters.aws import (
    BedrockCohereEmbeddingPort,
    OpenSearchVectorIndex,
    S3FullTextStore,
    S3RawContentStore,
    SqsQueue,
)
from .adapters.local import (
    CapturingObservabilityHub,
    FakeArxivSource,
    FakeEmbeddingPort,
    InMemoryControlPlaneStore,
    InMemoryDocModelStore,
    InMemoryFullTextStore,
    InMemoryQueue,
    InMemoryVectorIndex,
    sample_metadata,
)
from .adapters.postgres import PostgresControlPlaneStore
from .application import IngestionPipelineService, RefreshOrchestrationService
from .config import CORPUS_SLICE_CATEGORIES
from .corpus_sources import CorpusSourceAdapterSet
from .domain.enums import SourceName
from .observability import LoggingObservabilityHub
from .ports import FormulaReaderPort, TableExtractorPort
from .processors import Chunker
from .resilience import IngestFailureHandler, IngestionResilienceService, TokenBucket
from .settings import IngestionSettings


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    pipeline: IngestionPipelineService
    refresh: RefreshOrchestrationService
    queue: object
    observability: object
    corpus_sources: object | None = None
    # The arXiv source itself, for drivers that need bulk metadata before feeding the pipeline
    # one job at a time (``foundational``). The pipeline holds the same instance; exposing it
    # here beats reaching through the pipeline's private attribute.
    arxiv: object | None = None
    # Optional priority doc-model build queue (BR-30/D6). None → worker polls only `queue`.
    docmodel_queue: object | None = None


def build_local_runtime() -> RuntimeServices:
    # Seeded INSIDE the configured slice, or the offline smoke path goes dark: harvest_seed
    # intersects the sample's categories with CORPUS_SLICE_CATEGORIES, and when the slice
    # narrowed to cs.CL/cs.AI a default (cs.LG) sample made `--local trigger-full-rebuild`
    # queue 0 and exit 0 — a smoke test that silently tests nothing. Unlike the assertion-side
    # fixtures (which pin literals so the filter cannot be self-fulfilling), the runtime seed
    # SHOULD follow the config: its job is to exercise the pipeline as currently configured.
    metadata = [sample_metadata(category=CORPUS_SLICE_CATEGORIES[0])]
    arxiv = FakeArxivSource(metadata)
    control = InMemoryControlPlaneStore()
    queue = InMemoryQueue()
    observability = CapturingObservabilityHub()
    resilience = IngestionResilienceService(observability, timeout_seconds=2.0)
    failure_handler = IngestFailureHandler(queue, observability)
    from .docmodel import DocModelBuilder

    doc_model_builder = DocModelBuilder(source=arxiv, store=InMemoryDocModelStore())
    pipeline = IngestionPipelineService(
        arxiv=arxiv,
        full_text_store=InMemoryFullTextStore(),
        embedding=FakeEmbeddingPort(),
        vector_index=InMemoryVectorIndex(),
        control_plane=control,
        observability=observability,
        resilience=resilience,
        failure_handler=failure_handler,
        doc_model_builder=doc_model_builder,
    )
    refresh = RefreshOrchestrationService(
        arxiv=arxiv,
        control_plane=control,
        queue=queue,
        observability=observability,
    )
    return RuntimeServices(
        pipeline=pipeline,
        refresh=refresh,
        queue=queue,
        observability=observability,
        arxiv=arxiv,
    )


def _embedding_port(settings: IngestionSettings):
    """The writer's embedding model, chosen by the SAME setting the U2 reader reads.

    Reader and writer must resolve to one model: the vectors they produce only compare inside a
    single embedding space, and both sides are 1024-dimensional, so a mismatch passes every
    dimension check and shows up as semantically wrong neighbours. This used to be hardcoded to
    Bedrock here while the reader followed ``DOCSURI_EMBEDDING_PROVIDER``, which meant a single
    env value could split them with nothing failing until the index manifest was compared —
    after a full corpus build.
    """
    if settings.embedding_provider == "openai":
        from .adapters.openai_embedding import OpenAIEmbeddingPort

        return OpenAIEmbeddingPort(model=settings.openai_embedding_model)
    return BedrockCohereEmbeddingPort(
        model_id=settings.bedrock_model_id or "",
        # embed region decoupled from aws_region (OpenSearch SigV4): Cohere is not in apne2.
        region_name=settings.embed_region or settings.aws_region,
    )


def build_production_runtime(settings: IngestionSettings) -> RuntimeServices:
    settings.require_production()
    observability = LoggingObservabilityHub()
    # B3 raw-content cache wiring: only when explicitly enabled AND a bucket exists. Otherwise the
    # source keeps its default off mode → the live fetch path is byte-identical (raw_store=None).
    raw_cache_on = settings.raw_cache_mode != "off" and bool(settings.s3_bucket)
    # ONE store instance shared by every adapter that reads the cache: each S3RawContentStore
    # builds its own boto3 client (session/loader/endpoint resolution + a connection pool), so a
    # second instance is duplicated startup work against the same bucket.
    raw_store = (
        S3RawContentStore(
            bucket=settings.s3_bucket or "",
            prefix=settings.raw_cache_prefix,
            kms_key_id=settings.asset_kms_key_id,
        )
        if raw_cache_on
        else None
    )
    arxiv = ArxivHttpSource(
        timeout_seconds=settings.request_timeout_seconds,
        rate_limiter=TokenBucket(rate_per_second=settings.arxiv_rate_per_second),
        raw_store=raw_store,
        raw_cache_mode=settings.raw_cache_mode if raw_cache_on else "off",
        contact=settings.outbound_contact,
    )
    grobid = None
    if settings.grobid_url:
        from .adapters.grobid import GrobidHttpClient

        grobid = GrobidHttpClient(
            base_url=settings.grobid_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
    enabled_sources = _enabled_sources(settings.parsed_corpus_sources)
    semantic_scholar = openalex = None
    if grobid is not None:
        from .adapters.corpus_http import OpenAlexCorpusSource, SemanticScholarCorpusSource

        if SourceName.SEMANTIC_SCHOLAR in enabled_sources:
            semantic_scholar = SemanticScholarCorpusSource(
                api_key=settings.semantic_scholar_api_key,
                timeout_seconds=settings.request_timeout_seconds,
                contact=settings.outbound_contact,
            )
        if SourceName.OPENALEX in enabled_sources:
            openalex = OpenAlexCorpusSource(
                timeout_seconds=settings.request_timeout_seconds,
                mailto=settings.openalex_mailto,
                contact=settings.outbound_contact,
            )
    corpus_sources = CorpusSourceAdapterSet(
        arxiv=arxiv,
        grobid=grobid,
        semantic_scholar=semantic_scholar,
        openalex=openalex,
    )
    control = PostgresControlPlaneStore(settings.control_plane_dsn or "")
    queue = SqsQueue(
        queue_url=settings.sqs_queue_url or "",
        dlq_url=settings.sqs_dlq_url or "",
        region_name=settings.aws_region,
    )
    # Priority doc-model build queue (BR-30/D6) — reader-triggered BUILD_DOC_MODEL jobs land here,
    # off the bulk-backfill queue. Short poll (wait_time_seconds=0) so the worker's priority drain
    # never blocks the backfill queue. None when the URL is unset (feature off, single-queue).
    docmodel_queue = (
        SqsQueue(
            queue_url=settings.docmodel_queue_url,
            dlq_url=settings.docmodel_dlq_url or settings.sqs_dlq_url or "",
            region_name=settings.aws_region,
            wait_time_seconds=0,
        )
        if settings.docmodel_queue_url
        else None
    )
    resilience = IngestionResilienceService(
        observability,
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    failure_handler = IngestFailureHandler(queue, observability)
    # FR-17 multimodal assets (display-only), wired only when the flag is on — the pipeline gates
    # extraction on all three adapters being present, so the base worker is unaffected when off.
    # The arXiv PDF→GROBID rung (BR-30 2026-08-10) deliberately does NOT go through this source:
    # it reads the PDF from `arxiv` above, so a parsing rung never hangs on a display-only flag.
    asset_extractor = asset_store = asset_source = None
    if settings.multimodal_assets_enabled:
        from .adapters.assets import ArxivAssetSource, S3RdsAssetStore
        from .asset_extraction import AssetExtractor, ImageNormalizer

        asset_source = ArxivAssetSource(
            timeout_seconds=settings.asset_fetch_timeout_seconds,
            # Share the raw cache with the full-text source so an assets-enabled paper does not
            # download its PDF once for text and again for crops.
            raw_store=raw_store,
            raw_cache_mode=settings.raw_cache_mode if raw_cache_on else "off",
            contact=settings.outbound_contact,
        )

        asset_extractor = AssetExtractor(
            normalizer=ImageNormalizer(
                max_longest_side=settings.asset_max_longest_side,
                max_pixels=settings.asset_max_pixels,
                webp_quality=settings.asset_webp_quality,
            )
        )
        asset_store = S3RdsAssetStore(
            bucket=settings.s3_bucket or "",
            control_plane_dsn=settings.control_plane_dsn or "",
            prefix=settings.asset_s3_prefix,
            kms_key_id=settings.asset_kms_key_id,
        )
    # Doc-model builder (BR-30/D6): reuses the arXiv source (HTML→ar5iv tier) and the
    # single bucket's doc-model/ prefix. Phase-1 Corpus builds eagerly during ingest; the
    # BUILD_DOC_MODEL job remains for misses/backfills.
    from .adapters.aws import S3DocModelStore, S3UserDocumentSource
    from .docmodel import DocModelBuilder

    doc_model_builder = DocModelBuilder(
        source=arxiv,
        store=S3DocModelStore(
            bucket=settings.s3_bucket or "",
            kms_key_id=settings.asset_kms_key_id,
        ),
        # Reuse the asset e-print source (when assets are enabled) to read the author's LaTeX
        # preamble for KaTeX macros — best-effort, so None (assets off) just omits macros.
        eprint_source=asset_source,
        table_extractor=_table_extractor(settings),
        formula_reader=_formula_reader(settings),
        observability=observability,
    )
    pipeline = IngestionPipelineService(
        arxiv=arxiv,
        full_text_store=S3FullTextStore(bucket=settings.s3_bucket or ""),
        embedding=_embedding_port(settings),
        vector_index=OpenSearchVectorIndex(
            endpoint=settings.opensearch_endpoint or "",
            index_name=settings.opensearch_index,
            region_name=settings.aws_region,
            stats_ttl_seconds=settings.index_stats_ttl_seconds,
        ),
        control_plane=control,
        observability=observability,
        resilience=resilience,
        failure_handler=failure_handler,
        chunker=Chunker(
            max_chunk_chars=settings.max_chunk_chars,
            overlap_chars=settings.chunk_overlap_chars,
            max_chunks_per_paper=settings.max_chunks_per_paper,
        ),
        asset_extractor=asset_extractor,
        asset_store=asset_store,
        asset_source=asset_source,
        user_document_source=S3UserDocumentSource(
            bucket=settings.s3_bucket or "",
            max_bytes=settings.user_document_max_bytes,
        ),
        grobid=grobid,
        doc_model_builder=doc_model_builder,
        corpus_sources=corpus_sources,
    )
    refresh = RefreshOrchestrationService(
        arxiv=arxiv,
        control_plane=control,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        enabled_sources=enabled_sources,
    )
    return RuntimeServices(
        pipeline=pipeline,
        refresh=refresh,
        queue=queue,
        observability=observability,
        corpus_sources=corpus_sources,
        arxiv=arxiv,
        docmodel_queue=docmodel_queue,
    )


def _enabled_sources(names: tuple[str, ...]) -> tuple[SourceName, ...]:
    return tuple(SourceName(name) for name in names) or (SourceName.ARXIV,)


_OFF = {"", "off", "none", "false", "0", "disabled"}


def _optional_reader(setting: str | None, name: str, build: Callable[[], object]) -> object | None:
    """Resolve an ``auto`` / ``off`` / ``<name>`` reader setting to an adapter or None.

    ``auto`` (the default) means "on wherever the extra is installed": these readers only run on
    the PDF/GROBID path, which is the weakest one and the only path non-arXiv sources and user
    uploads ever take, so leaving them off by default would keep the worst path at its worst. The
    models ship as optional extras, so an environment without them silently gets the old
    behaviour instead of failing to boot. Naming the reader explicitly is the opposite contract —
    the ImportError propagates, because a deployment that asked for it must not quietly run without
    it.
    """
    value = (setting or "").strip().lower()
    if value in _OFF:
        return None
    if value == name:
        return build()
    if value != "auto":
        raise ValueError(f"unknown reader {setting!r}: expected 'auto', 'off', or {name!r}")
    try:
        return build()
    except ImportError:
        return None


def _table_extractor(settings: IngestionSettings) -> TableExtractorPort | None:
    """The second reader for the tables GROBID reconstructs wrongly (see ``_optional_reader``)."""

    def build() -> TableExtractorPort:
        from .adapters.docling_tables import DoclingTableExtractor

        return DoclingTableExtractor(max_pages=settings.docling_max_pages)

    return cast(
        "TableExtractorPort | None", _optional_reader(settings.table_extractor, "docling", build)
    )


def _formula_reader(settings: IngestionSettings) -> FormulaReaderPort | None:
    """The reader for the PDF path's formula images (see ``_optional_reader``)."""

    def build() -> FormulaReaderPort:
        from .adapters.pix2tex_formulas import Pix2TexFormulaReader

        return Pix2TexFormulaReader()

    return cast(
        "FormulaReaderPort | None", _optional_reader(settings.formula_reader, "pix2tex", build)
    )
