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
from collections import Counter

from .domain.ids import ArxivIdentifier, normalize_arxiv_ref
from .http_limits import is_pdf_payload
from .ports import RawContentStorePort
from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.raw_backfill")


def _identifier_from_member(name: str) -> ArxivIdentifier | None:
    """Paper id AND VERSION for an arXiv bulk-tar member (``2501.12345v2.pdf`` → 2501.12345 v2).

    The version is returned, not discarded, because the cache key carries one: this used to hand
    back the bare paper id, and the caller then wrote whatever bytes the tar held under the
    version the HARVEST wanted — so for a paper with several versions in the tar, whichever
    member the walk met LAST won the key, regardless of which one the harvest named. ``reparse``
    reads that cache exclusively (``raw_cache_mode=only``), so the wrong version's text and
    structure were indexed with nothing anywhere saying so. Matching the member's version to the
    target's makes the write deterministic.

    ``None`` for a directory, a non-PDF member, or a stem the id grammar does not accept. A member
    with no ``vN`` suffix reads as v1 and will simply not match a target on a later version, which
    is the fail-closed answer: arXiv's bulk tars name the version, so a bare stem is not something
    to guess about.
    """
    base = name.rsplit("/", 1)[-1]
    if not base.lower().endswith(".pdf"):
        return None
    try:
        return normalize_arxiv_ref(base[:-4])
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
    """Scratch directory for the bulk tar downloads (each is deleted as soon as it is drained)."""
    tmp = os.path.join(tempfile.gettempdir(), "docsuri-raw-backfill")
    os.makedirs(tmp, exist_ok=True)
    return tmp


def _wanted_months(settings: IngestionSettings) -> set[str]:
    raw = settings.raw_backfill_months
    return {m.strip() for m in raw.split(",") if m.strip()} if raw else set()


def _prime_from_tar(
    client,
    bucket: str,
    key: str,
    targets: dict[str, int],
    raw_store: RawContentStorePort,
    tmp_dir: str,
    skipped: Counter[str],
) -> set[str]:
    """Download one bulk tar (requester-pays) and cache every member PDF whose id is a target.

    Two things are refused rather than written, and both are counted into ``skipped`` so the run
    can say why a target went uncached instead of only that it did:

    * a member whose VERSION is not the one the harvest wants — the cache key is per version, so
      writing it would serve a different revision's bytes to every later cache-only reparse;
    * a member that is not a PDF by its magic bytes. Every READER of this cache checks that (the
      shared ``is_pdf_payload``, whose contract says "applied to cache reads as well as fetches"),
      and the one tool that WRITES the cache did not — so a poisoned entry read as a miss and the
      paper was excluded downstream with nothing pointing back to here.

    ``skipped`` is owned and reported by the caller — every Counter in this package is local to
    the function that reports it, and this one is no exception; it is passed in only because the
    refusals happen a level down.

    Returns the set of paperIds cached; the temp tar is deleted on block exit.
    """
    cached: set[str] = set()
    with tempfile.NamedTemporaryFile(dir=tmp_dir, suffix=".tar") as tf:
        client.download_fileobj(bucket, key, tf, ExtraArgs={"RequestPayer": "requester"})
        tf.flush()
        tf.seek(0)
        with tarfile.open(fileobj=tf) as tar:
            for member in tar:
                if not member.isfile():
                    continue
                identifier = _identifier_from_member(member.name)
                if identifier is None or identifier.paper_id not in targets:
                    continue
                wanted = targets[identifier.paper_id]
                if identifier.version != wanted:
                    # Counted ONLY when nothing for this paper has been cached yet. arXiv's bulk
                    # tars carry every version of a paper as its own member, and every harvest
                    # target is v1 (OAI ids are versionless), so a revised paper's v2+ members
                    # are the NORMAL shape — not a snapshot lagging the harvest. Counting them
                    # made a healthy run report hundreds of mismatches, which is exactly the
                    # signal this counter was added to distinguish. What it must explain is why
                    # a target ended up with NO cached bytes, so a member is a mismatch only
                    # while its paper is still uncached.
                    if identifier.paper_id not in cached:
                        skipped["version_mismatch"] += 1
                    continue
                fobj = tar.extractfile(member)
                if fobj is None:
                    continue
                data = fobj.read()
                if not is_pdf_payload(data):
                    skipped["not_pdf"] += 1
                    continue
                raw_store.put_raw(
                    identifier.paper_id, wanted, "pdf", data,
                    content_type="application/pdf",
                )
                cached.add(identifier.paper_id)
    return cached


