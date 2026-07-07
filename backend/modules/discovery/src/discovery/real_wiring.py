"""Real-adapter wiring — the production counterpart of ``mocks.wiring`` (MR-4).

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

from .adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from .adapters.bedrock_rerank import BedrockRerankAdapter
from .adapters.event_publisher import EventBridgeEventPublisher
from .adapters.opensearch_index import (
    OpenSearchClientFactory,
    OpenSearchLexicalIndexAdapter,
    OpenSearchPaperLookupAdapter,
    OpenSearchVectorStoreAdapter,
)
from .adapters.settings import DiscoverySettings
from .cache.embedding_cache import EmbeddingCache
from .domain.assembler import ResultAssembler
from .domain.expander import QueryUnderstandingExpander
from .domain.grounding_adapter import GroundingAdapter
from .domain.ranker import RelevanceRanker
from .domain.retriever import HybridRetriever
from .domain.validator import QueryValidator
from .mocks.port_stubs import InMemoryEventPublisher, NoopObservabilityHub, StubCostGuard
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
    if not settings.opensearch_endpoint or not settings.bedrock_model_id:
        raise ValueError(
            "build_real_orchestrator requires DOCSURI_OPENSEARCH_ENDPOINT + "
            "DOCSURI_BEDROCK_MODEL_ID (use build_mock_orchestrator otherwise)"
        )

    client = OpenSearchClientFactory.build(
        endpoint=settings.opensearch_endpoint,
        region_name=settings.aws_region,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )
    embedding = BedrockCohereQueryEmbedder(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
    )
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

    orchestrator = SearchOrchestrationService(
        validator=QueryValidator(),
        expander=QueryUnderstandingExpander(cache),
        retriever=HybridRetriever(
            OpenSearchVectorStoreAdapter(client, settings.opensearch_index),
            OpenSearchLexicalIndexAdapter(client, settings.opensearch_index),
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
        OpenSearchPaperLookupAdapter(client, settings.opensearch_index)
    )
    return RealBundle(
        orchestrator=orchestrator, event_publisher=publisher, paper_service=paper_service
    )
