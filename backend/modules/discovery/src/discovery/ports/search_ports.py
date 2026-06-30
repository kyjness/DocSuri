"""U2-owned ports: the capability adapters U2 depends on by injection (logical-components
§1.1). mock-first: these are interfaces only; real impls (OpenSearch/Bedrock) land after
Infra/U1 corpus (CG-2/MR-1). The cross-cutting U6 hooks (GroundingEnforcementHook,
CostGuardCircuitBreaker, ObservabilityHub) are NOT redefined here — import them from
``docsuri_shared.ports`` (single authority = U6).

Dependency-isolation exceptions (RES-9 / NFR-R2 / Q1=A fail-fast):
- ``EmbeddingUnavailable`` — Bedrock embedding failed → orchestrator falls back to
  lexical-only (degraded), embedding is a separable dependency.
- ``IndexUnavailable`` — the OpenSearch index (k-NN + BM25, one store) failed → no fallback
  path → orchestrator raises ``SearchUnavailable`` (fail-closed, INV-3/SEC-15).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from docsuri_shared.events import SearchExecutedEvent
from docsuri_shared.vector_spec import IndexRecord

__all__ = [
    "EmbeddingUnavailable",
    "IndexUnavailable",
    "SearchUnavailable",
    "ScoredRecord",
    "EmbeddingAdapter",
    "VectorStoreAdapter",
    "LexicalIndexAdapter",
    "PaperLookupAdapter",
    "EventPublisher",
]


class EmbeddingUnavailable(Exception):
    """Query-embedding dependency (Bedrock) failed — fall back to lexical-only (BR-11/16)."""


class IndexUnavailable(Exception):
    """Search index dependency (OpenSearch) failed — fail-closed, no fallback (INV-3)."""


class SearchUnavailable(Exception):
    """Fail-closed search outcome surfaced to the edge as a generic error (SEC-15/NFR-R1)."""


# A store result: a real record plus its (internal) store relevance score, in rank order.
ScoredRecord = tuple[IndexRecord, float]


@runtime_checkable
class EmbeddingAdapter(Protocol):
    """Query embedding (reader=search_query, cross-lingual KR↔EN; TD-3/TD-U2-6)."""

    def embed_query(self, text: str) -> list[float]:
        """Return the query embedding vector. Raises ``EmbeddingUnavailable`` on failure."""
        ...


@runtime_checkable
class VectorStoreAdapter(Protocol):
    """k-NN (ANN) reader over the shared OpenSearch index (FR-2; single reader)."""

    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        """Return up to ``top_k`` records in similarity order. ``abstract_only`` restricts the
        search to abstract chunks (lite scope: 1 vector/paper). Raises ``IndexUnavailable``."""
        ...


@runtime_checkable
class LexicalIndexAdapter(Protocol):
    """BM25 lexical reader over the shared OpenSearch index (FR-2; lexical fallback US-R2)."""

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        """Return up to ``top_k`` records in BM25 order over ``fields`` (lite vs full scope:
        title+abstract vs +body). Raises ``IndexUnavailable``."""
        ...


@runtime_checkable
class PaperLookupAdapter(Protocol):
    """Single-document read over the shared OpenSearch index — fetch one record for a paper by
    its id (paperId or display arxivId). Powers the paper-detail metadata endpoint (the detail
    page needs title/authors/abstract, which live on the corpus record, not in U7). Records are
    per-chunk; ANY chunk carries the paper-level metadata, so the first match is sufficient."""

    def fetch_paper(self, paper_id: str) -> IndexRecord | None:
        """Return one record for ``paper_id`` (matched on paperId or arxivId), or None when no
        such paper is indexed. Raises ``IndexUnavailable`` on a store failure (fail-closed)."""
        ...


@runtime_checkable
class EventPublisher(Protocol):
    """Non-blocking SearchExecuted publisher (FR-10; BR-14). Fire-and-forget."""

    def publish_search_executed(self, event: SearchExecutedEvent) -> None:
        """Publish off the P50<3s path; failures MUST NOT affect the search response."""
        ...
