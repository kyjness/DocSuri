"""Unit tests for the real Bedrock query embedder (no boto3 / network — fake client)."""

from __future__ import annotations

import json

import pytest
from docsuri_shared.vector_spec import DIMENSIONS, INPUT_TYPE_READER

from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from discovery.ports.search_ports import EmbeddingUnavailable


class _Body:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class FakeBedrock:
    def __init__(self, *, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.last_request: dict | None = None

    def invoke_model(self, *, modelId, body, accept, contentType):  # noqa: N803,ARG002
        self.last_request = json.loads(body.decode("utf-8"))
        if self.error is not None:
            raise self.error
        return {"body": _Body(self.payload or {})}


def _vec(n: int = DIMENSIONS) -> list[float]:
    return [0.1] * n


def test_embed_query_uses_search_query_input_type() -> None:
    fake = FakeBedrock(payload={"embeddings": {"float": [_vec()]}})
    emb = BedrockCohereQueryEmbedder(model_id="m", client=fake)

    out = emb.embed_query("확산 모델 단백질")

    assert len(out) == DIMENSIONS
    # vector-spec §1 asymmetry: the reader MUST use search_query (not search_document).
    assert fake.last_request is not None
    assert fake.last_request["input_type"] == INPUT_TYPE_READER == "search_query"
    assert fake.last_request["texts"] == ["확산 모델 단백질"]


def test_embed_query_handles_bare_list_embeddings_shape() -> None:
    fake = FakeBedrock(payload={"embeddings": [_vec()]})
    emb = BedrockCohereQueryEmbedder(model_id="m", client=fake)
    assert len(emb.embed_query("x")) == DIMENSIONS


def test_transient_failure_raises_embedding_unavailable() -> None:
    # A transient Bedrock/transport error must degrade (→ lexical-only), not crash.
    fake = FakeBedrock(error=RuntimeError("throttled"))
    emb = BedrockCohereQueryEmbedder(model_id="m", client=fake)
    with pytest.raises(EmbeddingUnavailable):
        emb.embed_query("x")


def test_empty_embedding_raises_embedding_unavailable() -> None:
    fake = FakeBedrock(payload={"embeddings": []})
    emb = BedrockCohereQueryEmbedder(model_id="m", client=fake)
    with pytest.raises(EmbeddingUnavailable):
        emb.embed_query("x")


def test_dimension_mismatch_fails_loud() -> None:
    # A wrong dimension is a SPACE mismatch (config error), not transient — fail loud.
    fake = FakeBedrock(payload={"embeddings": {"float": [[0.1, 0.2, 0.3]]}})
    emb = BedrockCohereQueryEmbedder(model_id="m", client=fake)
    with pytest.raises(ValueError):
        emb.embed_query("x")


def test_v4_model_pins_output_dimension_no_truncate() -> None:
    # v4 (model id without "-v3"): pin output_dimension, no truncate — byte-identical to before.
    fake = FakeBedrock(payload={"embeddings": {"float": [_vec()]}})
    emb = BedrockCohereQueryEmbedder(model_id="global.cohere.embed-v4:0", client=fake)
    emb.embed_query("x")
    assert fake.last_request["output_dimension"] == DIMENSIONS
    assert "truncate" not in fake.last_request


def test_v3_model_omits_output_dimension_truncates_and_caps_chars() -> None:
    # v3 (cohere.embed-multilingual-v3): no output_dimension, truncate=END, text capped at 2048.
    fake = FakeBedrock(payload={"embeddings": {"float": [_vec()]}})
    emb = BedrockCohereQueryEmbedder(model_id="cohere.embed-multilingual-v3", client=fake)
    emb.embed_query("q" * 5000)
    assert "output_dimension" not in fake.last_request
    assert fake.last_request["truncate"] == "END"
    assert len(fake.last_request["texts"][0]) == 2048
