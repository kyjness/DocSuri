"""Real-adapter wiring — the production counterpart of ``testing.wiring`` (MR-4).

``build_real_orchestrator`` assembles the SAME U2 pipeline as ``build_mock_orchestrator``
but injects the real OpenSearch/Bedrock adapters. Same constructor seam, same contract —
the only difference is which adapters are plugged in (a wiring decision, not a contract
change). The grounding gate is NOT wired here: it is U6's single authority (INV-1), injected
by the app-shell alongside the returned orchestrator (as it already is for the mock bundle).

The cost hook remains a local stub (advisory-read-only from U2's side, BR-12). The
observability hook is now injectable: the app-shell passes its process-wide U6 hub
(CloudWatch-backed in prod) so U2 app metrics actually leave the process; absent that, it
falls back to the no-op stub (US-R4).
"""

from __future__ import annotations

from dataclasses import dataclass

from docsuri_shared.ports import CostGuardCircuitBreaker, ObservabilityHub
from docsuri_shared.vector_spec import DIMENSIONS

from .adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from .adapters.bedrock_rerank import BedrockRerankAdapter
from .adapters.event_publisher import EventBridgeEventPublisher
from .adapters.openai_embedding import OpenAIQueryEmbedder
from .adapters.opensearch_index import (
    OpenSearchClientFactory,
    OpenSearchLexicalIndexAdapter,
    OpenSearchPaperLookupAdapter,
    OpenSearchVectorStoreAdapter,
)
from .adapters.resilience import CircuitBreaker, CircuitGuardedEmbedder
from .adapters.settings import DiscoverySettings
from .adapters.space_guard import MismatchedSpaceEmbedder, guard_embedding_space
from .cache.embedding_cache import EmbeddingCache
from .defaults.port_stubs import InMemoryEventPublisher, NoopObservabilityHub, StubCostGuard
from .domain.assembler import ResultAssembler
from .domain.expander import QueryUnderstandingExpander
from .domain.grounding_adapter import GroundingAdapter
from .domain.ranker import RelevanceRanker
from .domain.retriever import HybridRetriever
from .domain.validator import QueryValidator
from .ports.search_ports import EventPublisher
from .service.orchestrator import SearchOrchestrationService
from .service.paper_metadata import PaperMetadataService


@dataclass(frozen=True, slots=True)
class RealBundle:
    orchestrator: SearchOrchestrationService
    event_publisher: EventPublisher
    paper_service: PaperMetadataService


