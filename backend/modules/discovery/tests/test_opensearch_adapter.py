"""Unit tests for the real OpenSearch read adapters (fake client — no cluster needed)."""

from __future__ import annotations

import pytest
from docsuri_shared.vector_spec import DIMENSIONS

from discovery.adapters.opensearch_index import (
    _KNN_COLLAPSE_OVERSAMPLE,
    OpenSearchLexicalIndexAdapter,
    OpenSearchPaperLookupAdapter,
    OpenSearchVectorStoreAdapter,
)
from discovery.domain.models import YearRange
from discovery.ports.search_ports import IndexUnavailable
from discovery.testing import fixtures


def _hit(record, score: float) -> dict:
    return {"_score": score, "_source": record.model_dump(mode="json")}


class _StoreError(RuntimeError):
    """Mimics an opensearch-py failure by its duck-typed ``status_code`` (the adapter classifies
    transient-vs-terminal on that attribute without importing the ``real`` extra): 5xx / ``"N/A"`` /
    ``"TIMEOUT"`` are transient (retried), a 4xx is terminal (fail-closes on the first attempt)."""

    def __init__(self, status_code: int | str) -> None:
        super().__init__(f"store error status={status_code}")
        self.status_code = status_code


class FakeSearchClient:
    def __init__(self, *, hits: list[dict] | None = None, error: Exception | None = None) -> None:
        self.hits = hits or []
        self.error = error
        self.last: tuple | None = None
        self.request_timeouts: list[float | None] = []

    def search(self, *, index, body, request_timeout=None):
        self.last = (index, body)
        self.request_timeouts.append(request_timeout)
        if self.error is not None:
            raise self.error
        return {"hits": {"hits": self.hits}}


def test_knn_search_builds_query_and_deserializes_index_record() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 0.91)])
    adapter = OpenSearchVectorStoreAdapter(fake, "docsuri-corpus-v1")

    out = adapter.knn_search([0.0] * DIMENSIONS, 20)

    assert out[0][0].paperId == rec.paperId
    assert out[0][1] == pytest.approx(0.91)
    index, body = fake.last
    assert index == "docsuri-corpus-v1"
    # ``top_k`` counts PAPERS: the ANN is asked for a multiple of it (collapse cannot refill the
    # slots it frees) while ``size`` — which counts collapsed groups — stays at top_k.
    # See test_search_candidate_diversity.py for the measurements.
    assert body["size"] == 20
    assert body["query"]["knn"]["vector"]["k"] == 20 * _KNN_COLLAPSE_OVERSAMPLE
    assert body["collapse"] == {"field": "paperId"}


def test_bm25_search_builds_multi_match_query_over_split_lexical_fields() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 1.2)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    out = adapter.bm25_search(["diffusion", "protein"], 50)

    assert out[0][0].paperId == rec.paperId
    _, body = fake.last
    multi_match = body["query"]["multi_match"]
    assert multi_match["query"] == "diffusion protein"
    assert multi_match["fields"] == ["title", "abstract", "lexicalTerms"]


def test_phrase_search_matches_both_abstract_and_lexical_fields() -> None:
    # Regression: lexicalTerms is empty for abstract chunks (index_record contract), so a
    # phrase-only-in-the-abstract must still match via the `abstract` field — match_phrase over
    # lexicalTerms alone would silently miss it.
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    out = adapter.phrase_search("self-attention reduces computation", top_k=200)

    assert out[0][0].paperId == rec.paperId
    _, body = fake.last
    should = body["query"]["bool"]["should"]
    assert {"match_phrase": {"abstract": "self-attention reduces computation"}} in should
    assert {"match_phrase": {"lexicalTerms": "self-attention reduces computation"}} in should
    assert body["query"]["bool"]["minimum_should_match"] == 1
    assert "filter" not in body["query"]["bool"]


def test_phrase_search_restricts_to_paper_ids_via_bare_paperid_filter() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    adapter.phrase_search("x y z", top_k=200, paper_ids=["2001.00001", "2001.00002"])

    _, body = fake.last
    assert body["query"]["bool"]["filter"] == [
        {"terms": {"paperId": ["2001.00001", "2001.00002"]}}
    ]


def test_knn_failure_raises_index_unavailable() -> None:
    # OpenSearch is one store; any failure → fail-closed (INV-3), never a silent empty result.
    adapter = OpenSearchVectorStoreAdapter(
        FakeSearchClient(error=RuntimeError("connection refused")), "idx"
    )
    with pytest.raises(IndexUnavailable):
        adapter.knn_search([0.0] * DIMENSIONS, 10)


def test_bm25_failure_raises_index_unavailable() -> None:
    adapter = OpenSearchLexicalIndexAdapter(
        FakeSearchClient(error=RuntimeError("connection refused")), "idx"
    )
    with pytest.raises(IndexUnavailable):
        adapter.bm25_search(["x"], 10)


