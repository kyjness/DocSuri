"""Mock capability adapters (MR-1) — deterministic, fixture-backed. Real OpenSearch/Bedrock
adapters replace these after Infra/U1 corpus (CG-2/MR-4). Failing variants drive the RES-12
fault-injection tests.
"""

from __future__ import annotations

from collections.abc import Sequence

from docsuri_shared.vector_spec import IndexRecord

from ..ports.search_ports import (
    EmbeddingUnavailable,
    IndexUnavailable,
    RerankUnavailable,
    ScoredRecord,
)
from . import fixtures


class MockEmbeddingAdapter:
    """Deterministic query embedding (cross-lingual bag-of-keywords; reader=search_query)."""

    def embed_query(self, text: str) -> list[float]:
        return fixtures.embed(text)


class MockVectorStoreAdapter:
    """k-NN over fixtures by dot product with the query vector (matching keyword dims)."""

    def __init__(self, records: Sequence[IndexRecord] = tuple(fixtures.RECORDS)) -> None:
        self._records = list(records)

    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        scored: list[ScoredRecord] = []
        for record in self._records:
            if abstract_only and record.section != "abstract":
                continue
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

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        wanted = {t.lower() for t in terms}
        selected = set(fields)
        scored: list[ScoredRecord] = []
        for record in self._records:
            # Honor the requested field set so lite (title+abstract) realistically excludes
            # body-only matches, mirroring the real multi_match.
            parts = []
            if "title" in selected:
                parts.append(record.title)
            if "abstract" in selected:
                parts.append(record.abstract)
            if "lexicalTerms" in selected:
                parts.append(record.lexicalTerms)
            tokens = set(" ".join(parts).lower().split())
            overlap = len(wanted & tokens)
            if overlap > 0:
                scored.append((record, float(overlap)))
        scored.sort(key=lambda sr: (-sr[1], sr[0].chunkId))
        return scored[:top_k]

    def phrase_search(
        self,
        phrase: str,
        top_k: int,
        paper_ids: Sequence[str] | None = None,
    ) -> list[ScoredRecord]:
        """정확 문구 포함 여부만 확인(대소문자 무시) — 실제 match_phrase의 순서·인접성
        요구를 부분 문자열 포함으로 근사한다."""
        needle = phrase.lower()
        wanted_papers = set(paper_ids) if paper_ids else None
        scored: list[ScoredRecord] = []
        for record in self._records:
            if wanted_papers is not None and record.paperId not in wanted_papers:
                continue
            haystack = f"{record.abstract} {record.lexicalTerms}".lower()
            if needle in haystack:
                scored.append((record, 1.0))
        return scored[:top_k]


class MockRerankAdapter:
    """Deterministic cross-encoder stand-in (MR-1): score = query-term overlap with each document
    (case-insensitive). Higher overlap → higher relevance, so it reorders the fused pool by
    lexical match — a proxy for the real joint (query, document) encoder. Scores are returned in
    the SAME order as ``documents`` (the port contract)."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        wanted = {t for t in query.lower().split() if t}
        return [float(len(wanted & set(doc.lower().split()))) for doc in documents]


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
    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        raise IndexUnavailable("mock index outage")


class FailingLexicalIndexAdapter:
    """RES-12: index outage → fail-closed (no fallback for the index)."""

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        raise IndexUnavailable("mock index outage")

    def phrase_search(
        self,
        phrase: str,
        top_k: int,
        paper_ids: Sequence[str] | None = None,
    ) -> list[ScoredRecord]:
        raise IndexUnavailable("mock index outage")


class FailingRerankAdapter:
    """RES-12: rerank outage → orchestrator keeps the baseline order (fail-soft, search OK)."""

    def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        raise RerankUnavailable("mock rerank outage")
