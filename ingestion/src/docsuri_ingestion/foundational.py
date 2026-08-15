"""Ingest the named foundational papers listed in ``reports/foundational-papers.tsv``.

WHY THIS EXISTS. The corpus is harvested by DATE WINDOW, and a date window structurally misses
the papers everyone cites. Measured on the local development corpus (29,915 papers, 2025=68% /
2024=23%): of ten representative foundational papers only Transformer was present — BERT, GPT-3,
LLaMA, RAG, ResNet, InstructGPT, Chain-of-Thought, LoRA and Bahdanau attention were all absent.
The pre-2023 tail that does exist (~1,300 papers) is not the canon; it is arbitrary old papers
whose v2/v3 revision happened to land inside the window. Growing the window does not fix it, so
the list is named explicitly and fed in here.

WHY NOT ``trigger_full_rebuild``. That path harvests by ``CategoryFilter`` — categories plus a
date window — and there is no way to hand it an explicit set of ids. These papers exist because
a date window cannot reach them, so they go in one at a time through ``ingest_one`` instead.

WHY NOT the ``ingest-one`` CLI in a shell loop. It rebuilds the whole runtime per invocation,
and a failure anywhere loses the run. This builds the runtime once and keeps an append-only
resume ledger, so an interrupted run costs only the papers it had not reached.

RATE LIMITING IS NOT DONE HERE. The arXiv adapter holds a ``TokenBucket(0.33/s)`` — arXiv's
stated politeness budget — and a second sleep on top would only make the run slower without
making it politer. MEASURED 14.0s per paper on the 20-paper trial (2026-08-14), so ~5.8 hours for
1,500 — the earlier "3s per paper" was the rate limiter's floor, not the pipeline's cost: parse,
asset rendering, embedding and indexing all sit on top of the fetch.

ONE PAPER'S FAILURE DOES NOT STOP THE RUN; A COLLAPSE DOES. A paper that 404s or fails to parse
is recorded and skipped, and the summary groups them by reason so a systematic failure (a whole
bucket, a whole source) is visible instead of being averaged into a success rate. Two gates sit
on top, and they measure different things. ``CONSECUTIVE_FAILURE_LIMIT`` (a dead dependency) and
``RECENT_FAILURE_LIMIT`` (a throttle) abort a run that is already collapsing — "something is
broken right now". ``MAX_FAILURE_RATIO`` judges the finished run on PERMANENT loss only — "how
much of this list is gone for good" — because a retriable failure is deferred to the next
``--retry-failed``, not lost. All exit non-zero: unlike a date window, every id here was chosen
because U12 needs it, so losing many is a reason to stop rather than proceed to the recent slice.

    python -m docsuri_ingestion.foundational --dry-run
    python -m docsuri_ingestion.foundational
    python -m docsuri_ingestion.foundational --bucket canon --limit 20
"""

from __future__ import annotations

import json
import logging
import pathlib
import sys
import time
from collections import Counter, deque
from collections.abc import Collection

from .application import new_job_id
from .domain.enums import JobKind
from .domain.errors import PermanentIngestionError, RetriableIngestionError
from .domain.models import IngestionJob
from .runtime import build_production_runtime, preflight_dependencies
from .settings import IngestionSettings

_log = logging.getLogger("docsuri.ingestion.foundational")

# Anchored to the repo root, NOT the CWD. CWD-relative defaults made "run it from anywhere
# else" fail in the worst way available: the list read errors loudly, but the ledger path is
# CREATED wherever you happen to stand — an empty ledger, which silently discards all resume
# state and re-ingests 1,500 papers. (An installed wheel has no repo root; pass explicit paths
# there.)
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
DEFAULT_LIST = str(_REPO_ROOT / "reports" / "foundational-papers.tsv")
DEFAULT_LEDGER = str(_REPO_ROOT / ".cache" / "foundational-ingest.jsonl")

MAX_FAILURE_RATIO = 0.10

# In-flight abort. ``MAX_FAILURE_RATIO`` only judges at the END of a run, which is too late to be
# useful: when Bedrock's daily token quota ran out mid-batch (2026-08-14) the reach rate fell from
# 95% to 15% and the run kept going for five and a half hours, fetching from arXiv and rendering
# page crops for 490 papers that then died at the embed step. Nothing was indexed and every one of
# them was written to the ledger as `failed`, so recovering them costs the parse a second time.
#
# A ROLLING WINDOW, not a consecutive-failure counter: that throttle still let ~15% through, and a
# consecutive counter resets on every one of those, so it would never have fired.
#
# Not split by failure reason on purpose — embed, GROBID or arXiv, "more than half of the last 50
# papers are dying" is the same call either way.
RECENT_WINDOW = 50
RECENT_FAILURE_LIMIT = 0.6

