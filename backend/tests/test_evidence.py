from __future__ import annotations

from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from backend.app import create_app
from backend.config import Settings
from backend.modules.evidence import controller
from backend.modules.evidence.assembler import EvidenceComparisonAssembler
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
    class _StubOrchestrator:
        def run(self, ctx, request):
            return TurnAbstainResult(
                outcome=__import__(
                    'docsuri_shared._generated.dtos.evidence_schema',
                    fromlist=['EvidenceAbstainResult'],
                ).EvidenceAbstainResult(
                    state='abstain',
                    abstainReason='out_of_corpus',
                )
            )

    app.dependency_overrides[controller.get_orchestrator] = lambda: _StubOrchestrator()
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

@given(st.just([]))  # claims 항상 빈 리스트
def test_assembler_itself_does_not_gate_empty_claims(claims) -> None:
    """assembler 단독 호출은 빈 claims도 그대로 통과시킨다 — INV-EV-2 강제는
    orchestrator.run()의 책임이지 assembler의 책임이 아니다. 이 테스트는 그 경계를
    문서화할 뿐, INV-EV-2 자체의 실제 강제는 아래
    test_orchestrator_abstains_when_extractor_returns_no_items가 검증한다
    (PR #338 리뷰 Medium #17 — 기존에는 이 테스트 하나만 "empty claims yields abstain"이라는
    이름으로 존재해 실제로는 정반대(ok 반환)를 assert하고 있었고, orchestrator 레벨
    강제는 전혀 테스트되지 않고 있었다)."""
    from backend.modules.evidence.models import PaperSearchResult

    assembler = EvidenceComparisonAssembler()
    search_result = PaperSearchResult(records=(), query_used='test', scope='auto')

    result = assembler.assemble(claims, search_result, paper_count=0)
    assert result.state == 'ok'
    assert result.claims == claims


def test_orchestrator_abstains_when_extractor_returns_no_items() -> None:
    """PBT-EV-1 실검증 — INV-EV-2("claims=[] 이면 abstain")는 orchestrator.run()이 강제한다."""
    from types import SimpleNamespace

    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import AgentRunContext, PaperSearchResult
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    class _StubSearchTool:
        def search(self, *, topic, scope, paper_ids):
            return PaperSearchResult(
                records=(SimpleNamespace(arxivId='p1'),), query_used=topic, scope='auto'
            )

    class _StubDocModelTool:
        def get_doc_model(self, paper_id, version=1):
            return SimpleNamespace()

    class _EmptyExtractor:
        def extract(self, topic, doc_models):
            return []  # INV-EV-2 트리거 조건

    orchestrator = EvidenceAgentOrchestrator(
        search_tool=_StubSearchTool(),
        doc_model_tool=_StubDocModelTool(),
        extractor=_EmptyExtractor(),
        assembler=EvidenceComparisonAssembler(),
    )
    request = EvidenceRequest(topic='test', scope='auto', paperIds=[])
    session = EvidenceSession(owner_id='owner-1')
    turn = EvidenceTurn(session_id=session.session_id, request=request)
    ctx = AgentRunContext(
        session=session, current_turn=turn, owner_id='owner-1',
        request_id='req-1', budget_signal={'state': 'ok'},
    )

    result = orchestrator.run(ctx, request)

    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == 'insufficient_evidence'


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

