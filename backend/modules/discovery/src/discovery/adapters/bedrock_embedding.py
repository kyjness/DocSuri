"""BedrockCohereQueryEmbedder — real ``EmbeddingAdapter`` (vector-spec §1).

The reader-side mirror of U1's ``BedrockCohereEmbeddingPort``: SAME model/space, but
``input_type=search_query`` (Cohere Embed v4 asymmetry — writer embeds documents, reader the
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

# A healthy single-query embed is subsecond; 4s is already pathological. Failing fast matters
# more than waiting: timeout → EmbeddingUnavailable → the orchestrator's tested lexical-only
# fallback, keeping the whole search inside the BFF's 30s search hop (QA 2026-07-10 F1 — the
# old 10s read could eat the entire former hop budget). Module-level so the latency-budget
# contract test (test_latency_budget.py) can assert the cold-path sum.
_CONNECT_TIMEOUT_S = 3.0
_READ_TIMEOUT_S = 4.0


class BedrockCohereQueryEmbedder:
    """Query embedding via Bedrock (Cohere Embed Multilingual v4, reader=search_query)."""

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
                connect_timeout=_CONNECT_TIMEOUT_S,
                read_timeout=_READ_TIMEOUT_S,
                retries={"max_attempts": 1},
            )
            client = boto3.client("bedrock-runtime", region_name=region_name, config=config)
        self._client = client
        self._model_id = model_id
        # Cohere Embed Multilingual v3 is fixed 1024-dim (rejects output_dimension) with a
        # 512-token / 2048-char input cap (needs truncate). v4 keeps the output_dimension pin.
        # Detect by model-id suffix — mirrors the writer (BedrockCohereEmbeddingPort).
        self._is_v3 = "-v3" in model_id

    def embed_query(self, text: str) -> list[float]:
        # v3 hard-rejects text > 2048 CHARS at Bedrock input validation (before token-truncate);
        # cap client-side. Queries are short, but mirror the writer so the paths stay symmetric.
        query_text = text[:2048] if self._is_v3 else text
        body: dict[str, Any] = {
            "texts": [query_text],
            "input_type": INPUT_TYPE_READER,  # search_query (vector-spec §1 asymmetry)
            "embedding_types": ["float"],
        }
        if self._is_v3:
            # v3 is fixed 1024-dim (no output_dimension); truncate=END also caps tokens (<=512).
            body["truncate"] = "END"
        else:
            # Cohere Embed v4 defaults to 1536-dim; pin to the index width so query and index
            # share one space (else the dimension guard below fails loud). Matches the writer.
            body["output_dimension"] = DIMENSIONS
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
