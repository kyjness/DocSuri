"""BedrockCohereQueryEmbedder — real ``EmbeddingAdapter`` (vector-spec §1).

The reader-side mirror of U1's ``BedrockCohereEmbeddingPort``: SAME model/space, but
``input_type=search_query`` (Cohere v3 asymmetry — writer embeds documents, reader the
query; vector-spec §1). A transient Bedrock failure raises ``EmbeddingUnavailable`` so the
orchestrator degrades to lexical-only (Q1/BR-16). A dimension mismatch is NOT transient —
it means the query was embedded in a different space than the index (full re-embed
required, vector-spec §4) — so it fails loud rather than silently degrading.
"""

from __future__ import annotations

import json
from typing import Any

from docsuri_shared.vector_spec import DIMENSIONS, INPUT_TYPE_READER

from ..ports.search_ports import EmbeddingUnavailable


class BedrockCohereQueryEmbedder:
    """Query embedding via Bedrock (Cohere Embed Multilingual v3, reader=search_query)."""

    def __init__(
        self,
        *,
        model_id: str,
        region_name: str | None = None,
        client: Any | None = None,
    ) -> None:
        if client is None:
            import boto3  # lazy: only the `real` extra needs boto3
            from botocore.config import Config

            config = Config(
                connect_timeout=5.0,
                read_timeout=10.0,
                retries={"max_attempts": 1},
            )
            client = boto3.client("bedrock-runtime", region_name=region_name, config=config)
        self._client = client
        self._model_id = model_id

    def embed_query(self, text: str) -> list[float]:
        body = {
            "texts": [text],
            "input_type": INPUT_TYPE_READER,  # search_query (vector-spec §1 asymmetry)
            "embedding_types": ["float"],
            # Cohere Embed v4 defaults to 1536-dim; pin to the index width so query and index
            # share one space (else the dimension guard below fails loud). Matches the writer.
            "output_dimension": DIMENSIONS,
        }
        try:
            response = self._client.invoke_model(
                modelId=self._model_id,
                body=json.dumps(body).encode("utf-8"),
                accept="application/json",
                contentType="application/json",
            )
            payload = json.loads(response["body"].read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 — any Bedrock/transport error → degrade
            raise EmbeddingUnavailable("Bedrock query embedding failed") from exc

        vectors = payload.get("embeddings", [])
        if isinstance(vectors, dict):
            vectors = vectors.get("float", [])
        if not vectors:
            raise EmbeddingUnavailable("Bedrock returned no embedding")
        vector = vectors[0]
        if len(vector) != DIMENSIONS:
            # Space mismatch is a configuration error, not a transient outage (vector-spec §4).
            raise ValueError(
                f"Bedrock returned vector dimension {len(vector)}, expected {DIMENSIONS} "
                "— query/index embedding spaces differ (vector-spec §4)"
            )
        return [float(x) for x in vector]
