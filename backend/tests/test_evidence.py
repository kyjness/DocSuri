from __future__ import annotations

from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from backend.app import create_app
from backend.config import Settings
from backend.modules.evidence import controller
from backend.modules.evidence.models import (
    EvidenceSession,
    TurnAbstainResult,
    TurnPendingResult,
    TurnSuccessResult,
)
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.service import (
    EvidenceChatService,
    EvidenceSessionManagementService,
)


def _instant_stale():
    """하트비트가 끊긴 즉시 고아로 보는 실행 설정 — 테스트가 10분을 기다리지 않게."""
    from datetime import timedelta

    from backend.modules.evidence.settings import TurnExecutionSettings

    return TurnExecutionSettings(stale_after=timedelta(0), poll_seconds=0.01)


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


class _StubRunner:
    """Orchestrator 없이 테스트 — real_wiring 없이 controller만 마운트."""

    def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
        return TurnAbstainResult(
            outcome=__import__(
                'docsuri_shared._generated.dtos.evidence_schema',
                fromlist=['EvidenceAbstainResult'],
            ).EvidenceAbstainResult(
                state='abstain',
                abstainReason='out_of_corpus',
            )
        )


class _StubCheckpoints:
    """체크포인트 없는 배포 — 고아 턴은 마감할 스냅샷이 없다."""

    enabled = False

    def finalize(self, turn_id, topic):
        return None

    def delete(self, turn_ids):
        return 0


class _InlineDispatch:
    """테스트용 실행자 — 수락 직후 같은 스레드에서 process_job을 돌린다.

    실서비스의 실행자(스레드풀·SQS 워커)와 같은 본문을 밟되 비동기만 걷어낸 것이라,
    '수락 → 실행 → 결과' 경로가 API 테스트에서 끝까지 보인다.
    """

    def __init__(self, app, repo, *, run_inline: bool = True) -> None:
        self._app = app
        self._repo = repo
        self.run_inline = run_inline
        # 러너는 더 이상 요청 의존이 아니다(실행자가 쥔다) — 테스트가 여기서 갈아끼운다.
        self.runner = _StubRunner()
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> None:
        self.payloads.append(payload)
        if not self.run_inline:
            return
        from backend.modules.evidence.worker import process_sqs_payload

        docmodel_dep = self._app.dependency_overrides.get(controller.get_user_docmodel)
        process_sqs_payload(
            lambda: self._repo,
            payload,
            runner=self.runner,
            user_docmodel=docmodel_dep() if docmodel_dep else None,
        )


def _client(monkeypatch, principal: Principal | None = None, repo=None) -> TestClient:
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[controller.get_principal] = lambda: principal or _principal()
    repo = repo if repo is not None else InMemoryEvidenceRepository()
    app.dependency_overrides[controller.get_repo] = lambda: repo
    app.dependency_overrides[controller.get_repo_factory] = lambda: (lambda: repo)
    app.dependency_overrides[controller.get_checkpoints] = lambda: _StubCheckpoints()
    dispatch = _InlineDispatch(app, repo)
    app.dependency_overrides[controller.get_dispatch] = lambda: dispatch
    client = TestClient(app)
    client.dispatch = dispatch  # type: ignore[attr-defined]
    return client


class _FakeUserDocModel:
    def __init__(self, doc_model=None) -> None:
        self.doc_model = doc_model
        self.uploads: list[dict] = []
        self.enqueued: list[object] = []
        self.polled: list[object] = []

    def upload_pdf(self, ref, pdf: bytes, *, file_name: str, content_type: str) -> None:
        self.uploads.append(
            {
                "ref": ref,
                "pdf": pdf,
                "file_name": file_name,
                "content_type": content_type,
            }
        )

    def enqueue_build(self, ref) -> None:
        self.enqueued.append(ref)

    def enqueue_and_poll(self, ref):
        self.polled.append(ref)
        return self.doc_model


def _doc_model(full_text: str):
    from types import SimpleNamespace

    return SimpleNamespace(fullText=full_text, sections=[])


# ---------------------------------------------------------------------------
# PBT-EV-1: INV-EV-2 — claims=[] 이면 반드시 abstain 반환
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# PBT-EV-2: INV-EV-1 / SEC-9 — 소유권 불일치 → KeyError (→ 404)
# ---------------------------------------------------------------------------

