from __future__ import annotations

import logging
import signal
import sys
import threading

from .domain.enums import FailureClass, FailureReason, JobKind
from .domain.errors import IngestionError, PermanentIngestionError
from .domain.models import IngestionJob
from .observability import configure_logging
from .runtime import build_production_runtime
from .settings import IngestionSettings

log = logging.getLogger("docsuri.ingestion.worker")

_shutdown_event = threading.Event()


def _handle_shutdown_signal(signum, _frame):
    sig_name = signal.Signals(signum).name
    log.info("received signal %s — draining current batch then exiting", sig_name)
    _shutdown_event.set()


def main(argv: list[str] | None = None) -> int:
    del argv
    configure_logging()

    signal.signal(signal.SIGTERM, _handle_shutdown_signal)
    signal.signal(signal.SIGINT, _handle_shutdown_signal)

    runtime = build_production_runtime(IngestionSettings.from_env())
    queue = runtime.queue
    log.info("worker started — polling queue")
    while not _shutdown_event.is_set():
        for message in queue.receive_messages(max_messages=10):
            process_message(runtime, message)
            if _shutdown_event.is_set():
                break
        _shutdown_event.wait(timeout=1.0)
    log.info("worker shut down gracefully")
    return 0


def process_message(runtime, message) -> None:
    queue = runtime.queue

    message_type = message_type_from_payload(message.body)

    if message_type == "schedule_tick":
        queued = runtime.refresh.on_schedule_tick()
        log.info("schedule_tick completed, queued %d papers", queued)
        queue.ack(message)
        return

    if message_type != "ingest_paper":
        error = PermanentIngestionError(
            "invalid queue payload",
            reason=FailureReason.POISON_EVENT,
            stage="queue",
        ).public_error()
        runtime.observability.emit_failure_signal(
            getattr(message, "message_id", "unknown"),
            stage="queue",
            error=error,
        )
        queue.send_to_dlq(message.body, reason=error)
        queue.ack(message)
        return

    try:
        job = job_from_payload(message.body)
    except IngestionError as exc:
        runtime.observability.emit_failure_signal(
            getattr(message, "message_id", "unknown"),
            stage=exc.stage,
            error=exc.public_error(),
        )
        if exc.failure_class is FailureClass.PERMANENT:
            queue.send_to_dlq(message.body, reason=exc.public_error())
            queue.ack(message)
        return

    try:
        if job.kind is JobKind.BUILD_DOC_MODEL:
            # Lazy doc-model build (BR-30/D6) — separate from the index pipeline.
            runtime.pipeline.build_doc_model(job)
        else:
            runtime.pipeline.ingest_one(job)
    except IngestionError as exc:
        if exc.failure_class is FailureClass.PERMANENT:
            queue.ack(message)
    else:
        queue.ack(message)


def message_type_from_payload(payload) -> str | None:
    if payload.get("action") == "schedule_tick":
        return "schedule_tick"
    message_type = payload.get("type")
    if message_type is None:
        return "ingest_paper"
    return message_type


def job_from_payload(payload) -> IngestionJob:
    try:
        kind = JobKind(payload["kind"])
        job_id = payload["jobId"]
        arxiv_ref = payload.get("arxivRef")
    except (KeyError, ValueError, TypeError) as exc:
        raise PermanentIngestionError(
            "invalid queue payload",
            reason=FailureReason.POISON_EVENT,
            stage="queue",
        ) from exc
    return IngestionJob(
        job_id=job_id,
        kind=kind,
        arxiv_ref=arxiv_ref,
        event_id=payload.get("eventId"),
        correlation_id=payload.get("correlationId"),
    )


if __name__ == "__main__":
    # A step arg (provision|backfill|cutover) runs the v4 migration runner once and exits;
    # no arg runs the normal SQS-polling worker. Lets one-off ECS run-task reuse this image
    # (entrypoint is fixed to this module) without a separate task definition.
    _args = sys.argv[1:]
    if _args:
        from .migrate import run_step

        raise SystemExit(run_step(_args[0]))
    raise SystemExit(main())
