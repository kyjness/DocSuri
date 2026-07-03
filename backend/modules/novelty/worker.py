from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from .adapters import NoveltyAdapters, RetrievalBundle, build_default_novelty_adapters
from .models import TERMINAL_STATES, ArtifactKind, EvidenceStatus, InputType, JobState
from .repository import NoveltyRepository
from .service import NoveltyService

log = logging.getLogger("docsuri.novelty.worker")


class InvalidWorkerPayload(ValueError):
    pass


class JobProcessingFailed(RuntimeError):
    pass


class _Message:
    def __init__(self, body: dict[str, Any], receipt_handle: str | None = None) -> None:
        self.body = body
        self.receipt_handle = receipt_handle


def parse_sqs_payload(body: str | bytes | dict[str, Any]) -> tuple[str, str]:
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    payload = json.loads(body) if isinstance(body, str) else body
    owner_id = payload.get("ownerId") or payload.get("owner_id")
    job_id = payload.get("jobId") or payload.get("job_id")
    if not owner_id or not job_id:
        raise InvalidWorkerPayload("ownerId and jobId are required")
    return str(owner_id), str(job_id)


def process_sqs_payload(
    repo: NoveltyRepository,
    body: str | bytes | dict[str, Any],
    *,
    adapters: NoveltyAdapters | None = None,
    observability=None,
) -> None:
    owner_id, job_id = parse_sqs_payload(body)
    process_job(repo, owner_id, job_id, adapters=adapters, observability=observability)


def run_worker(
    *,
    repo_factory: Callable[[], NoveltyRepository],
    receive: Callable[[], Iterable[_Message]],
    ack: Callable[[_Message], None],
    should_stop: Callable[[], bool],
    adapters: NoveltyAdapters | None = None,
    observability=None,
) -> None:
    while not should_stop():
        for message in receive():
            repo = repo_factory()
            try:
                process_sqs_payload(
                    repo,
                    message.body,
                    adapters=adapters,
                    observability=observability,
                )
                commit = getattr(repo, "commit", None)
                if commit is not None:
                    commit()
            except JobProcessingFailed:  # FAILED state was recorded; commit and ack.
                commit = getattr(repo, "commit", None)
                if commit is not None:
                    commit()
                log.exception("novelty job failed; committed FAILED state")
            except Exception:  # noqa: BLE001 - leave unacked for retry/DLQ.
                rollback = getattr(repo, "rollback", None)
                if rollback is not None:
                    rollback()
                log.exception("novelty job failed; leaving message for redelivery")
                continue
            finally:
                close = getattr(repo, "close", None)
                if close is not None:
                    close()
            ack(message)
            if should_stop():
                break


def process_job(
    repo: NoveltyRepository,
    owner_id: str,
    job_id: str,
    *,
    adapters: NoveltyAdapters | None = None,
    observability=None,
) -> None:
    adapters = adapters or NoveltyAdapters()
    service = NoveltyService(repo, observability)
    try:
        job = repo.get_job(owner_id, job_id)
    except KeyError:
        log.warning("novelty job not found; dropping stale message", extra={"jobId": job_id})
        return
    if job.cancelled or job.state in TERMINAL_STATES:
        return
    try:
        degraded_reasons: list[str] = []

        service.advance_state(owner_id, job_id, JobState.RETRIEVING_CORPUS, "Searching U2 corpus")
        corpus = adapters.corpus.full_search(owner_id, job.topic)
        corpus_payload, degraded_reason = _payload_from_bundle(corpus)
        if degraded_reason:
            degraded_reasons.append(degraded_reason)
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.EVIDENCE,
            "Corpus evidence",
            corpus_payload,
        )

        service.advance_state(
            owner_id,
            job_id,
            JobState.SEARCHING_EXTERNAL,
            "Searching external sources",
        )
        external = adapters.external.search(job.topic)
        external_payload, degraded_reason = _payload_from_bundle(external)
        if degraded_reason:
            degraded_reasons.append(degraded_reason)
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.EXTERNAL_FINDINGS,
            "External findings",
            external_payload,
        )

        draft = adapters.llm.draft(topic=job.topic, corpus=corpus, external=external)
        if draft.degradedReason:
            degraded_reasons.append(draft.degradedReason)

        service.advance_state(
            owner_id,
            job_id,
            JobState.SUMMARIZING_PRIOR_WORK,
            "Summarizing similar completed work",
        )
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.SIMILAR_WORKS,
            "Similar completed work",
            draft.similarWorks,
        )

        if job.inputType is InputType.MANUSCRIPT and job.manuscript is not None:
            service.advance_state(
                owner_id,
                job_id,
                JobState.CHECKING_SIMILARITY,
                "Checking sentence similarity and AI-style risks",
            )
            similarity_ref = {**job.manuscript.model_dump(), "jobId": job_id}
            similarity = adapters.similarity.check(owner_id, similarity_ref)
            similarity_payload, degraded_reason = _payload_from_bundle(similarity)
            if degraded_reason:
                degraded_reasons.append(degraded_reason)
            service.save_artifact(
                owner_id,
                job_id,
                ArtifactKind.RISK_SIGNALS,
                "Similarity and style risk signals",
                similarity_payload,
            )

        service.advance_state(
            owner_id,
            job_id,
            JobState.FORMING_IDEAS,
            "Forming novelty candidates",
        )
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.NOVELTY_CANDIDATES,
            "Novelty candidates",
            draft.noveltyCandidates,
        )

        service.advance_state(
            owner_id,
            job_id,
            JobState.PLANNING_EXPERIMENT,
            "Drafting experiment plan",
        )
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.EXPERIMENT_PLAN,
            "Experiment plan",
            draft.experimentPlan,
        )
        if degraded_reasons:
            service.advance_state(
                owner_id,
                job_id,
                JobState.DEGRADED,
                "Novelty analysis complete with degraded adapters",
                {"degradedReasons": degraded_reasons},
            )
        else:
            service.advance_state(owner_id, job_id, JobState.COMPLETED, "Novelty analysis complete")
    except Exception as exc:
        service.advance_state(
            owner_id,
            job_id,
            JobState.FAILED,
            "Novelty analysis failed",
            {"error": str(exc)},
        )
        raise JobProcessingFailed(str(exc)) from exc