# The window above is tuned for a PARTIAL collapse (a throttle letting some through) and is far too
# slow for a TOTAL one. When the Postgres container died mid-run (2026-08-15, a Docker daemon
# restart took all six containers down at once) every paper failed instantly, and the window would
# have burned 50 of them before judging. A dead dependency needs no sample: nothing has succeeded
# at all, so there is nothing to average.
#
# Deliberately larger than one metadata chunk's worth of transient noise but far below the window:
# a genuine run has never produced this many consecutive failures, because the reasons that fail
# a single paper (404, no ar5iv build, a blocked licence) are independent of each other.
CONSECUTIVE_FAILURE_LIMIT = 12

# Papers per bulk metadata request. Matches the arXiv adapter's own ``id_list`` batch size, so a
# chunk here is exactly one request there.
METADATA_CHUNK = 100


def read_list(path: pathlib.Path, bucket: str | None = None) -> list[tuple[str, str]]:
    """(arxiv_id, bucket) rows, read by column NAME so the TSV can gain columns.

    No ``limit`` here on purpose: a limit applied before the ledger filter pins every run to the
    same first N rows, so a chunked ingest can never advance past them. The caller slices the
    PENDING list instead.
    """
    rows: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        i_id, i_bucket = header.index("arxiv_id"), header.index("bucket")
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) <= max(i_id, i_bucket):
                continue
            if bucket and parts[i_bucket] != bucket:
                continue
            rows.append((parts[i_id], parts[i_bucket]))
    return rows


def load_ledger(path: pathlib.Path) -> dict[str, str]:
    """arxiv_id -> outcome, from every prior run. Append-only so a crash cannot corrupt it."""
    done: dict[str, str] = {}
    if not path.exists():
        return done
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        # Valid JSON of the wrong shape (a hand-edited line, a partial write that still parses)
        # must cost that line, not the whole resume record.
        if isinstance(record, dict) and record.get("arxiv_id") and record.get("outcome"):
            done[str(record["arxiv_id"])] = str(record["outcome"])
    return done


def read_redo(path: pathlib.Path) -> frozenset[str]:
    """arXiv ids to re-INGEST even though the ledger says they succeeded, one per line.

    FOR PARSER CHANGES ONLY — not for a chunker or embedding change. Measured (2026-08-15): the
    217 papers truncated by the old chunk cap were fed back through here and every one returned
    DUPLICATE. That is correct behaviour, not a bug: ``ingest_one``'s dedup compares the PAPER's
    fingerprint, the paper did not change, and re-fetching and re-parsing it would produce the
    identical doc-model. What changed was our chunker.

    Re-chunking or re-embedding a stored doc-model is a REINDEX, and the tool for it is
    ``tools/local/reindex_docmodels.py --ids <file>`` — no arXiv fetch, no GROBID, no Docling.
    This flag is for the case where the doc-model itself is stale.

    The ledger is append-only so a crash cannot corrupt it, which is why this exists at all:
    hand-deleting rows to force a re-run puts the whole resume record one slip away from loss.
    """
    return frozenset(
        candidate
        for line in path.read_text(encoding="utf-8").splitlines()
        if (candidate := line.split("#", 1)[0].strip())
    )


def failure_stage(outcome: str) -> str:
    """The stage a recorded failure died at, or "" for a success or an older stage-less row.

    Outcomes are ``failed:<class>:<reason>:<stage>``; rows written before the stage was recorded
    simply have no fourth field and are never filtered out by it — an unknown stage must not be
    silently treated as a skippable one.
    """
    parts = outcome.split(":")
    return parts[3] if len(parts) > 3 else ""


def pending(
    rows: list[tuple[str, str]],
    done: dict[str, str],
    *,
    retry_failed: bool,
    redo: frozenset[str] = frozenset(),
    skip_stages: frozenset[str] = frozenset(),
) -> list[tuple[str, str]]:
    """Rows still to do. A failed paper is retried only on request — re-running the list should
    not spend an hour re-attempting the same 404s every time.

    ``redo`` forces ids back in regardless of their recorded outcome (see ``read_redo``).
    ``skip_stages`` holds a failure back: a paper that died at a stage whose dependency is
    deliberately down would only fail again, wasting its fetch and parse and pushing the run
    toward the collapse gate for a reason that is not a fault.
    """

    def wanted(aid: str) -> bool:
        if aid in redo or aid not in done:
            return True
        outcome = done[aid]
        if not (retry_failed and outcome.startswith("failed")):
            return False
        return failure_stage(outcome) not in skip_stages

    return [(aid, bucket) for aid, bucket in rows if wanted(aid)]


