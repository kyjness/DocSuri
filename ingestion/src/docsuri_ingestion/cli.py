from __future__ import annotations

import argparse
import sys

from .application import new_job_id
from .domain.enums import JobKind
from .domain.models import IngestionJob
from .observability import configure_logging
from .runtime import build_local_runtime, build_production_runtime
from .settings import IngestionSettings, validate_corpus_build_settings


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="docsuri-ingestion")
    parser.add_argument("--local", action="store_true", help="use local fake adapters")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest-one")
    ingest.add_argument("--arxiv-ref", required=True)

    subcommands.add_parser("trigger-full-rebuild")
    subcommands.add_parser("schedule-tick")

    args = parser.parse_args(argv)
    settings = IngestionSettings.from_env()
    if args.command == "trigger-full-rebuild" and not args.local:
        validate_corpus_build_settings(settings)
    runtime = build_local_runtime() if args.local else build_production_runtime(settings)

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
