"""Evidence Formation Agent — SQS polling worker (BR-EV-6 비동기 잡 경로).

AgentWorker는 SQS에서 메시지를 소비하여 동일한 EvidenceAgentOrchestrator 파이프라인을
실행하고 결과를 RDS evidence_turns에 기록한다.

SQS 메시지 페이로드:
  {
    "ownerId": "<uuid>",
    "sessionId": "<uuid>",
    "turnId": "<uuid>",
    "jobId": "<uuid>",
    "topic": "...",
    "scope": "auto" | "explicit" | "mixed",
    "paperIds": ["..."],
    "attachments": ["attachment-handle", "..."]
  }
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterable
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest, EvidenceScope

from .models import AgentRunContext, EvidenceTurn, TurnErrorResult, TurnPendingResult
from .orchestrator import EvidenceAgentOrchestrator
from .repository import EvidenceRepository

log = logging.getLogger('docsuri.evidence.worker')


class InvalidWorkerPayload(ValueError):
    pass


class JobProcessingFailed(RuntimeError):
    pass


class _Message:
    def __init__(self, body: dict[str, Any], receipt_handle: str | None = None) -> None:
        self.body = body
        self.receipt_handle = receipt_handle


def parse_sqs_payload(body: str | bytes | dict[str, Any]) -> dict[str, Any]:
    if isinstance(body, bytes):
        body = body.decode('utf-8')
    payload: dict[str, Any] = json.loads(body) if isinstance(body, str) else body
    owner_id = payload.get('ownerId') or payload.get('owner_id')
    turn_id = payload.get('turnId') or payload.get('turn_id')
    topic = payload.get('topic')
    if not owner_id or not turn_id or not topic:
        raise InvalidWorkerPayload('ownerId, turnId, topic are required')
    raw_attachments = payload.get('attachments') or []
    if not isinstance(raw_attachments, list):
        raise InvalidWorkerPayload('attachments must be a list')
    attachments: list[str] = []
    for item in raw_attachments:
        if not isinstance(item, str) or not item:
            raise InvalidWorkerPayload('attachments must contain string handles')
        attachments.append(item)
    raw_attachment_docs = payload.get('attachmentDocs') or []
    if not isinstance(raw_attachment_docs, list):
        raise InvalidWorkerPayload('attachmentDocs must be a list')
    attachment_docs = [
        item for item in raw_attachment_docs if isinstance(item, dict)
    ]
    return {
        'owner_id': str(owner_id),
        'session_id': str(payload.get('sessionId') or payload.get('session_id', '')),
        'turn_id': str(turn_id),
        'job_id': str(payload.get('jobId') or payload.get('job_id', '')),
        'topic': str(topic),
        'scope': payload.get('scope', 'auto'),
        'paper_ids': list(payload.get('paperIds') or payload.get('paper_ids') or []),
        'attachments': attachments,
        'attachment_docs': attachment_docs,
    }


def parse_received_messages(
    raw_messages: list[dict[str, Any]],
    *,
    on_poison: Callable[[dict[str, Any]], None],
) -> list[_Message]:
    """SQS receive_message() 원본 응답 → 파싱된 메시지 목록.

    poison message(파싱 불가한 Body) 하나가 예외를 밖으로 전파해 같은 배치의 정상
    메시지까지 unacked로 남기고 crash loop을 유발하던 문제를 방지한다(PR #338 리뷰
    Blocking #3). 실패한 메시지는 즉시 ``on_poison``으로 넘겨 삭제하고, 나머지는 정상
    처리한다.
    """
    messages: list[_Message] = []
    for msg in raw_messages:
        try:
            body = json.loads(msg['Body'])
        except (json.JSONDecodeError, TypeError):
            log.exception(
                'evidence worker: dropping poison message (invalid JSON body), receiptHandle=%s',
                msg.get('ReceiptHandle'),
            )
            on_poison(msg)
            continue
        messages.append(_Message(body, msg.get('ReceiptHandle')))
    return messages


def process_sqs_payload(
    repo: EvidenceRepository,
    body: str | bytes | dict[str, Any],
    *,
    orchestrator: EvidenceAgentOrchestrator,
    user_docmodel: Any = None,
) -> None:
    fields = parse_sqs_payload(body)
    process_job(repo, orchestrator=orchestrator, user_docmodel=user_docmodel, **fields)


def process_job(
    repo: EvidenceRepository,
    *,
    orchestrator: EvidenceAgentOrchestrator,
    owner_id: str,
    session_id: str,
    turn_id: str,
    job_id: str,
    topic: str,
    scope: str = 'auto',
    paper_ids: list[str] | None = None,
    attachments: list[str] | None = None,
    attachment_docs: list[dict[str, Any]] | None = None,
    user_docmodel: Any = None,
) -> None:
    # 세션 조회 (INV-EV-1: 소유권 확인)
    try:
        session = repo.get_session(owner_id, session_id)
    except KeyError:
        log.warning('evidence job %s: session %s not found or wrong owner', job_id, session_id)
        # turn을 pending으로 방치하면 GET /jobs/{job_id}가 영원히 pending을 반환한다
        # (PR #338 리뷰 Medium #12) — 세션이 소프트 삭제됐거나 소유자가 안 맞아도
        # turn 자체는 여전히 owner_id로 조회·갱신 가능하니 terminal로 전이시킨다.
        try:
            repo.update_turn_result(
                owner_id, turn_id, TurnErrorResult(error_code='session_unavailable')
            )
        except KeyError:
            log.warning(
                'evidence job %s: turn %s also unavailable, nothing to terminate',
                job_id, turn_id,
            )
        return

    # turn 조회 — 이미 완료 상태면 스킵
    turns = repo.list_turns(owner_id, session_id)
    turn: EvidenceTurn | None = next((t for t in turns if t.turn_id == turn_id), None)
    if turn is None:
        log.warning('evidence job %s: turn %s not found', job_id, turn_id)
        return

    # idempotency guard (PR #338 리뷰 Blocking #4): SQS at-least-once 특성상 동일 job이
    # visibility_timeout 초과 등으로 중복 배달될 수 있다. turn이 이미 pending을 벗어나
    # terminal 상태(성공/기권/에러)면 재실행하지 않고 스킵 — orchestrator 이중 실행과
    # update_turn_result의 결과 clobber를 함께 방지한다.
    if not isinstance(turn.result, TurnPendingResult):
        log.info(
            'evidence job %s: turn %s already resolved, skipping duplicate delivery',
            job_id, turn_id,
        )
        return

    request = EvidenceRequest(
        topic=topic,
        scope=(
            EvidenceScope(scope)
            if scope in EvidenceScope.__members__.values()
            else EvidenceScope.auto
        ),
        paperIds=paper_ids or [],
        attachments=attachments or [],
    )
    ctx = AgentRunContext(
        session=session,
        current_turn=turn,
        owner_id=owner_id,
        request_id=job_id,
        budget_signal={},
        attachment_docs=_attachment_inputs(
            owner_id=owner_id,
            scope_id=job_id,
            attachment_docs=attachment_docs or [],
            user_docmodel=user_docmodel,
        ),
    )

    try:
        result = orchestrator.run(ctx, request)
    except Exception as exc:
        log.exception('evidence job %s: orchestrator failed', job_id)
        # 검색/LLM 실패는 orchestrator.run() 내부에서 이미 abstain으로 잡아낸다 — 여기까지
        # 올라오는 건 분류되지 않은 예상 밖 실패다. 그런데도 항상 'llm_unavailable'로
        # 못박아 놓으면 원인이 LLM이 아닌 경우에도 사용자에게 오도된 코드가 노출된다
        # (PR #338 리뷰 Medium #11). SEC-9상 원본 예외 메시지는 노출 불가하므로, 비기술
        # 범용 코드로 정직하게 표현한다.
        result = TurnErrorResult(error_code='internal_error')
        repo.update_turn_result(owner_id, turn_id, result)
        repo.commit()
        raise JobProcessingFailed(str(exc)) from exc

    repo.update_turn_result(owner_id, turn_id, result)


def run_worker(
    *,
    repo_factory: Callable[[], EvidenceRepository],
    orchestrator: EvidenceAgentOrchestrator,
    receive: Callable[[], Iterable[_Message]],
    ack: Callable[[_Message], None],
    should_stop: Callable[[], bool],
    user_docmodel: Any = None,
) -> None:
    while not should_stop():
        for message in receive():
            repo = repo_factory()
            try:
                process_sqs_payload(
                    repo,
                    message.body,
                    orchestrator=orchestrator,
                    user_docmodel=user_docmodel,
                )
                commit = getattr(repo, 'commit', None)
                if commit is not None:
                    commit()
            except JobProcessingFailed:
                commit = getattr(repo, 'commit', None)
                if commit is not None:
                    commit()
                log.exception('evidence job failed; committed error state')
            except Exception:  # noqa: BLE001 — leave unacked for retry/DLQ
                rollback = getattr(repo, 'rollback', None)
                if rollback is not None:
                    rollback()
                log.exception('evidence job failed; leaving message for redelivery')
                continue
            finally:
                close = getattr(repo, 'close', None)
                if close is not None:
                    close()
            ack(message)
            if should_stop():
                break


_shutdown = threading.Event()


def _on_signal(signum, _frame) -> None:
    log.info('received %s; draining then exiting', signal.Signals(signum).name)
    _shutdown.set()


def main(argv: list[str] | None = None) -> int:
    del argv
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    queue_url = os.getenv('DOCSURI_EVIDENCE_JOB_QUEUE_URL')
    if not queue_url:
        log.error('DOCSURI_EVIDENCE_JOB_QUEUE_URL not set; nothing to consume')
        return 1

    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    from .real_wiring import build_evidence_orchestrator
    from .repository import SqlEvidenceRepository
    from .settings import EvidenceSettings

    ev_settings = EvidenceSettings.from_env()
    if not ev_settings.evidence_enabled:
        log.error('DOCSURI_DOCMODEL_BUCKET not set; evidence real path not configured')
        return 1

    # NFR-C1: 워커 프로세스별 cost guard (novelty/summarization 워커와 동일 패턴).
    # ponytail: 프로세스별 근사 카운터 — 공유 예산 권위가 생기면 교체.
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker

    bundle = build_evidence_orchestrator(ev_settings, cost_guard=CostGuardCircuitBreaker())
    orchestrator = bundle.orchestrator

    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    def repo_factory() -> EvidenceRepository:
        return SqlEvidenceRepository(session_factory())

    import boto3

    sqs = boto3.client(
        'sqs',
        region_name=ev_settings.region_name or 'ap-northeast-2',
    )

    def receive() -> list[_Message]:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=10,
            WaitTimeSeconds=20,
        )
        return parse_received_messages(
            resp.get('Messages', []),
            on_poison=lambda msg: sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=msg['ReceiptHandle']
            ),
        )

    def ack(message: _Message) -> None:
        if message.receipt_handle:
            sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message.receipt_handle)

    log.info('evidence agent worker started; polling queue')
    run_worker(
        repo_factory=repo_factory,
        orchestrator=orchestrator,
        receive=receive,
        ack=ack,
        should_stop=_shutdown.is_set,
        user_docmodel=_build_user_docmodel(),
    )
    log.info('evidence agent worker shut down gracefully')
    return 0


def _attachment_inputs(
    *,
    owner_id: str,
    scope_id: str,
    attachment_docs: list[dict[str, Any]],
    user_docmodel: Any,
):
    from .attachments import attachment_inputs_from_dicts

    return attachment_inputs_from_dicts(
        owner_id=owner_id,
        scope_id=scope_id,
        attachments=attachment_docs,
        user_docmodel=user_docmodel,
    )


def _build_user_docmodel():
    from backend.modules.user_docmodel import build_default_user_docmodel_coordinator

    return build_default_user_docmodel_coordinator()


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
