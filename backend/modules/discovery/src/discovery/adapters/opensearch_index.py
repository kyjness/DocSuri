"""OpenSearch read adapters — real ``VectorStoreAdapter`` + ``LexicalIndexAdapter``.

The reader mirror of U1's ``OpenSearchVectorIndex`` writer: the SAME index
(``docsuri-corpus-v1``), one store serving both k-NN (cosine, ``vector``) and BM25
(``title``/``abstract``/``lexicalTerms``) — hybrid retrieval (FR-2). Hits are
deserialized straight back into the shared ``IndexRecord`` (SSOT round-trip; no forked
shape). OpenSearch is one store, so ANY
query failure raises ``IndexUnavailable`` → the orchestrator fail-closes (INV-3/SEC-15);
there is no index fallback (only embedding has a fallback).

ports declares ``VectorStoreAdapter`` and ``LexicalIndexAdapter`` as two protocols; they are
exposed as two adapter objects but share one OpenSearch client via ``OpenSearchClientFactory``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from docsuri_shared.vector_spec import IndexRecord

from ..ports.search_ports import IndexUnavailable, ScoredRecord


class OpenSearchClientFactory:
    """Builds the shared ``opensearch-py`` client (lazy import; the ``real`` extra)."""

    @staticmethod
    def build(
        *,
        endpoint: str,
        region_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
    ) -> Any:
        from opensearchpy import OpenSearch

        # Auth order mirrors the U1 writer (ingestion.build_opensearch_client): basic-auth if
        # both creds are given (local/override), else SigV4 (``Urllib3AWSV4SignerAuth``, service
        # ``es``) when a region is set — the managed VPC domain authorizes the ECS task role by
        # resource policy, so signed requests are required — else unsigned (local open cluster).
        http_auth: Any
        if username and password:
            http_auth = (username, password)
        elif region_name:
            import boto3
            from opensearchpy import Urllib3AWSV4SignerAuth

            http_auth = Urllib3AWSV4SignerAuth(
                boto3.Session().get_credentials(), region_name, "es"
            )
        else:
            http_auth = None
        return OpenSearch(
            hosts=[endpoint],
            http_auth=http_auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            timeout=10,
        )


def _to_scored(hits: list[dict[str, Any]]) -> list[ScoredRecord]:
    """Deserialize OpenSearch hits → (IndexRecord, store score), preserving rank order."""
    scored: list[ScoredRecord] = []
    for hit in hits:
        record = IndexRecord.model_validate(hit["_source"])
        scored.append((record, float(hit.get("_score") or 0.0)))
    return scored


class OpenSearchVectorStoreAdapter:
    """k-NN (ANN) reader over the shared OpenSearch index (cosine; FR-2)."""

    def __init__(self, client: Any, index_name: str) -> None:
        self._client = client
        self._index = index_name

    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        knn: dict[str, Any] = {"vector": list(vector), "k": top_k}
        if abstract_only:
            # Efficient k-NN filtering: restrict the ANN search to abstract chunks (lite scope).
            knn["filter"] = {"term": {"section": "abstract"}}
        body = {
            "size": top_k,
            "query": {"knn": {"vector": knn}},
        }
        try:
            response = self._client.search(index=self._index, body=body)
            hits = response["hits"]["hits"]
        except Exception as exc:  # noqa: BLE001 — one store; any failure → fail-closed (INV-3)
            raise IndexUnavailable("OpenSearch k-NN query failed") from exc
        return _to_scored(hits)


class OpenSearchPaperLookupAdapter:
    """Single-document reader over the shared OpenSearch index — one record for a paper id
    (matched on ``paperId`` or display ``arxivId``). Powers the paper-detail metadata endpoint."""

    def __init__(self, client: Any, index_name: str) -> None:
        self._client = client
        self._index = index_name

    def fetch_paper(self, paper_id: str) -> IndexRecord | None:
        # Match either the version-less paperId or the display arxivId (the detail route id is
        # the arxivId). size=1: any chunk carries the paper-level metadata.
        body = {
            "size": 1,
            "query": {
                "bool": {
                    "should": [
                        {"term": {"paperId": paper_id}},
                        {"term": {"arxivId": paper_id}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        try:
            response = self._client.search(index=self._index, body=body)
            hits = response["hits"]["hits"]
        except Exception as exc:  # noqa: BLE001 — one store; any failure → fail-closed (INV-3)
            raise IndexUnavailable("OpenSearch paper lookup failed") from exc
        if not hits:
            return None
        return IndexRecord.model_validate(hits[0]["_source"])


class OpenSearchLexicalIndexAdapter:
    """BM25 reader over analyzed title, abstract, and chunk-body lexical fields (FR-2)."""

    def __init__(self, client: Any, index_name: str) -> None:
        self._client = client
        self._index = index_name

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        body = {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": " ".join(terms),
                    "fields": list(fields),
                }
            },
        }
        try:
            response = self._client.search(index=self._index, body=body)
            hits = response["hits"]["hits"]
        except Exception as exc:  # noqa: BLE001 — one store; any failure → fail-closed (INV-3)
            raise IndexUnavailable("OpenSearch BM25 query failed") from exc
        return _to_scored(hits)