def test_fetch_paper_matches_version_stripped_id_so_off_version_request_resolves() -> None:
    # Regression: paperId is stored version-less; a request for one version (…v1) must still
    # resolve a paper indexed at another (…v3) instead of 404-ing on an exact-version miss.
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 1.0)])
    adapter = OpenSearchPaperLookupAdapter(fake, "docsuri-corpus")

    out = adapter.fetch_paper("2503.18888v1")

    assert out is not None and out.paperId == rec.paperId
    _, body = fake.last
    should = body["query"]["bool"]["should"]
    # Includes the version-stripped paperId term (the fix) alongside the raw id + arxivId terms.
    assert {"term": {"paperId": "2503.18888"}} in should
    assert {"term": {"arxivId": "2503.18888v1"}} in should


def _bad_hit(record, score: float) -> dict:
    """A hit whose stored _source violates the current IndexRecord contract (schema drift):
    a required field is absent, exactly as a document indexed under an earlier vector-spec
    would read back."""
    source = record.model_dump(mode="json")
    source.pop("title")
    return {"_score": score, "_source": source}


def test_knn_search_drops_non_conforming_hits_and_keeps_valid_ones_in_order() -> None:
    good1, bad, good2 = fixtures.RECORDS[0], fixtures.RECORDS[1], fixtures.RECORDS[2]
    fake = FakeSearchClient(
        hits=[_hit(good1, 0.9), _bad_hit(bad, 0.8), _hit(good2, 0.7)]
    )
    adapter = OpenSearchVectorStoreAdapter(fake, "docsuri-corpus-v1")

    out = adapter.knn_search([0.0] * DIMENSIONS, 20)

    # The stale hit is dropped (not a 500); the two valid hits survive in rank order.
    assert [r.paperId for r, _ in out] == [good1.paperId, good2.paperId]


def test_search_with_only_non_conforming_hits_returns_empty_not_error() -> None:
    fake = FakeSearchClient(hits=[_bad_hit(fixtures.RECORDS[0], 0.9)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    # A drifted corpus degrades to an empty page, never a ValidationError escaping to a 500.
    assert adapter.bm25_search(["x"], 10) == []


def test_search_drops_hit_missing_source_without_raising() -> None:
    # A hit with no `_source` key (e.g. an `_source`-disabled / stored_fields response) must be
    # absorbed by the same drop path — the `_source` subscript would otherwise raise KeyError
    # (not ValidationError) and escape to a 500, breaking the per-record tolerance invariant.
    good = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[{"_score": 0.9}, _hit(good, 0.8)])
    adapter = OpenSearchVectorStoreAdapter(fake, "docsuri-corpus-v1")

    out = adapter.knn_search([0.0] * DIMENSIONS, 20)

    assert [r.paperId for r, _ in out] == [good.paperId]


# --- transient-retry (search read resilience under reindex load) --------------------

@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch) -> None:
    """Keep the bounded search retry from actually sleeping between attempts in tests."""
    import discovery.adapters.opensearch_index as osi

    monkeypatch.setattr(osi.time, "sleep", lambda _s: None)


class FlakySearchClient:
    """Fails the first ``fail_times`` calls with ``error`` (a transient store blip by default),
    then returns ``hits``. Records the per-request timeout the adapter passes each attempt."""

    def __init__(
        self, *, fail_times: int, hits: list[dict], error: Exception | None = None
    ) -> None:
        self._remaining = fail_times
        self._hits = hits
        self._error = error or _StoreError("N/A")  # connection error → transient
        self.calls = 0
        self.request_timeouts: list[float | None] = []

    def search(self, *, index, body, request_timeout=None):
        self.calls += 1
        self.request_timeouts.append(request_timeout)
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        return {"hits": {"hits": self._hits}}


def test_search_retries_transient_failure_then_succeeds() -> None:
    rec = fixtures.RECORDS[0]
    flaky = FlakySearchClient(fail_times=2, hits=[_hit(rec, 0.9)])
    adapter = OpenSearchVectorStoreAdapter(flaky, "idx")

    out = adapter.knn_search([0.0] * DIMENSIONS, 20)

    # A brief blip is absorbed — the query succeeds instead of surfacing a 503.
    assert [r.paperId for r, _ in out] == [rec.paperId]
    assert flaky.calls == 3  # two transient failures, then success


def test_search_fail_closes_after_bounded_retries() -> None:
    flaky = FlakySearchClient(fail_times=99, hits=[])
    adapter = OpenSearchLexicalIndexAdapter(flaky, "idx")

    with pytest.raises(IndexUnavailable):
        adapter.bm25_search(["x"], 10)
    assert flaky.calls == 3  # bounded — does not retry forever


