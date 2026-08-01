"""build_evidence_runner — U11 v2 실 어댑터 조립 (real-first).

Discovery(U2) 어댑터 재사용:
  BedrockCohereQueryEmbedder → EvidencePaperSearchTool.EmbeddingPort
  OpenSearchVectorStoreAdapter → VectorStorePort
  OpenSearchLexicalIndexAdapter → LexicalIndexPort
  OpenSearchPaperLookupAdapter → PaperLookupPort

Summarization(U7) 어댑터 재사용:
  S3DocModelReader → EvidenceDocModelTool

신규:
  EvidenceExtractor → Bedrock Sonnet 4.6 (claude-sonnet-4-6)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .runner import EvidenceTurnRunner, RunnerDeps
from .settings import EvidenceSettings


@dataclass(frozen=True)
class EvidenceBundle:
    runner: object
    settings: EvidenceSettings


def _build_guarded_query_embedder(
    d_settings: Any, os_client: Any, fallback_region: str | None
) -> Any:
    """Query-embedding provider switch + same-space guard, shared with discovery's read path.

    Bedrock Cohere (team deploy) vs OpenAI (solo-local, DOCSURI_EMBEDDING_PROVIDER=openai). The
    evidence agent is a SECOND reader over the SAME index, so it must resolve the provider the same
    (else a solo-local OpenAI-indexed corpus gets Bedrock query vectors) AND validate the index's
    embedding manifest against the reader identity — the dimension guard can't catch a
    same-dim/different-model swap (OpenAI vs Cohere, both 1024-dim).

    Returns the real embedder when the space matches (or can't be verified — logged), else a
    MismatchedSpaceEmbedder that raises EmbeddingUnavailable per request; EvidencePaperSearchTool.
    _hybrid_search catches that and degrades to lexical-only instead of scoring a foreign space.
    Extracted from build_evidence_runner so the guard wiring is unit-testable in isolation.
    """
    from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
    from discovery.adapters.openai_embedding import OpenAIQueryEmbedder
    from discovery.adapters.space_guard import guard_embedding_space
    from docsuri_shared.vector_spec import DIMENSIONS

    if d_settings.embedding_provider == 'openai':
        embedding: object = OpenAIQueryEmbedder(model=d_settings.openai_embedding_model)
        reader_identity = {
            'provider': 'openai',
            'model': d_settings.openai_embedding_model,
            'dimensions': DIMENSIONS,
        }
    else:
        embedding = BedrockCohereQueryEmbedder(
            model_id=d_settings.bedrock_model_id,
            # Bedrock region decoupled from region_name (OpenSearch SigV4): Cohere v3 isn't in
            # ap-northeast-2, so query embedding goes cross-region. Mirrors discovery real_wiring.
            region_name=d_settings.bedrock_region or fallback_region,
        )
        reader_identity = {
            'provider': 'bedrock',
            'model': d_settings.bedrock_model_id,
            'dimensions': DIMENSIONS,
        }
    return guard_embedding_space(os_client, d_settings.opensearch_index, reader_identity, embedding)


def build_evidence_runner(
    settings: EvidenceSettings, cost_guard: object | None = None
) -> EvidenceBundle:
    """실 어댑터 조립 — DOCSURI_DOCMODEL_BUCKET + OpenSearch 설정 필요.

    cost_guard(U6 단일 권위)를 주면 턴 실행의 비용 게이트에
    연결된다(NFR-C1).
    """
    # --- Discovery 어댑터 (U2 재사용) ---
    from discovery.adapters.opensearch_index import (
        OpenSearchClientFactory,
        OpenSearchLexicalIndexAdapter,
            OpenSearchVectorStoreAdapter,
    )
    from discovery.adapters.settings import DiscoverySettings

    d_settings = DiscoverySettings.from_env()
    os_client = OpenSearchClientFactory.build(
        endpoint=d_settings.opensearch_endpoint,
        region_name=settings.region_name,
        username=d_settings.opensearch_username,
        password=d_settings.opensearch_password,
        use_ssl=d_settings.opensearch_use_ssl,
        verify_certs=d_settings.opensearch_verify_certs,
    )

    # Query-embedding: provider switch (Bedrock/OpenAI) + same-space guard. The evidence agent is a
    # SECOND reader over the SAME index, so it must resolve the provider and validate the embedding
    # space exactly as discovery's read path does (see helper for the why).
    embedding = _build_guarded_query_embedder(d_settings, os_client, settings.region_name)
    vector_store = OpenSearchVectorStoreAdapter(os_client, d_settings.opensearch_index)
    lexical_index = OpenSearchLexicalIndexAdapter(os_client, d_settings.opensearch_index)

    from .adapters.sources import ArxivExternalSearch, CorpusSearch, DocModelReader

    corpus_search = CorpusSearch(
        embedding=embedding,
        vector_store=vector_store,
        lexical_index=lexical_index,
    )

    # --- S3 DocModel 리더 (U7 재사용) ---
    from summarization.adapters.s3_docmodel import S3DocModelReader

    doc_model_reader = S3DocModelReader(
        bucket=settings.docmodel_bucket,
        region_name=settings.region_name,
    )
    doc_models = DocModelReader(doc_model_reader)

    # --- LLM (결정 + 추출) ---
    from .adapters.llm_openai import OpenAiDecider, OpenAiExtractor

    decider = OpenAiDecider(model=settings.model_id)
    extractor = OpenAiExtractor(model=settings.model_id)

    # --- 선택 도구: 없으면 등록되지 않고 도구 목록이 자연 축소된다 ---
    external_search = None
    promotion = None
    if _external_enabled():
        external_search = ArxivExternalSearch(_build_arxiv_client())
        promotion = _build_promotion(doc_models)

    assets = _build_asset_reader()

    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=decider,
            extractor=extractor,
            corpus_search=corpus_search,
            external_search=external_search,
            doc_models=doc_models,
            promotion=promotion,
            assets=assets,
            cost_guard=cost_guard,
        )
    )
    return runner


# --- 선택 의존성 조립 --------------------------------------------------------
#
# 각 헬퍼는 설정이 없으면 None을 돌려주고, None인 도구는 레지스트리에 등록되지
# 않는다. "기능이 조용히 죽는" 것과 다르다 — 등록되지 않은 도구는 모델에게
# 보이지도 않으므로 에이전트가 그 경로를 시도하지 않는다.


def _external_enabled() -> bool:
    from docsuri_shared.env import env_flag

    return env_flag('DOCSURI_EVIDENCE_EXTERNAL_SEARCH_ENABLED')


def _build_arxiv_client() -> object:
    """u1의 arXiv 클라이언트를 재사용한다 — 별도 클라이언트를 만들지 않는다."""
    from docsuri_ingestion.adapters.arxiv import ArxivAdapter

    return ArxivAdapter()


def _build_promotion(doc_models: object) -> object | None:
    from .adapters.promotion import QueuedPaperPromotion

    queue = _build_build_queue()
    if queue is None:
        return None
    return QueuedPaperPromotion(
        build_queue=queue,
        doc_models=doc_models,
        poll_timeout_seconds=_float_env('DOCSURI_EVIDENCE_PROMOTION_TIMEOUT_MS', 20000) / 1000,
    )


def _build_build_queue() -> object | None:
    """u7이 쓰는 것과 같은 BUILD_DOC_MODEL 큐 어댑터를 재사용한다(TD-EV2-5)."""
    queue_url = os.environ.get('DOCSURI_DOCMODEL_BUILD_QUEUE_URL')
    if not queue_url:
        return None
    from summarization.adapters.sqs_docmodel_build import SqsDocModelBuildQueue

    return SqsDocModelBuildQueue(queue_url=queue_url)


def _build_asset_reader() -> object | None:
    if not os.environ.get('DOCSURI_DATABASE_URL'):
        return None
    from backend.db import make_engine, make_session_factory
    from backend.modules.paper_assets import SqlS3FigureReader

    engine = make_engine(os.environ['DOCSURI_DATABASE_URL'])
    return SqlS3FigureReader(make_session_factory(engine))


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default
