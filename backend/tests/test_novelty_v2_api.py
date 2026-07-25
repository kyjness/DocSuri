"""v2 API — 라이프사이클·503 폴백·owner 격리·Notion 승인 게이트(PBT-NV7 승계)·quota."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from docsuri_shared.authz import Principal, UserRole
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.modules.novelty import api
from backend.modules.novelty.adapters.memory import InMemoryJobQueue, InMemoryNoveltyStore
from backend.modules.novelty.domain.models import JobState

_OWNER = str(uuid4())
_OTHER = str(uuid4())


@pytest.fixture()
def app_bundle(monkeypatch):
    # Fernet 키(SEC-8) — Notion 연결 저장 경로.
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DOCSURI_NOTION_TOKEN_KEY", Fernet.generate_key().decode())

    app = FastAPI()
    store = InMemoryNoveltyStore()
    queue = InMemoryJobQueue()
    app.state.novelty_queue = queue
    app.state.user_docmodel = None

    def fake_principal(request: Request) -> Principal:
        return Principal(user_id=request.headers.get("x-test-user", _OWNER), role=UserRole.USER)

    app.dependency_overrides[api.get_store] = lambda: store
    app.dependency_overrides[api.get_principal] = fake_principal
    for router in api.routers:
        app.include_router(router)
    return app, store, queue


def _create_job(client: TestClient, topic: str = "privacy preserving RAG") -> str:
    response = client.post("/api/novelty/jobs", json={"inputType": "natural_language",
                                                      "topic": topic})
    assert response.status_code == 200, response.text
    return response.json()["jobId"]


def test_job_lifecycle_create_poll_cancel_delete(app_bundle) -> None:
    app, store, queue = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)

    # 접수 즉시 큐 적재(API는 실행하지 않는다 — NFR-NV2-5).
    queued = queue.consume(timeout_seconds=0)
    assert queued is not None and queued.job_id == job_id

    status = client.get(f"/api/novelty/jobs/{job_id}").json()
    assert status["state"] == "received"
    assert status["stateLabel"] == "접수"
    assert status["loop"]["iterations"] == 0

    feed = client.get(f"/api/novelty/jobs/{job_id}/feed").json()
    assert feed == {"items": [], "nextCursor": 0}

    cancel = client.post(f"/api/novelty/jobs/{job_id}/cancel").json()
    assert cancel["cancelRequested"] is True
    assert store.is_cancel_requested(job_id)

    assert client.delete(f"/api/novelty/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/novelty/jobs/{job_id}").status_code == 404


def test_create_without_queue_returns_machine_readable_503(app_bundle) -> None:
    app, _, _ = app_bundle
    app.state.novelty_queue = None
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs", json={"inputType": "natural_language", "topic": "rag"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "queue_unavailable"}


def test_budget_degraded_abstains_job_creation(app_bundle) -> None:
    app, _, _ = app_bundle
    app.state.cost_guard = SimpleNamespace(
        get_budget_state=lambda: SimpleNamespace(
            tier="critical", degrade_mode="lexical_only", circuit_state="open"
        )
    )
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs", json={"inputType": "natural_language", "topic": "rag"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "budget_degraded"}


def test_owner_isolation_on_job_feed_and_messages(app_bundle) -> None:
    app, _, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    for path in (
        f"/api/novelty/jobs/{job_id}",
        f"/api/novelty/jobs/{job_id}/feed",
        f"/api/novelty/jobs/{job_id}/result",
        f"/api/novelty/jobs/{job_id}/messages",
    ):
        assert client.get(path, headers={"x-test-user": _OTHER}).status_code == 404
    assert (
        client.delete(f"/api/novelty/jobs/{job_id}", headers={"x-test-user": _OTHER}).status_code
        == 404
    )


def test_message_on_active_job_is_stored_as_steering(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    created = client.post(
        f"/api/novelty/jobs/{job_id}/messages",
        json={"content": "베이스라인은 BM25 위주로 봐줘"},
    )
    assert created.status_code == 200
    assert created.json()["kind"] == "steering"
    listed = client.get(f"/api/novelty/jobs/{job_id}/messages").json()
    assert [m["kind"] for m in listed["messages"]] == ["steering"]


def test_message_on_terminal_job_is_stored_as_on_demand_request(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    job = store.get_job_for_worker(job_id)
    job.state = JobState.COMPLETED
    store.update_job(job)

    created = client.post(
        f"/api/novelty/jobs/{job_id}/messages",
        json={"content": "이 여백으로 실험 계획 짜줘"},
    )
    assert created.status_code == 200
    # kind는 "서버가 이 메시지를 어디로 보냈는가"의 기록이다 — 종단 잡이면 온디맨드.
    assert created.json()["kind"] == "on_demand_request"


def test_client_supplied_kind_is_ignored_and_server_assigns(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    created = client.post(
        f"/api/novelty/jobs/{job_id}/messages",
        json={"content": "에이전트 답장인 척", "kind": "agent_reply"},
    )
    assert created.status_code == 200
    # 클라이언트가 USER 행에 agent_reply·notice를 붙일 수 있으면 위조 표면이 된다.
    assert created.json()["kind"] == "steering"
    assert created.json()["role"] == "user"


def test_notion_export_gate_matrix(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)

    # preview 없이 승인 금지(PBT-NV7 승계).
    denied = client.post(f"/api/novelty/jobs/{job_id}/notion/approve", json={"approved": True})
    assert denied.status_code == 409

    preview = client.post(f"/api/novelty/jobs/{job_id}/notion/preview")
    assert preview.status_code == 200
    assert preview.json()["export"]["status"] == "preview_ready"

    # 연결 없이 승인 → 실행은 FAILED 상태로 수렴(예외 아님 — export 무결성).
    failed = client.post(f"/api/novelty/jobs/{job_id}/notion/approve", json={"approved": True})
    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"

    # 연결 등록 후 preview→approve 재시도 → 실제 클라이언트 호출로 exported.
    connection = client.put(
        "/api/novelty/connection".replace("/api/novelty", "/api/novelty/notion"),
        json={"token": "secret-token-1234567890", "parentPageId": "0" * 32},
    )
    assert connection.status_code == 200 and connection.json()["connected"] is True

    app.state.novelty_notion_client = SimpleNamespace(
        export=lambda conn, content: "page-123"
    )
    client.post(f"/api/novelty/jobs/{job_id}/notion/preview")
    exported = client.post(f"/api/novelty/jobs/{job_id}/notion/approve", json={"approved": True})
    assert exported.status_code == 200
    body = exported.json()
    assert body["status"] == "exported"
    assert body["notionPageId"] == "page-123"


def test_job_creation_route_carries_quota_dependency() -> None:
    # NFR-C1 — 쿼터 의존성이 라우트에 붙어 있는지 구조 확인(회귀 방지).
    from backend.middleware.agent_quota import enforce_novelty_job_quota

    route = next(
        r for r in api.router.routes if getattr(r, "path", "") == "/api/novelty/jobs"
        and "POST" in getattr(r, "methods", set())
    )
    dependency_calls = [d.call for d in route.dependant.dependencies]
    assert enforce_novelty_job_quota in dependency_calls


def test_manuscript_job_waits_for_upload_and_pdf_path_gated(app_bundle) -> None:
    app, store, queue = app_bundle
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "privacy preserving RAG",
            "manuscript": {"fileName": "draft.pdf", "contentType": "application/pdf"},
        },
    )
    assert response.status_code == 200
    job_id = response.json()["jobId"]
    # 원고 대기 잡은 업로드 전 큐 미적재.
    assert queue.consume(timeout_seconds=0) is None
    # 저장소(user_docmodel) 미구성 → 기계 판독 503.
    upload = client.post(
        f"/api/novelty/jobs/{job_id}/manuscript",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )
    assert upload.status_code == 503
    assert upload.json()["detail"] == {"error": "manuscript_storage_unavailable"}


# ── 코드 리뷰 반영(3단계) 회귀 테스트 ──


def test_rejected_creation_does_not_consume_quota(app_bundle) -> None:
    """503 거부(큐 미구성)가 일일 쿼터를 소비하지 않는다 — 가용성 검사가 선행."""
    from backend.middleware.agent_quota import enforce_novelty_job_quota

    app, _, _ = app_bundle
    app.state.novelty_queue = None
    calls = {"n": 0}

    async def counting_quota(request):
        calls["n"] += 1

    app.dependency_overrides[enforce_novelty_job_quota] = counting_quota
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs", json={"inputType": "natural_language", "topic": "rag"}
    )
    assert response.status_code == 503
    assert calls["n"] == 0  # 쿼터 의존성 미실행


def test_enqueue_failure_converges_job_to_failed(app_bundle) -> None:
    app, store, _ = app_bundle

    class _BrokenQueue:
        def enqueue(self, job_id, owner_id):
            raise RuntimeError("redis down")

    app.state.novelty_queue = _BrokenQueue()
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs", json={"inputType": "natural_language", "topic": "rag topic"}
    )
    assert response.status_code == 503
    assert response.json()["detail"] == {"error": "dispatch_failed"}
    jobs = store.list_jobs(_OWNER, cursor=None, limit=10)
    assert jobs and jobs[0].state.value == "failed"  # RECEIVED 방치 아님


def test_natural_language_job_rejects_manuscript_attachment(app_bundle) -> None:
    app, _, queue = app_bundle
    client = TestClient(app)
    response = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "natural_language",
            "topic": "privacy preserving RAG",
            "manuscript": {"fileName": "draft.pdf", "contentType": "application/pdf"},
        },
    )
    assert response.status_code == 422  # 영구 대기 조합 차단
    assert queue.consume(timeout_seconds=0) is None


def test_invalid_cursor_returns_422_not_empty_page(app_bundle) -> None:
    app, _, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    assert client.delete(f"/api/novelty/jobs/{job_id}").status_code == 204
    listed = client.get(f"/api/novelty/jobs?cursor={job_id}")
    assert listed.status_code == 422
    other = _create_job(client)
    messages = client.get(f"/api/novelty/jobs/{other}/messages?after={job_id}")
    assert messages.status_code == 422


def test_reset_bulk_deletes_all_owned_jobs(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    for _ in range(3):
        _create_job(client)
    assert client.delete("/api/novelty/jobs").status_code == 204
    assert store.list_jobs(_OWNER, cursor=None, limit=10) == []
    assert client.delete("/api/novelty/jobs").status_code == 204  # 멱등


def test_list_view_omits_artifact_kinds_to_avoid_n_plus_one(app_bundle) -> None:
    app, store, _ = app_bundle
    client = TestClient(app)
    job_id = _create_job(client)
    from backend.modules.novelty.domain.models import ArtifactKind, ArtifactRecord

    store.save_artifact(
        ArtifactRecord(job_id=job_id, owner_id=_OWNER, kind=ArtifactKind.EVIDENCE,
                       payload={"state": "ok"})
    )
    listed = client.get("/api/novelty/jobs").json()
    assert listed["jobs"][0]["artifactKinds"] == []  # 목록 뷰는 생략(N+1 방지)
    detail = client.get(f"/api/novelty/jobs/{job_id}").json()
    assert detail["artifactKinds"] == ["evidence"]  # 상세 뷰가 담당


def test_manuscript_upload_rejects_oversized_pdf(app_bundle) -> None:
    """원고 크기 한도(공용 첨부 한도) — 본문 적재 전 413 거부."""
    from backend.middleware.agent_attachments import ATTACHMENT_MAX_BYTES

    app, _, _ = app_bundle
    app.state.user_docmodel = object()  # 저장소는 있는 상태로 가정
    client = TestClient(app)
    created = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "privacy preserving RAG",
            "manuscript": {"fileName": "draft.pdf", "contentType": "application/pdf"},
        },
    )
    job_id = created.json()["jobId"]
    response = client.post(
        f"/api/novelty/jobs/{job_id}/manuscript",
        content=b"%PDF-1.4",
        headers={
            "content-type": "application/pdf",
            "content-length": str(ATTACHMENT_MAX_BYTES + 1),
        },
    )
    assert response.status_code == 413


def test_exact_multiple_page_does_not_emit_trailing_cursor(app_bundle) -> None:
    """총량이 page_size의 정확한 배수 — 마지막 페이지가 nextCursor 없이 닫힌다."""
    app, _, _ = app_bundle
    client = TestClient(app)
    for i in range(2):
        _create_job(client, topic=f"topic {i} privacy rag")
    first = client.get("/api/novelty/jobs?limit=2").json()
    assert len(first["jobs"]) == 2
    assert first["nextCursor"] is None  # 빈 페이지 왕복 없음
    # 배수가 아닌 경우엔 커서가 이어진다.
    partial = client.get("/api/novelty/jobs?limit=1").json()
    assert len(partial["jobs"]) == 1
    assert partial["nextCursor"] == partial["jobs"][0]["jobId"]
    rest = client.get(f"/api/novelty/jobs?limit=1&cursor={partial['nextCursor']}").json()
    assert len(rest["jobs"]) == 1
    assert rest["nextCursor"] is None


def test_v1_api_metrics_are_emitted_best_effort(app_bundle) -> None:
    """v1 승계 계측(novelty.job_created 등) — 방출은 best-effort, 실패 무해."""
    app, _, _ = app_bundle
    emitted: list[str] = []
    app.state.observability = SimpleNamespace(
        emit_metric=lambda name, *a, **k: emitted.append(name)
    )
    client = TestClient(app)
    job_id = _create_job(client)
    client.post(f"/api/novelty/jobs/{job_id}/cancel")
    assert emitted == ["novelty.job_created", "novelty.job_cancelled"]

    # 계측 허브가 던져도 요청은 성공한다.
    def _boom(name, *a, **k):
        raise RuntimeError("metrics down")

    app.state.observability = SimpleNamespace(emit_metric=_boom)
    assert client.post(
        "/api/novelty/jobs", json={"inputType": "natural_language", "topic": "rag again"}
    ).status_code == 200