def raw_backfill(settings: IngestionSettings | None = None) -> int:
    """Prime the raw-content cache from arXiv's requester-pays bulk PDFs (see module docstring).
    Idempotent: put_raw overwrites by key, so a re-run (or a re-scanned tar) just re-caches."""
    settings = settings or IngestionSettings.from_env()
    if not settings.s3_bucket:
        raise SystemExit("DOCSURI_S3_BUCKET is required for raw_backfill")

    from .adapters.arxiv import ArxivHttpSource
    from .adapters.aws import S3RawContentStore, build_s3_client
    from .config import CORPUS_END, CORPUS_SLICE_CATEGORIES, CORPUS_START
    from .domain.models import CategoryFilter

    arxiv = ArxivHttpSource(timeout_seconds=30.0)
    window_start, window_end = settings.backfill_window(CORPUS_START, CORPUS_END)
    filter_ = CategoryFilter(
        categories=CORPUS_SLICE_CATEGORIES,
        updated_after=window_start,
        updated_before=window_end,
    )
    # Target set keyed by versionless paperId → its canonical version for the cache key.
    targets: dict[str, int] = {
        metadata.paper_id: metadata.version for metadata in arxiv.harvest_seed(filter_)
    }
    months = _wanted_months(settings)
    if months:
        targets = {
            pid: version
            for pid, version in targets.items()
            if _yymm_from_paper_id(pid) in months
        }
    log.info("raw_backfill targets: %d papers (months=%s)", len(targets), sorted(months) or "all")

    # One client for the raw store and the bulk-bucket reads alike — the reason the factory
    # exists, applied here too (this site built two while calling the factory for one of them).
    client = build_s3_client()
    raw_store = S3RawContentStore(
        bucket=settings.s3_bucket,
        prefix=settings.raw_cache_prefix,
        kms_key_id=settings.asset_kms_key_id,
        client=client,
    )
    bucket = settings.arxiv_bulk_bucket
    tmp_dir = _tmp_dir()

    tars_processed = 0
    cached_ids: set[str] = set()
    # Why each uncached target was refused. Without it ``pdfs_cached`` is the only number the run
    # reports, and a systematic fault — a snapshot a revision behind the harvest, a tar of landing
    # pages — is indistinguishable from "those papers were not in these months".
    skipped: Counter[str] = Counter()
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
                cached_ids |= _prime_from_tar(
                    client, bucket, key, targets, raw_store, tmp_dir, skipped
                )
            except Exception as exc:  # noqa: BLE001 — one bad tar must not abort the prime
                # Counted, not just logged: without it the reason breakdown below does not add up
                # to the missed targets, and a run whose tars are systematically unreadable looks
                # the same as one whose papers were simply in other months.
                skipped["tar_failed"] += 1
                log.warning("FAILED tar %s: %s", key, exc)
            tars_processed += 1
            log.info(
                "tars=%d pdfs_cached=%d targets_missed=%d",
                tars_processed,
                len(cached_ids),
                len(targets) - len(cached_ids),
            )
    log.info(
        "raw_backfill complete: %d tars, %d pdfs cached, %d targets missed"
        " (version_mismatch=%d, not_pdf=%d, tar_failed=%d)",
        tars_processed,
        len(cached_ids),
        len(targets) - len(cached_ids),
        skipped["version_mismatch"],
        skipped["not_pdf"],
        skipped["tar_failed"],
    )
    return 0
