"""B3 bulk-PDF cache prime: seed the raw-content cache from arXiv's requester-pays bulk PDFs.

A full re-parse (reparse.py) reads source bytes CACHE-ONLY so it never hits arXiv's 1-req/3s
limit. This step fills that cache in bulk: it harvests the corpus target set (paperId, version)
from OAI-PMH, then streams arXiv's ``s3://arxiv/pdf/`` bulk tarballs (requester-pays), extracting
only the PDFs whose id is in the target set into ``S3RawContentStore`` under the ``pdf`` tier.

Run as a one-off ECS task through the worker entrypoint like migrate.py, sharded by submission
month (DOCSURI_RAW_BACKFILL_MONTHS) to bound each task's tar scan:

    python -m docsuri_ingestion.worker raw_backfill
"""

from __future__ import annotations

import logging
import os
import tarfile
import tempfile

from .domain.ids import normalize_arxiv_ref
from .ports import RawContentStorePort
from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.raw_backfill")


def _paper_id_from_member(name: str) -> str | None:
    """Paper-id stem for an arXiv bulk-tar member: basename minus ``.pdf`` and any ``vN`` suffix
    (``2501.12345v2.pdf`` → ``2501.12345``). ``None`` for a directory or non-PDF member."""
    base = name.rsplit("/", 1)[-1]
    if not base.lower().endswith(".pdf"):
        return None
    try:
        return normalize_arxiv_ref(base[:-4]).paper_id
    except ValueError:
        return None


def _yymm_from_paper_id(paper_id: str) -> str | None:
    """Submission-month shard ("2501") of a new-style arXiv id ("2501.12345"); ``None`` for
    anything that isn't the ``YYMM.NNNNN`` new-style form (old-style ids carry no month shard)."""
    head, dot, _rest = paper_id.partition(".")
    if dot and len(head) == 4 and head.isdigit():
        return head
    return None


def _tmp_dir() -> str:
    job_dir = os.getenv("CLAUDE_JOB_DIR")
    tmp = os.path.join(job_dir, "tmp") if job_dir else tempfile.gettempdir()
    os.makedirs(tmp, exist_ok=True)
    return tmp


def _wanted_months(settings: IngestionSettings) -> set[str]:
    raw = settings.raw_backfill_months
    return {m.strip() for m in raw.split(",") if m.strip()} if raw else set()


def _prime_from_tar(
    client,
    bucket: str,
    key: str,
    targets: dict[str, tuple[str, int]],
    raw_store: RawContentStorePort,
    tmp_dir: str,
) -> set[str]:
    """Download one bulk tar (requester-pays) and cache every member PDF whose id is a target.
    Returns the set of paperIds cached from this tar; the temp tar is deleted on block exit."""
    cached: set[str] = set()
    with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".tar") as tf:
        client.download_fileobj(bucket, key, tf, ExtraArgs={"RequestPayer": "requester"})
        tf.flush()
        tf.seek(0)
        with tarfile.open(fileobj=tf) as tar:
            for member in tar:
                if not member.isfile():
                    continue
                pid = _paper_id_from_member(member.name)
                if pid is None or pid not in targets:
                    continue
                fobj = tar.extractfile(member)
                if fobj is None:
                    continue
                target_pid, target_ver = targets[pid]
                raw_store.put_raw(
                    target_pid, target_ver, "pdf", fobj.read(),
                    content_type="application/pdf",
                )
                cached.add(pid)
    return cached


def raw_backfill(settings: IngestionSettings | None = None) -> int:
    """Prime the raw-content cache from arXiv's requester-pays bulk PDFs (see module docstring).
    Idempotent: put_raw overwrites by key, so a re-run (or a re-scanned tar) just re-caches."""
    settings = settings or IngestionSettings.from_env()
    if not settings.s3_bucket:
        raise SystemExit("DOCSURI_S3_BUCKET is required for raw_backfill")

    import boto3

    from .adapters.arxiv import ArxivHttpSource
    from .adapters.aws import S3RawContentStore
    from .config import CORPUS_END, CORPUS_SLICE_CATEGORIES, CORPUS_START
    from .domain.models import CategoryFilter
    from .migrate import _window

    arxiv = ArxivHttpSource(timeout_seconds=30.0)
    filter_ = CategoryFilter(
        categories=CORPUS_SLICE_CATEGORIES,
        updated_after=_window("DOCSURI_BACKFILL_START", CORPUS_START),
        updated_before=_window("DOCSURI_BACKFILL_END", CORPUS_END),
    )
    # Target set keyed by versionless paperId → its canonical (paperId, version) for the cache key.
    targets: dict[str, tuple[str, int]] = {
        metadata.paper_id: (metadata.paper_id, metadata.version)
        for metadata in arxiv.harvest_seed(filter_)
    }
    months = _wanted_months(settings)
    if months:
        targets = {pid: pv for pid, pv in targets.items() if _yymm_from_paper_id(pid) in months}
    log.info("raw_backfill targets: %d papers (months=%s)", len(targets), sorted(months) or "all")

    raw_store = S3RawContentStore(
        bucket=settings.s3_bucket,
        prefix=settings.raw_cache_prefix,
        kms_key_id=settings.asset_kms_key_id,
    )
    client = boto3.client("s3")
    bucket = settings.arxiv_bulk_bucket
    tmp_dir = _tmp_dir()

    tars_processed = 0
    cached_ids: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix="pdf/", RequestPayer="requester"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # arXiv bulk tars are named by submission month, e.g. pdf/arXiv_pdf_2501_001.tar.
            if not key.endswith(".tar"):
                continue
            if months and not any(f"_{m}_" in key for m in months):
                continue
            try:
                cached_ids |= _prime_from_tar(client, bucket, key, targets, raw_store, tmp_dir)
            except Exception as exc:  # noqa: BLE001 — one bad tar must not abort the prime
                log.warning("FAILED tar %s: %s", key, exc)
            tars_processed += 1
            log.info(
                "tars=%d pdfs_cached=%d targets_missed=%d",
                tars_processed,
                len(cached_ids),
                len(targets) - len(cached_ids),
            )
    log.info(
        "raw_backfill complete: %d tars, %d pdfs cached, %d targets missed",
        tars_processed,
        len(cached_ids),
        len(targets) - len(cached_ids),
    )
    return 0