def ingest_foundational(
    settings: IngestionSettings | None = None,
    *,
    runtime=None,
    list_path: str = DEFAULT_LIST,
    ledger_path: str = DEFAULT_LEDGER,
    bucket: str | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    redo_path: str | None = None,
    skip_stages: Collection[str] = (),
    preflight: bool = False,
    dry_run: bool = False,
) -> int:
    rows = read_list(pathlib.Path(list_path), bucket)
    ledger_file = pathlib.Path(ledger_path)
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    redo = read_redo(pathlib.Path(redo_path)) if redo_path else frozenset()
    if redo:
        _log.info("재수집 지정 %d편 (원장 결과와 무관하게 다시 돈다)", len(redo))
    skipped = frozenset(skip_stages)
    done = load_ledger(ledger_file)
    remaining = pending(rows, done, retry_failed=retry_failed, redo=redo, skip_stages=skipped)
    if skipped:
        # Tally what each named stage actually held back. There is no stage vocabulary to
        # validate against (stages are free-form strings across the pipeline), so a typo'd
        # --skip-stage would otherwise be accepted, logged, and silently hold back nothing —
        # sending the run straight back into the papers it was meant to avoid.
        held = Counter(
            failure_stage(done[aid])
            for aid, _ in rows
            if aid in done
            and done[aid].startswith("failed")
            and failure_stage(done[aid]) in skipped
        )
        for stage in sorted(skipped):
            if held.get(stage):
                _log.info("재시도 제외: %s 단계 %d편", stage, held[stage])
            else:
                _log.warning(
                    "--skip-stage %s: 일치하는 실패가 0편 — 단계 이름 오타이거나 이미 처리됨", stage
                )
    if redo_path and not redo:
        _log.warning("--redo %s: 지정된 id가 0개 — 전부 주석이거나 빈 파일", redo_path)
    # Sliced AFTER the ledger filter, so successive --limit N runs advance through the list
    # instead of re-reading the same first N rows forever. `is not None`, not truthiness:
    # --limit 0 means "do nothing", not "do everything".
    todo = remaining[:limit] if limit is not None else remaining
    # Counted off `remaining`, not `todo`: subtracting the limited slice reported the papers this
    # run merely deferred as "완료", which reads as resume progress that has not happened.
    _log.info(
        "목록 %d편 · 완료 %d편 · 남음 %d편 · 이번 실행 %d편",
        len(rows),
        len(rows) - len(remaining),
        len(remaining),
        len(todo),
    )
    if not todo:
        return 0

    if dry_run:
        # The runtime is NOT built here on purpose: this mode exists to exercise the list, the
        # ledger and the resume path without writing anything to whichever corpus is wired.
        for name, count in Counter(b for _, b in todo).most_common():
            _log.info("  %5d  %s", count, name)
        _log.info("예상 소요: 편당 약 14초(실측) → 약 %d분", len(todo) * 14 // 60)
        return 0

    if runtime is None:
        # The `python -m` path builds its own; the CLI passes one in so --local is honoured.
        runtime = build_production_runtime(settings or IngestionSettings.from_env())

    if preflight:
        # AFTER the `todo` check above, not before: a resumed run whose ledger is already complete
        # (or `--limit 0`) would otherwise pay a billed embed call and a GROBID timeout to learn it
        # has nothing to do. GROBID is probed separately by the caller, before the runtime is built.
        preflight_dependencies(
            runtime, settings or IngestionSettings.from_env(), sources=("ARXIV",)
        )

    counts: Counter[str] = Counter()
    started = time.monotonic()
    n = 0
    # Rolling outcome window feeding the in-flight abort below.
    recent: deque[bool] = deque(maxlen=RECENT_WINDOW)
    with ledger_file.open("a", encoding="utf-8") as ledger:
        # Chunked, not prefetched-all-at-once. The metadata itself is one request per chunk, but
        # the licence enrichment behind it is still one request per paper, so prefetching all
        # 1,500 would spend over an hour before the first paper was written — and lose the lot on
        # a crash, because the ledger only advances as papers finish. A chunk at a time keeps the
        # resume ledger moving while still collapsing 1,500 metadata requests into ~15.
        for offset in range(0, len(todo), METADATA_CHUNK):
            chunk = todo[offset : offset + METADATA_CHUNK]
            metadata_by_id = _batch_metadata(runtime, [aid for aid, _ in chunk])
            for arxiv_id, row_bucket in chunk:
                n += 1
                # .get, not [] — a paper absent from the batch (withdrawn, mistyped, a failed
                # chunk) falls back to ingest_one's own fetch rather than being skipped.
                outcome = _ingest_one_paper(runtime, arxiv_id, metadata_by_id.get(arxiv_id))
                counts[outcome] += 1
                ledger.write(
                    json.dumps({"arxiv_id": arxiv_id, "bucket": row_bucket, "outcome": outcome})
                    + "\n"
                )
                ledger.flush()
                # Only non-deterministic failures count toward the collapse gates. A permanent
                # failure (404, NON_OA, no ar5iv build) is a property of the PAPER, not evidence
                # about a dependency — and a --retry-failed set is dense in exactly those, so
                # counting them aborted a retry run on its 12th paper and then advised the very
                # command that reproduces the abort.
                recent.append(
                    outcome.startswith("failed") and not outcome.startswith("failed:permanent")
                )
                if n % 25 == 0 or n == len(todo):
                    rate = (time.monotonic() - started) / n
                    _log.info(
                        "  %d/%d  편당 %.1fs  남은 시간 약 %d분",
                        n,
                        len(todo),
                        rate,
                        int((len(todo) - n) * rate // 60),
                    )
                collapse = _recently_collapsed(recent)
                if collapse:
                    # Returning from inside the `with` closes the ledger exactly as falling out of
                    # it would, and every row is flushed as it is written — so the abort needs no
                    # flag threaded back through two loops.
                    _log.error("%s — 계속 돌아도 색인이 안 남는다. 중단한다.", collapse)
                    _log_outcomes(counts)
                    _log.error(
                        "%d/%d편에서 중단됨. 원인을 고친 뒤 --retry-failed로 재개하면 이어서 간다.",
                        n,
                        len(todo),
                    )
                    return 1

    _log_outcomes(counts)
    # LOST vs DEFERRED. The gate asks "how much of this list is gone for good", because the whole
    # reason the list exists is that U12 needs these specific papers — so permanent losses (a
    # blocked licence, a withdrawn id) are what it measures.
    #
    # Retriable and unexpected failures are DEFERRED, not lost: `--retry-failed` gets them on a
    # later pass. Counting them made the gate fire on a run whose 28 failures were 20 papers
    # waiting on a GROBID the operator had deliberately taken down plus 8 genuine licence
    # exclusions — a 19% "loss" that was really 5.4%. A gate that cries wolf is a gate nobody
    # reads. The in-flight gates above are what catch a dependency dying mid-run; this one is
    # about coverage.
    lost = sum(c for o, c in counts.items() if o.startswith("failed:permanent"))
    deferred = sum(
        c
        for o, c in counts.items()
        if o.startswith("failed") and not o.startswith("failed:permanent")
    )
    ratio = lost / len(todo)
    _log.info(
        "성공 %d편 · 영구 손실 %d편 (%.1f%%) · 재시도 대상 %d편",
        len(todo) - lost - deferred,
        lost,
        ratio * 100,
        deferred,
    )
    if ratio > MAX_FAILURE_RATIO:
        _log.error(
            "영구 손실 %.1f%%가 상한 %.0f%%를 넘었다 — 원인 확인 전에 다음 단계로 넘어가지 말 것",
            ratio * 100,
            MAX_FAILURE_RATIO * 100,
        )
        return 1
    return 0


def _log_outcomes(counts: Counter[str]) -> None:
    """Every outcome, never a truncated head. The aborted run is precisely the one whose reason
    breakdown matters, and it used to print only the top six."""
    for outcome, count in counts.most_common():
        _log.info("  %5d  %s", count, outcome)


def _recently_collapsed(recent: deque[bool]) -> str | None:
    """Why the run should stop now, or None to carry on. Two thresholds, two failure shapes.

    TOTAL collapse — every recent paper failed. A dead dependency needs no sample: nothing has
    succeeded, so there is nothing to average, and waiting for the window below would burn 50
    papers to learn what 12 already said.

    PARTIAL collapse — a majority failed but not all, which is what a throttle looks like. This
    one DOES need the full window, because the opening papers of a run are a poor sample and an
    early cluster of 404s must not abort a healthy batch.
    """
    if len(recent) >= CONSECUTIVE_FAILURE_LIMIT and all(list(recent)[-CONSECUTIVE_FAILURE_LIMIT:]):
        return f"최근 {CONSECUTIVE_FAILURE_LIMIT}편 연속 실패 — 의존성이 죽은 것으로 본다"
    if len(recent) == recent.maxlen and sum(recent) / len(recent) > RECENT_FAILURE_LIMIT:
        return f"최근 {len(recent)}편 중 {sum(recent)}편 실패"
    return None


def _batch_metadata(runtime, arxiv_ids: list[str]) -> dict[str, object]:
    """Bulk metadata for one chunk, keyed by bare paper id. Never raises: this is a prefetch, and
    an empty result just means every paper in the chunk fetches its own the way it used to.

    The COVERAGE is logged, not just the failures. Falling back is invisible from the outside —
    the run still succeeds, it just spends 15x the arXiv requests and eventually gets throttled
    off the source — so an unattended 1,500-paper run must say how many papers the batch actually
    covered rather than only speaking up when it raised.
    """
    arxiv = getattr(runtime, "arxiv", None)
    if arxiv is None or not hasattr(arxiv, "fetch_metadata_batch"):
        return {}
    try:
        found = arxiv.fetch_metadata_batch(arxiv_ids)
    except Exception as exc:  # noqa: BLE001 — fall back to per-paper fetch
        _log.warning(
            "메타데이터 일괄 조회 실패(%s) — %d편 논문별 조회", type(exc).__name__, len(arxiv_ids)
        )
        return {}
    _log.info("메타데이터 일괄 조회 %d/%d편", len(found), len(arxiv_ids))
    return found


def _ingest_one_paper(runtime, arxiv_id: str, metadata=None) -> str:
    """One paper's outcome as a ledger string. Never raises — one bad paper must not end the run.

    NO retry here, deliberately. ``ingest_one`` already owns retry: every dependency call inside
    it goes through ``IngestionResilienceService.dependency_call`` — up to 5 attempts with
    backoff, behind a circuit breaker. An outer retry layer multiplied that (3 x 5 = 15 attempts
    against a dead dependency) and, worse, re-ran the WHOLE pipeline from the metadata fetch,
    hammering a breaker that had just opened. A RetriableIngestionError surfacing here means the
    inner retries are already exhausted; the ledger records it and ``--retry-failed`` on a later
    run is the second chance.

    THE STAGE IS PART OF THE OUTCOME. Without it every dependency failure reads the same, and
    ``--retry-failed`` cannot tell "died on the embed quota, which is back now" from "died on
    GROBID, which is still deliberately down" — so a retry run re-fetches and re-parses papers
    that are certain to fail again, and a long enough run of them trips the collapse gate for a
    dependency nobody expected to be up.
    """
    try:
        return runtime.pipeline.ingest_one(
            IngestionJob(
                job_id=new_job_id("foundational"),
                kind=JobKind.EVENT,
                arxiv_ref=arxiv_id,
                # Pre-fetched in bulk. ``ingest_one`` skips its own per-paper metadata request
                # when this is present — the path the harvest already uses.
                arxiv_metadata=metadata.to_payload() if metadata is not None else None,
            )
        ).value
    except RetriableIngestionError as exc:
        return f"failed:retriable:{exc.reason.value}:{exc.stage}"
    except PermanentIngestionError as exc:
        return f"failed:permanent:{exc.reason.value}:{exc.stage}"
    except Exception as exc:  # noqa: BLE001 — classify and continue
        return f"failed:unexpected:{type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    """Delegate to the real CLI so this entry point cannot drift from it.

    It used to re-declare every flag and call ``ingest_foundational`` directly, which meant the
    documented ``python -m`` path silently skipped the pre-flight checks and ``--local`` — and the
    two copies of ``--redo``'s help text had already diverged.

    ``--local`` is hoisted in front of the subcommand: the CLI declares it on the TOP-LEVEL parser
    (before ``add_subparsers``), so left in place it would reach the subparser and exit 2 — and an
    operator who then drops the flag gets a live run against the real corpus.
    """
    from .cli import main as cli_main

    raw = list(argv) if argv is not None else sys.argv[1:]
    local = [flag for flag in raw if flag == "--local"]
    rest = [flag for flag in raw if flag != "--local"]
    return cli_main([*local[:1], "ingest-foundational", *rest])


if __name__ == "__main__":
    raise SystemExit(main())
