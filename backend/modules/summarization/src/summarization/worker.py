"""Summarization worker — long-input background jobs (BR-S6/BR-S8/BR-S18, #135).

Consumes the jobs the API enqueues on the LengthRouter MAP_REDUCE band and runs them **inline**
(``allow_enqueue=False``) — here there is no request/gateway timeout, so the long-input work can
complete: summary map-reduce (3-5 LLM calls) or translate map-only (section-by-section). The
worker is task-agnostic (the payload carries ``task``); the orchestrator write-throughs the
result to the shared store, so the client's next poll of ``/api/summarize`` hits the cache.

Deployment note: this is its own deploy unit (separate from the API). It MUST run with
``DOCSURI_MAP_REDUCE_ENABLED`` on (so the orchestrator has the map-reduce summarizer) and
``DOCSURI_SUMMARY_JOB_QUEUE_URL`` pointing at the same queue the API enqueues to. Build/synth
only — actual deploy is handled separately.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from .domain.models import (
    AuthSession,
    Persona,
    RequestContext,
    Scope,
    SummaryRequest,
    TargetLang,
    Task,
)
from .service.orchestrator import SummarizationOrchestrationService

log = logging.getLogger("docsuri.summarization.worker")


class _Message(Protocol):
    body: dict


def request_from_payload(payload: dict) -> tuple[SummaryRequest, str]:
    """Reconstruct the ``SummaryRequest`` + owner ``user_id`` a SqsSummaryJobQueue message
    carries. Unknown enum values raise (poison message → not acked → DLQ via redrive)."""
    request = SummaryRequest(
        paper_id=str(payload["paperId"]),
        version=int(payload.get("version", 1)),
        task=Task(str(payload["task"])),
        target_lang=TargetLang(str(payload.get("targetLang", TargetLang.KO.value))),
        persona=Persona(str(payload.get("persona", Persona.EXPERT.value))),
        scope=Scope(str(payload.get("scope", Scope.ABSTRACT.value))),
        abstract=str(payload["abstract"]) if payload.get("abstract") else None,
    )
    return request, str(payload["userId"])


def process_job(orchestrator: SummarizationOrchestrationService, payload: dict) -> None:
    """Run one long-summary job inline. The result write-throughs to the store (idempotent — a
    cache hit short-circuits, so a duplicate delivery is cheap)."""
    request, user_id = request_from_payload(payload)
    ctx = RequestContext(auth_session=AuthSession(user_id=user_id), request_id="")
    orchestrator.run(request, ctx, allow_enqueue=False)


def run_worker(
    orchestrator: SummarizationOrchestrationService,
    *,
    receive: Callable[[], Iterable[_Message]],
    ack: Callable[[_Message], None],
    should_stop: Callable[[], bool],
) -> None:
    """Poll → process → ack loop with an injectable transport (real SQS in ``main``, fakes in
    tests). A job that raises is left unacked for redelivery; success acks."""
    while not should_stop():
        for message in receive():
            try:
                process_job(orchestrator, message.body)
            except Exception:  # noqa: BLE001 — leave unacked for redelivery / eventual DLQ.
                log.exception("summary job failed; leaving for redelivery")
                continue
            ack(message)
            if should_stop():
                break


# --- production entry ------------------------------------------------------

_shutdown = threading.Event()


def _on_signal(signum, _frame) -> None:
    log.info("received %s — draining then exiting", signal.Signals(signum).name)
    _shutdown.set()


def _build_observability():
    import os

    from docsuri_ops.observability import ObservabilityHub

    namespace = os.getenv("CLOUDWATCH_NAMESPACE")
    if namespace:
        from docsuri_ops.adapters.cloudwatch import CloudWatchEventStore

        store: Any = CloudWatchEventStore(
            namespace=namespace,
            log_group=os.getenv("CLOUDWATCH_LOG_GROUP", "/docsuri/ops"),
            region_name=os.getenv("AWS_REGION", "ap-northeast-2"),
        )
    else:
        from docsuri_ops.adapters.local import InMemoryEventStore

        store = InMemoryEventStore()
    return ObservabilityHub(store)


def main(argv: list[str] | None = None) -> int:
    del argv
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    from docsuri_ops.cost_guard import CostGuardCircuitBreaker

    from .adapters.settings import SummarizationSettings
    from .real_wiring import build_real_orchestrator

    settings = SummarizationSettings.from_env()
    if not settings.summary_job_queue_url:
        log.error("DOCSURI_SUMMARY_JOB_QUEUE_URL not set — nothing to consume")
        return 1
    if not settings.map_reduce_enabled:
        log.error("DOCSURI_MAP_REDUCE_ENABLED not on — worker cannot produce long summaries")
        return 1

    bundle = build_real_orchestrator(
        settings,
        cost_guard=CostGuardCircuitBreaker(),
        observability=_build_observability(),
    )

    import boto3

    sqs = boto3.client("sqs", region_name=settings.region_name)
    queue_url = settings.summary_job_queue_url

    class _Sqs:
        def __init__(self, raw: dict) -> None:
            self.body = json.loads(raw["Body"])
            self._receipt = raw["ReceiptHandle"]

    def receive() -> list[_Sqs]:
        resp = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=20)
        return [_Sqs(m) for m in resp.get("Messages", [])]

    def ack(message: _Sqs) -> None:
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message._receipt)

    log.info("summarization worker started — polling queue")
    run_worker(
        bundle.orchestrator, receive=receive, ack=ack, should_stop=_shutdown.is_set
    )
    log.info("summarization worker shut down gracefully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
