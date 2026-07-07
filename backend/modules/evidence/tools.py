from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from discovery.ports.search_ports import (
    IndexUnavailable,
    ScoredRecord,
)
from docsuri_shared._generated.dtos.evidence_schema import EvidenceScope
from docsuri_shared.dtos import DocModel
from summarization.adapters._paper_ref import paper_version

from .models import PaperSearchResult

logger = logging.getLogger(__name__)


class PaperSearchUnavailable(Exception):
    """Vector Store 장애 — Orchestrator가 abstain으로 처리."""


@runtime_checkable
class EmbeddingPort(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStorePort(Protocol):
    def knn_search(
        self, vector: list[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]: ...


@runtime_checkable
class LexicalIndexPort(Protocol):
    def bm25_search(
        self,
        terms: list[str],
        top_k: int,
        fields: tuple[str, ...] = ('title', 'abstract', 'lexicalTerms'),
    ) -> list[ScoredRecord]: ...


@runtime_checkable
class PaperLookupPort(Protocol):
    def fetch_paper(self, paper_id: str) -> Any | None: ...


_SEARCH_TOP_K = 50
_FULL_FIELDS = ('title', 'abstract', 'lexicalTerms')


class EvidencePaperSearchTool:
    """scope에 따라 논문 검색 — BR-EV-2, INV-EV-3."""

    def __init__(
        self,
        *,
        embedding: EmbeddingPort,
        vector_store: VectorStorePort,
        lexical_index: LexicalIndexPort,
        paper_lookup: PaperLookupPort,
    ) -> None:
        self._embedding = embedding
        self._vector_store = vector_store
        self._lexical_index = lexical_index
        self._paper_lookup = paper_lookup

    def search(
        self,
        topic: str,
        scope: EvidenceScope | None,
        paper_ids: list[str] | None,
    ) -> PaperSearchResult:
        effective_scope = scope or EvidenceScope.auto
        try:
            if effective_scope is EvidenceScope.explicit:
                return self._explicit_search(paper_ids or [])
            elif effective_scope is EvidenceScope.mixed:
                return self._mixed_search(topic, paper_ids or [])
            else:
                return self._auto_search(topic)
        except IndexUnavailable as exc:
            raise PaperSearchUnavailable('search index unavailable') from exc

    def _auto_search(self, topic: str) -> PaperSearchResult:
        records = self._hybrid_search(topic)
        return PaperSearchResult(
            records=tuple(r for r, _ in records),
            query_used=topic,
            scope=EvidenceScope.auto,
        )

    # explicit scope — paper_ids 명시 집합만 사용, 자동 검색 금지(INV-EV-3)
    def _explicit_search(self, paper_ids: list[str]) -> PaperSearchResult:
        records = []
        for pid in paper_ids:
            rec = self._paper_lookup.fetch_paper(pid)
            if rec is not None:
                records.append(rec)
            else:
                logger.warning('explicit paper not found in corpus: %s', pid)
        return PaperSearchResult(
            records=tuple(records),
            query_used=None,
            scope=EvidenceScope.explicit,
        )

    def _mixed_search(self, topic: str, paper_ids: list[str]) -> PaperSearchResult:
        auto_records = self._hybrid_search(topic)
        auto_by_id = {r.paperId: r for r, _ in auto_records}

        for pid in paper_ids:
            if pid not in auto_by_id:
                rec = self._paper_lookup.fetch_paper(pid)
                if rec is not None:
                    auto_by_id[pid] = rec
                else:
                    logger.warning('explicit paper not found in corpus: %s', pid)

        return PaperSearchResult(
            records=tuple(auto_by_id.values()),
            query_used=topic,
            scope=EvidenceScope.mixed,
        )

    def _hybrid_search(self, topic: str) -> list[ScoredRecord]:
        from discovery.domain.models import QueryPlan, RetrievalMode, SearchScope
        from discovery.domain.retriever import HybridRetriever

        try:
            vector = self._embedding.embed_query(topic)
            mode = RetrievalMode.HYBRID
        except Exception:
            logger.warning('embedding unavailable — falling back to lexical-only')
            vector = None
            mode = RetrievalMode.LEXICAL_ONLY

        plan = QueryPlan(
            lexical_terms=tuple(topic.split()),
            mode=mode,
            embedding_vector=tuple(vector) if vector else None,
            scope=SearchScope.FULL,
        )

        class _DegSignal:
            llm_enabled = True
            rerank_enabled = True

        retriever = HybridRetriever(self._vector_store, self._lexical_index)
        candidate_set = retriever.retrieve(plan, _DegSignal())
        return [(c.record, c.retrieval_score) for c in candidate_set.candidates[:_SEARCH_TOP_K]]


class EvidenceDocModelTool:
    """paperId + version 기반 S3 DocModel 읽기 — EvidenceDocModelTool(§3.4)."""

    def __init__(self, *, doc_model_reader: Any) -> None:
        # S3DocModelReader 또는 동일 인터페이스 구현체
        self._reader = doc_model_reader

    def get_doc_model(self, paper_id: str, version: int | None = None) -> DocModel | None:
        # Evidence carries only the versioned arxivId; recover the arXiv version so a revised
        # paper (v2+) reads its real doc-model instead of a perpetual v1 miss (→ no grounded
        # evidence). An explicit version still wins for callers that pass one.
        ver = version if version is not None else paper_version(paper_id)
        try:
            return self._reader.get_doc_model(paper_id, ver)
        except Exception:
            logger.warning('docmodel read failed for %s v%s', paper_id, ver, exc_info=True)
            return None
