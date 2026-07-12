"""US-D6 no-match relevance floor (QA 2026-07-10 F2).

k-NN returns nearest neighbors for ANY query, so without an absolute floor the
"관련 논문 없음" empty page is unreachable for out-of-corpus queries. The retriever now
preserves the query's best RAW k-NN store score through fusion, and the orchestrator gates
the (pre-existing, BR-9) no-match empty page on it when ``DISCOVERY_NO_MATCH_KNN_FLOOR`` is
set. Floor 0.0 (default) = off — these tests pin both the off-behavior and the gate.
"""

from __future__ import annotations

from docsuri_shared.dtos import SearchRequest, SearchResultPageDTO

from discovery.api import run_search
from discovery.domain.models import (
    AuthSession,
    CandidateSet,
    QueryPlan,
    RequestContext,
    RetrievalMode,
    SearchScope,
)
from discovery.domain.retriever import HybridRetriever
from discovery.mocks import build_mock_orchestrator, fixtures


def _ctx() -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id="u1"), request_id="req-1")


# Matches the English mock fixtures (same query test_orchestrator uses for the happy path).
_QUERY = "diffusion models for protein structure"


def _search_with_floor(floor: float):
    bundle = build_mock_orchestrator()
    bundle.orchestrator._no_match_knn_floor = floor
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook, SearchRequest(query=_QUERY), _ctx()
    )
    return resp, bundle


# --- retriever: the raw score must survive fusion -----------------------------------------


class _FakeVectorStore:
    def __init__(self, scored):
        self._scored = scored

    def knn_search(self, vector, top_k, abstract_only=False):  # noqa: ARG002
        return self._scored


class _EmptyLexicalIndex:
    def bm25_search(self, terms, top_k, fields):  # noqa: ARG002
        return []


def test_retriever_preserves_best_raw_knn_score() -> None:
    records = fixtures.RECORDS
    retriever = HybridRetriever(
        _FakeVectorStore([(records[0], 0.42), (records[1], 0.77), (records[2], 0.13)]),
        _EmptyLexicalIndex(),
    )
    plan = QueryPlan(
        lexical_terms=("diffusion",),
        mode=RetrievalMode.HYBRID,
        embedding_vector=(1.0, 0.0),
        scope=SearchScope.LITE,
    )
    out = retriever.retrieve(plan, None)
    assert out.best_knn_score == 0.77  # max RAW store score, not an RRF contribution


def test_retriever_best_score_is_none_in_lexical_only() -> None:
    retriever = HybridRetriever(_FakeVectorStore([]), _EmptyLexicalIndex())
    plan = QueryPlan(lexical_terms=("diffusion",), mode=RetrievalMode.LEXICAL_ONLY)
    out = retriever.retrieve(plan, None)
    assert out.best_knn_score is None


# --- orchestrator: the floor gates the empty page ------------------------------------------


def test_floor_off_by_default_keeps_results() -> None:
    bundle = build_mock_orchestrator()
    resp = run_search(
        bundle.orchestrator, bundle.grounding_hook, SearchRequest(query=_QUERY), _ctx()
    )
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards  # behavior unchanged while the floor is unset


def test_floor_below_best_score_keeps_results() -> None:
    resp, _bundle = _search_with_floor(1e-9)  # mock scores are positive dot products
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards


def test_floor_above_best_score_is_explicit_no_match_empty_page() -> None:
    # Same terminal as a zero-hit query (BR-9: 기권 ≠ 빈 결과): empty page, resultCount=0,
    # SearchExecuted still published with count 0 — near-noise neighbors are not "관련 논문".
    resp, bundle = _search_with_floor(1e9)
    assert isinstance(resp.root, SearchResultPageDTO)
    assert resp.root.cards == []
    assert resp.root.meta.resultCount == 0
    assert bundle.event_publisher.events[0].resultCount == 0


def test_lexical_only_degrade_is_never_floor_gated() -> None:
    # No k-NN ran → no semantic score to judge; BM25 term matches must not be floor-abstained.
    bundle = build_mock_orchestrator()
    bundle.orchestrator._no_match_knn_floor = 1e9
    lexical_only = CandidateSet(
        candidates=(), retrieval_mode=RetrievalMode.LEXICAL_ONLY, best_knn_score=None
    )
    assert bundle.orchestrator._below_no_match_floor(lexical_only) is False
