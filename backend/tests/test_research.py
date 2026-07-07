from __future__ import annotations

from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.app import create_app
from backend.config import Settings
from backend.modules.novelty.repository import NoveltyJobTable
from backend.modules.research import controller
from backend.modules.research.repository import InMemoryResearchRepository, ResearchJobTable
from backend.modules.user_docmodel import EVIDENCE_PDF_DEGRADED_NOTICE


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


def _client(monkeypatch, principal: Principal | None = None, repo=None) -> TestClient:
    monkeypatch.setenv("RESEARCH_AGENT_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    app.dependency_overrides[controller.get_principal] = lambda: principal or _principal()
    if repo is not None:
        app.dependency_overrides[controller.get_repo] = lambda: repo
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


def test_research_session_lifecycle(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post(
        "/api/research/jobs",
        json={"content": "find evidence for retrieval augmented generation evaluation"},
    )
    job_id = created.json()["jobId"]
    added = client.post(
        f"/api/research/jobs/{job_id}/messages",
        json={"content": "include multi-paper contradiction checks"},
    )
    listed = client.get("/api/research/jobs")
    detail = client.get(f"/api/research/jobs/{job_id}")
    messages = client.get(f"/api/research/jobs/{job_id}/messages")
    deleted = client.delete(f"/api/research/jobs/{job_id}")

    assert created.status_code == 200
    assert added.status_code == 200
    assert listed.json()["jobs"][0]["jobId"] == job_id
    assert detail.json()["job"]["title"].startswith("find evidence")
    assert [item["content"] for item in messages.json()["messages"]] == [
        "find evidence for retrieval augmented generation evaluation",
        "include multi-paper contradiction checks",
    ]
    assert deleted.status_code == 204
    assert client.get(f"/api/research/jobs/{job_id}").status_code == 404


def test_research_sessions_are_owner_scoped(monkeypatch) -> None:
    owner_a = _principal()
    owner_b = _principal()
    repo = InMemoryResearchRepository()
    client_a = _client(monkeypatch, owner_a, repo)
    client_b = _client(monkeypatch, owner_b, repo)

    created = client_a.post("/api/research/jobs", json={"content": "owner scoped session"})
    job_id = created.json()["jobId"]

    assert client_a.get(f"/api/research/jobs/{job_id}").status_code == 200
    assert client_b.get(f"/api/research/jobs/{job_id}").status_code == 404
    assert client_b.get("/api/research/jobs").json()["jobs"] == []


def test_research_message_rejects_bad_attachment_with_422(monkeypatch) -> None:
    """US-AG5(#297)/US-EV4(#268) — 허용 형식·크기 밖 첨부는 처리 전 422로 즉시 거부."""
    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post("/api/research/jobs", json={"content": "attachment validation"})
    job_id = created.json()["jobId"]

    bad_kind = client.post(
        f"/api/research/jobs/{job_id}/messages",
        json={
            "content": "with bad attachment",
            "attachments": [{"id": "a-1", "name": "x.docx", "kind": "unknown", "sizeBytes": 10}],
        },
    )
    oversized = client.post(
        f"/api/research/jobs/{job_id}/messages",
        json={
            "content": "with oversized attachment",
            "attachments": [
                {"id": "a-2", "name": "big.pdf", "kind": "pdf", "sizeBytes": 10 * 1024 * 1024 + 1}
            ],
        },
    )
    ok = client.post(
        f"/api/research/jobs/{job_id}/messages",
        json={
            "content": "with valid attachment",
            "attachments": [
                {"id": "a-3", "name": "draft.md", "kind": "markdown", "sizeBytes": 2048}
            ],
        },
    )

    assert bad_kind.status_code == 422
    assert oversized.status_code == 422
    assert ok.status_code == 200


def test_research_job_transitions_to_completed_after_message(monkeypatch) -> None:
    """PR #338 리뷰 Blocking #3 — job.state가 active로 남으면 FE가 이를 running으로
    매핑해 답변이 저장돼도 폴링을 멈추지 않는다."""
    from backend.modules.research.models import ResearchJobState

    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post("/api/research/jobs", json={"content": "test question"})
    assert created.json()["state"] == ResearchJobState.COMPLETED.value

    job_id = created.json()["jobId"]
    detail = client.get(f"/api/research/jobs/{job_id}")
    assert detail.json()["job"]["state"] == ResearchJobState.COMPLETED.value

    followup = client.post(
        f"/api/research/jobs/{job_id}/messages", json={"content": "follow-up"}
    )
    assert followup.status_code == 200
    detail_after_followup = client.get(f"/api/research/jobs/{job_id}")
    assert detail_after_followup.json()["job"]["state"] == ResearchJobState.COMPLETED.value


def test_sql_repositories_bind_postgres_uuid_ids() -> None:
    dialect = postgresql.dialect()

    for table in (ResearchJobTable, NoveltyJobTable):
        stmt = table.__table__.select().where(
            table.owner_id == "00000000-0000-0000-0000-000000000001"
        )
        compiled = stmt.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})

        assert table.__table__.c.owner_id.type.compile(dialect=dialect) == "UUID"
        assert "::UUID" in str(compiled)


