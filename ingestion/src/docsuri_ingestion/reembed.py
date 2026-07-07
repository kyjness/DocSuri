"""Fast corpus re-embed rebuild runner: reindex the existing OpenSearch corpus into a fresh,
bulk-tuned index changing ONLY the ``vector`` field, then alias-swap. Every other field
(metadata, blockRefs, section, chunkId, lexicalTerms, abstract) is already correct in the source.

Two modes:
  * MODE A (reshard / same embedding model) -- ``reembed_copy``: server-side ``_reindex`` copies
    everything incl. vectors, no Bedrock.
  * MODE B (embedding model change) -- ``reembed``: fleet sliced-scrolls the source, re-embeds each
    doc's stored text with the new model, and writes the full doc with the new vector to the target.

Both: ``reembed_provision`` -> (copy | reembed) -> ``reembed_finalize`` -> ``reembed_cutover``.
Run as one-off ECS tasks through the worker entrypoint like migrate.py, one task per shard for
MODE B (DOCSURI_REEMBED_SHARD / SHARD_COUNT), e.g.:

    python -m docsuri_ingestion.worker reembed
"""

from __future__ import annotations

import json
import logging
import time

from docsuri_shared.index_spec import papers_index_body
from docsuri_shared.vector_spec import EMBEDDING_SPEC

from .adapters.aws import BedrockCohereEmbeddingPort, build_opensearch_client, collect_bulk_failures
from .resilience import RetryPolicy, TokenBucket, is_retriable
from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.reembed")


def _client(settings: IngestionSettings):
    """OpenSearch admin client matching migrate._admin_client (TLS + SigV4 in prod, unsigned
    local). Duplicated here rather than imported from .migrate: migrate imports THIS module for
    _STEPS, so reusing its client would be a circular import."""
    if not settings.opensearch_endpoint:
        raise SystemExit("DOCSURI_OPENSEARCH_ENDPOINT is required")
    local = settings.env == "local"
    return build_opensearch_client(
        endpoint=settings.opensearch_endpoint,
        region_name=None if local else settings.aws_region,
        use_ssl=not local,
        verify_certs=not local,
    )


def _source_index(settings: IngestionSettings) -> str:
    return settings.reembed_source or settings.opensearch_alias


def _embed_text_for_source(src: dict) -> str:
    """The text that produced a stored doc's vector: abstract chunks embedded the ``abstract``
    field; body chunks embedded ``lexicalTerms`` (== normalize_text(chunk.text)). Fall back to
    abstract then title so a body chunk with an empty lexicalTerms still yields a usable vector."""
    if src.get("section") == "abstract":
        return src.get("abstract") or ""
    return src.get("lexicalTerms") or src.get("abstract") or src.get("title") or ""


def _scroll_body(settings: IngestionSettings, *, page_size: int) -> dict:
    body: dict = {"query": {"match_all": {}}, "size": page_size}
    if settings.reembed_shard_count > 1:
        body["slice"] = {"id": settings.reembed_shard_index, "max": settings.reembed_shard_count}
    return body


def _embed_with_retry(embedding, texts, policy: RetryPolicy | None = None) -> list[list[float]]:
    """Embed with backoff on transient Bedrock failures (throttling/5xx are now retriable via
    resilience.is_retriable), rather than letting one throttle abort a shard."""
    policy = policy or RetryPolicy(max_attempts=8, base_delay_seconds=2.0)
    attempt = 0
    while True:
        attempt += 1
        try:
            return embedding.embed_documents(texts)
        except Exception as exc:
            if is_retriable(exc) and attempt < policy.max_attempts:
                time.sleep(policy.delay_for_attempt(attempt))
                continue
            raise


def reembed_provision(settings: IngestionSettings | None = None) -> int:
    """Create the bulk-tuned re-embed target (0 replicas, refresh disabled) to minimize write
    amplification during the load. Idempotent: skips creation if it already exists."""
    settings = settings or IngestionSettings.from_env()
    client = _client(settings)
    dst = settings.opensearch_index_reembed
    if client.indices.exists(index=dst):
        log.info("index %s already exists", dst)
        return 0
    client.indices.create(
        index=dst,
        body=papers_index_body(
            on_disk=settings.env != "local",
            number_of_shards=settings.reembed_shards,
            number_of_replicas=0,
            refresh_interval="-1",
            dimension=settings.reembed_dimension,
        ),
    )
    log.info(
        "created re-embed target %s (shards=%d, dim=%s)",
        dst,
        settings.reembed_shards,
        settings.reembed_dimension or EMBEDDING_SPEC.dimensions,
    )
    return 0