def test_turn_result_serialization_excludes_internal_fields() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceCoverage,
        EvidenceResult,
    )

    success = TurnSuccessResult(
        outcome=EvidenceResult(
            state='ok',
            claims=[],
            coverage=EvidenceCoverage(paperCount=1, queryUsed='test'),
        )
    )
    abstain = TurnAbstainResult(
        outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
    )
    error = TurnErrorResult(error_code='llm_unavailable')

    from backend.modules.evidence.repository import _serialize_result

    for result in (success, abstain, error):
        data, _ = _serialize_result(result)
        if data:
            raw = str(data)
            for forbidden in ('score', 'chunk_id', 'chunkId', 'vector', 'llm_meta'):
                assert forbidden not in raw, (
                    f'INV-EV-5 violation: {forbidden!r} in serialized result'
                )


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
# API: POST /api/evidence/turns → 201 + abstain (stub orchestrator)
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

    class _CapturingOrchestrator:
        def run(self, ctx, request):
            captured["ctx"] = ctx
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
    client.app.dependency_overrides[controller.get_orchestrator] = (
        lambda: _CapturingOrchestrator()
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
    docs = captured["ctx"].attachment_docs
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
        orchestrator=object(),
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


def test_run_evidence_degrades_on_overlong_topic() -> None:
    """research content 상한(12000) > evidence topic 상한(2000). 긴 메시지가 _run_evidence에서
    EvidenceRequest 검증에 걸려 500 나던 걸 degrade(None→'[error]')로 막는다(Blocking #3).
    orchestrator까지 도달하면 안 된다."""
    import asyncio

    from backend.modules.research.service import _format_turn_result, _run_evidence

    class _Orch:
        def run(self, ctx, request):
            raise AssertionError('overlong topic must not reach the orchestrator')

    result = asyncio.run(_run_evidence(_Orch(), 'owner-1', 'a' * 2001))

    assert result is None
    assert _format_turn_result(result) == '[error] evidence_unavailable'


# ---------------------------------------------------------------------------
# FR-37: 멀티턴 검색 맥락화 (PR #338 리뷰 Blocking #2 — buildable 절반)
# ---------------------------------------------------------------------------

def test_orchestrator_contextualizes_search_with_prior_topics() -> None:
    """이전 topic이 검색 질의에 포함 — 후속 질문이 이전 근거를 잇는다(추출은 현재 topic만)."""
    from types import SimpleNamespace

    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import AgentRunContext, PaperSearchResult
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    captured: dict[str, str] = {}

    class _SpySearch:
        def search(self, *, topic, scope, paper_ids):
            captured['topic'] = topic
            return PaperSearchResult(records=(), query_used=topic, scope='auto')

    orchestrator = EvidenceAgentOrchestrator(
        search_tool=_SpySearch(),
        doc_model_tool=SimpleNamespace(get_doc_model=lambda *a, **k: None),
        extractor=SimpleNamespace(extract=lambda **k: []),
        assembler=EvidenceComparisonAssembler(),
    )
    request = EvidenceRequest(topic='current question', scope='auto', paperIds=[])
    session = EvidenceSession(owner_id='o')
    turn = EvidenceTurn(session_id=session.session_id, request=request)
    ctx = AgentRunContext(
        session=session,
        current_turn=turn,
        owner_id='o',
        request_id='r',
        budget_signal={'state': 'ok'},
        prior_topics=('prior alpha', 'prior beta'),
    )

    orchestrator.run(ctx, request)

    assert 'prior alpha' in captured['topic']
    assert 'current question' in captured['topic']


def test_run_turn_threads_prior_topics_across_turns() -> None:
    """run_turn이 같은 세션의 이전 턴 topic을 orchestrator ctx.prior_topics로 넘긴다."""
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceRequest,
    )

    from backend.modules.evidence.service import EvidenceChatService

    captured: dict[str, tuple[str, ...]] = {}

    class _SpyOrch:
        def run(self, ctx, request):
            captured['prior'] = ctx.prior_topics
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(state='abstain', abstainReason='out_of_corpus')
            )

    repo = InMemoryEvidenceRepository()
    svc = EvidenceChatService(repo=repo, orchestrator=_SpyOrch())

    r1 = svc.run_turn(
        owner_id='o', request=EvidenceRequest(topic='first', scope='auto', paperIds=[])
    )
    svc.run_turn(
        owner_id='o',
        request=EvidenceRequest(topic='second', scope='auto', paperIds=[]),
        session_id=r1.session_id,
    )

    assert captured['prior'] == ('first',)


def test_run_evidence_forwards_prior_topics() -> None:
    """research _run_evidence가 prior_topics를 orchestrator ctx로 전달한다."""
    import asyncio

    from backend.modules.research.service import _run_evidence

    captured: dict[str, tuple[str, ...]] = {}

    class _Orch:
        def run(self, ctx, request):
            captured['prior'] = ctx.prior_topics
            return None

    asyncio.run(_run_evidence(_Orch(), 'o', 'current', ('p1', 'p2')))

    assert captured['prior'] == ('p1', 'p2')


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


def test_orchestrator_abstains_with_cost_degraded_reason_when_signal_degraded() -> None:
    """BR-EV-7/US-EV6 — 비용 게이트는 error가 아니라 abstain(cost_degraded)로 떨어져야
    research 경로가 '[abstain] cost_degraded'로 영속하고 FE 라벨에 닿는다."""
    from backend.modules.evidence.models import TurnAbstainResult
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    orchestrator = EvidenceAgentOrchestrator(
        search_tool=_NoToolAllowed(),
        doc_model_tool=_NoToolAllowed(),
        extractor=_NoToolAllowed(),
        assembler=_NoToolAllowed(),
    )
    ctx, request = _cost_gate_ctx({'state': 'degraded'})

    result = orchestrator.run(ctx, request)

    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == 'cost_degraded'


def test_orchestrator_does_not_gate_wired_cost_guard_at_warning() -> None:
    """NFR-C1 — agent hard gate는 warning(80%)이 아니라 critical(95%)부터 발화한다."""
    from types import SimpleNamespace

    from docsuri_ops.cost_guard import CostGuardCircuitBreaker
    from docsuri_ops.domain.models import UsageEvent

    from backend.modules.evidence.models import PaperSearchResult, TurnAbstainResult
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    class _Search:
        called = False

        def search(self, *, topic, scope, paper_ids):
            self.called = True
            return PaperSearchResult(records=(), query_used=topic, scope='auto')

    guard = CostGuardCircuitBreaker()
    guard.record_spend(UsageEvent(event_id='seed', amount_usd=1280.0, source='test'))
    search = _Search()
    orchestrator = EvidenceAgentOrchestrator(
        search_tool=search,
        doc_model_tool=SimpleNamespace(),
        extractor=SimpleNamespace(),
        assembler=SimpleNamespace(),
        cost_guard=guard,
    )
    ctx, request = _cost_gate_ctx({})

    result = orchestrator.run(ctx, request)

    assert search.called is True
    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == 'out_of_corpus'