def test_search_bounds_each_attempt_with_a_small_request_timeout() -> None:
    # The retry must not stretch across the client's full connect/read timeout: every attempt is
    # capped by a small per-request timeout, so even a genuine ConnectionTimeout fail-close stays
    # within the search latency budget instead of ~MAX_ATTEMPTS * the 10s client default.
    from discovery.adapters.opensearch_index import _SEARCH_REQUEST_TIMEOUT_S

    flaky = FlakySearchClient(fail_times=99, hits=[], error=_StoreError("TIMEOUT"))
    adapter = OpenSearchVectorStoreAdapter(flaky, "idx")

    with pytest.raises(IndexUnavailable):
        adapter.knn_search([0.0] * DIMENSIONS, 20)
    assert flaky.request_timeouts == [_SEARCH_REQUEST_TIMEOUT_S] * 3


def test_search_does_not_retry_non_transient_failure() -> None:
    # A 4xx (e.g. a malformed query) can't be fixed by retrying — fail-close on the first attempt
    # rather than burning the latency budget on doomed retries.
    flaky = FlakySearchClient(fail_times=99, hits=[], error=_StoreError(400))
    adapter = OpenSearchLexicalIndexAdapter(flaky, "idx")

    with pytest.raises(IndexUnavailable):
        adapter.bm25_search(["x"], 10)
    assert flaky.calls == 1  # terminal error → no retry


# --- year bound: it has to be IN the query, not applied to the page it returns ---------------


def test_bm25_year_bound_is_a_filter_clause_so_it_never_touches_scoring() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    adapter.bm25_search(["x"], top_k=10, years=YearRange(start=2023, end=2025))

    _, body = fake.last
    bool_q = body["query"]["bool"]
    assert bool_q["filter"] == [{"range": {"year": {"gte": 2023, "lte": 2025}}}]
    # The original query survives untouched under `must` — a filter clause is not scored, so
    # BM25 ordering within the matching subset is identical to the unbounded search.
    assert bool_q["must"] == [
        {"multi_match": {"query": "x", "fields": ["title", "abstract", "lexicalTerms"]}}
    ]


def test_an_unbounded_search_body_is_unchanged_by_the_year_feature() -> None:
    """Wrapping unconditionally would alter every existing query's shape for nothing."""
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    adapter.bm25_search(["x"], top_k=10, years=YearRange())

    _, body = fake.last
    assert "bool" not in body["query"]
    assert body["query"]["multi_match"]["query"] == "x"


def test_one_sided_year_bounds_emit_only_that_side() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    adapter.bm25_search(["x"], top_k=10, years=YearRange(start=2023))
    _, body = fake.last
    assert body["query"]["bool"]["filter"] == [{"range": {"year": {"gte": 2023}}}]

    adapter.bm25_search(["x"], top_k=10, years=YearRange(end=2019))
    _, body = fake.last
    assert body["query"]["bool"]["filter"] == [{"range": {"year": {"lte": 2019}}}]


def test_knn_year_bound_goes_into_the_ann_filter_not_a_post_filter() -> None:
    """Efficient k-NN filtering picks the k neighbours FROM the matching subset. As a post-filter
    the bound would instead cut an already-chosen k, so a narrow window returns a handful of
    papers out of the requested top_k and reads as "few such papers exist"."""
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 0.9)])
    adapter = OpenSearchVectorStoreAdapter(fake, "docsuri-corpus-v1")

    adapter.knn_search([0.0] * DIMENSIONS, top_k=10, years=YearRange(start=2023))

    _, body = fake.last
    assert body["query"]["knn"]["vector"]["filter"] == {"range": {"year": {"gte": 2023}}}


def test_knn_combines_the_abstract_and_year_restrictions_instead_of_dropping_one() -> None:
    """`abstract_only` already owned `knn["filter"]`. A second restriction assigned over it would
    silently drop the lite-scope one — one paper's whole chunk set then floods the slice."""
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 0.9)])
    adapter = OpenSearchVectorStoreAdapter(fake, "docsuri-corpus-v1")

    adapter.knn_search([0.0] * DIMENSIONS, top_k=10, abstract_only=True, years=YearRange(end=2020))

    _, body = fake.last
    assert body["query"]["knn"]["vector"]["filter"] == {
        "bool": {
            "filter": [
                {"term": {"section": "abstract"}},
                {"range": {"year": {"lte": 2020}}},
            ]
        }
    }


def test_phrase_search_keeps_both_the_paper_id_and_year_filters() -> None:
    rec = fixtures.RECORDS[0]
    fake = FakeSearchClient(hits=[_hit(rec, 2.5)])
    adapter = OpenSearchLexicalIndexAdapter(fake, "docsuri-corpus-v1")

    adapter.phrase_search("x", top_k=200, paper_ids=["2001.00001"], years=YearRange(start=2023))

    _, body = fake.last
    assert body["query"]["bool"]["filter"] == [
        {"terms": {"paperId": ["2001.00001"]}},
        {"range": {"year": {"gte": 2023}}},
    ]
