"""evidence real_wiring — query-embedding provider switch + same-space guard (⑤a(b)-1).

The evidence agent is a SECOND reader over discovery's index. These tests pin that its wiring
resolves the embedding provider like discovery AND applies the same-space guard, so a
same-dimension/different-model swap (OpenAI vs Cohere, both 1024-dim) disables the vector leg
instead of scoring queries against a foreign embedding space.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from discovery.adapters.openai_embedding import OpenAIQueryEmbedder
from discovery.adapters.space_guard import MismatchedSpaceEmbedder
from discovery.ports.search_ports import EmbeddingUnavailable
from docsuri_shared.vector_spec import DIMENSIONS

from backend.modules.evidence.real_wiring import _build_guarded_query_embedder

_INDEX = "docsuri-corpus-v1"


def _d_settings(provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        embedding_provider=provider,
        openai_embedding_model="text-embedding-3-small",
        bedrock_model_id="cohere.embed-multilingual-v3",
        bedrock_region="us-west-2",
        opensearch_index=_INDEX,
    )


def _client(manifest: dict | None) -> SimpleNamespace:
    """OpenSearch client stub whose get_mapping returns (or omits) an _meta.embedding stamp."""

    class _Indices:
        def get_mapping(self, index: str) -> dict:  # noqa: ARG002
            meta = {"_meta": {"embedding": manifest}} if manifest is not None else {}
            return {_INDEX: {"mappings": meta}}

    return SimpleNamespace(indices=_Indices())


def test_openai_provider_matching_manifest_keeps_embedder() -> None:
    client = _client(
        {"provider": "openai", "model": "text-embedding-3-small", "dimensions": DIMENSIONS}
    )
    emb = _build_guarded_query_embedder(_d_settings("openai"), client, "ap-northeast-2")
    assert isinstance(emb, OpenAIQueryEmbedder)


def test_openai_provider_mismatch_disables_vector_leg() -> None:
    # Index was stamped by the Bedrock writer, but the reader is OpenAI → same-dim foreign space.
    client = _client(
        {"provider": "bedrock", "model": "cohere.embed-multilingual-v3", "dimensions": DIMENSIONS}
    )
    emb = _build_guarded_query_embedder(_d_settings("openai"), client, "ap-northeast-2")
    assert isinstance(emb, MismatchedSpaceEmbedder)
    with pytest.raises(EmbeddingUnavailable):
        emb.embed_query("some query")


def test_bedrock_provider_selected() -> None:
    client = _client(
        {"provider": "bedrock", "model": "cohere.embed-multilingual-v3", "dimensions": DIMENSIONS}
    )
    emb = _build_guarded_query_embedder(_d_settings("bedrock"), client, "ap-northeast-2")
    assert isinstance(emb, BedrockCohereQueryEmbedder)


def test_absent_manifest_passes_through() -> None:
    # Legacy index without the _meta.embedding stamp → guard can't verify, serves anyway (not fail).
    emb = _build_guarded_query_embedder(_d_settings("openai"), _client(None), "ap-northeast-2")
    assert isinstance(emb, OpenAIQueryEmbedder)
