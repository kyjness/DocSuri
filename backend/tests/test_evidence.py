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
    EvidenceTurn,
    TurnAbstainResult,
    TurnErrorResult,
    TurnPendingResult,
    TurnSuccessResult,
)
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.service import (
    EvidenceChatService,
    EvidenceSessionManagementService,
)


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


def _client(monkeypatch, principal: Principal | None = None, repo=None) -> TestClient:
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[controller.get_principal] = lambda: principal or _principal()
    if repo is not None:
        app.dependency_overrides[controller.get_repo] = lambda: repo

    # Orchestrator 없이 테스트 — real_wiring 없이 controller만 마운트
    class _StubRunner:
        def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
            return TurnAbstainResult(
                outcome=__import__(
                    'docsuri_shared._generated.dtos.evidence_schema',
                    fromlist=['EvidenceAbstainResult'],
                ).EvidenceAbstainResult(
                    state='abstain',
                    abstainReason='out_of_corpus',
                )
            )

    app.dependency_overrides[controller.get_runner] = lambda: _StubRunner()
    return TestClient(app)


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
# API: POST /api/evidence/turns → 201 + abstain (stub runner)
# ---------------------------------------------------------------------------

def test_api_create_turn_returns_turn_out(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'transformer attention mechanism', 'scope': 'auto'},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body['result']['state'] == 'abstain'
    assert 'sessionId' in body
    assert 'turnId' in body


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

    assert resp.status_code == 200


def test_api_uploads_user_pdf_and_turn_polls_docmodel(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)
    fake_user_docmodel = _FakeUserDocModel(_doc_model("PDF extracted text"))
    captured: dict = {}

    class _CapturingRunner:
        def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
            captured["ctx"] = ctx
            captured["attachments"] = attachments
            return TurnAbstainResult(
                outcome=__import__(
                    "docsuri_shared._generated.dtos.evidence_schema",
                    fromlist=["EvidenceAbstainResult"],
                ).EvidenceAbstainResult(
                    state="abstain",
                    abstainReason="out_of_corpus",
                )
            )

    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )
    client.app.dependency_overrides[controller.get_runner] = (
        lambda: _CapturingRunner()
    )

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

    assert turn.status_code == 200
    assert fake_user_docmodel.uploads[0]["pdf"] == b"%PDF-1.4"
    assert fake_user_docmodel.enqueued[0].payload()["kind"] == "BUILD_USER_DOC_MODEL"
    assert fake_user_docmodel.polled[0].paper_id == attachment["paperId"]
    # v2: 첨부는 컨텍스트가 아니라 실행 인자로 전달된다(러너가 확인 대상으로 seed한다).
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
# FR-38: 동기 경로 턴 영속화 (PR #338 리뷰 Blocking #1)
# ---------------------------------------------------------------------------

