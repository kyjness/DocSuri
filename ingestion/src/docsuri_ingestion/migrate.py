"""In-VPC runner for the v4 embedding migration (FR-21): provision -> backfill -> cutover.

One module, run from the ingestion image (the only image with the ingestion package AND
Bedrock + OpenSearch network access). Invoked through the worker entrypoint with a step arg,
e.g. as a one-off ECS task on the existing worker task definition:

    aws ecs run-task --task-definition <WorkerTaskDef> --launch-type FARGATE \\
      --network-configuration '{...worker subnets + SG...}' \\
      --overrides '{"containerOverrides":[{"name":"worker","command":["provision"]}]}'

so the container runs ``python -m docsuri_ingestion.worker provision``. Every step is idempotent
(re-runnable). Reads its config from the task-def env (DOCSURI_OPENSEARCH_*, *_V2, BEDROCK_*).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

from docsuri_shared.index_spec import papers_index_body

from .observability import configure_logging
from .raw_backfill import raw_backfill
from .reembed import (
    reembed,
    reembed_copy,
    reembed_cutover,
    reembed_finalize,
    reembed_provision,
)
from .reparse import reparse
from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.migrate")

_ALIAS = "docsuri-corpus"
# ponytail: 1 req/3s matches arXiv politeness + Bedrock default TPS; raise if quota allows.
_BACKFILL_DELAY_SECONDS = 3.0


def _window(env_name: str, default: datetime) -> datetime:
    """Run-scoped window override (ISO date in DOCSURI_BACKFILL_START/END) — lets a one-off
    backfill narrow the slice without redefining the corpus (CORPUS_START/END stay canonical)."""
    raw = os.getenv(env_name)
    if not raw:
        return default
    dt = datetime.fromisoformat(raw)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _admin_client(settings: IngestionSettings):
    """OpenSearch admin client matching the writer adapter (aws.build_opensearch_client):
    TLS on in prod and SigV4-signed (service ``es``) with the ECS task role, so the managed
    VPC domain's resource policy authorizes the request. Unsigned only for local clusters."""
    from .adapters.aws import build_opensearch_client

    if not settings.opensearch_endpoint:
        raise SystemExit("DOCSURI_OPENSEARCH_ENDPOINT is required")
    local = settings.env == "local"
    return build_opensearch_client(
        endpoint=settings.opensearch_endpoint,
        region_name=None if local else settings.aws_region,
        use_ssl=not local,
        verify_certs=not local,
    )


def provision(settings: IngestionSettings | None = None) -> int:
    """Create the empty v2 index (canonical on_disk mapping in prod) and ensure the read alias
    exists pointing at v1 — so a later Discovery deploy that reads the alias is safe in any
    deploy order. Idempotent."""
    settings = settings or IngestionSettings.from_env()
    client = _admin_client(settings)
    v1, v2 = settings.opensearch_index, settings.opensearch_index_v2
    on_disk = settings.env != "local"

    if client.indices.exists(index=v2):
        log.info("index %s already exists", v2)
    else:
        client.indices.create(index=v2, body=papers_index_body(on_disk=on_disk))
        log.info("created index %s (on_disk=%s)", v2, on_disk)

    # exists_alias returns a clean bool; get_alias(ignore=[404]) returns a *truthy* 404
    # error-dict when the alias is absent, which silently skips creation (the original bug).
    if client.indices.exists_alias(name=_ALIAS):
        log.info("alias %s already exists", _ALIAS)
    else:
        client.indices.put_alias(index=v1, name=_ALIAS)
        log.info("created alias %s -> %s", _ALIAS, v1)
    return 0


def cutover(settings: IngestionSettings | None = None) -> int:
    """Atomically repoint the read alias from v1 to v2. Idempotent: only removes v1 from the
    alias if it is currently there, so re-running once already on v2 is a no-op."""
    settings = settings or IngestionSettings.from_env()
    client = _admin_client(settings)
    v1, v2 = settings.opensearch_index, settings.opensearch_index_v2

    actions: list[dict] = []
    existing = client.indices.get_alias(name=_ALIAS, ignore=[404])
    if isinstance(existing, dict) and v1 in existing:
        actions.append({"remove": {"index": v1, "alias": _ALIAS}})
    actions.append({"add": {"index": v2, "alias": _ALIAS}})
    client.indices.update_aliases(body={"actions": actions})
    log.info("alias %s -> %s", _ALIAS, v2)
    return 0