def test_orchestrator_gates_on_critical_wired_cost_guard_without_external_signal() -> None:
    """NFR-C1 — U6 단일 권위(cost guard)를 직접 물면 critical부터 게이트된다."""
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker
    from docsuri_ops.domain.models import UsageEvent

    from backend.modules.evidence.models import TurnAbstainResult
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    guard = CostGuardCircuitBreaker()
    guard.record_spend(UsageEvent(event_id='seed', amount_usd=1520.0, source='test'))
    orchestrator = EvidenceAgentOrchestrator(
        search_tool=_NoToolAllowed(),
        doc_model_tool=_NoToolAllowed(),
        extractor=_NoToolAllowed(),
        assembler=_NoToolAllowed(),
        cost_guard=guard,
    )
    ctx, request = _cost_gate_ctx({})

    result = orchestrator.run(ctx, request)

    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == 'cost_degraded'


def test_extractor_records_bedrock_spend_into_cost_guard() -> None:
    """NFR-C1 — 스트리밍 응답 마지막 청크의 invocationMetrics가 cost guard 지출로 기록된다."""
    import json

    from docsuri_ops.cost_guard import CostGuardCircuitBreaker

    from backend.modules.evidence.extractor import EvidenceExtractor

    def _chunk(payload: dict) -> dict:
        return {'chunk': {'bytes': json.dumps(payload).encode('utf-8')}}

    class _FakeStream:
        def invoke_model_with_response_stream(self, **kwargs):
            return {
                'body': [
                    _chunk(
                        {
                            'type': 'content_block_delta',
                            'delta': {'type': 'text_delta', 'text': '{"items": []}'},
                        }
                    ),
                    _chunk(
                        {
                            'type': 'message_stop',
                            'amazon-bedrock-invocationMetrics': {
                                'inputTokenCount': 1_000_000,
                                'outputTokenCount': 200_000,
                            },
                        }
                    ),
                ]
            }

    guard = CostGuardCircuitBreaker()
    extractor = EvidenceExtractor(model_id='m', client=_FakeStream(), cost_guard=guard)

    payload = extractor._invoke_json('system', 'user')

    assert payload == {'items': []}
    # 기본 단가 $3/1M input + $15/1M output → 1M in + 0.2M out = $6
    assert abs(guard.get_budget_state().spend_usd - 6.0) < 1e-9


def test_orchestrator_includes_attachment_content_as_extraction_target() -> None:
    """US-EV4(#268) 2차 — md/txt 본문 첨부는 corpus가 비어도 추출 대상 문서가 되고,
    본문 없는 첨부(PDF)는 추출 대상에 포함되지 않는다."""
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    from backend.modules.evidence.models import (
        AgentRunContext,
        AttachmentInput,
        PaperSearchResult,
    )
    from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator

    captured: dict = {}

    class _EmptySearchTool:
        def search(self, *, topic, scope, paper_ids):
            return PaperSearchResult(records=(), query_used=topic, scope='auto')

    class _NoDocModelTool:
        def get_doc_model(self, paper_id, version=1):
            return None

    class _CapturingExtractor:
        def extract(self, topic, doc_models):
            captured['doc_models'] = doc_models
            return []  # abstain으로 종료 — 추출 대상 전달만 검증

    orchestrator = EvidenceAgentOrchestrator(
        search_tool=_EmptySearchTool(),
        doc_model_tool=_NoDocModelTool(),
        extractor=_CapturingExtractor(),
        assembler=EvidenceComparisonAssembler(),
    )
    request = EvidenceRequest(topic='rag evaluation', scope='auto', paperIds=[])
    session = EvidenceSession(owner_id='owner-1')
    turn = EvidenceTurn(session_id=session.session_id, request=request)
    ctx = AgentRunContext(
        session=session,
        current_turn=turn,
        owner_id='owner-1',
        request_id='req-1',
        budget_signal={'state': 'ok'},
        attachment_docs=(
            AttachmentInput(name='draft.md', kind='markdown', text='# RAG 초안\n평가 프로토콜.'),
            AttachmentInput(name='scan.pdf', kind='pdf', text=None),
        ),
    )

    orchestrator.run(ctx, request)

    ids = [source[0] for source in captured['doc_models']]
    assert ids == ['attachment:draft.md']
    doc = captured['doc_models'][0][1]
    assert 'RAG 초안' in doc.fullText
    assert doc.sections[0].blocks[0].text.startswith('# RAG 초안')
