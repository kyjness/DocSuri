from __future__ import annotations

import argparse
import sys

from .application import new_job_id
from .domain.enums import JobKind
from .domain.models import IngestionJob
from .foundational import (
    DEFAULT_LEDGER as FOUNDATIONAL_LEDGER,
)
from .foundational import (
    DEFAULT_LIST as FOUNDATIONAL_LIST,
)
from .foundational import (
    ingest_foundational,
)
from .observability import configure_logging
from .runtime import (
    build_local_runtime,
    build_production_runtime,
    preflight_dependencies,
    probe_grobid,
)
from .settings import IngestionSettings, validate_corpus_build_settings


def _guard(check) -> bool:
    """Run a pre-start check, reporting its failure as a message rather than a traceback.

    Both checks raise the same ``RuntimeError("; ".join(errors))``: this is an operator being told
    to go fix something, and a stack trace buries the one line that says what. Shared so the two
    cannot drift — the settings check used to escape as a traceback while the liveness probe was
    printed, three lines apart.
    """
    try:
        check()
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="docsuri-ingestion")
    parser.add_argument("--local", action="store_true", help="use local fake adapters")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest-one")
    ingest.add_argument("--arxiv-ref", required=True)

    subcommands.add_parser("trigger-full-rebuild")
    subcommands.add_parser("schedule-tick")

    # The named foundational papers (⑧-2). Separate from trigger-full-rebuild because a
    # CategoryFilter cannot express an explicit id list, which is the whole point of that set.
    foundational = subcommands.add_parser("ingest-foundational")
    foundational.add_argument("--list", dest="list_path", default=FOUNDATIONAL_LIST)
    foundational.add_argument("--ledger", dest="ledger_path", default=FOUNDATIONAL_LEDGER)
    foundational.add_argument("--bucket")
    foundational.add_argument("--limit", type=int)
    foundational.add_argument("--retry-failed", action="store_true")
    foundational.add_argument(
        "--skip-stage",
        dest="skip_stages",
        default=(),
        type=lambda raw: tuple(p.strip() for p in raw.split(",") if p.strip()),
        help="이 단계에서 실패한 논문은 --retry-failed 대상에서 뺀다 (예: grobid,extract_tei). "
        "일부러 내려둔 의존성을 쓰는 논문을 다시 태우지 않기 위한 것",
    )
    foundational.add_argument(
        "--redo",
        dest="redo_path",
        help="이 파일에 적힌 arXiv id는 원장이 성공으로 적어뒀어도 다시 돈다 "
        "(파서·청커가 바뀌어 이전 산출물이 낡았을 때). 한 줄에 하나, # 뒤는 주석",
    )
    foundational.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    settings = IngestionSettings.from_env()

    # Dispatched BEFORE the shared runtime construction below. Building the runtime first
    # discarded --local (a local runtime was built and thrown away while foundational.py went on
    # to construct a production one and ingest 1,500 papers into the real corpus), violated
    # --dry-run's documented no-runtime guarantee, and made normal runs build two runtimes.
    if args.command == "ingest-foundational":
        live = not args.local and not args.dry_run
        if live:
            # Writes a third of the corpus, so it needs the same preconditions the full rebuild
            # checks (multimodal assets on, no v2 model shadow, GROBID reachable, rollout
            # confirmed) — skipping them here would be discovered after the ~1.5-hour run.
            # Before the runtime is built, so a misconfiguration costs no model loading.
            if not _guard(lambda: validate_corpus_build_settings(settings)):
                return 1
            # GROBID needs only its URL, so probe it before Docling and pix2tex are imported.
            # An id list is arXiv-only whatever the env lists, so a down GROBID is a warning here
            # (probe_grobid logs it) rather than a stop.
            probe_grobid(settings, required=False)
        foundational_runtime = None
        if not args.dry_run:
            foundational_runtime = (
                build_local_runtime() if args.local else build_production_runtime(settings)
            )
        return ingest_foundational(
            settings,
            runtime=foundational_runtime,
            list_path=args.list_path,
            ledger_path=args.ledger_path,
            bucket=args.bucket,
            limit=args.limit,
            retry_failed=args.retry_failed,
            redo_path=args.redo_path,
            skip_stages=args.skip_stages,
            preflight=live,
            dry_run=args.dry_run,
        )

    if args.command == "trigger-full-rebuild" and not args.local:
        if not _guard(lambda: validate_corpus_build_settings(settings)):
            return 1
    runtime = build_local_runtime() if args.local else build_production_runtime(settings)
    if args.command == "trigger-full-rebuild" and not args.local:
        if not _guard(
            lambda: preflight_dependencies(
                runtime, settings, sources=settings.parsed_corpus_sources
            )
        ):
            return 1

    if args.command == "ingest-one":
        decision = runtime.pipeline.ingest_one(
            IngestionJob(
                job_id=new_job_id("manual"),
                kind=JobKind.EVENT,
                arxiv_ref=args.arxiv_ref,
            )
        )
        print(decision.value)
        return 0
    if args.command == "trigger-full-rebuild":
        queued = runtime.refresh.trigger_full_rebuild()
        print(f"queued={queued}")
        return 0
    if args.command == "schedule-tick":
        queued = runtime.refresh.on_schedule_tick()
        print(f"queued={queued}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