@given(
    st.text(alphabet='abcdef0123456789-', min_size=36, max_size=36),
    st.text(alphabet='abcdef0123456789-', min_size=36, max_size=36),
)
def test_cross_owner_session_read_raises_key_error(owner_a: str, owner_b: str) -> None:
    if owner_a == owner_b:
        return

    repo = InMemoryEvidenceRepository()
    session = EvidenceSession(owner_id=owner_a)
    repo.create_session(session)

    try:
        repo.get_session(owner_b, session.session_id)
    except KeyError:
        pass
    else:
        raise AssertionError('cross-owner session read must raise KeyError (SEC-9 → 404)')


# ---------------------------------------------------------------------------
# PBT-EV-3: INV-EV-5 — TurnResult 직렬화에 벡터 점수 미포함
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 단위: 세션 소프트 삭제 (BR-EV-8)
# ---------------------------------------------------------------------------

def test_soft_delete_hides_session() -> None:
    repo = InMemoryEvidenceRepository()
    owner = str(uuid4())
    session = EvidenceSession(owner_id=owner)
    repo.create_session(session)

    assert len(repo.list_sessions(owner)) == 1
    repo.soft_delete_session(owner, session.session_id)
    assert repo.list_sessions(owner) == []

    # 삭제 후 get_session도 KeyError (INV-EV-1 / SEC-9)
    try:
        repo.get_session(owner, session.session_id)
    except KeyError:
        pass
    else:
        raise AssertionError('deleted session must not be retrievable')


# ---------------------------------------------------------------------------
# 단위: 전체 초기화 (BR-EV-9)
# ---------------------------------------------------------------------------

def test_reset_all_only_affects_owner() -> None:
    repo = InMemoryEvidenceRepository()
    owner_a = str(uuid4())
    owner_b = str(uuid4())

    for _ in range(3):
        repo.create_session(EvidenceSession(owner_id=owner_a))
    repo.create_session(EvidenceSession(owner_id=owner_b))

    svc = EvidenceSessionManagementService(repo=repo)
    svc.reset_all(owner_a)

    assert repo.list_sessions(owner_a) == []
    assert len(repo.list_sessions(owner_b)) == 1


# ---------------------------------------------------------------------------
# 단위: 세션 목록 정렬 (BR-EV-10)
# ---------------------------------------------------------------------------

def test_list_sessions_returns_updated_at_desc() -> None:
    import time

    repo = InMemoryEvidenceRepository()
    owner = str(uuid4())

    s1 = EvidenceSession(owner_id=owner, title='first')
    repo.create_session(s1)
    time.sleep(0.01)
    s2 = EvidenceSession(owner_id=owner, title='second')
    repo.create_session(s2)

    sessions = repo.list_sessions(owner)
    assert sessions[0].session_id == s2.session_id  # 최신 우선


# ---------------------------------------------------------------------------
# API: POST /api/evidence/turns → 202 수락 → GET /turns/{id}에서 결과 (stub runner)
# ---------------------------------------------------------------------------

def test_api_create_turn_accepts_then_result_is_polled(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'transformer attention mechanism', 'scope': 'auto'},
    )

    assert resp.status_code == 202
    body = resp.json()
    assert body['result']['state'] == 'pending'
    assert body['result']['startedAt']
    assert 'jobId' not in body['result']
    assert 'sessionId' in body and 'turnId' in body

    done = client.get(f"/api/evidence/turns/{body['turnId']}")
    assert done.status_code == 200
    assert done.json()['result']['state'] == 'abstain'


def test_api_turn_accepts_fe_attachment_objects_not_500(monkeypatch) -> None:
    """FE는 AgentAttachment 객체를 보낸다 — 공유 계약(list[str] 핸들)로 변환되어야 한다(#268).

    종전에는 객체가 EvidenceRequest(attachments=list[str]) 생성에서 ValidationError → 500.
    """
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post(
        '/api/evidence/turns',
        json={
            'topic': 'attachment handling',
            'attachments': [
                {
                    'id': 'att-1',
                    'name': 'draft.pdf',
                    'kind': 'pdf',
                    'sizeBytes': 2048,
                    'status': 'ready',
                },
            ],
        },
    )

    assert resp.status_code == 202