def test_api_sync_turn_is_persisted(monkeypatch) -> None:
    """동기 경로 실행 후 반환된 turnId가 세션 이력(list_turns)에서 조회돼야 한다.
    회귀: 동기 분기가 add_turn을 빠뜨려 저장된 턴이 0건이라 turnId를 되찾을 수 없었다."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)  # sqs_enqueue 미주입 → 동기 경로

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'transformer attention', 'scope': 'auto'},
    )
    assert resp.status_code == 200
    body = resp.json()

    turns = repo.list_turns(principal.user_id, body['sessionId'])
    assert [t.turn_id for t in turns] == [body['turnId']]


def test_async_turn_enqueue_preserves_attachment_handles() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    repo = InMemoryEvidenceRepository()
    enqueued: list[dict] = []
    service = EvidenceChatService(
        repo=repo,
        runner=object(),
        sqs_enqueue=enqueued.append,
    )

    resp = service.run_turn(
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


# ---------------------------------------------------------------------------
# SEC-5: topic 길이 검증 정렬 — 500 금지 (PR #338 리뷰 Blocking #3)
# ---------------------------------------------------------------------------

def test_api_topic_2000_succeeds_not_500(monkeypatch) -> None:
    """controller(2000)와 DTO(옛 1000) 상한 불일치로 1001~2000자 topic이 handler 내부
    Pydantic ValidationError→HTTP 500으로 떨어지던 회귀. DTO를 2000으로 정렬 후 200(abstain)."""
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post('/api/evidence/turns', json={'topic': 'a' * 2000, 'scope': 'auto'})

    assert resp.status_code == 200
    assert resp.json()['result']['state'] == 'abstain'


def test_api_topic_over_2000_rejected_with_422(monkeypatch) -> None:
    """topic 경계(2000) 초과는 요청 검증(422)에서 걸러진다 — 500이 아니다."""
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    resp = client.post('/api/evidence/turns', json={'topic': 'a' * 2001})

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# FR-37: 멀티턴 검색 맥락화 (PR #338 리뷰 Blocking #2 — buildable 절반)
# ---------------------------------------------------------------------------

def _cost_gate_ctx(budget_signal: dict):
    """비용 게이트 테스트용 최소 ctx/request — research 경로와 동일한 구성."""
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import AgentRunContext, EvidenceSession, EvidenceTurn

    request = EvidenceRequest(topic='t', paperIds=[])
    session = EvidenceSession(owner_id='o')
    ctx = AgentRunContext(
        session=session,
        current_turn=EvidenceTurn(session_id=session.session_id, request=request),
        owner_id='o',
        request_id='',
        budget_signal=budget_signal,
    )
    return ctx, request


class _NoToolAllowed:
    """비용 게이트 이후 어떤 tool도 호출되면 안 된다 — 속성 접근 자체가 실패."""

    def __getattr__(self, name: str):
        raise AssertionError('cost gate must run before any tool call')


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

    class _ConflictOrchestrator:
        def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
            return _success_result_with_conflict()

    client.app.dependency_overrides[controller.get_runner] = (
        lambda: _ConflictOrchestrator()
    )

    resp = client.post('/api/evidence/turns', json={'topic': 'self-attention', 'scope': 'auto'})

    assert resp.status_code == 200
    claim = resp.json()['result']['claims'][0]
    assert [ref['paperId'] for ref in claim['supporting']] == ['2401.00001']
    assert [ref['paperId'] for ref in claim['conflicting']] == ['2401.00002']
    assert claim['conflicting'][0]['quote']  # 상충 출처도 원문 인용을 유지한다


# ---------------------------------------------------------------------------
# US-EV2(#266) AC1 / NFR-P6 — 점진 표시의 현존 구현(비동기 잡 경로) 수명주기
# 토큰 스트리밍(SSE)은 미구현 — "스트리밍으로 점진 표시" AC 문구 대비 편차로 QA 리포트에
# 기록(스토리 오너 승인 필요). 여기서는 실제로 존재하는 점진 경로를 고정한다:
# pending 즉시 응답(결과 확정 전) → GET /jobs/{id} 폴링 → 동일 표면에서 terminal 결과.
# ---------------------------------------------------------------------------

def test_api_async_turn_progressive_lifecycle_pending_then_polled_terminal(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo)

    class _MustNotRunInline:
        """비동기 경로에서는 요청 스레드가 orchestrator를 실행하지 않는다(BR-EV-6) —
        pending 응답은 LLM/검색 작업 시작 전에 즉시 나가야 한다."""

        def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
            raise AssertionError('async path must not run the orchestrator inline')

    client.app.dependency_overrides[controller.get_runner] = lambda: _MustNotRunInline()
    enqueued: list[dict] = []
    client.app.state.evidence_sqs_enqueue = enqueued.append

    # 1단계 — 결과 확정 전 즉시 pending + jobId 반환
    resp = client.post(
        '/api/evidence/turns', json={'topic': 'transformer attention', 'scope': 'auto'}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body['result']['state'] == 'pending'
    job_id = body['result']['jobId']
    assert job_id
    assert enqueued[0]['jobId'] == job_id
    assert enqueued[0]['topic'] == 'transformer attention'

    # 2단계 — 실행 중 폴링은 같은 jobId로 pending을 반환
    polled = client.get(f'/api/evidence/jobs/{job_id}')
    assert polled.status_code == 200
    assert polled.json()['result']['state'] == 'pending'

    # 3단계 — 워커가 잡을 terminal로 전이(BR-EV-6)
    from backend.modules.evidence.worker import process_job

    class _ResolvingOrchestrator:
        def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
            return _success_result_with_conflict()

    msg = enqueued[0]
    process_job(
        repo,
        runner=_ResolvingOrchestrator(),
        owner_id=msg['ownerId'],
        session_id=msg['sessionId'],
        turn_id=msg['turnId'],
        job_id=msg['jobId'],
        topic=msg['topic'],
    )

    # 4단계 — 동일 폴링 표면에서 terminal 결과(쟁점 오버레이 포함)가 나온다
    done = client.get(f'/api/evidence/jobs/{job_id}')
    assert done.status_code == 200
    result = done.json()['result']
    assert result['state'] == 'ok'
    assert result['claims'][0]['supporting'][0]['paperId'] == '2401.00001'
    assert result['claims'][0]['conflicting'][0]['paperId'] == '2401.00002'


# v1에서 사라진 테스트들의 행방(대상이 없어진 것이지 커버리지가 준 것이 아니다):
#   - 비용 게이트 3종        → test_evidence_runner.py (루프 시작 전 차단)
#   - 이전 topic 이어붙이기   → 폐기. 후속 질문 해석이 루프 판단으로 이관됐다(FR-36 v2)
#   - 첨부를 추출 대상에 포함 → test_evidence_runner.py (검색 없이 확인 대상이 된다)
#   - Bedrock 지출 기록      → test_evidence_llm.py (토큰이 없으면 계상하지 않는다)
