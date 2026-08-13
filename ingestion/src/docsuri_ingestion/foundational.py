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
making it politer. Expect roughly 3s per paper, so ~1.5 hours for 1,500.

FAILURES DO NOT STOP THE RUN. A paper that 404s or fails to parse is recorded and skipped; the
summary groups them by reason so a systematic failure (a whole bucket, a whole source) is
visible instead of being averaged into a success rate. Above ``MAX_FAILURE_RATIO`` the run
exits non-zero: unlike a date window, every id here was chosen because U12 needs it, so losing
many is a reason to stop rather than to proceed to the recent slice.

    python -m docsuri_ingestion.foundational --dry-run
    python -m docsuri_ingestion.foundational
    python -m docsuri_ingestion.foundational --bucket canon --limit 20
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import time
from collections import Counter

from .application import new_job_id
from .domain.enums import JobKind
from .domain.errors import PermanentIngestionError, RetriableIngestionError
from .domain.models import IngestionJob
from .observability import configure_logging
from .resilience import RetryPolicy, retry_with_policy
from .runtime import build_production_runtime
from .settings import IngestionSettings

_log = logging.getLogger("docsuri.ingestion.foundational")

DEFAULT_LIST = "reports/foundational-papers.tsv"
DEFAULT_LEDGER = ".cache/foundational-ingest.jsonl"

# A retriable error means the dependency asked us to come back, so one more try is worth it;
# beyond that the paper is recorded and the run moves on rather than stalling the other 1,499.
# ``retry_with_policy``'s default predicate already means "RetriableIngestionError only".
_RETRY = RetryPolicy(max_attempts=3, base_delay_seconds=10.0, factor=2.0, jitter_ratio=0.1)

MAX_FAILURE_RATIO = 0.10


def read_list(
    path: pathlib.Path, bucket: str | None = None, limit: int | None = None
) -> list[tuple[str, str]]:
    """(arxiv_id, bucket) rows, read by column NAME so the TSV can gain columns."""
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
    return rows[:limit] if limit else rows


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
        done[record["arxiv_id"]] = record["outcome"]
    return done


def pending(
    rows: list[tuple[str, str]], done: dict[str, str], *, retry_failed: bool
) -> list[tuple[str, str]]:
    """Rows still to do. A failed paper is retried only on request — re-running the list should
    not spend an hour re-attempting the same 404s every time."""
    return [
        (aid, bucket)
        for aid, bucket in rows
        if aid not in done or (retry_failed and done[aid].startswith("failed"))
    ]


def ingest_foundational(
    settings: IngestionSettings | None = None,
    *,
    list_path: str = DEFAULT_LIST,
    ledger_path: str = DEFAULT_LEDGER,
    bucket: str | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    dry_run: bool = False,
) -> int:
    rows = read_list(pathlib.Path(list_path), bucket, limit)
    ledger_file = pathlib.Path(ledger_path)
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    todo = pending(rows, load_ledger(ledger_file), retry_failed=retry_failed)
    _log.info("목록 %d편 · 완료 %d편 · 이번 실행 %d편", len(rows), len(rows) - len(todo), len(todo))
    if not todo:
        return 0

    if dry_run:
        # The runtime is NOT built here on purpose: this mode exists to exercise the list, the
        # ledger and the resume path without writing anything to whichever corpus is wired.
        for name, count in Counter(b for _, b in todo).most_common():
            _log.info("  %5d  %s", count, name)
        _log.info("예상 소요: 편당 약 3초 → 약 %d분", len(todo) * 3 // 60)
        return 0

    runtime = build_production_runtime(settings or IngestionSettings.from_env())
    counts: Counter[str] = Counter()
    started = time.monotonic()
    with ledger_file.open("a", encoding="utf-8") as ledger:
        for n, (arxiv_id, row_bucket) in enumerate(todo, 1):
            outcome = _ingest_one_paper(runtime, arxiv_id)
            counts[outcome] += 1
            ledger.write(
                json.dumps({"arxiv_id": arxiv_id, "bucket": row_bucket, "outcome": outcome}) + "\n"
            )
            ledger.flush()
            if n % 25 == 0 or n == len(todo):
                rate = (time.monotonic() - started) / n
                _log.info(
                    "  %d/%d  편당 %.1fs  남은 시간 약 %d분",
                    n, len(todo), rate, int((len(todo) - n) * rate // 60),
                )

    for outcome, count in counts.most_common():
        _log.info("  %5d  %s", count, outcome)
    failed = sum(c for o, c in counts.items() if o.startswith("failed"))
    ratio = failed / len(todo)
    _log.info("성공 %d편 · 실패 %d편 (%.1f%%)", len(todo) - failed, failed, ratio * 100)
    if ratio > MAX_FAILURE_RATIO:
        _log.error(
            "실패율 %.1f%%가 상한 %.0f%%를 넘었다 — 원인 확인 전에 다음 단계로 넘어가지 말 것",
            ratio * 100,
            MAX_FAILURE_RATIO * 100,
        )
        return 1
    return 0


def _ingest_one_paper(runtime, arxiv_id: str) -> str:
    """One paper's outcome as a ledger string. Never raises — one bad paper must not end the run."""

    def once() -> str:
        return runtime.pipeline.ingest_one(
            IngestionJob(
                job_id=new_job_id("foundational"), kind=JobKind.EVENT, arxiv_ref=arxiv_id
            )
        ).value

    try:
        return retry_with_policy(_RETRY, once)
    except RetriableIngestionError as exc:
        return f"failed:retriable:{exc.reason.value}"
    except PermanentIngestionError as exc:
        return f"failed:permanent:{exc.reason.value}"
    except Exception as exc:  # noqa: BLE001 — classify and continue
        return f"failed:unexpected:{type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    ap = argparse.ArgumentParser(prog="python -m docsuri_ingestion.foundational")
    ap.add_argument("--list", dest="list_path", default=DEFAULT_LIST)
    ap.add_argument("--ledger", dest="ledger_path", default=DEFAULT_LEDGER)
    ap.add_argument("--bucket", help="canon / cs.CL / cs.AI / cs.LG / cs.CV 중 하나만")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-failed", action="store_true", help="원장의 실패분을 다시 시도")
    ap.add_argument("--dry-run", action="store_true", help="목록·원장·재개만 확인, 수집 없음")
    args = ap.parse_args(argv)
    return ingest_foundational(
        list_path=args.list_path,
        ledger_path=args.ledger_path,
        bucket=args.bucket,
        limit=args.limit,
        retry_failed=args.retry_failed,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