def test_api_uploads_user_pdf_and_turn_polls_docmodel(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    fake_user_docmodel = _FakeUserDocModel(_doc_model("PDF extracted text"))
    captured: dict = {}

    class _CapturingRunner(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            captured["ctx"] = ctx
            captured["attachments"] = attachments
            return super().run(ctx, request)

    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )
    client.dispatch.runner = _CapturingRunner()

    uploaded = client.post(
        "/api/evidence/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    assert attachment["paperId"].startswith("userdoc:")
    assert attachment["recordRef"].startswith(f"upload:{principal.user_id}:userdoc-")
    assert "arxivRef" not in attachment

    turn = client.post(
        "/api/evidence/turns",
        json={"topic": "attachment handling", "attachments": [attachment]},
    )

    assert turn.status_code == 202
    assert fake_user_docmodel.uploads[0]["pdf"] == b"%PDF-1.4"
    assert fake_user_docmodel.enqueued[0].payload()["kind"] == "BUILD_USER_DOC_MODEL"
    assert fake_user_docmodel.polled[0].paper_id == attachment["paperId"]
    # 첨부는 실행 인자로 전달된다(러너가 확인 대상으로 seed한다) — 실행자가 핸들에서 재수화.
    docs = captured["attachments"]
    assert docs[0].paper_id == attachment["paperId"]
    assert docs[0].record_ref == attachment["recordRef"]
    assert docs[0].doc_model.fullText == "PDF extracted text"


def test_api_turn_rejects_forged_pdf_object_key_without_polling(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    fake_user_docmodel = _FakeUserDocModel(_doc_model("PDF extracted text"))
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )

    uploaded = client.post(
        "/api/evidence/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    attachment["objectKey"] = "uploads/evidence/other-user/att-1/att-1/scan.pdf"

    turn = client.post(
        "/api/evidence/turns",
        json={"topic": "attachment handling", "attachments": [attachment]},
    )

    assert turn.status_code == 422
    assert fake_user_docmodel.polled == []


def test_api_turn_rejects_invalid_pdf_identity_without_polling(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    fake_user_docmodel = _FakeUserDocModel(_doc_model("PDF extracted text"))
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )

    uploaded = client.post(
        "/api/evidence/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    attachment["paperId"] = "userdoc:not-a-uuid"

    turn = client.post(
        "/api/evidence/turns",
        json={"topic": "attachment handling", "attachments": [attachment]},
    )

    assert turn.status_code == 422
    assert fake_user_docmodel.polled == []


def test_api_turn_rejects_disallowed_attachment_kind_with_422(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post(
        '/api/evidence/turns',
        json={
            'topic': 'attachment handling',
            'attachments': [
                {'id': 'att-1', 'name': 'x.docx', 'kind': 'unknown', 'sizeBytes': 10},
            ],
        },
    )

    assert resp.status_code == 422


def test_api_turn_rejects_oversized_attachment_with_422(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post(
        '/api/evidence/turns',
        json={
            'topic': 'attachment handling',
            'attachments': [
                {
                    'id': 'att-1',
                    'name': 'big.pdf',
                    'kind': 'pdf',
                    'sizeBytes': 10 * 1024 * 1024 + 1,
                },
            ],
        },
    )

    assert resp.status_code == 422


def test_api_turn_rejects_invalid_scope_with_422(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'attachment handling', 'scope': 'invalid'},
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# API: 인증 없으면 401
# ---------------------------------------------------------------------------

def test_api_requires_authentication(monkeypatch) -> None:
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    # principal override 없음 → get_principal이 401 반환
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'test'},
    )

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# FR-38: 수락된 턴은 실행 전에 영속된다 — turnId가 세션 이력(list_turns)에서 조회된다
# ---------------------------------------------------------------------------

def test_api_accepted_turn_is_persisted(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'transformer attention', 'scope': 'auto'},
    )
    assert resp.status_code == 202
    body = resp.json()

    turns = repo.list_turns(principal.user_id, body['sessionId'])
    assert [t.turn_id for t in turns] == [body['turnId']]


def test_accept_turn_dispatch_payload_preserves_attachment_handles() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    repo = InMemoryEvidenceRepository()
    enqueued: list[dict] = []
    service = EvidenceChatService(repo=repo, dispatch=enqueued.append)

    resp = service.accept_turn(
        owner_id='owner-1',
        request=EvidenceRequest(
            topic='attachment handling',
            scope='auto',
            paperIds=[],
            attachments=['att-1', 'att-2'],
        ),
    )

    assert isinstance(resp.result, TurnPendingResult)
    assert enqueued[0]['attachments'] == ['att-1', 'att-2']
    assert enqueued[0]['attachmentDocs'] == []
    assert enqueued[0]['turnId'] == resp.turn_id
    assert 'jobId' not in enqueued[0]


def test_accept_turn_commits_before_dispatch_and_closes_on_dispatch_failure() -> None:
    """dispatch가 실패하면 pending 행이 세션 잠금으로 남지 않는다 — error로 닫고 올린다."""
    import pytest as _pytest
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import TurnErrorResult
    from backend.modules.evidence.service import DispatchFailed

    repo = InMemoryEvidenceRepository()
    seen: list[str] = []

    def failing_dispatch(payload: dict) -> None:
        # 실행자 스레드는 수락 직후 출발한다 — 이 시점에 행이 보여야 한다.
        seen.append(repo.get_turn('o1', payload['turnId']).turn_id)
        raise RuntimeError('queue down')

    service = EvidenceChatService(repo=repo, dispatch=failing_dispatch)
    with _pytest.raises(DispatchFailed):
        service.accept_turn(owner_id='o1', request=EvidenceRequest(topic='q'))

    session = repo.list_sessions('o1')[0]
    turn = repo.list_turns('o1', session.session_id)[0]
    assert seen == [turn.turn_id]
    assert isinstance(turn.result, TurnErrorResult)
    assert turn.result.error_code == 'dispatch_failed'
    assert repo.active_turn('o1', session.session_id) is None  # 잠금이 풀렸다


# ---------------------------------------------------------------------------
# SEC-5: topic 길이 검증 정렬 — 500 금지 (PR #338 리뷰 Blocking #3)
# ---------------------------------------------------------------------------

def test_api_topic_2000_succeeds_not_500(monkeypatch) -> None:
    """controller(2000)와 DTO(옛 1000) 상한 불일치로 1001~2000자 topic이 handler 내부
    Pydantic ValidationError→HTTP 500으로 떨어지던 회귀. DTO를 2000으로 정렬 후 200(abstain)."""
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post('/api/evidence/turns', json={'topic': 'a' * 2000, 'scope': 'auto'})

    assert resp.status_code == 202
    done = client.get(f"/api/evidence/turns/{resp.json()['turnId']}")
    assert done.json()['result']['state'] == 'abstain'


def test_api_topic_over_2000_rejected_with_422(monkeypatch) -> None:
    """topic 경계(2000) 초과는 요청 검증(422)에서 걸러진다 — 500이 아니다."""
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post('/api/evidence/turns', json={'topic': 'a' * 2001})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# FR-37: 멀티턴 검색 맥락화 (PR #338 리뷰 Blocking #2 — buildable 절반)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# US-EV2(#266) AC3 — 쟁점 오버레이: 지지/상충 출처가 API 응답 한 항목에 함께 실린다
# ---------------------------------------------------------------------------

def _success_result_with_conflict() -> TurnSuccessResult:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
        SourceRef,
    )

    return TurnSuccessResult(
        outcome=EvidenceResult(
            state='ok',
            claims=[
                EvidenceItem(
                    statement='self-attention reduces sequential operations',
                    supporting=[
                        SourceRef(
                            paperId='2401.00001',
                            recordRef='rec-1',
                            quote='a constant number of sequential operations',
                        )
                    ],
                    conflicting=[
                        SourceRef(
                            paperId='2401.00002',
                            recordRef='rec-2',
                            quote='recurrence remains faster for short sequences',
                        )
                    ],
                )
            ],
            coverage=EvidenceCoverage(paperCount=2, queryUsed='self-attention'),
        ),
        resolved_paper_ids=('2401.00001', '2401.00002'),
    )


def test_api_turn_serializes_conflict_overlay_with_both_source_kinds(monkeypatch) -> None:
    """상충 출처가 있는 근거 명제는 지지/상충 출처가 함께 표시된다(쟁점 오버레이)."""
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    class _ConflictOrchestrator(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            return _success_result_with_conflict()

    client.dispatch.runner = _ConflictOrchestrator()

    resp = client.post('/api/evidence/turns', json={'topic': 'self-attention', 'scope': 'auto'})

    assert resp.status_code == 202
    done = client.get(f"/api/evidence/turns/{resp.json()['turnId']}")
    claim = done.json()['result']['claims'][0]
    assert [ref['paperId'] for ref in claim['supporting']] == ['2401.00001']
    assert [ref['paperId'] for ref in claim['conflicting']] == ['2401.00002']
    assert claim['conflicting'][0]['quote']  # 상충 출처도 원문 인용을 유지한다


# ---------------------------------------------------------------------------
# v3 §5.1 — 수락 → 실행자 → 같은 turn_id로 폴링. 요청 스레드는 orchestrator를 돌리지 않는다.
# ---------------------------------------------------------------------------

def test_api_turn_lifecycle_pending_then_executor_then_polled_terminal(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    client.dispatch.run_inline = False  # 실행자가 아직 집지 않은 상태를 흉내 낸다

    class _MustNotRunInline(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            raise AssertionError('the request thread must not run the orchestrator')

    client.dispatch.runner = _MustNotRunInline()

    # 1단계 — 결과 확정 전 즉시 pending
    resp = client.post(
        '/api/evidence/turns', json={'topic': 'transformer attention', 'scope': 'auto'}
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body['result']['state'] == 'pending'
    turn_id = body['turnId']
    assert client.dispatch.payloads[0]['turnId'] == turn_id
    assert client.dispatch.payloads[0]['topic'] == 'transformer attention'

    # 2단계 — 실행 중 폴링은 pending
    polled = client.get(f'/api/evidence/turns/{turn_id}')
    assert polled.status_code == 200
    assert polled.json()['result']['state'] == 'pending'

    # 3단계 — 실행자가 턴을 terminal로 전이
    from backend.modules.evidence.worker import process_job

    class _ResolvingOrchestrator(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            return _success_result_with_conflict()

    msg = client.dispatch.payloads[0]
    process_job(
        lambda: repo,
        runner=_ResolvingOrchestrator(),
        owner_id=msg['ownerId'],
        session_id=msg['sessionId'],
        turn_id=msg['turnId'],
        topic=msg['topic'],
    )

    # 4단계 — 같은 폴링 표면에서 terminal 결과(쟁점 오버레이 포함)
    done = client.get(f'/api/evidence/turns/{turn_id}')
    assert done.status_code == 200
    result = done.json()['result']
    assert result['state'] == 'ok'
    assert result['claims'][0]['supporting'][0]['paperId'] == '2401.00001'
    assert result['claims'][0]['conflicting'][0]['paperId'] == '2401.00002'


def test_api_second_turn_on_a_busy_session_is_409_and_refunds_quota(monkeypatch) -> None:
    """세션당 진행 중 턴 하나(§5.4) — 수락되지 않은 턴은 쿼터를 소모하지 않는다."""
    principal = _principal()
    client = _client(monkeypatch, principal, InMemoryEvidenceRepository())
    client.dispatch.run_inline = False
    refunds: list[str] = []

    async def fake_refund(request):
        refunds.append('evidence')

    monkeypatch.setattr(controller, 'refund_evidence_turn_quota', fake_refund)

    first = client.post('/api/evidence/turns', json={'topic': 'q1'})
    assert first.status_code == 202
    session_id = first.json()['sessionId']

    second = client.post('/api/evidence/turns', json={'topic': 'q2', 'sessionId': session_id})
    assert second.status_code == 409
    assert refunds == ['evidence']
    # 새 세션은 막히지 않는다
    other = client.post('/api/evidence/turns', json={'topic': 'q3'})
    assert other.status_code == 202


def test_api_cancel_sets_the_flag_and_the_executor_sees_it(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    client.dispatch.run_inline = False

    resp = client.post('/api/evidence/turns', json={'topic': 'q'})
    turn_id = resp.json()['turnId']

    cancelled = client.post(f'/api/evidence/turns/{turn_id}/cancel')
    assert cancelled.status_code == 200
    assert cancelled.json() == {'turnId': turn_id, 'state': 'pending', 'cancelRequested': True}
    assert repo.heartbeat(principal.user_id, turn_id) is True  # 실행자가 읽는 것

    # 실행자가 집으면 루프 없이 취소로 마감된다
    from backend.modules.evidence.worker import process_job

    class _MustNotRun(_StubRunner):
        def run(self, *a, **k):
            raise AssertionError('cancelled before start must not run the loop')

    msg = client.dispatch.payloads[0]
    process_job(lambda: repo, runner=_MustNotRun(), owner_id=msg['ownerId'],
                session_id=msg['sessionId'], turn_id=turn_id, topic=msg['topic'])
    done = client.get(f'/api/evidence/turns/{turn_id}').json()
    assert (done['result']['state'], done['result']['abstainReason']) == ('abstain', 'cancelled')

    # 끝난 턴의 취소는 409, 남의/없는 턴은 404
    assert client.post(f'/api/evidence/turns/{turn_id}/cancel').status_code == 409
    assert client.post('/api/evidence/turns/nope/cancel').status_code == 404


def test_api_stale_turn_is_finalized_from_the_checkpoint_on_poll(monkeypatch) -> None:
    """실행자가 죽은 턴(하트비트 없음)은 폴링이 마지막 스냅샷으로 부분 답을 만든다(§5.5)."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    client.dispatch.run_inline = False
    client.app.state.evidence_execution = _instant_stale()

    class _CheckpointedRun(_StubCheckpoints):
        enabled = True

        def finalize(self, turn_id, topic):
            return _success_result_with_conflict()

    client.app.dependency_overrides[controller.get_checkpoints] = lambda: _CheckpointedRun()

    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']
    done = client.get(f'/api/evidence/turns/{turn_id}').json()
    assert done['result']['state'] == 'ok'
    # 마감된 턴은 잠금이 아니다 — 같은 세션에 다음 질문이 들어간다
    follow = client.post(
        '/api/evidence/turns', json={'topic': 'q2', 'sessionId': done['sessionId']}
    )
    assert follow.status_code == 202


def test_api_stale_turn_without_a_snapshot_closes_as_internal_error(monkeypatch) -> None:
    principal = _principal()
    client = _client(monkeypatch, principal, InMemoryEvidenceRepository())
    client.dispatch.run_inline = False
    client.app.state.evidence_execution = _instant_stale()

    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']
    done = client.get(f'/api/evidence/turns/{turn_id}').json()
    assert (done['result']['state'], done['result']['errorCode']) == ('error', 'internal_error')


def test_session_crud_works_without_a_configured_agent(monkeypatch) -> None:
    """repo-only 배포(러너 미구성)에서도 세션 표면은 산다.

    회귀: 체크포인트 정리를 러너에 매달았더니 세션 삭제·초기화가 러너 의존을 선언하게 됐고,
    러너가 구성되지 않는 배포에서 `RuntimeError` → 500이 났다.
    """
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    monkeypatch.delenv('DOCSURI_DOCMODEL_BUCKET', raising=False)
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[controller.get_principal] = lambda: principal
    app.dependency_overrides[controller.get_repo] = lambda: repo
    client = TestClient(app)

    session = repo.create_session(EvidenceSession(owner_id=principal.user_id))
    assert client.get('/api/evidence/sessions').status_code == 200
    assert client.delete(f'/api/evidence/sessions/{session.session_id}').status_code == 204
    assert client.delete('/api/evidence/sessions').status_code == 204


def test_api_cancel_that_loses_the_race_to_completion_is_409(monkeypatch) -> None:
    """get_turn(pending)과 조건부 UPDATE 사이에 턴이 끝나면 취소된 척하지 않는다."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    client.dispatch.run_inline = False
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']

    original = repo.request_cancel

    def finish_then_cancel(owner_id, tid):
        repo.update_turn_result(owner_id, tid, TurnAbstainResult(
            outcome=__import__('docsuri_shared._generated.dtos.evidence_schema',
                               fromlist=['EvidenceAbstainResult']).EvidenceAbstainResult(
                state='abstain', abstainReason='out_of_corpus')))
        return original(owner_id, tid)

    monkeypatch.setattr(repo, 'request_cancel', finish_then_cancel)
    assert client.post(f'/api/evidence/turns/{turn_id}/cancel').status_code == 409


def test_api_turn_without_an_executor_is_503_and_refunds_quota(monkeypatch) -> None:
    """repo-only 배포 — 의존성 단계에서 503이 나면 먼저 오른 쿼터를 못 되돌린다."""
    principal = _principal()
    client = _client(monkeypatch, principal, InMemoryEvidenceRepository())
    client.app.dependency_overrides[controller.get_dispatch] = lambda: None
    refunds: list[str] = []

    async def fake_refund(request):
        refunds.append('evidence')

    monkeypatch.setattr(controller, 'refund_evidence_turn_quota', fake_refund)

    assert client.post('/api/evidence/turns', json={'topic': 'q'}).status_code == 503
    assert refunds == ['evidence']


def test_api_unpicked_turn_waits_three_times_longer_before_stale_finalize(monkeypatch) -> None:
    """실행자가 한 번도 집지 않은 턴(큐 대기)은 실행 중 고아보다 3배 길게 기다린다."""
    from datetime import timedelta

    from backend.modules.evidence.settings import TurnExecutionSettings

    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    client.dispatch.run_inline = False
    client.app.state.evidence_execution = TurnExecutionSettings(
        stale_after=timedelta(seconds=10), poll_seconds=0.01
    )
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']
    turn = repo.get_turn(principal.user_id, turn_id)
    turn.created_at = turn.created_at - timedelta(seconds=20)  # 10s 기준은 넘었지만 30s는 아직

    assert client.get(f'/api/evidence/turns/{turn_id}').json()['result']['state'] == 'pending'
    turn.created_at = turn.created_at - timedelta(seconds=20)  # 이제 40s
    assert client.get(f'/api/evidence/turns/{turn_id}').json()['result']['state'] == 'error'


def test_api_jobs_polling_surface_is_gone(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())
    assert client.get('/api/evidence/jobs/anything').status_code in {404, 405}


# v1에서 사라진 테스트들의 행방(대상이 없어진 것이지 커버리지가 준 것이 아니다):
#   - 비용 게이트 3종        → test_evidence_runner.py (루프 시작 전 차단)
#   - 이전 topic 이어붙이기   → 폐기. 후속 질문 해석이 루프 판단으로 이관됐다(FR-36 v2)
#   - 첨부를 추출 대상에 포함 → test_evidence_runner.py (검색 없이 확인 대상이 된다)
#   - Bedrock 지출 기록      → test_evidence_llm.py (토큰이 없으면 계상하지 않는다)


def test_executor_crash_leaves_a_terminal_turn_not_a_phantom_pending() -> None:
    """러너가 예상 밖 예외를 던져도 턴은 error로 종단된다 — pending 유령 턴이 남으면
    폴링·이벤트가 끝나지 않고 세션 잠금이 stale 시간까지 막힌다."""
    import pytest as _pytest
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import TurnErrorResult
    from backend.modules.evidence.worker import JobProcessingFailed, process_job

    class _ExplodingRunner(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            raise RuntimeError('unexpected')

    repo = InMemoryEvidenceRepository()
    payloads: list[dict] = []
    service = EvidenceChatService(repo=repo, dispatch=payloads.append)
    resp = service.accept_turn(owner_id='o1', request=EvidenceRequest(topic='q'))

    with _pytest.raises(JobProcessingFailed):
        process_job(lambda: repo, runner=_ExplodingRunner(), owner_id='o1',
                    session_id=resp.session_id, turn_id=resp.turn_id, topic='q')

    turns = repo.list_turns('o1', resp.session_id)
    assert isinstance(turns[0].result, TurnErrorResult)
    assert turns[0].result.error_code == 'internal_error'


def test_formation_port_reports_the_real_error_code_not_a_made_up_reason(caplog) -> None:
    """U12가 쓰는 포트가 실패 사유를 지어내면 안 된다.

    종전에는 어떤 `TurnErrorResult`든 `llm_unavailable`로 못박고 로그도 남기지 않아,
    novelty 산출물에는 "LLM 사용 불가"라고 적히는데 워커 로그에는 아무 것도 없었다
    (2026-08-24 실측). 원인이 지워지면 조용한 열화가 된다.
    """
    import asyncio
    import logging

    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import TurnErrorResult
    from backend.modules.evidence.service import EvidenceFormationService

    class _FailingRunner(_StubRunner):
        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            return TurnErrorResult(error_code='internal_error')

    service = EvidenceFormationService(runner=_FailingRunner())
    ctx = type('Ctx', (), {'owner_id': 'o1', 'request_id': 'r1'})()

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(service.form_evidence(EvidenceRequest(topic='q'), ctx))

    assert result.state == 'abstain'
    assert result.abstainReason == 'internal_error'
    assert any('internal_error' in record.getMessage() for record in caplog.records)
