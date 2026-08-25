"""FR-2 — lite/full retrieval scope: lite is hybrid over title+abstract (k-NN restricted to
abstract chunks, cross-lingual preserved); full adds the full-body chunk index."""

from __future__ import annotations

from collections.abc import Sequence

from discovery.domain.models import QueryPlan, RetrievalMode, SearchScope, YearRange
from discovery.domain.retriever import HybridRetriever
from discovery.ports.search_ports import ScoredRecord


class _RecordingVector:
    def __init__(self) -> None:
        self.calls: list[bool] = []
        self.years: list[YearRange | None] = []

    def knn_search(
        self,
        vector: Sequence[float],
        top_k: int,
        abstract_only: bool = False,
        years: YearRange | None = None,
    ) -> list[ScoredRecord]:
        self.calls.append(abstract_only)
        self.years.append(years)
        return []


class _RecordingLexical:
    def __init__(self) -> None:
        self.fields: list[tuple[str, ...]] = []
        self.years: list[YearRange | None] = []

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
        years: YearRange | None = None,
    ) -> list[ScoredRecord]:
        self.fields.append(tuple(fields))
        self.years.append(years)
        return []


def _plan(scope: SearchScope, years: YearRange | None = None) -> QueryPlan:
    return QueryPlan(
        lexical_terms=("x",),
        mode=RetrievalMode.HYBRID,
        embedding_vector=(0.0,),
        scope=scope,
        years=years,
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


def test_the_year_bound_reaches_both_stores() -> None:
    """연도는 **질의로 내려간다.** 리트리버가 안 넘기면 두 스토어가 무제한으로 검색하고,
    호출측은 상위 k를 사후에 자를 수밖에 없다 — 좁은 창에서 그 결과는 0건이고 그것이
    "그런 논문이 없다"와 구분되지 않는다."""
    vector, lexical = _RecordingVector(), _RecordingLexical()
    years = YearRange(start=2023)

    HybridRetriever(vector, lexical).retrieve(_plan(SearchScope.FULL, years), degradation=None)

    assert vector.years == [years]
    assert lexical.years == [years]


def test_an_unbounded_plan_passes_none_not_an_empty_range() -> None:
    """`YearRange()`를 넘기면 어댑터가 `bounded=False`를 다시 판정해야 한다 — 판정 지점이
    둘이 되지 않게 무제한은 처음부터 None이다."""
    vector, lexical = _RecordingVector(), _RecordingLexical()

    HybridRetriever(vector, lexical).retrieve(_plan(SearchScope.FULL), degradation=None)

    assert vector.years == [None]
    assert lexical.years == [None]


# --- the doubles must apply the bound too ------------------------------------------------


def test_the_mock_adapters_actually_apply_the_year_bound() -> None:
    """A double that ignores a filter reports the filter as working. Every mock-backed test
    downstream would then prove nothing about year narrowing."""
    from discovery.testing import fixtures
    from discovery.testing.adapters import MockLexicalIndexAdapter, MockVectorStoreAdapter

    terms = [t for r in fixtures.RECORDS for t in r.title.lower().split()]
    lexical = MockLexicalIndexAdapter()
    unbounded = lexical.bm25_search(terms, top_k=50)
    bounded = lexical.bm25_search(terms, top_k=50, years=YearRange(start=2024))

    assert unbounded, "fixture query must match something for this test to mean anything"
    assert len(bounded) < len(unbounded)
    assert all(record.year >= 2024 for record, _ in bounded)

    vector = MockVectorStoreAdapter()
    query = fixtures.embed(fixtures.RECORDS[0].title)
    assert all(
        record.year <= 2022
        for record, _ in vector.knn_search(query, top_k=50, years=YearRange(end=2022))
    )
