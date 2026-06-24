"""Seed a local OpenSearch with a deterministic mini-corpus for U2 read-path validation.

Creates the shared index (``docsuri-corpus-v1``) with the k-NN + BM25 mapping the U1 writer
uses, then bulk-indexes the deterministic fixtures (``mocks.fixtures.RECORDS``) exactly as
the writer would (``_id = chunkId``). This lets the real OpenSearch adapters be exercised
end-to-end with NO cloud/Bedrock dependency — the fixtures carry precomputed vectors and the
integration test embeds queries with the matching offline embedder.

Run (from ``backend/modules/discovery``, with local OpenSearch up):

    export DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200
    export DOCSURI_OPENSEARCH_USE_SSL=0 DOCSURI_OPENSEARCH_VERIFY_CERTS=0
    uv run --extra real python -m discovery.scripts.seed_local_opensearch
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from typing import Any

from docsuri_shared.index_spec import papers_index_body
from docsuri_shared.vector_spec import IndexRecord

from ..adapters.opensearch_index import OpenSearchClientFactory
from ..adapters.settings import DiscoverySettings
from ..mocks import fixtures

# papers_index_body moved to docsuri_shared.index_spec (single source — the ingestion image
# provisions from the same body). Re-exported here so existing callers keep importing it from
# this module.

# Local seed mapping (lucene, in-memory). Production uses papers_index_body(on_disk=True).
INDEX_BODY: dict[str, Any] = papers_index_body()


def create_index(
    client: Any, index_name: str, *, recreate: bool = True, body: dict[str, Any] | None = None
) -> None:
    """Create a single index (default ``INDEX_BODY``). Used by ``bootstrap_papers_index`` to
    build the production on_disk index; ``recreate`` drops an existing one first."""
    if recreate and client.indices.exists(index=index_name):
        client.indices.delete(index=index_name)
    if not client.indices.exists(index=index_name):
        client.indices.create(index=index_name, body=body or INDEX_BODY)


def create_indices_and_alias(client: Any, alias_name: str, *, recreate: bool = True) -> None:
    v1_index = f"{alias_name}-v1"
    v2_index = f"{alias_name}-v2"
    for index_name in [v1_index, v2_index]:
        if recreate and client.indices.exists(index=index_name):
            client.indices.delete(index=index_name)
        if not client.indices.exists(index=index_name):
            client.indices.create(index=index_name, body=INDEX_BODY)

    client.indices.put_alias(index=v1_index, name=alias_name)


def bulk_index(client: Any, index_name: str, records: Iterable[IndexRecord]) -> int:
    lines: list[str] = []
    count = 0
    for record in records:
        lines.append(json.dumps({"index": {"_index": index_name, "_id": record.chunkId}}))
        lines.append(json.dumps(record.model_dump(mode="json")))
        count += 1
    if not lines:
        return 0
    client.bulk(body="\n".join(lines) + "\n", refresh=True)
    return count


def seed(settings: DiscoverySettings | None = None) -> int:
    settings = settings or DiscoverySettings.from_env()
    if not settings.opensearch_endpoint:
        raise SystemExit("DOCSURI_OPENSEARCH_ENDPOINT is required to seed")
    client = OpenSearchClientFactory.build(
        endpoint=settings.opensearch_endpoint,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )
    alias_name = settings.opensearch_index
    v1_index = f"{alias_name}-v1"
    create_indices_and_alias(client, alias_name)
    n = bulk_index(client, v1_index, fixtures.RECORDS)
    return n


def main() -> int:
    n = seed()
    print(f"seeded {n} chunk record(s) into the local OpenSearch index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
