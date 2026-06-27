"""Unit tests for the real OpenSearch read adapters (fake client — no cluster needed)."""

from __future__ import annotations

import pytest
from docsuri_shared.vector_spec import DIMENSIONS

from discovery.adapters.opensearch_index import (
    OpenSearchLexicalIndexAdapter,
    OpenSearchVectorStoreAdapter,
)
from discovery.mocks import fixtures
from discovery.ports.search_ports import IndexUnavailable


def _hit(record, score: float) -> dict:
    return {"_score": score, "_source": record.model_dump(mode="json")}


class FakeSearchClient:
    def __init__(self, *, hits: list[dict] | None = None, error: Exception | None = None) -> None:
        self.hits = hits or []
        self.error = error
        self.last: tuple | None = None

    def search(self, *, index, body):
        self.last = (index, body)
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
    assert body["size"] == 20
    assert body["query"]["knn"]["vector"]["k"] == 20


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