def backfill(settings: IngestionSettings | None = None) -> int:
    """Re-embed the full seed corpus with the v2 model into the v2 index (rate-limited).
    Idempotent: bulk_upsert is keyed by chunkId, so re-runs overwrite rather than duplicate.
    One bad paper is logged and skipped, never aborts the run."""
    settings = settings or IngestionSettings.from_env()
    model_id = settings.bedrock_model_id_v2
    index_name = settings.opensearch_index_v2
    if not model_id:
        raise SystemExit("DOCSURI_BEDROCK_MODEL_ID_V2 is required for backfill")

    from .adapters.arxiv import ArxivHttpSource
    from .config import CORPUS_END, CORPUS_SLICE_CATEGORIES, CORPUS_START
    from .domain.enums import JobKind
    from .domain.models import CategoryFilter, IngestionJob
    from .runtime import build_production_runtime

    arxiv = ArxivHttpSource(timeout_seconds=30.0)
    runtime = build_production_runtime(
        settings.model_copy(
            update={
                "bedrock_model_id": model_id,
                "bedrock_model_id_v2": None,
                "opensearch_index": index_name,
            }
        )
    )
    filter_ = CategoryFilter(
        categories=CORPUS_SLICE_CATEGORIES,
        updated_after=_window("DOCSURI_BACKFILL_START", CORPUS_START),
        updated_before=_window("DOCSURI_BACKFILL_END", CORPUS_END),
    )

    count = errors = 0
    for metadata in arxiv.harvest_seed(filter_):
        try:
            # Use the OAI harvest record directly. The old per-paper Atom id_list re-fetch
            # (export.arxiv.org/api/query) was redundant — OAI already returns full metadata —
            # and arXiv 429-rate-limited it, skipping ~all papers. OAI also keeps the license the
            # Atom feed drops, so the OA gate sees it without a restore step.
            runtime.pipeline.ingest_metadata(
                IngestionJob(
                    job_id=f"v4-backfill-{metadata.paper_id}",
                    kind=JobKind.SEED_REBUILD,
                    arxiv_ref=metadata.arxiv_ref,
                ),
                metadata,
            )
            count += 1
            log.info("[%d] backfilled %s", count, metadata.arxiv_ref)
        except Exception as exc:  # noqa: BLE001 — one bad paper must not abort the backfill
            errors += 1
            log.warning("FAILED %s: %s", metadata.arxiv_ref, exc)
        time.sleep(_BACKFILL_DELAY_SECONDS)
    log.info("backfill complete: %d indexed, %d failures", count, errors)
    return 0


def backfill_external(settings: IngestionSettings | None = None) -> int:
    """Enqueue a bounded SS/OpenAlex backfill over the run-scoped DOCSURI_BACKFILL_START/END
    window (defaults to CORPUS_START/END). arXiv is NOT re-harvested and no rebuild lock is taken
    — this only ENQUEUES source-record jobs; the live worker service drains them through
    GROBID->embed->index. Idempotent: canonical dedup + chunkId upsert make re-runs safe."""
    settings = settings or IngestionSettings.from_env()

    from .config import CORPUS_END, CORPUS_START
    from .runtime import build_production_runtime

    runtime = build_production_runtime(settings)
    since = _window("DOCSURI_BACKFILL_START", CORPUS_START)
    until = _window("DOCSURI_BACKFILL_END", CORPUS_END)
    queued = runtime.refresh.backfill_external_sources(since, until)
    log.info(
        "external backfill enqueued %d jobs [%s .. %s]", queued, since.date(), until.date()
    )
    return 0


_STEPS = {
    "provision": provision,
    "backfill": backfill,
    "backfill_external": backfill_external,
    "cutover": cutover,
    # Fast re-embed rebuild (reembed.py): provision -> (copy | reembed) -> finalize -> cutover.
    "reembed_provision": reembed_provision,
    "reembed_copy": reembed_copy,
    "reembed": reembed,
    "reembed_finalize": reembed_finalize,
    "reembed_cutover": reembed_cutover,
    # B3 full re-parse: raw_backfill (prime cache from bulk PDF) -> reembed_provision -> reparse
    # (cache-only -> offline index) -> reembed_finalize -> reembed_cutover.
    "raw_backfill": raw_backfill,
    "reparse": reparse,
}


def run_step(step: str, settings: IngestionSettings | None = None) -> int:
    """Dispatch a migration step by name. Raises SystemExit on an unknown step (before any
    network/logging side effect)."""
    fn = _STEPS.get(step)
    if fn is None:
        raise SystemExit(f"unknown migration step {step!r}; expected one of {sorted(_STEPS)}")
    configure_logging()
    log.info("running migration step: %s", step)
    return fn(settings)


def main(argv: list[str] | None = None) -> int:
    import sys

    args = argv if argv is not None else sys.argv[1:]
    if not args:
        raise SystemExit(f"usage: python -m docsuri_ingestion.migrate <{'|'.join(_STEPS)}>")
    return run_step(args[0])


if __name__ == "__main__":
    raise SystemExit(main())
