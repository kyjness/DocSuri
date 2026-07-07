from __future__ import annotations

from docsuri_ingestion.adapters.local import (
    CapturingObservabilityHub,
    FakeArxivSource,
    FakeEmbeddingPort,
    InMemoryControlPlaneStore,
    InMemoryFullTextStore,
    InMemoryQueue,
    InMemoryVectorIndex,
    sample_metadata,
)
from docsuri_ingestion.application import IngestionPipelineService
from docsuri_ingestion.resilience import (
    IngestFailureHandler,
    IngestionResilienceService,
    RetryPolicy,
)


def build_test_pipeline(
    *,
    vector_index: InMemoryVectorIndex | None = None,
    embedding=None,
    arxiv=None,
    retry_attempts: int = 1,
    doc_model_builder=None,
    asset_store=None,
    user_document_source=None,
    grobid=None,
    corpus_sources=None,
):
    metadata = sample_metadata()
    arxiv = arxiv or FakeArxivSource([metadata])
    control = InMemoryControlPlaneStore()
    queue = InMemoryQueue()
    observability = CapturingObservabilityHub()
    resilience = IngestionResilienceService(
        observability,
        retry_policy=RetryPolicy(
            max_attempts=retry_attempts, base_delay_seconds=0.0, jitter_ratio=0.0
        ),
        timeout_seconds=2.0,
    )
    vector_index = vector_index or InMemoryVectorIndex()
    pipeline = IngestionPipelineService(
        arxiv=arxiv,
        full_text_store=InMemoryFullTextStore(),
        embedding=embedding or FakeEmbeddingPort(),
        vector_index=vector_index,
        control_plane=control,
        observability=observability,
        resilience=resilience,
        failure_handler=IngestFailureHandler(queue, observability),
        asset_store=asset_store,
        user_document_source=user_document_source,
        grobid=grobid,
        doc_model_builder=doc_model_builder,
        corpus_sources=corpus_sources,
    )
    return pipeline, control, vector_index, queue, observability
