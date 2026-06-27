"""Mock capability adapters (MR-1) — deterministic, fixture-backed. Real OpenSearch/Bedrock
adapters replace these after Infra/U1 corpus (CG-2/MR-4). Failing variants drive the RES-12
fault-injection tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.vector_spec import IndexRecord

from ..ports.search_ports import EmbeddingUnavailable, IndexUnavailable, ScoredRecord
from . import fixtures


class MockEmbeddingAdapter:
    """Deterministic query embedding (cross-lingual bag-of-keywords; reader=search_query)."""

    def embed_query(self, text: str) -> list[float]:
        return fixtures.embed(text)


class MockVectorStoreAdapter:
    """k-NN over fixtures by dot product with the query vector (matching keyword dims)."""

    def __init__(self, records: Sequence[IndexRecord] = tuple(fixtures.RECORDS)) -> None:
        self._records = list(records)

    def knn_search(self, vector: Sequence[float], top_k: int) -> list[ScoredRecord]:
        scored: list[ScoredRecord] = []
        for record in self._records:
            score = sum(a * b for a, b in zip(vector, record.vector, strict=True))
            if score > 0:
                scored.append((record, score))
        scored.sort(key=lambda sr: (-sr[1], sr[0].chunkId))
        return scored[:top_k]


class MockLexicalIndexAdapter:
    """BM25 stand-in: overlap count against title, abstract, and chunk body tokens.

    NOT cross-lingual (matches English fixtures) — a Korean query yields no lexical hits,
    which is why a Korean query in lexical-only mode degrades to empty (realistic)."""

    def __init__(self, records: Sequence[IndexRecord] = tuple(fixtures.RECORDS)) -> None:
        self._records = list(records)

    def bm25_search(self, terms: Sequence[str], top_k: int) -> list[ScoredRecord]:
        wanted = {t.lower() for t in terms}
        scored: list[ScoredRecord] = []
        for record in self._records:
            text = f"{record.title} {record.abstract} {record.lexicalTerms}"
            tokens = set(text.lower().split())
            overlap = len(wanted & tokens)
            if overlap > 0:
                scored.append((record, float(overlap)))
        scored.sort(key=lambda sr: (-sr[1], sr[0].chunkId))
        return scored[:top_k]


class MockPaperLookupAdapter:
    """Fixture-backed single-paper lookup — returns the first record matching ``paper_id`` on
    either paperId or display arxivId (the detail route id is the arxivId)."""

    def __init__(self, records: Sequence[IndexRecord] = tuple(fixtures.RECORDS)) -> None:
        self._records = list(records)

    def fetch_paper(self, paper_id: str) -> IndexRecord | None:
        for record in self._records:
            if paper_id in (record.paperId, record.arxivId):
                return record
        return None


class FailingEmbeddingAdapter:
    """Always fails — RES-12: embedding outage → orchestrator lexical-only fallback."""

    def embed_query(self, text: str) -> list[float]:
        raise EmbeddingUnavailable("mock embedding outage")


class FailingVectorStoreAdapter:
    def knn_search(self, vector: Sequence[float], top_k: int) -> list[ScoredRecord]:
        raise IndexUnavailable("mock index outage")


class FailingLexicalIndexAdapter:
    """RES-12: index outage → fail-closed (no fallback for the index)."""

    def bm25_search(self, terms: Sequence[str], top_k: int) -> list[ScoredRecord]:
        raise IndexUnavailable("mock index outage")
