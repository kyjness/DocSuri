"""Mock wiring helper — assembles the full U2 pipeline with mocks + stubs for standalone
dev/test (mock-first). Real adapters swap in via the same constructor args (MR-4)."""

from __future__ import annotations

from dataclasses import dataclass

from ..cache.embedding_cache import EmbeddingCache
from ..domain.assembler import ResultAssembler
from ..domain.expander import QueryUnderstandingExpander
from ..domain.grounding_adapter import GroundingAdapter
from ..domain.ranker import RelevanceRanker
from ..domain.retriever import HybridRetriever
from ..domain.validator import QueryValidator
from ..service.orchestrator import SearchOrchestrationService
from ..service.paper_metadata import PaperMetadataService
from .adapters import (
    MockEmbeddingAdapter,
    MockLexicalIndexAdapter,
    MockPaperLookupAdapter,
    MockVectorStoreAdapter,
)
from .port_stubs import (
    InMemoryEventPublisher,
    NoopObservabilityHub,
    StubCostGuard,
    StubGroundingHook,
)


@dataclass(frozen=True, slots=True)
class MockBundle:
    orchestrator: SearchOrchestrationService
    grounding_hook: StubGroundingHook
    event_publisher: InMemoryEventPublisher
    paper_service: PaperMetadataService


def build_mock_orchestrator(
    *,
    degrade_mode: str = "normal",
    grounding_verdict: str = "pass",
    embedding_adapter=None,
    vector_store=None,
    lexical_index=None,
    ttl_seconds: float = 300.0,
    observability=None,
    cost_guard=None,
) -> MockBundle:
    """Wire the U2 pipeline with mocks. Override any adapter (e.g. a Failing* one) for tests."""
    embedding = embedding_adapter or MockEmbeddingAdapter()
    cache = EmbeddingCache(embedding, ttl_seconds=ttl_seconds)
    publisher = InMemoryEventPublisher()
    orchestrator = SearchOrchestrationService(
        validator=QueryValidator(),
        expander=QueryUnderstandingExpander(cache),
        retriever=HybridRetriever(
            vector_store or MockVectorStoreAdapter(),
            lexical_index or MockLexicalIndexAdapter(),
        ),
        ranker=RelevanceRanker(),
        grounding_adapter=GroundingAdapter(),
        assembler=ResultAssembler(),
        cost_guard=cost_guard or StubCostGuard(degrade_mode=degrade_mode),
        observability=observability or NoopObservabilityHub(),
        event_publisher=publisher,
    )
    return MockBundle(
        orchestrator=orchestrator,
        grounding_hook=StubGroundingHook(verdict=grounding_verdict),
        event_publisher=publisher,
        paper_service=PaperMetadataService(MockPaperLookupAdapter()),
    )
