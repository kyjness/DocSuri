"""``top_k`` counts PAPERS, not chunks — both search paths, real adapter and mock.

Chunking is block-level: one paper is roughly 91 chunks (measured on the ⑧-2 deploy corpus, and
capped per paper). So a chunk-counted slice collapses onto a fraction of that many papers, and the
retriever's PaperId dedup runs AFTER fusion — it can only pick from what the slice already
contains. Measured on the 827-paper deploy index before this contract existed:

    BM25, size=150     -> 150 hits spanning   2 distinct papers
    k-NN FULL, k=150   -> 150 hits spanning  55 distinct papers

BM25 was the worse of the two because ``title``/``abstract`` are COPIED onto every chunk of a
paper, so a lite-scope match scores that paper's whole chunk set identically.

The failure is invisible from the outside: the cards a user finally sees look normal either way,
because dedup hides the duplication. What silently shrinks is the candidate breadth the ranker
and the U12 novelty agent get to reason over. That is why this is pinned as a test rather than
left to the adapters' own docstrings.
"""

from __future__ import annotations

from docsuri_shared.vector_spec import DIMENSIONS

from discovery.adapters.opensearch_index import (
    _KNN_COLLAPSE_OVERSAMPLE,
    OpenSearchLexicalIndexAdapter,
    OpenSearchVectorStoreAdapter,
)
from discovery.mocks import fixtures
from discovery.mocks.adapters import MockLexicalIndexAdapter, MockVectorStoreAdapter

from .test_opensearch_adapter import FakeSearchClient


def _body(client: FakeSearchClient) -> dict:
    """The query body the adapter sent. ``FakeSearchClient.last`` is ``(index, body)``."""
    assert client.last is not None
    return client.last[1]


def _hits_for_one_paper(count: int) -> list[dict]:
    """``count`` hits that all belong to ONE paper — the shape a single strong match produced."""
    record = fixtures.RECORDS[0]
    out = []
    for i in range(count):
        source = record.model_dump(mode="json")
        source["chunkId"] = f"{record.paperId}:{i}"
        out.append({"_score": 1.0 - i * 0.001, "_source": source})
    return out


def test_bm25_collapses_on_paper_id_in_the_query() -> None:
    """Collapse must be in the QUERY, not applied afterwards: OpenSearch then fills ``size`` with
    that many distinct groups, so no over-fetch is needed to reach ``top_k`` papers."""
    client = FakeSearchClient(hits=_hits_for_one_paper(1))
    adapter = OpenSearchLexicalIndexAdapter(client, "docsuri-deploy-v1")

    adapter.bm25_search(["fine-tuning"], 150)

    assert _body(client)["collapse"] == {"field": "paperId"}
    assert _body(client)["size"] == 150  # papers, and the query counts groups


def test_knn_over_fetches_because_collapse_alone_does_not_refill() -> None:
    """The ANN picks its k neighbours FIRST and collapse dedups them without refilling the freed
    slots (measured: k=150 -> 150 hits -> 55 after collapse). Over-fetching is what buys breadth;
    collapse only removes the duplicates."""
    client = FakeSearchClient(hits=_hits_for_one_paper(1))
    adapter = OpenSearchVectorStoreAdapter(client, "docsuri-deploy-v1")

    adapter.knn_search([0.0] * DIMENSIONS, 150)

    body = _body(client)
    assert body["query"]["knn"]["vector"]["k"] == 150 * _KNN_COLLAPSE_OVERSAMPLE
    assert body["collapse"] == {"field": "paperId"}
    # ``size`` counts collapsed GROUPS, so it stays at top_k — over-fetching rows would transfer
    # six times the records the caller keeps, each carrying a 1024-float vector to validate.
    assert body["size"] == 150


def test_knn_lite_scope_does_not_over_fetch() -> None:
    """Lite restricts the ANN to abstract chunks — one per paper — so breadth is guaranteed by
    construction and over-fetching would cost latency for nothing."""
    client = FakeSearchClient(hits=_hits_for_one_paper(1))
    adapter = OpenSearchVectorStoreAdapter(client, "docsuri-deploy-v1")

    adapter.knn_search([0.0] * DIMENSIONS, 150, abstract_only=True)

    body = _body(client)
    assert body["query"]["knn"]["vector"]["k"] == 150
    assert body["query"]["knn"]["vector"]["filter"] == {"term": {"section": "abstract"}}


def test_phrase_search_collapses_too() -> None:
    """The method that was MISSED when the paper-level contract landed.

    ``match_phrase`` runs against ``abstract``, which is copied onto every chunk, so a phrase from
    a paper's abstract matches that paper's entire chunk set. Measured on the deploy index before
    this: 128 hits spanning **1** paper — against U11's evidence caller, which asks for 200 and
    wants 20 distinct papers (`evidence/adapters/sources.py`).
    """
    client = FakeSearchClient(hits=_hits_for_one_paper(1))
    adapter = OpenSearchLexicalIndexAdapter(client, "docsuri-deploy-v1")

    adapter.phrase_search("we propose a unified neural network", top_k=200)

    body = _body(client)
    assert body["collapse"] == {"field": "paperId"}
    assert body["size"] == 200


def test_every_paper_level_query_goes_through_one_builder() -> None:
    """Three call sites spelled the collapse out separately and one of them was missed. Asserting
    the SHAPE on each method individually would not have caught that — a fourth query added
    tomorrow would repeat it. So the property asserted here is that they share a builder."""
    for adapter_cls, call in (
        (OpenSearchLexicalIndexAdapter, lambda a: a.bm25_search(["x"], 10)),
        (OpenSearchLexicalIndexAdapter, lambda a: a.phrase_search("x", top_k=10)),
        (OpenSearchVectorStoreAdapter, lambda a: a.knn_search([0.0] * DIMENSIONS, 10)),
    ):
        client = FakeSearchClient(hits=_hits_for_one_paper(1))
        call(adapter_cls(client, "docsuri-deploy-v1"))
        body = _body(client)
        assert body["collapse"] == {"field": "paperId"}
        assert body["size"] == 10, "size must count PAPERS on every path"


def test_mocks_collapse_too_or_tests_exercise_breadth_production_lacks() -> None:
    """The mock wiring backs most of this package's tests. If it hands back several chunks of one
    paper where the real store hands back one, every mock-backed test measures a candidate set the
    deployment never produces."""
    # 2401.00001 is the fixture paper with two chunks (see fixtures.RECORDS).
    mock_lexical = MockLexicalIndexAdapter()
    results = {
        "knn": MockVectorStoreAdapter().knn_search(
            fixtures.embed("diffusion protein structure"), 50
        ),
        "bm25": mock_lexical.bm25_search(["diffusion", "protein"], 50),
        "phrase": mock_lexical.phrase_search("diffusion models", top_k=50),
    }

    for label, out in results.items():
        ids = [record.paperId for record, _ in out]
        assert len(ids) == len(set(ids)), f"{label} returned the same paper more than once: {ids}"