def test_research_reset_deletes_only_own_sessions(monkeypatch) -> None:
    """US-EV8(#272) 전체 초기화 — 소유 잡·대화 이력 전부 삭제(멱등), 타 사용자 세션 보존."""
    owner_a = _principal()
    owner_b = _principal()
    repo = InMemoryResearchRepository()
    client_a = _client(monkeypatch, owner_a, repo)
    client_b = _client(monkeypatch, owner_b, repo)

    created = client_a.post("/api/research/jobs", json={"content": "reset target session one"})
    job_a = created.json()["jobId"]
    client_a.post("/api/research/jobs", json={"content": "reset target session two"})
    job_b = client_b.post("/api/research/jobs", json={"content": "surviving session"}).json()[
        "jobId"
    ]

    reset = client_a.delete("/api/research/jobs")

    assert reset.status_code == 204
    assert client_a.get("/api/research/jobs").json()["jobs"] == []
    assert client_a.get(f"/api/research/jobs/{job_a}/messages").status_code == 404
    assert client_b.get(f"/api/research/jobs/{job_b}").status_code == 200
    # 멱등 — 이미 비어 있어도 204.
    assert client_a.delete("/api/research/jobs").status_code == 204


def test_research_turn_passes_attachment_docs_and_notices_unparsed(monkeypatch) -> None:
    """US-EV4(#268) 2차 — contentText(md 본문)는 orchestrator 추출 대상으로 전달되고,
    본문 없는 첨부(PDF)는 별도의 비기술 안내 메시지를 남긴다."""
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult

    from backend.modules.evidence.models import TurnAbstainResult

    captured: dict = {}

    class FakeOrchestrator:
        def run(self, ctx, request):
            captured["ctx"] = ctx
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(state="abstain", abstainReason="no_corpus")
            )

    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _client(monkeypatch, principal, repo)
    client.app.dependency_overrides[controller.get_evidence_orchestrator] = (
        lambda: FakeOrchestrator()
    )

    created = client.post(
        "/api/research/jobs",
        json={
            "content": "첨부 기반 근거 형성",
            "attachments": [
                {
                    "id": "a1",
                    "name": "draft.md",
                    "kind": "markdown",
                    "sizeBytes": 24,
                    "contentText": "# 초안 본문\nRAG 평가 프로토콜.",
                },
                {"id": "a2", "name": "scan.pdf", "kind": "pdf", "sizeBytes": 1024},
            ],
        },
    )

    assert created.status_code == 200
    docs = captured["ctx"].attachment_docs
    assert [(doc.name, bool(doc.text)) for doc in docs] == [
        ("draft.md", True),
        ("scan.pdf", False),
    ]
    messages = client.get(
        f"/api/research/jobs/{created.json()['jobId']}/messages"
    ).json()["messages"]
    notices = [m["content"] for m in messages if m["content"].startswith("[첨부 안내]")]
    assert len(notices) == 1
    assert notices[0] == EVIDENCE_PDF_DEGRADED_NOTICE

    # 본문 상한(262,144자) 초과는 처리 전 422 — US-EV4 AC2 연장.
    oversized = client.post(
        "/api/research/jobs",
        json={
            "content": "oversize attachment body",
            "attachments": [
                {
                    "id": "a3",
                    "name": "big.md",
                    "kind": "markdown",
                    "sizeBytes": 1,
                    "contentText": "x" * 262_145,
                }
            ],
        },
    )
    assert oversized.status_code == 422