def _payload_from_bundle(bundle: RetrievalBundle) -> tuple[dict[str, Any], str | None]:
    source_refs = _collect_source_refs(bundle.items)
    degraded_reason = bundle.degradedReason
    status = bundle.evidenceStatus
    if status is EvidenceStatus.SUPPORTED and not source_refs:
        status = EvidenceStatus.UNSUPPORTED
        degraded_reason = degraded_reason or "supported adapter output missing sourceRefs"
    return (
        {
            "items": bundle.items,
            "evidenceStatus": status.value,
            "degradedReason": degraded_reason,
            "sourceRefs": source_refs,
        },
        degraded_reason,
    )


def _collect_source_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for item in items:
        for ref in item.get("sourceRefs") or item.get("source_refs") or []:
            if isinstance(ref, dict):
                refs.append(ref)
    return refs


_shutdown = threading.Event()


def _on_signal(signum, _frame) -> None:
    log.info("received %s; draining then exiting", signal.Signals(signum).name)
    _shutdown.set()


def main(argv: list[str] | None = None) -> int:
    del argv
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    queue_url = os.getenv("DOCSURI_NOVELTY_JOB_QUEUE_URL")
    if not queue_url:
        log.error("DOCSURI_NOVELTY_JOB_QUEUE_URL not set; nothing to consume")
        return 1

    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    from .repository import SqlNoveltyRepository

    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    def repo_factory() -> NoveltyRepository:
        return SqlNoveltyRepository(session_factory())

    import boto3

    sqs = boto3.client(
        "sqs",
        region_name=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2"),
    )
    observability, cost_guard, telemetry_store = _build_worker_ops()

    def receive() -> list[_Message]:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )
        return [
            _Message(json.loads(message["Body"]), message["ReceiptHandle"])
            for message in resp.get("Messages", [])
        ]

    def ack(message: _Message) -> None:
        if message.receipt_handle:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message.receipt_handle)

    log.info("novelty worker started; polling queue")
    try:
        run_worker(
            repo_factory=repo_factory,
            receive=receive,
            ack=ack,
            should_stop=_shutdown.is_set,
            adapters=build_default_novelty_adapters(
                observability=observability,
                cost_guard=cost_guard,
            ),
            observability=observability,
        )
    finally:
        close = getattr(telemetry_store, "close", None)
        if close is not None:
            close()
    log.info("novelty worker shut down gracefully")
    return 0


def _build_worker_ops() -> tuple[Any, Any, Any]:
    try:
        from backend.app import _build_observability, _build_ops_dashboard_service
    except ImportError:
        return None, None, None

    observability, telemetry_store = _build_observability()
    _, cost_guard, _, _ = _build_ops_dashboard_service(telemetry_store)
    return observability, cost_guard, telemetry_store


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
