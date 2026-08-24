"""Evidence 턴 실행자 — `process_job`이 본체이고, SQS 폴링 워커는 그 껍데기 중 하나다.

턴은 항상 백그라운드다(v3 §5.1). 실행자가 SQS 워커 프로세스인지 API 프로세스 안의
스레드(`executor.LocalTurnExecutor`)인지는 배포 환경이 정하고, 둘 다 여기 `process_job`을
돌린다. 긴 트랜잭션을 들지 않는다 — 조회는 짧은 세션 하나로 끝내고, 이후 하트비트·취소·
트레이스·결과는 `TurnControl`이 호출마다 커밋한다(이유는 그 모듈 docstring).

메시지 페이로드:
  {
    "ownerId": "<uuid>",
    "sessionId": "<uuid>",
    "turnId": "<uuid>",
    "topic": "...",
    "scope": "auto" | "explicit" | "mixed",
    "paperIds": ["..."],
    "attachments": ["attachment-handle", "..."],
    "attachmentDocs": [{...}]
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
from datetime import timedelta
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest, EvidenceScope

from .domain.models import LoopState, TerminationReason, utc_now
from .models import EvidenceTurn, TurnErrorResult, TurnPendingResult, to_turn_result
from .repository import EvidenceRepository, in_transaction
from .service import build_run_context
from .turn_control import TurnControl

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
    repo_factory: Callable[[], EvidenceRepository],
    body: str | bytes | dict[str, Any],
    *,
    runner: Any,
    user_docmodel: Any = None,
    shutdown: threading.Event | None = None,
    checkpoints: Any = None,
    checkpoint_retention: timedelta | None = None,
) -> None:
    fields = parse_sqs_payload(body)
    process_job(
        repo_factory,
        runner=runner,
        user_docmodel=user_docmodel,
        shutdown=shutdown,
        checkpoints=checkpoints,
        checkpoint_retention=checkpoint_retention,
        **fields,
    )


def _prepare_turn(
    repo: EvidenceRepository, *, owner_id: str, session_id: str, turn_id: str
) -> Any:
    """실행 전 관문 — 소유권·존재·멱등을 한 짧은 트랜잭션에서 본다. 돌릴 수 없으면 None.

    "돌리지 않는다"에는 세 가지가 섞여 있고 셋 다 turn을 pending으로 방치하면 안 된다:
    세션이 사라졌거나(소프트 삭제·소유자 불일치) 턴이 없거나, 이미 종단이라 재배달인 경우.
    """
    try:
        repo.get_session(owner_id, session_id)
    except KeyError:
        log.warning('evidence turn %s: session %s not found or wrong owner', turn_id, session_id)
        # pending으로 두면 폴링이 영원히 pending을 반환한다 — turn 자체는 owner_id로 갱신 가능.
        try:
            repo.update_turn_result(
                owner_id, turn_id, TurnErrorResult(error_code='session_unavailable')
            )
        except KeyError:
            log.warning('evidence turn %s also unavailable, nothing to terminate', turn_id)
        return None

    try:
        turn: EvidenceTurn | None = repo.get_turn(owner_id, turn_id)
    except KeyError:
        turn = None
    if turn is None:
        log.warning('evidence turn %s not found', turn_id)
        return None
    # 멱등 가드: 큐의 at-least-once 재배달로 같은 턴이 두 번 올 수 있다. 이미 pending을
    # 벗어났으면 재실행하지 않는다 — 이중 실행과 결과 clobber를 함께 막는다.
    if not isinstance(turn.result, TurnPendingResult):
        log.info('evidence turn %s already resolved, skipping duplicate delivery', turn_id)
        return None
    return build_run_context(
        repo, owner_id=owner_id, session_id=session_id, turn_id=turn_id, request_id=turn_id
    )


def process_job(
    repo_factory: Callable[[], EvidenceRepository],
    *,
    runner: Any,
    owner_id: str,
    session_id: str,
    turn_id: str,
    topic: str,
    scope: str = 'auto',
    paper_ids: list[str] | None = None,
    attachments: list[str] | None = None,
    attachment_docs: list[dict[str, Any]] | None = None,
    user_docmodel: Any = None,
    shutdown: threading.Event | None = None,
    checkpoints: Any = None,
    checkpoint_retention: timedelta | None = None,
) -> None:
    control = TurnControl(repo_factory, owner_id=owner_id, turn_id=turn_id, shutdown=shutdown)

    loop_ctx = in_transaction(
        repo_factory,
        lambda repo: _prepare_turn(
            repo, owner_id=owner_id, session_id=session_id, turn_id=turn_id
        ),
    )
    if loop_ctx is None:
        return

    # 수락과 실행 사이에 취소됐으면 루프를 시작하지 않는다(novelty `_finalize_cancelled`).
    if control.heartbeat():
        control.finish(_cancelled_before_start(topic))
        return

    # 여기부터는 무엇이 터져도 턴을 error로 닫는다 — 러너 앞(첨부 재수화의 S3 대기 등)에서
    # 죽으면 pending이 남아 세션이 stale 시간까지 잠긴다.
    try:
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
        docs = _attachment_inputs(
            owner_id=owner_id,
            scope_id=turn_id,
            attachment_docs=attachment_docs or [],
            user_docmodel=user_docmodel,
        )
        result = runner.run(
            loop_ctx,
            request,
            attachments=docs,
            on_trace=control.append_trace,
            should_stop=control.should_stop,
        )
    except Exception as exc:
        log.exception('evidence turn %s: runner failed', turn_id)
        # 검색/LLM 실패는 루프 안에서 이미 abstain으로 잡아낸다 — 여기까지 올라오는 건
        # 분류되지 않은 예상 밖 실패다. SEC-9상 원본 예외 메시지는 노출 불가하므로 비기술
        # 범용 코드로 정직하게 표현한다('llm_unavailable'로 못박으면 원인이 오도된다).
        control.finish(TurnErrorResult(error_code='internal_error'))
        raise JobProcessingFailed(str(exc)) from exc

    control.finish(result)
    _prune_checkpoints(repo_factory, checkpoints, checkpoint_retention)


def _cancelled_before_start(topic: str):
    """루프 없이 취소된 턴의 결과 — 후보 0편·근거 0건의 취소 기권."""
    return to_turn_result(LoopState(topic=topic), TerminationReason.CANCELLED, query_used=topic)


def _prune_checkpoints(
    repo_factory: Callable[[], EvidenceRepository], checkpoints: Any, retention: timedelta | None
) -> None:
    """보존 기간이 지난 종단 턴의 체크포인트 스레드를 지운다 — 턴 완료마다 상각(스케줄러 없음).

    지운 턴에는 도장을 찍는다. 도장이 없으면 같은 앞쪽 N건이 매번 다시 뽑혀 영원히 재삭제되고,
    그 뒤 턴들은 영영 정리되지 않는다 — 로그의 `pruned: N`은 계속 정상으로 보인다.
    """
    if retention is None or checkpoints is None or not checkpoints.enabled:
        return
    try:
        expired = in_transaction(
            repo_factory, lambda r: r.expired_turn_ids(utc_now() - retention)
        )
        if not expired:
            return
        deleted = checkpoints.delete(expired)
        in_transaction(repo_factory, lambda r: r.mark_checkpoints_pruned(expired))
        log.info('evidence checkpoints pruned: %d', deleted)
    except Exception:  # noqa: BLE001 — 정리 실패가 턴을 깨지 않는다
        log.warning('evidence checkpoint prune failed', exc_info=True)


def run_worker(
    *,
    repo_factory: Callable[[], EvidenceRepository],
    runner: Any,
    receive: Callable[[], Iterable[_Message]],
    ack: Callable[[_Message], None],
    should_stop: Callable[[], bool],
    user_docmodel: Any = None,
    shutdown: threading.Event | None = None,
    checkpoints: Any = None,
    checkpoint_retention: timedelta | None = None,
) -> None:
    while not should_stop():
        for message in receive():
            try:
                process_sqs_payload(
                    repo_factory,
                    message.body,
                    runner=runner,
                    user_docmodel=user_docmodel,
                    shutdown=shutdown,
                    checkpoints=checkpoints,
                    checkpoint_retention=checkpoint_retention,
                )
            except JobProcessingFailed:
                # 턴은 이미 error로 커밋됐다 — 메시지는 지운다(재배달해도 멱등 가드가 건너뛴다).
                log.exception('evidence job failed; error state committed')
            except Exception:  # noqa: BLE001 — leave unacked for retry/DLQ
                log.exception('evidence job failed; leaving message for redelivery')
                continue
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

    from .real_wiring import build_evidence_runner
    from .repository import SqlEvidenceRepository
    from .settings import EvidenceSettings

    ev_settings = EvidenceSettings.from_env()
    if not ev_settings.evidence_enabled:
        log.error('DOCSURI_DOCMODEL_BUCKET not set; evidence real path not configured')
        return 1

    # NFR-C1: 워커 프로세스별 cost guard (novelty/summarization 워커와 동일 패턴).
    # ponytail: 프로세스별 근사 카운터 — 공유 예산 권위가 생기면 교체.
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker

    settings = Settings.from_env()
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)

    # 체크포인터는 API와 같은 Postgres — setup은 멱등이라 워커가 먼저 떠도 된다.
    from .checkpoints import TurnCheckpoints, build_postgres_checkpointer

    checkpointer, close_checkpointer = build_postgres_checkpointer(
        settings.database_url, setup=True
    )
    checkpoints = TurnCheckpoints(checkpointer)
    runner = build_evidence_runner(
        ev_settings, cost_guard=CostGuardCircuitBreaker(), graph=checkpoints.graph
    )

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
        runner=runner,
        receive=receive,
        ack=ack,
        should_stop=_shutdown.is_set,
        user_docmodel=_build_user_docmodel(),
        shutdown=_shutdown,
        checkpoints=checkpoints,
        checkpoint_retention=timedelta(days=ev_settings.checkpoint_retention_days),
    )
    close_checkpointer()
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


# 엔트리포인트는 반드시 파일 끝이어야 한다 — `python -m`으로 실행하면 이 지점에서
# main()이 (무한 폴링으로) 돌기 시작하므로, 이 아래에 정의된 이름은 영원히 바인딩되지
# 않는다. 실제로 _append_trace가 이 블록 뒤에 있어 배포 경로에서만 NameError가 났고,
# advisory except가 삼켜 트레이스가 0건이 되는데 잡은 성공으로 보였다.
if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