def reembed_copy(settings: IngestionSettings | None = None) -> int:
    """MODE A (same embedding model): server-side ``_reindex`` copies every field incl. vectors
    into the target -- no Bedrock. Polls the reindex task to completion, then refreshes the target
    (refresh_interval=-1 means docs are not searchable until an explicit refresh)."""
    settings = settings or IngestionSettings.from_env()
    if settings.reembed_dimension not in (None, EMBEDDING_SPEC.dimensions):
        # MODE A copies source vectors verbatim; they can't land in a different-dimension mapping.
        raise SystemExit(
            f"reembed_copy cannot copy {EMBEDDING_SPEC.dimensions}-dim source vectors into a "
            f"{settings.reembed_dimension}-dim target -- a dimension change needs MODE B (reembed)"
        )
    client = _client(settings)
    src, dst = _source_index(settings), settings.opensearch_index_reembed
    throttle = (
        {"requests_per_second": settings.reembed_copy_rps}
        if settings.reembed_copy_rps > 0
        else {}
    )
    resp = client.reindex(
        body={"source": {"index": src}, "dest": {"index": dst, "op_type": "index"}},
        wait_for_completion=False,
        slices="auto",
        **throttle,
    )
    task_id = resp["task"]
    log.info("reindex %s -> %s started (task %s)", src, dst, task_id)
    while True:
        res = client.tasks.get(task_id=task_id)
        if res.get("completed"):
            break
        status = res.get("task", {}).get("status", {})
        log.info("reindex progress: %s/%s", status.get("created"), status.get("total"))
        time.sleep(5)
    client.indices.refresh(index=dst)
    log.info("reindex complete: %d docs in %s", int(client.count(index=dst)["count"]), dst)
    return 0