def build_real_orchestrator(
    settings: DiscoverySettings,
    observability: ObservabilityHub | None = None,
    cost_guard: CostGuardCircuitBreaker | None = None,
) -> RealBundle:
    """Wire the U2 pipeline against real OpenSearch + Bedrock (production read path).

    ``observability`` is the app-shell's process-wide U6 hub (CloudWatch-backed in prod);
    omitted (standalone/tests) → the no-op stub. This is the seam that routes U2 app metrics
    to CloudWatch — without it (the old default) the orchestrator emitted into the void.
    """
    if not settings.search_enabled:
        raise ValueError(
            "build_real_orchestrator requires DOCSURI_OPENSEARCH_ENDPOINT + an embedding "
            "provider — DOCSURI_BEDROCK_MODEL_ID or DOCSURI_EMBEDDING_PROVIDER=openai "
            "(use build_mock_orchestrator otherwise)"
        )

    client = OpenSearchClientFactory.build(
        endpoint=settings.opensearch_endpoint,
        region_name=settings.aws_region,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )
    if settings.embedding_provider == "openai":
        # Solo-local migration: personal OpenAI key replaces Bedrock (see the adapter's
        # docstring for the same-space invariant with the reindex writer).
        embedding: object = OpenAIQueryEmbedder(model=settings.openai_embedding_model)
        reader_identity = {
            "provider": "openai",
            "model": settings.openai_embedding_model,
            "dimensions": DIMENSIONS,
        }
    else:
        embedding = BedrockCohereQueryEmbedder(
            model_id=settings.bedrock_model_id or "",
            # Bedrock region decoupled from aws_region (OpenSearch SigV4): Cohere v3 isn't in
            # ap-northeast-2, so the reader embeds queries cross-region. Falls back to aws_region.
            region_name=settings.bedrock_region or settings.aws_region,
        )
        reader_identity = {
            "provider": "bedrock",
            "model": settings.bedrock_model_id or "",
            "dimensions": DIMENSIONS,
        }
    # Same-space guard (u2 business-rules §6 / N1): validate the active index's embedding
    # manifest against the reader identity ONCE here; a mismatch swaps in a sentinel that
    # degrades every request to lexical-only (vector leg off) instead of serving semantically
    # contaminated neighbors. Legacy manifest-less indices pass with a warning.
    embedding = guard_embedding_space(
        client, settings.opensearch_index, reader_identity, embedding
    )
    # Dependency circuits (nfr-design-patterns §1.2): cache → circuit → real adapter, so cache
    # hits bypass the breaker and a sustained embedding outage fails fast into lexical-only.
    # The mismatch sentinel is NOT breaker-wrapped: its deliberate per-request raise would open
    # the circuit and replace the mismatch reason with a phantom "provider outage" message.
    if not isinstance(embedding, MismatchedSpaceEmbedder):
        embedding_breaker = CircuitBreaker(f"{reader_identity['provider']}-embedding")
        embedding = CircuitGuardedEmbedder(embedding, embedding_breaker)
    cache = EmbeddingCache(embedding, ttl_seconds=settings.embedding_cache_ttl_seconds)

    # The bus is shared infra (system/U6 EventBridge). Until provisioned, keep events
    # in-memory so search still serves — history is best-effort (BR-14).
    publisher: EventPublisher
    if settings.search_event_bus:
        publisher = EventBridgeEventPublisher(
            event_bus_name=settings.search_event_bus, region_name=settings.aws_region
        )
    else:
        publisher = InMemoryEventPublisher()

    # Cross-encoder reranker (FR-3), optional: wired only when the model ARN is configured;
    # absent → baseline RRF order. Its failures are fail-soft (RerankUnavailable → baseline).
    # The client region is the RESOLVED rerank region (Tokyo/us-west-2 via DOCSURI_RERANK_REGION or
    # the ARN's region) — NOT the Seoul deploy region, where the rerank model does not exist.
    reranker = (
        BedrockRerankAdapter(
            model_arn=settings.rerank_model_arn,
            region_name=settings.rerank_region_resolved,
        )
        if settings.rerank_model_arn
        else None
    )

    # ONE circuit for the one OpenSearch store (k-NN, BM25, and lookup share the dependency);
    # OPEN → immediate IndexUnavailable → the existing fail-closed 503, skipping the doomed
    # retry+timeout budget on every request of a sustained outage.
    store_breaker = CircuitBreaker("opensearch")
    orchestrator = SearchOrchestrationService(
        validator=QueryValidator(),
        expander=QueryUnderstandingExpander(cache),
        retriever=HybridRetriever(
            OpenSearchVectorStoreAdapter(client, settings.opensearch_index, store_breaker),
            OpenSearchLexicalIndexAdapter(client, settings.opensearch_index, store_breaker),
        ),
        ranker=RelevanceRanker(),
        grounding_adapter=GroundingAdapter(),
        assembler=ResultAssembler(),
        cost_guard=cost_guard or StubCostGuard(),
        observability=observability or NoopObservabilityHub(),
        event_publisher=publisher,
        reranker=reranker,
    )
    paper_service = PaperMetadataService(
        OpenSearchPaperLookupAdapter(client, settings.opensearch_index, store_breaker)
    )
    return RealBundle(
        orchestrator=orchestrator, event_publisher=publisher, paper_service=paper_service
    )
