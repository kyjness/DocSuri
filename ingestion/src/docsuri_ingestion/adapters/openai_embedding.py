"""OpenAIEmbeddingPort — solo-local writer ``EmbeddingPort`` (solo-local-migration.md §2/§3).

Replaces ``BedrockCohereEmbeddingPort`` for the local reindex of the downloaded doc-model
mirror (the AWS deployment is retired). ``dimensions`` pins text-embedding-3-* output to the
frozen spec width (``vector_spec.DIMENSIONS`` = 1024) so the index mapping and IndexRecord
contract are untouched; the reader (discovery ``OpenAIQueryEmbedder``) MUST use the same
model so writer and reader share one space (vector-spec §4). OpenAI embeddings are
symmetric — Cohere's ``input_type`` writer/reader asymmetry has no equivalent here, so the
writer-role assert stays a spec-level concern only.

NOT wired into ``runtime.build_production_pipeline``: the production worker path needs
SQS + control-plane, which the local migration defers. The local reindex script constructs
this port directly.

Faults are raised as the unit's failure taxonomy rather than as transport errors: neither
``urllib.error.HTTPError`` nor a bare ``httpx`` exception is recognised by
``resilience.is_retriable``, so a 429 from a long local reindex aborted the run instead of
backing off. Going through the shared HTTP mappers makes rate limits and 5xx retriable and
leaves genuine 4xx permanent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence

from docsuri_shared.vector_spec import DIMENSIONS

from docsuri_ingestion.http_limits import (
    http_failures_as_ingestion_errors,
    raise_for_fetch_status,
)

_ENDPOINT = "https://api.openai.com/v1/embeddings"
# Batch write runs in an offline script/worker — generous ceiling bounds a genuine hang
# without cutting a slow large batch (mirrors the summarization Bedrock read_timeout logic).
_TIMEOUT_S = 60.0
# Chunks are capped at max_chunk_chars (2400) by the Chunker, but be defensive: the model
# rejects a single input > 8192 tokens, and one oversized stray text must not 400 the batch
# (the Cohere-v3 2048-char lesson). ~24k chars stays safely under the token cap.
_MAX_INPUT_CHARS = 24_000
_DEFAULT_BATCH_SIZE = 96  # request stays well under the API's total-token cap at 2400-char chunks


class OpenAIEmbeddingPort:
    """Document embedding via the OpenAI embeddings API (writer side, symmetric model)."""

    def __init__(
        self,
        *,
        model: str = "text-embedding-3-small",
        api_key: str | None = None,
        output_dimension: int | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self._dimensions = output_dimension or DIMENSIONS
        self._batch_size = batch_size

    def embed_documents(
        self,
        texts: Sequence[str],
        *,
        correlation_id: str | None = None,
    ) -> list[list[float]]:
        del correlation_id
        # Sub-batch and concatenate IN ORDER — the assembler zips chunk_ids↔vectors with
        # strict=True, so order must be preserved (same invariant as the Bedrock writer).
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(self._embed_batch(texts[start : start + self._batch_size]))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        # The API rejects empty strings; a blank chunk should never reach here, but map it to
        # a single space rather than failing the whole batch.
        payload_texts = [t[:_MAX_INPUT_CHARS] or " " for t in texts]
        body = json.dumps(
            {"model": self._model, "input": payload_texts, "dimensions": self._dimensions}
        ).encode("utf-8")
        import httpx

        with http_failures_as_ingestion_errors(
            stage="embed",
            timeout_message="OpenAI embeddings request timed out",
            failure_message="OpenAI embeddings request failed",
            # No rejected_message: this path runs no body guard. The endpoint is fixed and
            # authenticated and the response size is bounded by the batch we just sent, so there
            # is nothing for the NFR §0.5 size cap (which exists for untrusted hosts) to defend.
        ):
            # follow_redirects: urllib followed 3xx automatically and httpx does not. Without it a
            # gateway or regional redirect in front of the API falls past raise_for_fetch_status
            # (which only classifies >= 400) into response.json(), raising a JSONDecodeError that
            # is_retriable does not recognise — aborting the run this rewrite exists to keep alive.
            with httpx.Client(timeout=_TIMEOUT_S, follow_redirects=True) as client:
                response = client.post(
                    _ENDPOINT,
                    content=body,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
                # 429 becomes RATE_LIMITED and 5xx FETCH_FAILURE, both retriable, so a paced
                # reindex backs off instead of losing the run to one throttle.
                raise_for_fetch_status(
                    response.status_code, stage="embed", source_label="OpenAI embeddings"
                )
                payload = response.json()
        # The API documents index-ordered results; sort defensively so a reordered response
        # can never mis-align chunk_ids↔vectors (that corruption would be silent at query time).
        rows = sorted(payload["data"], key=lambda row: row["index"])
        if len(rows) != len(payload_texts):
            raise RuntimeError(
                f"embedding count mismatch: sent {len(payload_texts)}, got {len(rows)}"
            )
        vectors = [[float(v) for v in row["embedding"]] for row in rows]
        for vector in vectors:
            if len(vector) != self._dimensions:
                raise RuntimeError(
                    f"embedding dimension mismatch: got {len(vector)}, "
                    f"spec expects {self._dimensions} (vector-spec §4)"
                )
        return vectors
