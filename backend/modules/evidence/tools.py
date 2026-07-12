from __future__ import annotations

import logging
import re
from typing import Any, Protocol, runtime_checkable

from discovery.ports.search_ports import (
    IndexUnavailable,
    ScoredRecord,
)
from docsuri_shared._generated.dtos.evidence_schema import EvidenceScope
from docsuri_shared.dtos import DocModel
from summarization.adapters._paper_ref import bare_paper_id, paper_version

from .models import LiteralMatch, LiteralSearchResult, PaperSearchResult

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

    def phrase_search(
        self,
        phrase: str,
        top_k: int,
        paper_ids: list[str] | None = None,
    ) -> list[ScoredRecord]: ...


@runtime_checkable
class PaperLookupPort(Protocol):
    def fetch_paper(self, paper_id: str) -> Any | None: ...


_SEARCH_TOP_K = 50
_FULL_FIELDS = ('title', 'abstract', 'lexicalTerms')
# 청크 단위 히트를 넉넉히 훑어야 서로 다른 논문의 문단을 놓치지 않는다(한 논문이 여러
# 청크에 걸쳐 있을 수 있음, ingestion Chunker: max_chunks_per_paper=128).
_LITERAL_SEARCH_TOP_K = 200
_LITERAL_MAX_PAPERS = 20
_QUOTE_CONTEXT_CHARS = 240


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

    # -- 정확 문구 검색 (LLM 우회 경로) -----------------------------------------------

    def literal_search(
        self,
        phrase: str,
        paper_ids: list[str] | None = None,
    ) -> LiteralSearchResult:
        """``phrase``가 원문에 그대로 있는 위치만 반환한다 — HybridRetriever(의미 검색)를
        타지 않고 OpenSearch match_phrase 결과를 직접 IndexRecord에서 읽는다. 그 자체로
        원문 발췌이므로 LLM 추출·환각 검증이 필요 없다."""
        # 색인의 paperId는 버전 없는(bare) id인데 evidence가 이어붙이는 꼬리질문 id는
        # 버전 붙은 arxivId다(위 get_doc_model 주석 참고). 버전을 떼고 넘겨야 terms 필터가
        # 매칭된다 — 안 그러면 "그 중에서…" 좁히기가 항상 0건(perpetual miss)이 된다.
        bare_ids = [bare_paper_id(p) for p in paper_ids] if paper_ids else None
        try:
            hits = self._lexical_index.phrase_search(
                phrase, top_k=_LITERAL_SEARCH_TOP_K, paper_ids=bare_ids
            )
        except IndexUnavailable as exc:
            raise PaperSearchUnavailable('phrase search index unavailable') from exc

        matches: list[LiteralMatch] = []
        seen_papers: set[str] = set()
        for record, _score in hits:
            paper_id = _get_paper_id(record)
            if not paper_id:
                continue
            quote = _sentence_around(_searchable_text(record), phrase)
            if not quote:
                continue
            matches.append(
                LiteralMatch(paper_id=paper_id, anchor=_first_block_id(record), quote=quote)
            )
            seen_papers.add(paper_id)
            if len(seen_papers) >= _LITERAL_MAX_PAPERS:
                break
        return LiteralSearchResult(phrase=phrase, matches=tuple(matches))


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


def _get_paper_id(record: object) -> str | None:
    """IndexRecord 또는 ScoredRecord에서 arxivId 추출 (INV-EV-5: 점수 미노출)."""
    for attr in ('arxivId', 'paper_id', 'paperId', 'id'):
        val = getattr(record, attr, None)
        if val:
            return str(val)
    return None


def _searchable_text(record: object) -> str:
    """phrase 검색 대상 텍스트 — 초록 청크는 lexicalTerms가 비어있으므로(ingestion
    Chunker) abstract 필드로 보완한다."""
    lexical = getattr(record, 'lexicalTerms', '') or ''
    abstract = getattr(record, 'abstract', '') or ''
    return f'{abstract} {lexical}'.strip()


def _first_block_id(record: object) -> str | None:
    """청크의 blockRefs 중 첫 번째 block id — DocModel 문단 단위 위치(anchor)."""
    for ref in getattr(record, 'blockRefs', None) or []:
        block_id = ref.get('blockId') if isinstance(ref, dict) else getattr(ref, 'blockId', None)
        if block_id:
            return str(block_id)
    return None


def _sentence_around(text: str, phrase: str) -> str | None:
    """phrase를 포함하는 문장(정확히 못 찾으면 앞뒤 문맥)만 잘라 반환 — 청크 전체(최대
    2400자)를 quote로 그대로 내보내지 않기 위함. 청크 원문의 개행·연속 공백은 단일 공백으로
    정규화한 뒤 찾는다(문장이 줄바꿈을 걸쳐 있어도 매칭; 인용문도 그 정규화형으로 나가지만
    어순·표현은 원문 그대로라 grounding 불변). match_phrase(분석기)만 매칭하고 원문
    substring이 아닌 경우(어간·문장부호 차이 등)는 여기서 None을 반환해 의도적으로 버린다 —
    '정확 문구'를 약속한 경로이므로 verbatim이 아니면 인용하지 않는다."""
    text = re.sub(r'\s+', ' ', text)
    idx = text.lower().find(phrase.lower())
    if idx == -1:
        return None
    start = max(0, idx - _QUOTE_CONTEXT_CHARS // 2)
    end = min(len(text), idx + len(phrase) + _QUOTE_CONTEXT_CHARS // 2)
    # 문장 경계(마침표) 쪽으로 살짝 당겨 자연스러운 인용이 되게 한다.
    prior_period = text.rfind('. ', start, idx)
    if prior_period != -1:
        start = prior_period + 2
    next_period = text.find('. ', idx + len(phrase), end)
    if next_period != -1:
        end = next_period + 1
    return text[start:end].strip()
