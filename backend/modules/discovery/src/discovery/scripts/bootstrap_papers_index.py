"""Create the EMPTY production papers index with the disk-based (on_disk 4x) k-NN mapping.

Unlike ``seed_local_opensearch`` (which loads fixtures into a lucene in-memory index for the
U2 read-path test), this creates the real, empty index the bulk harvest then fills. ``on_disk``
is fixed at index-creation time, so this must run BEFORE the harvest, against a domain at
OpenSearch >= 2.17 (we run 2.19 — see ops/cdk/stacks/search_stack.py).

Defaults to create-if-absent (will NOT touch an existing index). Pass ``--recreate`` to delete
and rebuild — needed to migrate the current lucene index to the on_disk mapping (drops its docs;
the corpus is (re)built by the harvest anyway).

    export DOCSURI_OPENSEARCH_ENDPOINT=https://<prod-domain-endpoint>
    uv run --extra real python -m discovery.scripts.bootstrap_papers_index [--recreate]
"""

from __future__ import annotations

import sys

from ..adapters.opensearch_index import OpenSearchClientFactory
from ..adapters.settings import DiscoverySettings
from .seed_local_opensearch import create_index, papers_index_body


def bootstrap(settings: DiscoverySettings | None = None, *, recreate: bool = False) -> str:
    settings = settings or DiscoverySettings.from_env()
    if not settings.opensearch_endpoint:
        raise SystemExit("DOCSURI_OPENSEARCH_ENDPOINT is required to bootstrap")
    client = OpenSearchClientFactory.build(
        endpoint=settings.opensearch_endpoint,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        use_ssl=settings.opensearch_use_ssl,
        verify_certs=settings.opensearch_verify_certs,
    )
    index = settings.opensearch_index
    existed = client.indices.exists(index=index)
    if existed and not recreate:
        return f"index {index!r} exists — pass --recreate to rebuild it with the on_disk mapping"
    create_index(client, index, recreate=recreate, body=papers_index_body(on_disk=True))
    verb = "recreated" if existed else "created"
    return f"{verb} empty on_disk index {index!r} (run the bulk harvest to populate it)"


def main() -> int:
    print(bootstrap(recreate="--recreate" in sys.argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
