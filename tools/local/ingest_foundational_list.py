"""Ingest the named foundational papers (``reports/foundational-papers.tsv``) one by one.

WHY A DRIVER AND NOT THE REBUILD PATH. ``trigger_full_rebuild`` harvests by CategoryFilter —
categories plus a date window — and there is no way to hand it an explicit list of ids. The
foundational papers exist precisely because a date window cannot reach them (measured: of ten
representative foundational papers only Transformer was inside the local corpus), so they have
to go in through the single-paper entry point instead.

``docsuri-ingestion ingest-one --arxiv-ref X`` already does the whole pipeline for one paper —
fetch, dedup, doc-model, assets, chunk, embed, index. What it does not do is survive 1,500
papers: it rebuilds the runtime per invocation, and a failure anywhere loses the run. This
driver builds the runtime once and keeps a resume ledger, so an interrupted run costs only the
papers it had not reached.

RATE LIMITING IS NOT DONE HERE. The arXiv adapter holds a ``TokenBucket(0.33/s)`` — arXiv's
stated politeness budget — and adding a second sleep on top would only make the run slower
without making it politer. Expect roughly 3s per paper, so ~1.5 hours for 1,500.

FAILURES DO NOT STOP THE RUN. A paper that 404s or fails to parse is recorded and skipped; the
summary groups them by reason so a systematic failure (all of one year, all of one source) is
visible instead of being averaged into a success rate.

Usage (다른 tools/local 도구와 같은 관례 — 패키지 환경 안에서 돌린다):
    # 목록·원장·재개만 확인, 실제 수집 없음
    uv run --project ingestion python tools/local/ingest_foundational_list.py --dry-run

    # 목록 전체 (약 1.5시간)
    uv run --project ingestion python tools/local/ingest_foundational_list.py

    # 한 계층만 / 중단 후 재개(기본 동작 — 원장에 있는 것은 건너뛴다)
    uv run --project ingestion python tools/local/ingest_foundational_list.py --bucket canon
"""

from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys
import time

from docsuri_ingestion.application import new_job_id
from docsuri_ingestion.domain.enums import JobKind
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.observability import configure_logging
from docsuri_ingestion.runtime import build_production_runtime
from docsuri_ingestion.settings import IngestionSettings

DEFAULT_LIST = "reports/foundational-papers.tsv"
DEFAULT_LEDGER = ".cache/foundational-ingest.jsonl"
# A retriable error means the dependency asked us to come back, so one more try is worth it;
# beyond that the paper is recorded and the run moves on rather than stalling the other 1,499.
RETRIES = 2
RETRY_SLEEP = 10.0


def read_list(path: pathlib.Path, bucket: str | None, limit: int | None) -> list[tuple[str, str]]:
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
            rec = json.loads(line)
        except ValueError:
            continue
        done[rec["arxiv_id"]] = rec["outcome"]
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default=DEFAULT_LIST)
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--bucket", help="canon / cs.CL / cs.AI / cs.LG / cs.CV 중 하나만")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-failed", action="store_true", help="원장의 실패분을 다시 시도")
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="목록 읽기·원장·재개만 확인하고 실제 수집은 하지 않는다(런타임도 구성하지 않음)",
    )
    args = ap.parse_args()

    configure_logging()
    rows = read_list(pathlib.Path(args.list), args.bucket, args.limit)
    ledger_path = pathlib.Path(args.ledger)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    done = load_ledger(ledger_path)

    def already(aid: str) -> bool:
        outcome = done.get(aid)
        if outcome is None:
            return False
        # A failed paper is retried only on request: re-running the whole list should not spend
        # an hour re-attempting the 404s every time.
        return not (args.retry_failed and outcome.startswith("failed"))

    todo = [(a, b) for a, b in rows if not already(a)]
    print(f"목록 {len(rows)}편 · 완료 {len(rows) - len(todo)}편 · 이번 실행 {len(todo)}편")
    if not todo:
        return 0

    if args.dry_run:
        # The runtime is NOT built here on purpose: this mode exists to exercise the list, the
        # ledger and the resume path while the environment still points at the local development
        # corpus, where a real ingest would write papers that do not belong to it.
        by_bucket: collections.Counter = collections.Counter(b for _, b in todo)
        print("dry-run — 실제 수집 없음")
        for bucket, c in by_bucket.most_common():
            print(f"  {c:5d}  {bucket}")
        print(f"\n예상 소요: 편당 약 3초 → 약 {len(todo) * 3 / 60:.0f}분")
        return 0

    settings = IngestionSettings.from_env()
    runtime = build_production_runtime(settings)

    counts: collections.Counter = collections.Counter()
    started = time.monotonic()
    with ledger_path.open("a", encoding="utf-8") as ledger:
        for n, (aid, bucket) in enumerate(todo, 1):
            outcome = "?"
            for attempt in range(RETRIES + 1):
                try:
                    decision = runtime.pipeline.ingest_one(
                        IngestionJob(
                            job_id=new_job_id("foundational"),
                            kind=JobKind.EVENT,
                            arxiv_ref=aid,
                        )
                    )
                    outcome = decision.value
                    break
                except RetriableIngestionError as exc:
                    if attempt < RETRIES:
                        time.sleep(RETRY_SLEEP * (attempt + 1))
                        continue
                    outcome = f"failed:retriable:{exc.reason.value}"
                except PermanentIngestionError as exc:
                    outcome = f"failed:permanent:{exc.reason.value}"
                    break
                except Exception as exc:  # noqa: BLE001 — one bad paper must not end the run
                    outcome = f"failed:unexpected:{type(exc).__name__}"
                    break
            counts[outcome] += 1
            ledger.write(
                json.dumps({"arxiv_id": aid, "bucket": bucket, "outcome": outcome}) + "\n"
            )
            ledger.flush()
            if n % 25 == 0 or n == len(todo):
                rate = (time.monotonic() - started) / n
                left = (len(todo) - n) * rate / 60
                print(f"  {n}/{len(todo)}  편당 {rate:.1f}s  남은 시간 약 {left:.0f}분")

    print("\n=== 결과 ===")
    for outcome, c in counts.most_common():
        print(f"  {c:5d}  {outcome}")
    failed = sum(c for o, c in counts.items() if o.startswith("failed"))
    print(f"\n성공 {len(todo) - failed}편 · 실패 {failed}편 ({failed / len(todo) * 100:.1f}%)")
    # A high loss rate on a NAMED list is different from a high loss rate on a date window: every
    # one of these papers was chosen because U12 needs it, so losing many is a reason to stop and
    # look rather than to proceed to the recent slice.
    if failed and failed / len(todo) > 0.10:
        print("\n⚠️ 실패율 10% 초과 — 원인을 확인하기 전에 다음 단계로 넘어가지 말 것", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
