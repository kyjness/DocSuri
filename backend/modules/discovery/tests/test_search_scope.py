"""FR-2 — lite/full retrieval scope: lite is hybrid over title+abstract (k-NN restricted to
abstract chunks, cross-lingual preserved); full adds the full-body chunk index."""

from __future__ import annotations

from collections.abc import Sequence

from discovery.domain.models import QueryPlan, RetrievalMode, SearchScope
from discovery.domain.retriever import HybridRetriever
from discovery.ports.search_ports import ScoredRecord


class _RecordingVector:
    def __init__(self) -> None:
        self.calls: list[bool] = []

    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        self.calls.append(abstract_only)
        return []


class _RecordingLexical:
    def __init__(self) -> None:
        self.fields: list[tuple[str, ...]] = []

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        self.fields.append(tuple(fields))
        return []


def _plan(scope: SearchScope) -> QueryPlan:
    return QueryPlan(
        lexical_terms=("x",),
        mode=RetrievalMode.HYBRID,
        embedding_vector=(0.0,),
        scope=scope,
    )


def test_lite_runs_knn_on_abstract_chunks_and_card_only_bm25() -> None:
    vec, lex = _RecordingVector(), _RecordingLexical()
    HybridRetriever(vec, lex).retrieve(_plan(SearchScope.LITE), degradation=None)
    # lite still runs k-NN (cross-lingual), restricted to abstract chunks
    assert vec.calls == [True]
    assert lex.fields == [("title", "abstract")]


def test_full_runs_knn_on_all_chunks_and_full_body_bm25() -> None:
    vec, lex = _RecordingVector(), _RecordingLexical()
    HybridRetriever(vec, lex).retrieve(_plan(SearchScope.FULL), degradation=None)
    assert vec.calls == [False]
    assert lex.fields == [("title", "abstract", "lexicalTerms")]
