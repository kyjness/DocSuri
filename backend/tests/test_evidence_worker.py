from __future__ import annotations

import json

import pytest
from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult, EvidenceRequest

from backend.modules.evidence.models import (
    AgentRunContext,
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

class _StubOrchestrator:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[EvidenceRequest] = []
        self.contexts: list[AgentRunContext] = []

    def run(self, ctx: AgentRunContext, request: EvidenceRequest):
        self.calls += 1
        self.requests.append(request)
        self.contexts.append(ctx)
        return TurnAbstainResult(
            outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
        )


def _seeded_repo() -> tuple[InMemoryEvidenceRepository, str, str]:
    repo = InMemoryEvidenceRepository()
    session = repo.create_session(EvidenceSession(owner_id='owner-1'))
    turn = EvidenceTurn(session_id=session.session_id, result=TurnPendingResult(job_id='job-1'))
    repo.add_turn(turn)
    return repo, session.session_id, turn.turn_id


def test_pending_turn_is_processed_once() -> None:
    repo, session_id, turn_id = _seeded_repo()
    orchestrator = _StubOrchestrator()

    process_job(
        repo, orchestrator=orchestrator, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, job_id='job-1', topic='transformer attention',
    )

    assert orchestrator.calls == 1
    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnAbstainResult)


def test_parse_sqs_payload_preserves_attachment_handles() -> None:
    fields = parse_sqs_payload(
        json.dumps({
            'ownerId': 'owner-1',
            'sessionId': 'session-1',
            'turnId': 'turn-1',
            'jobId': 'job-1',
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
            'jobId': 'job-1',
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
    orchestrator = _StubOrchestrator()

    process_job(
        repo, orchestrator=orchestrator, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, job_id='job-1', topic='attachment handling',
        attachments=['att-1', 'att-2'],
    )

    assert orchestrator.requests[0].attachments == ['att-1', 'att-2']


def test_worker_polls_user_pdf_attachment_docmodel() -> None:
    from types import SimpleNamespace

    repo, session_id, turn_id = _seeded_repo()
    orchestrator = _StubOrchestrator()

    class _FakeUserDocModel:
        def __init__(self) -> None:
            self.refs = []

        def enqueue_and_poll(self, ref):
            self.refs.append(ref)
            return SimpleNamespace(fullText='PDF worker text', sections=[])

    process_job(
        repo,
        orchestrator=orchestrator,
        owner_id='owner-1',
        session_id=session_id,
        turn_id=turn_id,
        job_id='job-1',
        topic='attachment handling',
        attachment_docs=[
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
        user_docmodel=_FakeUserDocModel(),
    )

    docs = orchestrator.contexts[0].attachment_docs
    assert docs[0].paper_id == 'userdoc:11111111-1111-4111-8111-111111111111'
    assert docs[0].doc_model.fullText == 'PDF worker text'


def test_duplicate_delivery_of_already_resolved_turn_is_skipped() -> None:
    """SQS at-least-once로 동일 job이 두 번 배달돼도 orchestrator가 두 번 실행되지 않는다."""
    repo, session_id, turn_id = _seeded_repo()
    orchestrator = _StubOrchestrator()

    process_job(
        repo, orchestrator=orchestrator, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, job_id='job-1', topic='transformer attention',
    )
    process_job(  # 중복 배달
        repo, orchestrator=orchestrator, owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, job_id='job-1', topic='transformer attention',
    )

    assert orchestrator.calls == 1


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


def test_orchestrator_failure_stores_error_result_and_raises() -> None:
    repo, session_id, turn_id = _seeded_repo()

    class _FailingOrchestrator:
        def run(self, ctx, request):
            raise RuntimeError('bedrock throttled')

    with pytest.raises(JobProcessingFailed):
        process_job(
            repo, orchestrator=_FailingOrchestrator(), owner_id='owner-1', session_id=session_id,
            turn_id=turn_id, job_id='job-1', topic='transformer attention',
        )

    from backend.modules.evidence.models import TurnErrorResult

    resolved = repo.list_turns('owner-1', session_id)[0]
    assert isinstance(resolved.result, TurnErrorResult)
    # PR #338 리뷰 Medium #11 — 원인 불문 'llm_unavailable'로 못박던 것을 비기술 범용
    # 코드로 정정: 여기선 RuntimeError('bedrock throttled')인데도 LLM 문제로 오도되면 안 된다.
    assert resolved.result.error_code == 'internal_error'


def test_soft_deleted_session_turn_is_terminated_not_left_pending() -> None:
    """PR #338 리뷰 Medium #12 — 세션이 소프트 삭제된 뒤 도착한 job은 turn을 pending으로
    방치하면 안 된다(GET /jobs/{id}가 영원히 pending을 반환하게 됨)."""
    repo, session_id, turn_id = _seeded_repo()
    repo.soft_delete_session('owner-1', session_id)

    process_job(
        repo, orchestrator=_StubOrchestrator(), owner_id='owner-1', session_id=session_id,
        turn_id=turn_id, job_id='job-1', topic='transformer attention',
    )

    from backend.modules.evidence.models import TurnErrorResult

    turns = repo._turns[session_id]  # soft-delete 후 list_turns는 세션 자체를 못 찾으므로 직접 조회
    resolved = next(t for t in turns if t.turn_id == turn_id)
    assert isinstance(resolved.result, TurnErrorResult)
    assert resolved.result.error_code == 'session_unavailable'
