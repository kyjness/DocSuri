"""evidence real_wiring — the second reader must share discovery's embedding space (⑤a(b)-1).

The evidence agent reads discovery's index with its own wiring. These tests pin that it builds
the same embedder AND applies the same-space guard, so a same-dimension/different-model swap
disables the vector leg instead of scoring queries against a foreign embedding space. The live
case is Cohere Embed Multilingual v3 vs Embed v4 — both 1024-dimensional, so no shape check
catches the swap.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from discovery.adapters.space_guard import MismatchedSpaceEmbedder
from discovery.ports.search_ports import EmbeddingUnavailable
from docsuri_shared.vector_spec import DIMENSIONS

from backend.modules.evidence.real_wiring import _build_guarded_query_embedder

_INDEX = "docsuri-corpus-v1"
_MODEL = "cohere.embed-v4:0"


def _d_settings(model_id: str = _MODEL) -> SimpleNamespace:
    return SimpleNamespace(
        bedrock_model_id=model_id,
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


def _manifest(model: str) -> dict:
    return {"provider": "bedrock", "model": model, "dimensions": DIMENSIONS}


def test_matching_manifest_keeps_the_embedder() -> None:
    emb = _build_guarded_query_embedder(
        _d_settings(), _client(_manifest(_MODEL)), "ap-northeast-2"
    )
    assert isinstance(emb, BedrockCohereQueryEmbedder)


def test_same_dimension_model_swap_disables_the_vector_leg() -> None:
    # Index stamped with v3, reader compiled against v4 — same vendor, same 1024 dimensions,
    # incompatible spaces. Nothing but the manifest can tell these apart.
    emb = _build_guarded_query_embedder(
        _d_settings(_MODEL),
        _client(_manifest("cohere.embed-multilingual-v3")),
        "ap-northeast-2",
    )
    assert isinstance(emb, MismatchedSpaceEmbedder)
    with pytest.raises(EmbeddingUnavailable):
        emb.embed_query("some query")


def test_absent_manifest_passes_through() -> None:
    # Legacy index without the _meta.embedding stamp → guard can't verify, serves anyway
    # (logged, not failed) so pre-manifest local indices keep working.
    emb = _build_guarded_query_embedder(_d_settings(), _client(None), "ap-northeast-2")
    assert isinstance(emb, BedrockCohereQueryEmbedder)