def _estimate_tokens(text: str) -> int:
    """Conservative input-token estimate for pacing (Bedrock bills input tokens). ~1 token per
    3.5 chars OVER-counts vs Cohere's tokenizer on typical scientific text, so pacing stays under
    the cap rather than tripping it. Min 1 so a short text still consumes budget."""
    return max(1, len(text) * 2 // 7)  # len / 3.5


def _existing_ids(client, index: str, ids: list[str]) -> set[str]:
    """The subset of ``ids`` already present in ``index`` (realtime mget, source suppressed). Lets
    a paced re-embed skip docs a prior (possibly killed) run already wrote -- so a relaunch resumes
    instead of re-embedding, and re-spending the token budget, from zero. mget is realtime, so it
    sees docs written but not yet refreshed (the target runs refresh_interval=-1 during the
    load)."""
    if not ids:
        return set()
    resp = client.mget(index=index, body={"ids": ids}, _source=False)
    return {d["_id"] for d in resp.get("docs", []) if d.get("found")}


def reembed(settings: IngestionSettings | None = None) -> int:
    """MODE B (embedding model change): sliced-scroll the source, recompute each doc's vector from
    its stored embed text with the new model, and bulk-write the full doc (only ``vector`` changes)
    to the target. Run one task per shard (DOCSURI_REEMBED_SHARD / SHARD_COUNT).

    With DOCSURI_REEMBED_TARGET_TPM>0 the run is PACED (holds Bedrock throughput under a binding,
    non-adjustable quota so it never throttle-storms) and RESUMABLE (skips docs already written to
    the target). Fan-out gives no speedup against an account-wide token/day cap, so a capped run is
    one continuous paced task; the pacing to <cap/min inherently keeps a day under the daily cap."""
    settings = settings or IngestionSettings.from_env()
    if not settings.bedrock_model_id:
        raise SystemExit("DOCSURI_BEDROCK_MODEL_ID is required for re-embed")
    client = _client(settings)
    embedding = BedrockCohereEmbeddingPort(
        model_id=settings.bedrock_model_id,
        region_name=settings.aws_region,
        output_dimension=settings.reembed_dimension,
    )
    src, dst = _source_index(settings), settings.opensearch_index_reembed
    page_size = min(96, max(1, settings.reembed_batch_size))
    # Paced mode: cap token throughput below the Bedrock quota + skip already-written docs. None →
    # unpaced legacy behaviour (needs quota headroom), byte-identical to before this knob existed.
    limiter = (
        TokenBucket(
            rate_per_second=settings.reembed_target_tpm / 60.0,
            capacity=settings.reembed_target_tpm,
        )
        if settings.reembed_target_tpm > 0
        else None
    )

    total = skipped_empty = skipped_done = 0
    resp = client.search(index=src, body=_scroll_body(settings, page_size=page_size), scroll="10m")
    sid = resp.get("_scroll_id")
    try:
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break
            # Drop docs whose stored embed text is empty (nothing to embed) but keep going.
            usable = [(h, text) for h in hits if (text := _embed_text_for_source(h["_source"]))]
            skipped_empty += len(hits) - len(usable)
            if usable and limiter is not None:
                # Resumability: don't re-embed (or re-spend budget on) docs a prior run wrote.
                done = _existing_ids(client, dst, [h["_id"] for h, _ in usable])
                if done:
                    usable = [(h, t) for (h, t) in usable if h["_id"] not in done]
                    skipped_done += len(done)
            if usable:
                if limiter is not None:
                    # Pace to the token budget BEFORE hitting Bedrock so we never trip the cap.
                    limiter.acquire(sum(_estimate_tokens(t) for _, t in usable))
                vectors = _embed_with_retry(embedding, [text for _, text in usable])
                lines: list[str] = []
                for (h, _text), vec in zip(usable, vectors, strict=True):
                    lines.append(json.dumps({"index": {"_index": dst, "_id": h["_id"]}}))
                    lines.append(json.dumps({**h["_source"], "vector": vec}))
                bulk_resp = client.bulk(body="\n".join(lines) + "\n")
                failures = collect_bulk_failures(bulk_resp)
                if failures:
                    raise RuntimeError(f"re-embed bulk had {len(failures)} failed item(s)")
                total += len(usable)
            log.info(
                "re-embedded %d (skipped_empty=%d, skipped_done=%d)",
                total, skipped_empty, skipped_done,
            )
            resp = client.scroll(scroll_id=sid, scroll="10m")
            sid = resp.get("_scroll_id")
    finally:
        if sid:
            try:
                client.clear_scroll(scroll_id=sid)
            except Exception:  # noqa: BLE001 -- best-effort scroll cleanup
                pass
    log.info(
        "re-embed shard %d/%d complete: %d reembedded, %d skipped_empty, %d skipped_done",
        settings.reembed_shard_index,
        settings.reembed_shard_count,
        total,
        skipped_empty,
        skipped_done,
    )
    return 0


def reembed_finalize(settings: IngestionSettings | None = None) -> int:
    """Restore production index settings after the bulk load, force-merge for read efficiency,
    and gate on a document-count floor before anyone cuts over to the target."""
    settings = settings or IngestionSettings.from_env()
    client = _client(settings)
    dst = settings.opensearch_index_reembed
    client.indices.put_settings(
        index=dst, body={"index": {"number_of_replicas": 1, "refresh_interval": "1s"}}
    )
    try:
        client.indices.forcemerge(index=dst, max_num_segments=1)
    except Exception as exc:  # noqa: BLE001 -- forcemerge can time out client-side, continues server-side
        log.warning("forcemerge on %s did not confirm (continues server-side): %s", dst, exc)
    client.indices.refresh(index=dst)
    count = int(client.count(index=dst)["count"])
    if count < settings.reembed_min_documents:
        raise SystemExit(f"re-embed target {dst} has too few docs: {count}")
    log.info("re-embed target %s finalized: %d docs", dst, count)
    return 0


def reembed_cutover(settings: IngestionSettings | None = None) -> int:
    """Atomically repoint the read alias to point ONLY at the re-embed target. Idempotent:
    removes whatever indices the alias currently names, then adds the target."""
    settings = settings or IngestionSettings.from_env()
    client = _client(settings)
    alias, dst = settings.opensearch_alias, settings.opensearch_index_reembed
    actions: list[dict] = []
    # exists_alias returns a clean bool; get_alias(ignore=[404]) returns a *truthy* 404 error-dict
    # when the alias is absent, whose keys ("error"/"status") would become bogus remove targets
    # (the trap documented in migrate.provision). Only enumerate real members.
    if client.indices.exists_alias(name=alias):
        existing = client.indices.get_alias(name=alias)
        actions.extend({"remove": {"index": i, "alias": alias}} for i in existing)
    actions.append({"add": {"index": dst, "alias": alias}})
    client.indices.update_aliases(body={"actions": actions})
    log.info("alias %s -> %s", alias, dst)
    return 0
