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
    window_start, window_end = settings.backfill_window(CORPUS_START, CORPUS_END)
    filter_ = CategoryFilter(
        categories=CORPUS_SLICE_CATEGORIES,
        updated_after=window_start,
        updated_before=window_end,
    )

    from .domain.errors import PermanentIngestionError

    count = excluded = errors = 0
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
        except PermanentIngestionError as exc:
            # BR-30 2026-08-10 corpus exclusion (or any other permanent verdict) — counted apart
            # from faults: an exclusion RATE is the signal a mis-tuned gate or an unwired/broken
            # GROBID would show, and it must fail the run, not scroll past as warnings.
            excluded += 1
            log.warning("EXCLUDED %s: %s", metadata.arxiv_ref, exc)
        except Exception as exc:  # noqa: BLE001 — one bad paper must not abort the reparse
            errors += 1
            log.warning("FAILED %s: %s", metadata.arxiv_ref, exc)
    total = count + excluded + errors
    bad_ratio = (excluded + errors) / total if total else 1.0
    log.info(
        "reparse complete: %d indexed, %d excluded, %d failures (bad ratio %.3f, budget %.3f)",
        count, excluded, errors, bad_ratio, settings.reparse_max_failure_ratio,
    )
    if bad_ratio > settings.reparse_max_failure_ratio:
        # The run itself must refuse to look successful: reembed_finalize's document floor
        # defaults to 1 and reembed_cutover swaps the alias unconditionally, so a silent shrink
        # here would go live. A nonzero exit blocks the finalize→cutover chain and puts the
        # decision (retune the gate / fix GROBID / raise the budget) in the operator's hands.
        log.error(
            "reparse FAILED its loss budget: %.1f%% of %d papers excluded/errored (budget %.1f%%)"
            " — finalize/cutover must not proceed on this run",
            bad_ratio * 100, total, settings.reparse_max_failure_ratio * 100,
        )
        return 1
    return 0
