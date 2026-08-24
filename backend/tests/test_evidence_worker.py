from __future__ import annotations

import json

import pytest
from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult, EvidenceRequest

from backend.modules.evidence.models import (
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
    TurnPendingResult,
)
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.worker import (
    JobProcessingFailed,
    parse_received_messages,
    parse_sqs_payload,
    process_job,
)

# ---------------------------------------------------------------------------
# poison message 처리 (PR #338 리뷰 Blocking #3)
# ---------------------------------------------------------------------------

def test_poison_message_is_dropped_without_blocking_the_batch() -> None:
    dropped: list[dict] = []
    ok_body = json.dumps({'ownerId': 'o1', 'turnId': 't1', 'topic': 'x'})
    raw_messages = [
        {'Body': 'not valid json', 'ReceiptHandle': 'rh-poison'},
        {'Body': ok_body, 'ReceiptHandle': 'rh-ok'},
    ]

    messages = parse_received_messages(raw_messages, on_poison=dropped.append)

    assert len(messages) == 1
    assert messages[0].receipt_handle == 'rh-ok'
    assert len(dropped) == 1
    assert dropped[0]['ReceiptHandle'] == 'rh-poison'


def test_all_valid_messages_pass_through_untouched() -> None:
    body_a = json.dumps({'ownerId': 'o1', 'turnId': 't1', 'topic': 'a'})
    body_b = json.dumps({'ownerId': 'o2', 'turnId': 't2', 'topic': 'b'})
    raw_messages = [
        {'Body': body_a, 'ReceiptHandle': 'r1'},
        {'Body': body_b, 'ReceiptHandle': 'r2'},
    ]

    def _fail_on_poison(_msg: dict) -> None:
        pytest.fail('should not fire')

    messages = parse_received_messages(raw_messages, on_poison=_fail_on_poison)

    assert len(messages) == 2


# ---------------------------------------------------------------------------
# idempotency guard (PR #338 리뷰 Blocking #4)
# ---------------------------------------------------------------------------

class _StubRunner:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[EvidenceRequest] = []
        self.contexts: list = []
        self.attachments: list = []

    def run(self, ctx, request: EvidenceRequest, *, attachments=(), on_trace=None,
            should_stop=None):
        self.calls += 1
        self.requests.append(request)
        self.contexts.append(ctx)
        self.attachments.append(attachments)
        return TurnAbstainResult(
            outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
        )


def _seeded_repo() -> tuple[InMemoryEvidenceRepository, str, str]:
    repo = InMemoryEvidenceRepository()
    session = repo.create_session(EvidenceSession(owner_id='owner-1'))
    turn = EvidenceTurn(session_id=session.session_id, result=TurnPendingResult())
    repo.add_turn(turn)
    return repo, session.session_id, turn.turn_id


def test_pending_turn_is_processed_once() -> None:
    repo, session_id, turn_id = _seeded_repo()
    runner = _StubRunner()

    process_job(
        lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='transformer attention',
    )

    assert runner.calls == 1
    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnAbstainResult)


def test_parse_sqs_payload_preserves_attachment_handles() -> None:
    fields = parse_sqs_payload(
        json.dumps({
            'ownerId': 'owner-1',
            'sessionId': 'session-1',
            'turnId': 'turn-1',
            'topic': 'attachment handling',
            'attachments': ['att-1', 'att-2'],
        })
    )

    assert fields['attachments'] == ['att-1', 'att-2']


def test_parse_sqs_payload_preserves_attachment_doc_contract() -> None:
    fields = parse_sqs_payload(
        json.dumps({
            'ownerId': 'owner-1',
            'sessionId': 'session-1',
            'turnId': 'turn-1',
            'topic': 'attachment handling',
            'attachmentDocs': [
                {
                    'id': 'att-1',
                    'name': 'scan.pdf',
                    'kind': 'pdf',
                    'objectKey': 'uploads/evidence/owner-1/att-1/att-1/scan.pdf',
                    'paperId': 'userdoc:11111111-1111-4111-8111-111111111111',
                    'recordRef': (
                        'upload:owner-1:'
                        'userdoc-11111111-1111-4111-8111-111111111111:att-1'
                    ),
                },
            ],
        })
    )

    assert fields['attachment_docs'][0]['paperId'].startswith('userdoc:')


def test_worker_passes_attachment_handles_to_evidence_request() -> None:
    repo, session_id, turn_id = _seeded_repo()
    runner = _StubRunner()

    process_job(
        lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='attachment handling',
        attachments=['att-1', 'att-2'],
    )

    assert runner.requests[0].attachments == ['att-1', 'att-2']


