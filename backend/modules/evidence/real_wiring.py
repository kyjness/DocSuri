"""build_evidence_runner — U11 v2 실 어댑터 조립 (real-first).

Discovery(U2) 어댑터 재사용:
  BedrockCohereQueryEmbedder → EvidencePaperSearchTool.EmbeddingPort
  OpenSearchVectorStoreAdapter → VectorStorePort
  OpenSearchLexicalIndexAdapter → LexicalIndexPort
  OpenSearchPaperLookupAdapter → PaperLookupPort

Summarization(U7) 어댑터 재사용:
  S3DocModelReader → EvidenceDocModelTool

신규:
  EvidenceExtractor/Decider → Bedrock Anthropic Sonnet 4.6.
"""

from __future__ import annotations

import os
from typing import Any

from docsuri_shared.env import env_float

from .runner import EvidenceTurnRunner, RunnerDeps
from .settings import EvidenceSettings


def _build_guarded_query_embedder(
    d_settings: Any, os_client: Any, fallback_region: str | None
) -> Any:
    """Query embedder + same-space guard, built the same way discovery's read path builds it.

    The evidence agent is a SECOND reader over the SAME index, so it must resolve the same model
    AND validate the index's embedding manifest against the reader identity — the dimension guard
    cannot catch a same-dimension/different-model swap, and Cohere Embed Multilingual v3 and
    Embed v4 are both 1024-dimensional.

    Returns the real embedder when the space matches (or can't be verified — logged), else a
    MismatchedSpaceEmbedder that raises EmbeddingUnavailable per request; EvidencePaperSearchTool.
    _hybrid_search catches that and degrades to lexical-only instead of scoring a foreign space.
    Extracted from build_evidence_runner so the guard wiring is unit-testable in isolation.
    """
    from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
    from discovery.adapters.space_guard import guard_embedding_space
    from docsuri_shared.vector_spec import DIMENSIONS

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
    settings: EvidenceSettings,
    *,
    cost_guard: Any | None = None,
    session_factory: Any | None = None,
    graph: Any | None = None,
) -> EvidenceTurnRunner:
    """실 어댑터 조립 — DOCSURI_DOCMODEL_BUCKET + OpenSearch 설정 필요.

    cost_guard(U6 단일 권위)를 주면 턴 실행의 비용 게이트에
    연결된다(NFR-C1). graph(=TurnCheckpoints.graph)를 주면 super-step마다 루프 스냅샷이
    저장된다(v3 §5). 안 주면 체크포인트 없이 돈다.
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

    # Query-embedding: same embedder as U2 + same-space guard. The evidence agent is a
    # SECOND reader over the SAME index, so it must resolve the same model and validate the
    # embedding space exactly as discovery's read path does (see helper for the why).
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
    # 어댑터 조립은 여기, composition root에서만 일어난다(TD-EV2-2). 루프 코어와 프롬프트는
    # 무엇이 조립됐는지 모른다 — 포트가 같기 때문이다.
    import boto3
    from botocore.config import Config

    from .adapters.llm_bedrock import BedrockDecider, BedrockExtractor

    rates = {
        "input_usd_per_mtok": settings.input_usd_per_mtok,
        "output_usd_per_mtok": settings.output_usd_per_mtok,
    }
    # ONE client for both adapters, with botocore's own retries turned off. The failure
    # contract belongs to SourceBreaker (retry once, then trip) — botocore's default legacy
    # mode would retry ~5x underneath it, so a sustained outage cost ~10 wire attempts per
    # turn and the breaker saw one failure per ten, never opening. Timeouts bound a hung
    # turn; the loop budget, not the transport, decides how long a job may run.
    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.region_name,
        config=Config(connect_timeout=5, read_timeout=90, retries={"max_attempts": 1}),
    )
    decider = BedrockDecider(model=settings.model_id, client=client, **rates)
    extractor = BedrockExtractor(model=settings.model_id, client=client, **rates)

    # --- 선택 도구: 없으면 등록되지 않고 도구 목록이 자연 축소된다 ---
    external_search = None
    promotion = None
    if _external_enabled():
        external_search = ArxivExternalSearch(_build_arxiv_client())
        promotion = _build_promotion(doc_models)

    assets = _build_asset_reader(session_factory)

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
            budget_factory=settings.build_loop_budget,
        ),
        graph=graph,
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
    """evidence 자체의 arXiv 검색 클라이언트.

    초안은 u1 `ArxivAdapter` 재사용을 적었지만 둘 다 성립하지 않았다: 그 어댑터에는
    search()가 없고(수확·전문 취득용), `docsuri_ingestion`은 backend 의존성이 아니라
    import 자체가 마운트를 죽인다. "질의 → 제목·초록"은 표준 라이브러리로 닫힌다.
    """
    from .adapters.sources import ArxivApiClient

    return ArxivApiClient()


def _build_promotion(doc_models: object) -> object | None:
    from .adapters.promotion import QueuedPaperPromotion

    queue = _build_build_queue()
    if queue is None:
        return None
    return QueuedPaperPromotion(
        build_queue=queue,
        doc_models=doc_models,
        poll_timeout_seconds=env_float('DOCSURI_EVIDENCE_PROMOTION_TIMEOUT_MS', 20000) / 1000,
    )


def _build_build_queue() -> object | None:
    """u7이 쓰는 것과 같은 BUILD_DOC_MODEL 큐 어댑터를 재사용한다(TD-EV2-5)."""
    queue_url = os.environ.get('DOCSURI_DOCMODEL_BUILD_QUEUE_URL')
    if not queue_url:
        return None
    from summarization.adapters.sqs_docmodel_build import SqsDocModelBuildQueue

    return SqsDocModelBuildQueue(queue_url=queue_url)


def _build_asset_reader(session_factory: object | None) -> object | None:
    """자산 리더 — 앱쉘이 이미 가진 세션 팩토리를 재사용한다.

    여기서 엔진을 새로 만들면 같은 프로세스에 같은 Postgres로 향하는 커넥션 풀이
    두 벌 생긴다. 팩토리가 없을 때(단독 워커)만 직접 만든다.
    """
    from backend.modules.paper_assets import SqlS3FigureReader

    if session_factory is not None:
        return SqlS3FigureReader(session_factory)
    # 단독 워커 경로 — DB 접속은 config가 소유한 해석(DATABASE_URL/DB_HOST 조합)을
    # 그대로 쓴다. 별도 env 이름을 지어내면 아무도 안 세팅해 view_figure가 워커에서만
    # 조용히 빠진다(리뷰 지적 — DOCSURI_DATABASE_URL은 저장소 어디에도 없는 이름이었다).
    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    database_url = Settings.from_env().database_url
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        return None  # paper_asset은 Postgres에만 있다
    engine = make_engine(database_url)
    return SqlS3FigureReader(make_session_factory(engine))

