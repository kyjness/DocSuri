from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from backend.modules.user_docmodel import USER_DOCMODEL_PDF_CONTENT_TYPE

from .adapters import NoveltyAdapters, RetrievalBundle, build_default_novelty_adapters
from .models import TERMINAL_STATES, ArtifactKind, EvidenceStatus, InputType, JobState
from .repository import NoveltyRepository
from .service import NoveltyService, _emit_metric

log = logging.getLogger("docsuri.novelty.worker")


class InvalidWorkerPayload(ValueError):
    pass


class JobProcessingFailed(RuntimeError):
    pass


# US-EV4/#268 consume-on-retry: a user-uploaded manuscript PDF's doc-model builds asynchronously
# (slower than one poll). Rather than terminally DEGRADE, re-drive the job with a bounded backoff.
_MANUSCRIPT_DOCMODEL_MAX_ATTEMPTS = int(os.getenv("DOCSURI_NOVELTY_MANUSCRIPT_MAX_ATTEMPTS", "8"))
_MANUSCRIPT_DOCMODEL_RETRY_DELAY_SECONDS = min(
    900, max(0, int(os.getenv("DOCSURI_NOVELTY_MANUSCRIPT_RETRY_DELAY_SECONDS", "30")))
)


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


def _payload_attempt(body: str | bytes | dict[str, Any]) -> int:
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    payload = json.loads(body) if isinstance(body, str) else body
    value = payload.get("attempt", 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def process_sqs_payload(
    repo: NoveltyRepository,
    body: str | bytes | dict[str, Any],
    *,
    adapters: NoveltyAdapters | None = None,
    observability=None,
    reenqueue: Callable[[str, str, int], None] | None = None,
) -> None:
    owner_id, job_id = parse_sqs_payload(body)
    process_job(
        repo,
        owner_id,
        job_id,
        adapters=adapters,
        observability=observability,
        attempt=_payload_attempt(body),
        reenqueue=reenqueue,
    )


def run_worker(
    *,
    repo_factory: Callable[[], NoveltyRepository],
    receive: Callable[[], Iterable[_Message]],
    ack: Callable[[_Message], None],
    should_stop: Callable[[], bool],
    adapters: NoveltyAdapters | None = None,
    observability=None,
    reenqueue: Callable[[str, str, int], None] | None = None,
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
                    reenqueue=reenqueue,
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


def _await_manuscript_doc_model(
    service: NoveltyService,
    adapters: NoveltyAdapters,
    job: Any,
    owner_id: str,
    job_id: str,
    attempt: int,
    reenqueue: Callable[[str, str, int], None] | None,
) -> bool:
    """Early retry gate for user-uploaded manuscript PDFs (#268 consume-on-retry). The doc-model
    builds asynchronously and is usually not ready within one poll; rather than run the LLM
    pipeline and terminally DEGRADE, re-enqueue the same job with a bounded backoff until the
    doc-model lands. Returns True when re-enqueued (caller returns without running the pipeline)."""
    if reenqueue is None or job.manuscript is None:
        return False
    if job.inputType is not InputType.MANUSCRIPT:
        return False
    if job.manuscript.contentType != USER_DOCMODEL_PDF_CONTENT_TYPE:
        return False
    probe = getattr(adapters.similarity, "manuscript_doc_model_ready", None)
    if probe is None:
        return False
    manuscript_ref = {**job.manuscript.model_dump(), "jobId": job_id}
    if probe(owner_id, manuscript_ref):
        return False
    if attempt >= _MANUSCRIPT_DOCMODEL_MAX_ATTEMPTS:
        return False  # exhausted → run the pipeline; it degrades as before.
    service.record_event(
        job,
        "Waiting for the uploaded PDF to be processed",
        {"source": _SIMILARITY_SOURCE, "attempt": attempt + 1},
    )
    reenqueue(owner_id, job_id, attempt + 1)
    return True


def process_job(
    repo: NoveltyRepository,
    owner_id: str,
    job_id: str,
    *,
    adapters: NoveltyAdapters | None = None,
    observability=None,
    attempt: int = 0,
    reenqueue: Callable[[str, str, int], None] | None = None,
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
    if _await_manuscript_doc_model(service, adapters, job, owner_id, job_id, attempt, reenqueue):
        return
    try:
        degraded_reasons: list[str] = []
        topic_preview = job.topic[:_PREVIEW_LEN]

        # US-NV1(#251) — 자연어 잡은 D5 EvidenceFormationPort로 근거 묶음을 먼저 만들고(AC1),
        # 아래 U2 full 검색이 결과를 보강한다(AC2). abstain·장애는 저하로 계속(날조 금지, D5).
        evidence_bundle: RetrievalBundle | None = None
        if job.inputType is InputType.NATURAL_LANGUAGE:
            job = service.advance_state(
                owner_id,
                job_id,
                JobState.RETRIEVING_CORPUS,
                "Forming evidence bundle",
                {"source": _EVIDENCE_SOURCE, "query": topic_preview},
            )
            evidence_bundle = adapters.evidence.form(owner_id, job.topic)
            service.record_event(
                job,
                "Evidence bundle formed",
                _step_result_payload(
                    _EVIDENCE_SOURCE, len(evidence_bundle.items), None
                ),
            )

        # US-NV7(#257) — 단계 이벤트가 도구/쿼리/발견 수/저하 사유를 싣는다. 검색 단계는
        # 시작 이벤트(도구+쿼리) 뒤 완료 이벤트(count)를 덧붙이고, LLM 단계는 draft가 이미
        # 끝난 뒤 전이되므로 시작 이벤트 하나가 결과 수까지 나른다.
        job = service.advance_state(
            owner_id,
            job_id,
            JobState.RETRIEVING_CORPUS,
            "Searching U2 corpus",
            {"source": _CORPUS_SOURCE, "query": topic_preview},
        )
        corpus = adapters.corpus.full_search(owner_id, job.topic)
        corpus_payload, degraded_reason = _payload_from_bundle(corpus)
        if degraded_reason:
            degraded_reasons.append(degraded_reason)
            _note_degraded(observability, _CORPUS_SOURCE)
        service.record_event(
            job,
            "U2 corpus search finished",
            _step_result_payload(_CORPUS_SOURCE, len(corpus.items), degraded_reason),
        )
        if evidence_bundle is not None and evidence_bundle.items:
            # 근거 묶음이 앞서고 corpus가 보강 — 병합 번들이 artifact와 LLM draft에 흐른다.
            corpus = _merge_bundles(evidence_bundle, corpus)
            corpus_payload, _ = _payload_from_bundle(corpus)
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.EVIDENCE,
            "Corpus evidence",
            corpus_payload,
        )

        job = service.advance_state(
            owner_id,
            job_id,
            JobState.SEARCHING_EXTERNAL,
            "Searching external sources",
            {"source": _EXTERNAL_SOURCE, "query": topic_preview},
        )
        external = adapters.external.search(job.topic)
        external_payload, degraded_reason = _payload_from_bundle(external)
        if degraded_reason:
            degraded_reasons.append(degraded_reason)
            _note_degraded(observability, _EXTERNAL_SOURCE)
        service.record_event(
            job,
            "External source search finished",
            _step_result_payload(_EXTERNAL_SOURCE, len(external.items), degraded_reason),
        )
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
            _note_degraded(observability, _LLM_SOURCE)

        job = service.advance_state(
            owner_id,
            job_id,
            JobState.SUMMARIZING_PRIOR_WORK,
            "Summarizing similar completed work",
            _step_result_payload(
                _LLM_SOURCE,
                len(draft.similarWorks.get("items") or []),
                draft.degradedReason,
            ),
        )
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.SIMILAR_WORKS,
            "Similar completed work",
            draft.similarWorks,
        )

        if job.inputType is InputType.MANUSCRIPT and job.manuscript is not None:
            job = service.advance_state(
                owner_id,
                job_id,
                JobState.CHECKING_SIMILARITY,
                "Checking sentence similarity and AI-style risks",
                {"source": _SIMILARITY_SOURCE, "query": job.manuscript.fileName},
            )
            similarity_ref = {**job.manuscript.model_dump(), "jobId": job_id}
            similarity = adapters.similarity.check(owner_id, similarity_ref)
            similarity_payload, degraded_reason = _payload_from_bundle(similarity)
            if degraded_reason:
                degraded_reasons.append(degraded_reason)
                _note_degraded(observability, _SIMILARITY_SOURCE)
            service.record_event(
                job,
                "Similarity check finished",
                _step_result_payload(_SIMILARITY_SOURCE, len(similarity.items), degraded_reason),
            )
            service.save_artifact(
                owner_id,
                job_id,
                ArtifactKind.RISK_SIGNALS,
                "Similarity and style risk signals",
                similarity_payload,
            )

        job = service.advance_state(
            owner_id,
            job_id,
            JobState.FORMING_IDEAS,
            "Forming novelty candidates",
            _step_result_payload(
                _LLM_SOURCE,
                len(draft.noveltyCandidates.get("items") or []),
                draft.degradedReason,
            ),
        )
        service.save_artifact(
            owner_id,
            job_id,
            ArtifactKind.NOVELTY_CANDIDATES,
            "Novelty candidates",
            draft.noveltyCandidates,
        )

        plan_summary = str(draft.experimentPlan.get("researchQuestion") or "")[:_PREVIEW_LEN]
        planning_payload: dict[str, Any] = {"source": _LLM_SOURCE}
        if plan_summary:
            planning_payload["outputSummary"] = plan_summary
        job = service.advance_state(
            owner_id,
            job_id,
            JobState.PLANNING_EXPERIMENT,
            "Drafting experiment plan",
            planning_payload,
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


# US-NV7(#257) — 이벤트 payload 키는 FE timelineDetail 계약(source/query/count/outputSummary/
# reason)을 따른다. 값은 표시용 프리뷰라 _PREVIEW_LEN에서 자른다.
_PREVIEW_LEN = 160
_EVIDENCE_SOURCE = "U11 evidence formation"
_CORPUS_SOURCE = "U2 full search"
_EXTERNAL_SOURCE = "GitHub · Hugging Face · Zenodo"
_SIMILARITY_SOURCE = "manuscript similarity"
_LLM_SOURCE = "Bedrock LLM"


def _note_degraded(observability, source: str) -> None:
    """US-NV9(#259) — 대시보드용 소스별 저하 카운트."""
    _emit_metric(observability, "novelty.step_degraded", tags={"source": source})


def _step_result_payload(source: str, count: int, reason: str | None) -> dict[str, Any]:
    payload: dict[str, Any] = {"source": source, "count": count}
    if reason:
        payload["reason"] = reason
    return payload


def _merge_bundles(first: RetrievalBundle, second: RetrievalBundle) -> RetrievalBundle:
    """US-NV1(#251) — 근거 묶음 + corpus 보강 병합. 개별 저하 사유는 각 단계에서 이미 기록됨."""
    items = [*first.items, *second.items]
    return RetrievalBundle(
        items=items,
        evidenceStatus=EvidenceStatus.SUPPORTED if items else EvidenceStatus.ABSTAINED,
        degradedReason=second.degradedReason,
    )


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

    def reenqueue(o_id: str, j_id: str, attempt: int) -> None:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"ownerId": o_id, "jobId": j_id, "attempt": attempt}),
            DelaySeconds=_MANUSCRIPT_DOCMODEL_RETRY_DELAY_SECONDS,
        )

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
                user_docmodel=_build_user_docmodel(),
            ),
            observability=observability,
            reenqueue=reenqueue,
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


def _build_user_docmodel():
    from backend.modules.user_docmodel import build_default_user_docmodel_coordinator

    return build_default_user_docmodel_coordinator()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