def test_worker_polls_user_pdf_attachment_docmodel() -> None:
    from types import SimpleNamespace

    repo, session_id, turn_id = _seeded_repo()
    runner = _StubRunner()

    class _FakeUserDocModel:
        def __init__(self) -> None:
            self.refs = []

        def enqueue_and_poll(self, ref):
            self.refs.append(ref)
            return SimpleNamespace(fullText='PDF worker text', sections=[])

    # 식별자는 업로드 표면이 발급한 그대로여야 한다 — 임의 uuid는 거부된다
    # (서버가 인증된 owner_id에서 재유도해 대조한다).
    from backend.modules.user_docmodel import user_docmodel_ref

    issued = user_docmodel_ref(
        owner_id='owner-1',
        scope_id='att-1',
        attachment_id='att-1',
        object_key='uploads/evidence/owner-1/att-1/att-1/scan.pdf',
        module='evidence',
    )

    process_job(
        lambda: repo,
        runner=runner,
        owner_id='owner-1',
        session_id=session_id,
        turn_id=turn_id,
        topic='attachment handling',
        attachment_docs=[
            {
                'id': 'att-1',
                'name': 'scan.pdf',
                'kind': 'pdf',
                'objectKey': issued.object_key,
                'paperId': issued.paper_id,
                'recordRef': issued.record_ref,
            },
        ],
        user_docmodel=_FakeUserDocModel(),
    )

    docs = runner.attachments[0]
    assert docs[0].paper_id == issued.paper_id
    assert docs[0].doc_model.fullText == 'PDF worker text'


def test_duplicate_delivery_of_already_resolved_turn_is_skipped() -> None:
    """SQS at-least-once로 동일 job이 두 번 배달돼도 루프가 두 번 실행되지 않는다."""
    repo, session_id, turn_id = _seeded_repo()
    runner = _StubRunner()

    process_job(
        lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='transformer attention',
    )
    process_job(  # 중복 배달
        lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='transformer attention',
    )

    assert runner.calls == 1


def test_repository_update_turn_result_rejects_stale_overwrite() -> None:
    """update_turn_result 자체도 pending이 아닌 turn을 덮어쓰지 않는다(worker 우회 경로 대비)."""
    repo, session_id, turn_id = _seeded_repo()

    first_result = TurnAbstainResult(
        outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
    )
    repo.update_turn_result('owner-1', turn_id, first_result)
    from backend.modules.evidence.models import TurnErrorResult

    repo.update_turn_result('owner-1', turn_id, TurnErrorResult(error_code='llm_unavailable'))

    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnAbstainResult)  # 나중 결과로 clobber되지 않음


def test_runner_failure_stores_error_result_and_raises() -> None:
    repo, session_id, turn_id = _seeded_repo()

    class _FailingOrchestrator:
        def run(self, ctx, request, **kwargs):
            raise RuntimeError('bedrock throttled')

    with pytest.raises(JobProcessingFailed):
        process_job(
            lambda: repo, runner=_FailingOrchestrator(), owner_id='owner-1', session_id=session_id,
            turn_id=turn_id, topic='transformer attention',
        )

    from backend.modules.evidence.models import TurnErrorResult

    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnErrorResult)
    # PR #338 리뷰 Medium #11 — 원인 불문 'llm_unavailable'로 못박던 것을 비기술 범용
    # 코드로 정정: 여기선 RuntimeError('bedrock throttled')인데도 LLM 문제로 오도되면 안 된다.
    assert resolved.result.error_code == 'internal_error'


def test_soft_deleted_session_turn_is_terminated_not_left_pending() -> None:
    """PR #338 리뷰 Medium #12 — 세션이 소프트 삭제된 뒤 도착한 job은 turn을 pending으로
    방치하면 안 된다(GET /turns/{id}가 영원히 pending을 반환하게 됨)."""
    repo, session_id, turn_id = _seeded_repo()
    repo.soft_delete_session('owner-1', session_id)

    process_job(
        lambda: repo, runner=_StubRunner(), owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='transformer attention',
    )

    from backend.modules.evidence.models import TurnErrorResult

    turns = repo._turns[session_id]  # soft-delete 후 list_turns는 세션 자체를 못 찾으므로 직접 조회
    resolved = next(t for t in turns if t.turn_id == turn_id)
    assert isinstance(resolved.result, TurnErrorResult)
    assert resolved.result.error_code == 'session_unavailable'


# ---------------------------------------------------------------------------
# v3 §5.2 — 취소·중단은 실행자 경계에서
# ---------------------------------------------------------------------------

def test_cancel_before_pickup_finishes_without_running_the_loop() -> None:
    repo, session_id, turn_id = _seeded_repo()
    repo.request_cancel('owner-1', turn_id)
    runner = _StubRunner()

    process_job(
        lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='q',
    )

    assert runner.calls == 0
    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnAbstainResult)
    assert resolved.result.outcome.abstainReason == 'cancelled'


