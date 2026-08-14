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


class _CapturingClient:
    """Returns the same hits for any query; records the body so the query shape can be asserted."""

    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.body: dict | None = None

    def search(self, *, index, body, request_timeout=None):  # noqa: ARG002
        self.body = body
        return {"hits": {"hits": self.hits}}


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
    client = _CapturingClient(_hits_for_one_paper(1))
    adapter = OpenSearchLexicalIndexAdapter(client, "docsuri-deploy-v1")

    adapter.bm25_search(["fine-tuning"], 150)

    assert client.body is not None
    assert client.body["collapse"] == {"field": "paperId"}
    assert client.body["size"] == 150  # papers, and the query counts groups


def test_knn_over_fetches_because_collapse_alone_does_not_refill() -> None:
    """The ANN picks its k neighbours FIRST and collapse dedups them without refilling the freed
    slots (measured: k=150 -> 150 hits -> 55 after collapse). Over-fetching is what buys breadth;
    collapse only removes the duplicates."""
    client = _CapturingClient(_hits_for_one_paper(1))
    adapter = OpenSearchVectorStoreAdapter(client, "docsuri-deploy-v1")

    adapter.knn_search([0.0] * DIMENSIONS, 150)

    assert client.body is not None
    assert client.body["query"]["knn"]["vector"]["k"] == 150 * _KNN_COLLAPSE_OVERSAMPLE
    assert client.body["collapse"] == {"field": "paperId"}


def test_knn_lite_scope_does_not_over_fetch() -> None:
    """Lite restricts the ANN to abstract chunks — one per paper — so breadth is guaranteed by
    construction and over-fetching would cost latency for nothing."""
    client = _CapturingClient(_hits_for_one_paper(1))
    adapter = OpenSearchVectorStoreAdapter(client, "docsuri-deploy-v1")

    adapter.knn_search([0.0] * DIMENSIONS, 150, abstract_only=True)

    assert client.body is not None
    assert client.body["query"]["knn"]["vector"]["k"] == 150
    assert client.body["query"]["knn"]["vector"]["filter"] == {"term": {"section": "abstract"}}


def test_knn_returns_at_most_top_k_papers_after_over_fetching() -> None:
    """The over-fetch must not leak out: the caller asked for ``top_k`` papers and sizes its
    fusion budget on that."""
    client = _CapturingClient(_hits_for_one_paper(50))
    adapter = OpenSearchVectorStoreAdapter(client, "docsuri-deploy-v1")

    out = adapter.knn_search([0.0] * DIMENSIONS, 3)

    assert len(out) <= 3


def test_mocks_collapse_too_or_tests_exercise_breadth_production_lacks() -> None:
    """The mock wiring backs most of this package's tests. If it hands back several chunks of one
    paper where the real store hands back one, every mock-backed test measures a candidate set the
    deployment never produces."""
    # 2401.00001 is the fixture paper with two chunks (see fixtures.RECORDS).
    knn = MockVectorStoreAdapter().knn_search(fixtures.embed("diffusion protein structure"), 50)
    lexical = MockLexicalIndexAdapter().bm25_search(["diffusion", "protein"], 50)

    for label, out in (("knn", knn), ("bm25", lexical)):
        ids = [record.paperId for record, _ in out]
        assert len(ids) == len(set(ids)), f"{label} returned the same paper more than once: {ids}"
