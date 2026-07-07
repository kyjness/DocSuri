from __future__ import annotations

from dataclasses import dataclass

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
from .corpus_sources import CorpusSourceAdapterSet
from .domain.enums import SourceName
from .observability import LoggingObservabilityHub
from .resilience import IngestFailureHandler, IngestionResilienceService
from .settings import IngestionSettings


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    pipeline: IngestionPipelineService
    refresh: RefreshOrchestrationService
    queue: object
    observability: object
    corpus_sources: object | None = None
    # Optional priority doc-model build queue (BR-30/D6). None → worker polls only `queue`.
    docmodel_queue: object | None = None


def build_local_runtime() -> RuntimeServices:
    metadata = [sample_metadata()]
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
        pipeline=pipeline, refresh=refresh, queue=queue, observability=observability
    )


def build_production_runtime(settings: IngestionSettings) -> RuntimeServices:
    settings.require_production()
    observability = LoggingObservabilityHub()
    # B3 raw-content cache wiring: only when explicitly enabled AND a bucket exists. Otherwise the
    # source keeps its default off mode → the live fetch path is byte-identical (raw_store=None).
    raw_cache_on = settings.raw_cache_mode != "off" and bool(settings.s3_bucket)
    arxiv = ArxivHttpSource(
        timeout_seconds=settings.request_timeout_seconds,
        rate_limiter=None,
        raw_store=(
            S3RawContentStore(
                bucket=settings.s3_bucket or "",
                prefix=settings.raw_cache_prefix,
                kms_key_id=settings.asset_kms_key_id,
            )
            if raw_cache_on
            else None
        ),
        raw_cache_mode=settings.raw_cache_mode if raw_cache_on else "off",
    )
    grobid = None
    if settings.grobid_url:
        from .adapters.grobid import GrobidHttpClient

        grobid = GrobidHttpClient(
            base_url=settings.grobid_url,
            timeout_seconds=settings.request_timeout_seconds,
        )
    enabled_sources = _enabled_sources(settings.corpus_sources)
    semantic_scholar = openalex = None
    if grobid is not None:
        from .adapters.corpus_http import OpenAlexCorpusSource, SemanticScholarCorpusSource

        if SourceName.SEMANTIC_SCHOLAR in enabled_sources:
            semantic_scholar = SemanticScholarCorpusSource(
                api_key=settings.semantic_scholar_api_key,
                timeout_seconds=settings.request_timeout_seconds,
            )
        if SourceName.OPENALEX in enabled_sources:
            openalex = OpenAlexCorpusSource(
                timeout_seconds=settings.request_timeout_seconds,
                mailto=settings.openalex_mailto,
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
    # FR-17 multimodal assets (display-only). Wired only when the flag is on — the three
    # adapters are injected together (the pipeline gates extraction on all three being
    # present), so the base worker is unaffected when off. Best-effort: never blocks indexing.
    asset_extractor = asset_store = asset_source = None
    if settings.multimodal_assets_enabled:
        from .adapters.assets import ArxivAssetSource, S3RdsAssetStore
        from .asset_extraction import AssetExtractor, ImageNormalizer

        asset_extractor = AssetExtractor(
            normalizer=ImageNormalizer(
                max_longest_side=settings.asset_max_longest_side,
                max_pixels=settings.asset_max_pixels,
                webp_quality=settings.asset_webp_quality,
            )
        )
        asset_source = ArxivAssetSource(timeout_seconds=settings.asset_fetch_timeout_seconds)
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
        observability=observability,
    )
    pipeline = IngestionPipelineService(
        arxiv=arxiv,
        full_text_store=S3FullTextStore(bucket=settings.s3_bucket or ""),
        embedding=BedrockCohereEmbeddingPort(
            model_id=settings.bedrock_model_id or "",
            region_name=settings.aws_region,
        ),
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
        embedding_v2=BedrockCohereEmbeddingPort(
            model_id=settings.bedrock_model_id_v2,
            region_name=settings.aws_region,
        ) if settings.bedrock_model_id_v2 else None,
        vector_index_v2=OpenSearchVectorIndex(
            endpoint=settings.opensearch_endpoint or "",
            index_name=settings.opensearch_index_v2,
            region_name=settings.aws_region,
            stats_ttl_seconds=settings.index_stats_ttl_seconds,
        ) if settings.bedrock_model_id_v2 else None,
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
        docmodel_queue=docmodel_queue,
    )


def _enabled_sources(raw: str) -> tuple[SourceName, ...]:
    sources = tuple(SourceName(part.strip()) for part in raw.split(",") if part.strip())
    return sources or (SourceName.ARXIV,)