def test_should_stop_reads_the_flag_and_the_shutdown_event_each_super_step() -> None:
    """하트비트 한 번 = 취소 플래그 한 번 — 취소가 종료 신호보다 먼저다."""
    import threading

    from backend.modules.evidence.domain.models import TerminationReason

    repo, session_id, turn_id = _seeded_repo()
    shutdown = threading.Event()
    seen: list = []

    class _ProbingRunner(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            seen.append(should_stop())           # 아무 신호 없음
            shutdown.set()
            seen.append(should_stop())           # 종료 신호
            repo.request_cancel('owner-1', turn_id)
            seen.append(should_stop())           # 취소가 우선
            return super().run(ctx, request)

    process_job(
        lambda: repo, runner=_ProbingRunner(), owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='q', shutdown=shutdown,
    )

    assert seen == [None, TerminationReason.INTERRUPTED, TerminationReason.CANCELLED]
    assert repo.get_turn('owner-1', turn_id).heartbeat_at is not None


def test_trace_rows_are_committed_as_they_happen_not_with_the_result() -> None:
    """이벤트 스트림의 원천 — 러너가 도는 동안 다른 세션이 트레이스 행을 본다."""
    from backend.modules.evidence.domain.models import ToolCallOutcome, ToolCallRecord

    repo, session_id, turn_id = _seeded_repo()
    visible_during_run: list[int] = []

    class _TracingRunner(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            on_trace(ToolCallRecord(seq=1, tool='corpus_search', args_summary='q=a',
                                    outcome=ToolCallOutcome.OK))
            visible_during_run.extend(
                r['seq'] for r in repo.list_trace_after('owner-1', turn_id, 0)
            )
            return super().run(ctx, request)

    process_job(
        lambda: repo, runner=_TracingRunner(), owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='q',
    )

    assert visible_during_run == [1]


def _second_pending_turn(repo, session_id: str) -> str:
    turn = EvidenceTurn(session_id=session_id, result=TurnPendingResult())
    repo.add_turn(turn)
    return turn.turn_id


def test_completed_turn_prunes_expired_checkpoints() -> None:
    from datetime import timedelta

    repo, session_id, turn_id = _seeded_repo()
    old = EvidenceTurn(
        session_id=session_id, result=TurnAbstainResult(
            outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
        ),
    )
    old.created_at = old.created_at - timedelta(days=30)
    repo.add_turn(old)

    class _Checkpoints:
        enabled = True

        def __init__(self) -> None:
            self.deleted: list[str] = []

        def delete(self, turn_ids):
            self.deleted.extend(turn_ids)
            return len(self.deleted)

    checkpoints = _Checkpoints()
    process_job(
        lambda: repo, runner=_StubRunner(), owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, topic='q', checkpoints=checkpoints,
        checkpoint_retention=timedelta(days=7),
    )

    assert checkpoints.deleted == [old.turn_id]  # 방금 끝난 턴은 보존 기간 안이라 남는다

    # 정리 도장이 찍혔으므로 다음 턴이 같은 스레드를 다시 지우지 않는다 —
    # 도장이 없으면 앞쪽 N건만 영원히 재삭제되고 그 뒤는 영영 안 지워진다.
    checkpoints.deleted.clear()
    process_job(
        lambda: repo, runner=_StubRunner(), owner_id='owner-1',
        session_id=session_id, turn_id=_second_pending_turn(repo, session_id), topic='q2',
        checkpoints=checkpoints, checkpoint_retention=timedelta(days=7),
    )
    assert checkpoints.deleted == []


def test_failure_before_the_runner_still_closes_the_turn() -> None:
    """첨부 재수화(S3 대기)에서 죽어도 pending을 남기지 않는다 — 남기면 세션이 stale까지 잠긴다."""
    repo, session_id, turn_id = _seeded_repo()

    class _ExplodingDocModel:
        def enqueue_and_poll(self, ref):
            raise TimeoutError('s3')

    from backend.modules.user_docmodel import user_docmodel_ref

    issued = user_docmodel_ref(owner_id='owner-1', scope_id='att-1', attachment_id='att-1',
                               object_key='uploads/evidence/owner-1/att-1/att-1/scan.pdf',
                               module='evidence')
    runner = _StubRunner()
    with pytest.raises(JobProcessingFailed):
        process_job(
            lambda: repo, runner=runner, owner_id='owner-1', session_id=session_id,
            turn_id=turn_id, topic='q',
            attachment_docs=[{'id': 'att-1', 'name': 'scan.pdf', 'kind': 'pdf',
                              'objectKey': issued.object_key, 'paperId': issued.paper_id,
                              'recordRef': issued.record_ref}],
            user_docmodel=_ExplodingDocModel(),
        )

    from backend.modules.evidence.models import TurnErrorResult

    assert runner.calls == 0
    assert isinstance(repo.list_turns('owner-1', session_id)[0].result, TurnErrorResult)


def test_local_executor_closes_the_turn_when_the_payload_cannot_even_be_parsed() -> None:
    from backend.modules.evidence.executor import LocalTurnExecutor
    from backend.modules.evidence.models import TurnErrorResult

    repo, session_id, turn_id = _seeded_repo()
    executor = LocalTurnExecutor(repo_factory=lambda: repo, runner=_StubRunner(), workers=1)
    try:
        # topic이 없어 parse_sqs_payload가 던진다 — process_job 관문 앞이다.
        executor.submit({'ownerId': 'owner-1', 'sessionId': session_id, 'turnId': turn_id})
    finally:
        assert executor.close(timeout=5) is True
    assert isinstance(repo.get_turn('owner-1', turn_id).result, TurnErrorResult)
