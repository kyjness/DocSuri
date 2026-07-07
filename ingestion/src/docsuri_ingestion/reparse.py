"""B3 full re-parse driver: rebuild the SEARCH index from the raw cache into an OFFLINE index.

Modeled on migrate.backfill, changing only target/cache/sleep: it harvests the corpus metadata
from OAI-PMH (cheap, paged) and re-runs the ingest pipeline, but the pipeline writes to the
re-embed target index (offline) and fetches source bytes CACHE-ONLY (raw_cache_mode="only", primed
by raw_backfill.py) — so there is NO arXiv per-paper fetch and NO 1-req/3s rate limit. After all
shards finish, reuse the existing reembed_finalize -> reembed_cutover + alias swap.

Run as one-off ECS tasks through the worker entrypoint like migrate.py, sharded via
DOCSURI_BACKFILL_START/END sub-windows:

    python -m docsuri_ingestion.worker reparse
"""

from __future__ import annotations

import logging

from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.reparse")


def reparse(settings: IngestionSettings | None = None) -> int:
    """Re-parse the seed corpus from the raw cache into the offline re-embed index. Idempotent:
    bulk_upsert is keyed by chunkId, so re-runs overwrite rather than duplicate. One bad paper is
    logged and skipped, never aborts the run. No sleep — cache-only reads are not rate-limited."""
    settings = settings or IngestionSettings.from_env()
    if not settings.bedrock_model_id:
        raise SystemExit("DOCSURI_BEDROCK_MODEL_ID is required for reparse")

    from .adapters.arxiv import ArxivHttpSource
    from .config import CORPUS_END, CORPUS_SLICE_CATEGORIES, CORPUS_START
    from .domain.enums import JobKind
    from .domain.models import CategoryFilter, IngestionJob
    from .migrate import _window
    from .runtime import build_production_runtime

    # Pipeline writes to the OFFLINE re-embed index and fetches source bytes CACHE-ONLY (no arXiv).
    runtime = build_production_runtime(
        settings.model_copy(
            update={
                "opensearch_index": settings.opensearch_index_reembed,
                "raw_cache_mode": "only",
            }
        )
    )
    # harvest_seed only lists OAI metadata (cheap/paged) — not the per-paper bottleneck.
    arxiv = ArxivHttpSource(timeout_seconds=30.0)
    filter_ = CategoryFilter(
        categories=CORPUS_SLICE_CATEGORIES,
        updated_after=_window("DOCSURI_BACKFILL_START", CORPUS_START),
        updated_before=_window("DOCSURI_BACKFILL_END", CORPUS_END),
    )

    count = errors = 0
    for metadata in arxiv.harvest_seed(filter_):
        try:
            runtime.pipeline.ingest_metadata(
                IngestionJob(
                    job_id=f"reparse-{metadata.paper_id}",
                    kind=JobKind.SEED_REBUILD,
                    arxiv_ref=metadata.arxiv_ref,
                ),
                metadata,
            )
            count += 1
            log.info("[%d] reparsed %s", count, metadata.arxiv_ref)
        except Exception as exc:  # noqa: BLE001 — one bad paper must not abort the reparse
            errors += 1
            log.warning("FAILED %s: %s", metadata.arxiv_ref, exc)
    log.info("reparse complete: %d indexed, %d failures", count, errors)
    return 0
