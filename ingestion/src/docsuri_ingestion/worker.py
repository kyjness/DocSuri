from __future__ import annotations

import logging
import signal
import sys
import threading

from .domain.enums import FailureClass, FailureReason, JobKind, SourceName
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

    settings = IngestionSettings.from_env()
    max_messages = max(1, min(10, settings.worker_max_messages))
    loop_delay = max(0.0, settings.worker_loop_delay_seconds)
    runtime = build_production_runtime(settings)
    queue = runtime.queue
    docmodel_queue = runtime.docmodel_queue
    poll_bulk = settings.worker_queue_mode in ("all", "bulk")
    poll_docmodel = settings.worker_queue_mode in ("all", "docmodel")
    if settings.worker_queue_mode == "docmodel" and docmodel_queue is None:
        raise RuntimeError("DOCSURI_DOCMODEL_QUEUE_URL is required in docmodel worker mode")
    log.info("worker started — polling queue")
    while not _shutdown_event.is_set():
        # Priority: drain reader-triggered doc-model builds first so the viewer/citation-tree are
        # never starved behind a bulk backfill on the main queue. The doc-model SqsQueue short-polls
        # (wait_time_seconds=0), so an empty one returns immediately and we fall through to the
        # backfill queue; a non-empty one loops back here before touching the backfill queue.
        if poll_docmodel and docmodel_queue is not None:
            docmodel_messages = docmodel_queue.receive_messages(max_messages=max_messages)
            if docmodel_messages:
                for message in docmodel_messages:
                    process_message(runtime, message, docmodel_queue)
                    if _shutdown_event.is_set():
                        break
                continue
        if _shutdown_event.is_set():
            break
        if poll_bulk:
            for message in queue.receive_messages(max_messages=max_messages):
                process_message(runtime, message, queue)
                if _shutdown_event.is_set():
                    break
        _shutdown_event.wait(timeout=loop_delay)
    log.info("worker shut down gracefully")
    return 0


def process_message(runtime, message, queue=None) -> None:
    # ack/DLQ must target the queue the message came from (main backfill queue or the priority
    # doc-model queue). Defaults to the main queue so existing 2-arg callers are unaffected.
    queue = queue if queue is not None else runtime.queue

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

    if job.kind in (JobKind.INCREMENTAL, JobKind.EVENT) and runtime.pipeline.is_rebuild_active():
        # BR-13 single-writer: a full rebuild is in progress and re-harvests this window, so drop
        # the in-flight incremental/event job rather than let it advance the watermark the rebuild
        # just reset (watermark pollution). The rebuild re-covers this paper.
        runtime.observability.emit_metric(
            "ingestion.incremental.fenced", 1.0, {"kind": job.kind.value}
        )
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
            if job.kind is JobKind.BUILD_DOC_MODEL:
                # ingest_one DLQs + signals internally before re-raising; the doc-model build path
                # does not, so surface its permanent failures here (BR-15/17) instead of silently
                # acking and dropping them.
                runtime.observability.emit_failure_signal(
                    job.job_id, stage=exc.stage, error=exc.public_error()
                )
                queue.send_to_dlq(message.body, reason=exc.public_error())
            queue.ack(message)
    except Exception as exc:  # noqa: BLE001 - never let one unexpected error crash-loop the worker
        # An exception outside the failure taxonomy (e.g. an unguarded parse) must not escape
        # the loop and crash-loop on redelivery. Isolate it like a poison payload (RES-9/BR-18).
        log.exception("unexpected error processing job %s", job.job_id)
        runtime.observability.emit_failure_signal(job.job_id, stage="worker", error=str(exc))
        queue.send_to_dlq(message.body, reason="unexpected_error")
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
        source_name = payload.get("sourceName")
    except (KeyError, ValueError, TypeError) as exc:
        raise PermanentIngestionError(
            "invalid queue payload",
            reason=FailureReason.POISON_EVENT,
            stage="queue",
        ) from exc
    try:
        parsed_source = SourceName(source_name) if source_name else None
    except ValueError as exc:
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
        source_name=parsed_source,
        failure_stage=payload.get("failureStage"),
        canonical_key=payload.get("canonicalKey"),
        paper_id=payload.get("paperId"),
        version=payload.get("version"),
        source_record=payload.get("sourceRecord"),
        arxiv_metadata=payload.get("arxivMetadata"),
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
