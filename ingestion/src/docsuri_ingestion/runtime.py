from __future__ import annotations

from dataclasses import dataclass

from .adapters.arxiv import ArxivHttpSource
from .adapters.aws import (
    BedrockCohereEmbeddingPort,
    OpenSearchVectorIndex,
    S3FullTextStore,
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
    arxiv = ArxivHttpSource(
        timeout_seconds=settings.request_timeout_seconds,
        rate_limiter=None,
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
            openalex = OpenAlexCorpusSource(timeout_seconds=settings.request_timeout_seconds)
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
    resilience = IngestionResilienceService(
        observability,
        timeout_seconds=settings.request_timeout_seconds,
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
    from .adapters.aws import S3DocModelStore
    from .docmodel import DocModelBuilder

    doc_model_builder = DocModelBuilder(
        source=arxiv,
        store=S3DocModelStore(
            bucket=settings.s3_bucket or "",
            kms_key_id=settings.asset_kms_key_id,
        ),
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
    )


def _enabled_sources(raw: str) -> tuple[SourceName, ...]:
    sources = tuple(SourceName(part.strip()) for part in raw.split(",") if part.strip())
    return sources or (SourceName.ARXIV,)
