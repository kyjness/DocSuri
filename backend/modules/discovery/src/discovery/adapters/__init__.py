"""Real capability adapters (CG-2 / MR-4) — the production swap for ``discovery.testing``.

These implement the U2-owned ports (``ports.search_ports``) against the real
infrastructure the U1 writer already populates:

- ``BedrockCohereQueryEmbedder``  → ``EmbeddingAdapter``  (Bedrock, Cohere v3, search_query)
- ``OpenSearchVectorStoreAdapter`` → ``VectorStoreAdapter`` (OpenSearch k-NN, cosine)
- ``OpenSearchLexicalIndexAdapter``→ ``LexicalIndexAdapter`` (OpenSearch BM25)
- ``EventBridgeEventPublisher``    → ``EventPublisher``     (SearchExecuted → U4 history)

The reader side is the mirror of U1's writer (``ingestion.adapters.aws``): same FROZEN
embedding space (vector-spec §4) and the SAME shared index (``docsuri-corpus-v1``). The
contract (``shared/dtos/search.schema.json``) is unchanged — swapping the test doubles for
these is a wiring decision, not a contract change (MR-4).

boto3 / opensearch-py are imported lazily inside each adapter's ``__init__`` (the ``real``
extra) so the mock-first domain core and its test suite stay dependency-free.
"""

from __future__ import annotations

from .bedrock_embedding import BedrockCohereQueryEmbedder
from .event_publisher import EventBridgeEventPublisher
from .opensearch_index import (
    OpenSearchClientFactory,
    OpenSearchLexicalIndexAdapter,
    OpenSearchVectorStoreAdapter,
)
from .settings import DiscoverySettings

__all__ = [
    "BedrockCohereQueryEmbedder",
    "EventBridgeEventPublisher",
    "OpenSearchClientFactory",
    "OpenSearchLexicalIndexAdapter",
    "OpenSearchVectorStoreAdapter",
    "DiscoverySettings",
]
