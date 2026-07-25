"""build_evidence_orchestrator — U11 실 어댑터 조립 (real-first, TD-E1~E11).

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

from dataclasses import dataclass
from typing import Any

from .assembler import EvidenceComparisonAssembler
from .extractor import EvidenceExtractor
from .orchestrator import EvidenceAgentOrchestrator
from .settings import EvidenceSettings
from .tools import EvidenceDocModelTool, EvidencePaperSearchTool


@dataclass(frozen=True)
class EvidenceBundle:
    orchestrator: EvidenceAgentOrchestrator
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
    Extracted from build_evidence_orchestrator so the guard wiring is unit-testable in isolation.
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


def build_evidence_orchestrator(
    settings: EvidenceSettings, cost_guard: object | None = None
) -> EvidenceBundle:
    """실 어댑터 조립 — DOCSURI_DOCMODEL_BUCKET + OpenSearch 설정 필요.

    cost_guard(U6 단일 권위)를 주면 orchestrator 비용 게이트 + extractor 지출 기록에
    연결된다(NFR-C1).
    """
    # --- Discovery 어댑터 (U2 재사용) ---
    from discovery.adapters.opensearch_index import (
        OpenSearchClientFactory,
        OpenSearchLexicalIndexAdapter,
        OpenSearchPaperLookupAdapter,
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
    paper_lookup = OpenSearchPaperLookupAdapter(os_client, d_settings.opensearch_index)

    search_tool = EvidencePaperSearchTool(
        embedding=embedding,
        vector_store=vector_store,
        lexical_index=lexical_index,
        paper_lookup=paper_lookup,
    )

    # --- S3 DocModel 리더 (U7 재사용) ---
    from summarization.adapters.s3_docmodel import S3DocModelReader

    doc_model_reader = S3DocModelReader(
        bucket=settings.docmodel_bucket,
        region_name=settings.region_name,
    )
    doc_model_tool = EvidenceDocModelTool(doc_model_reader=doc_model_reader)

    # --- EvidenceExtractor (Bedrock Sonnet 4.6) ---
    extractor = EvidenceExtractor(
        model_id=settings.model_id,
        region_name=settings.region_name,
        cost_guard=cost_guard,
    )

    # --- Assembler & Orchestrator ---
    assembler = EvidenceComparisonAssembler()
    orchestrator = EvidenceAgentOrchestrator(
        search_tool=search_tool,
        doc_model_tool=doc_model_tool,
        extractor=extractor,
        assembler=assembler,
        cost_guard=cost_guard,
    )

    return EvidenceBundle(orchestrator=orchestrator, settings=settings)