def test_research_uploads_pdf_and_uses_docmodel_attachment(monkeypatch) -> None:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult

    from backend.modules.evidence.models import TurnAbstainResult

    captured: dict = {}

    class FakeOrchestrator:
        def run(self, ctx, request):
            captured["ctx"] = ctx
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(state="abstain", abstainReason="no_corpus")
            )

    principal = _principal()
    repo = InMemoryResearchRepository()
    fake_user_docmodel = _FakeUserDocModel(_doc_model("Research PDF text"))
    client = _client(monkeypatch, principal, repo)
    client.app.dependency_overrides[controller.get_evidence_orchestrator] = (
        lambda: FakeOrchestrator()
    )
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )

    uploaded = client.post(
        "/api/research/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()

    created = client.post(
        "/api/research/jobs",
        json={"content": "첨부 기반 근거 형성", "attachments": [attachment]},
    )

    assert created.status_code == 200
    assert fake_user_docmodel.uploads[0]["pdf"] == b"%PDF-1.4"
    assert fake_user_docmodel.enqueued[0].payload()["kind"] == "BUILD_USER_DOC_MODEL"
    assert fake_user_docmodel.polled[0].paper_id == attachment["paperId"]
    docs = captured["ctx"].attachment_docs
    assert docs[0].paper_id == attachment["paperId"]
    assert docs[0].record_ref == attachment["recordRef"]
    assert docs[0].doc_model.fullText == "Research PDF text"
    messages = client.get(
        f"/api/research/jobs/{created.json()['jobId']}/messages"
    ).json()["messages"]
    assert not [m["content"] for m in messages if m["content"].startswith("[첨부 안내]")]


def test_research_create_job_rejects_forged_pdf_object_key_without_polling(monkeypatch) -> None:
    class FailingOrchestrator:
        def run(self, ctx, request):
            raise AssertionError("invalid attachment should be rejected before orchestration")

    principal = _principal()
    repo = InMemoryResearchRepository()
    fake_user_docmodel = _FakeUserDocModel(_doc_model("Research PDF text"))
    client = _client(monkeypatch, principal, repo)
    client.app.dependency_overrides[controller.get_evidence_orchestrator] = (
        lambda: FailingOrchestrator()
    )
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )

    uploaded = client.post(
        "/api/research/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    attachment["objectKey"] = "uploads/evidence/other-user/att-1/att-1/scan.pdf"

    created = client.post(
        "/api/research/jobs",
        json={"content": "첨부 기반 근거 형성", "attachments": [attachment]},
    )

    assert created.status_code == 422
    assert fake_user_docmodel.polled == []


def test_research_message_rejects_invalid_pdf_identity_without_polling(monkeypatch) -> None:
    class FailingOrchestrator:
        def run(self, ctx, request):
            raise AssertionError("invalid attachment should be rejected before orchestration")

    principal = _principal()
    repo = InMemoryResearchRepository()
    fake_user_docmodel = _FakeUserDocModel(_doc_model("Research PDF text"))
    client = _client(monkeypatch, principal, repo)
    created = client.post("/api/research/jobs", json={"content": "seed"})
    assert created.status_code == 200
    job_id = created.json()["jobId"]

    client.app.dependency_overrides[controller.get_evidence_orchestrator] = (
        lambda: FailingOrchestrator()
    )
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )

    uploaded = client.post(
        "/api/research/attachments?fileName=scan.pdf&id=att-1",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert uploaded.status_code == 200
    attachment = uploaded.json()
    attachment["recordRef"] = "upload:someone:userdoc-11111111-1111-4111-8111-111111111111:att-1"

    added = client.post(
        f"/api/research/jobs/{job_id}/messages",
        json={"content": "첨부 기반 근거 형성", "attachments": [attachment]},
    )

    assert added.status_code == 422
    assert fake_user_docmodel.polled == []
