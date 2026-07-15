"""OpenAIQueryEmbedder — solo-local ``EmbeddingAdapter`` (solo-local-migration.md §2).

Replaces the Bedrock Cohere reader when ``DOCSURI_EMBEDDING_PROVIDER=openai`` (the AWS
deployment is retired). Same contract as ``BedrockCohereQueryEmbedder``: a transport/API
failure raises ``EmbeddingUnavailable`` so the orchestrator degrades to lexical-only
(Q1/BR-16); a dimension mismatch is NOT transient — it means the query was embedded in a
different space than the index (full re-embed required, vector-spec §4) — so it fails loud
rather than silently degrading.

``dimensions`` pins text-embedding-3-* output to the frozen index width
(``vector_spec.DIMENSIONS`` = 1024), so the IndexRecord contract and the OpenSearch mapping
stay untouched by the provider swap. OpenAI embeddings are symmetric — Cohere's
writer/reader ``input_type`` asymmetry has no equivalent and is intentionally dropped; the
writer (ingestion ``OpenAIEmbeddingPort``) MUST use the same model so both sides share one
space. Stdlib ``urllib`` only: no new dependency, and the ``real`` extra stays
Bedrock/OpenSearch-scoped.
"""

from __future__ import annotations

import json
import os
import urllib.request

from docsuri_shared.vector_spec import DIMENSIONS

from ..ports.search_ports import EmbeddingUnavailable

_ENDPOINT = "https://api.openai.com/v1/embeddings"
# Mirror the Bedrock reader's fail-fast budget: a healthy single-query embed is subsecond;
# a slow one must fail into the tested lexical-only fallback well inside the search budget
# (QA 2026-07-10 F1), not stall the whole request.
_TIMEOUT_S = 4.0


class OpenAIQueryEmbedder:
    """Query embedding via the OpenAI embeddings API (reader side, symmetric model)."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        dimensions: int = DIMENSIONS,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self._dimensions = dimensions

    def embed_query(self, text: str) -> list[float]:
        body = json.dumps(
            {"model": self._model, "input": [text], "dimensions": self._dimensions}
        ).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 — fixed https endpoint, not user input
            _ENDPOINT,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
            vector = payload["data"][0]["embedding"]
        except Exception as exc:  # noqa: BLE001 — any transport/API error → lexical degrade
            raise EmbeddingUnavailable("OpenAI query embedding failed") from exc
        if len(vector) != self._dimensions:
            raise RuntimeError(
                f"embedding dimension mismatch: got {len(vector)}, "
                f"index expects {self._dimensions} (vector-spec §4 — re-embed required)"
            )
        return [float(v) for v in vector]
