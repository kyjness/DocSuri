from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from backend.app import create_app
from backend.config import Settings
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.novelty import controller
from backend.modules.novelty.adapters import NoveltyAdapters, RetrievalBundle
from backend.modules.novelty.models import (
    ArtifactKind,
    ArtifactValidationError,
    EvidenceStatus,
    ExportApprovalError,
    JobState,
    NoveltyJobRequest,
)
from backend.modules.novelty.repository import InMemoryNoveltyRepository
from backend.modules.novelty.security import is_safe_external_url, sanitize_external_query
from backend.modules.novelty.service import NoveltyService
from backend.modules.novelty.streaming import encode_sse
from backend.modules.novelty.validators import normalize_source_key, validate_artifact_payload
from backend.modules.novelty.worker import process_job, run_worker


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


def _service_job(repo: InMemoryNoveltyRepository, owner_id: str | None = None):
    owner_id = owner_id or str(uuid4())
    service = NoveltyService(repo)
    created = service.create_job(
        owner_id,
        NoveltyJobRequest(inputType="natural_language", topic="privacy preserving RAG"),
    )
    return service, owner_id, created.jobId


def _client(monkeypatch, principal: Principal | None = None, repo=None) -> TestClient:
    monkeypatch.setenv("NOVELTY_AGENT_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    app.dependency_overrides[controller.get_principal] = lambda: principal or _principal()
    if repo is not None:
        app.dependency_overrides[controller.get_repo] = lambda: repo
    return TestClient(app)


@given(st.text(alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=1))
def test_source_key_normalization_is_stable(raw: str) -> None:
    normalized_once = normalize_source_key(" DOI ", raw)
    normalized_twice = normalize_source_key("doi", " ".join(raw.split()))

    assert normalized_once == normalized_twice


def test_supported_artifact_requires_source_refs() -> None:
    try:
        validate_artifact_payload(
            ArtifactKind.NOVELTY_CANDIDATES,
            {"items": [{"evidenceStatus": "supported", "title": "claim"}]},
        )
    except ArtifactValidationError:
        pass
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("supported novelty output must carry sourceRefs")


def test_owner_isolation_blocks_cross_owner_reads() -> None:
    repo = InMemoryNoveltyRepository()
    _, owner_a, job_id = _service_job(repo)
    owner_b = str(uuid4())

    assert repo.get_job(owner_a, job_id).jobId == job_id
    try:
        repo.get_job(owner_b, job_id)
    except KeyError:
        pass
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("cross-owner job read should fail closed")


def test_state_transition_guard_rejects_backtracking() -> None:
    repo = InMemoryNoveltyRepository()
    service, owner_id, job_id = _service_job(repo)

    service.advance_state(owner_id, job_id, JobState.RETRIEVING_CORPUS, "retrieving")
    try:
        service.advance_state(owner_id, job_id, JobState.QUEUED, "backtrack")
    except Exception as exc:
        assert "invalid transition" in str(exc)
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("backtracking should be rejected")


def test_notion_export_requires_preview_then_approval() -> None:
    repo = InMemoryNoveltyRepository()
    service, owner_id, job_id = _service_job(repo)

    try:
        service.complete_export(owner_id, job_id, "page-1")
    except ExportApprovalError:
        pass
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("export should not complete before approval")

    service.preview_export(owner_id, job_id)
    service.approve_export(owner_id, job_id, approved=True)
    export = service.complete_export(owner_id, job_id, "page-1")

    assert export.notionPageId == "page-1"
    assert export.status == "exported"


def test_external_query_and_url_guards() -> None:
    assert sanitize_external_query("  hello\nworld  ") == "hello world"
    assert is_safe_external_url("https://github.com/openai/codex") is True
    assert is_safe_external_url("http://github.com/openai/codex") is False
    assert is_safe_external_url("https://127.0.0.1/admin") is False
    assert is_safe_external_url("https://8.8.8.8/dns-query") is False
    assert is_safe_external_url("https://github.com.evil.example/x") is False


def test_worker_processes_minimal_job_to_completion() -> None:
    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(repo, owner_id, job_id)

    result = NoveltyService(repo).result(owner_id, job_id)
    assert result.job.state is JobState.DEGRADED
    assert {artifact.kind for artifact in result.artifacts} >= {
        ArtifactKind.EVIDENCE,
        ArtifactKind.EXPERIMENT_PLAN,
    }


def test_worker_completes_when_adapters_are_not_degraded() -> None:
    class CleanCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[{"title": query}])

    class CleanExternal:
        def search(self, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[{"title": query}])

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(corpus=CleanCorpus(), external=CleanExternal()),
    )

    assert NoveltyService(repo).result(owner_id, job_id).job.state is JobState.COMPLETED


def test_worker_manuscript_path_records_similarity_risk_degradation() -> None:
    repo = InMemoryNoveltyRepository()
    service = NoveltyService(repo)
    owner_id = str(uuid4())
    created = service.create_job(
        owner_id,
        NoveltyJobRequest(
            inputType="manuscript",
            topic="novelty agent draft",
            manuscript={"fileName": "draft.pdf", "contentType": "application/pdf"},
        ),
    )

    process_job(repo, owner_id, created.jobId)

    result = service.result(owner_id, created.jobId)
    assert result.job.state is JobState.DEGRADED
    assert ArtifactKind.RISK_SIGNALS in {artifact.kind for artifact in result.artifacts}


def test_supported_adapter_without_source_refs_degrades_not_fails() -> None:
    class UnsupportedCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(
                items=[{"title": query}],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(repo, owner_id, job_id, adapters=NoveltyAdapters(corpus=UnsupportedCorpus()))

    result = NoveltyService(repo).result(owner_id, job_id)
    assert result.job.state is JobState.DEGRADED
    assert "missing sourceRefs" in repo.list_events(owner_id, job_id)[-1].model_dump_json()


def test_worker_loop_acks_successful_message() -> None:
    class Message:
        def __init__(self, body):
            self.body = body

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)
    message = Message({"ownerId": owner_id, "jobId": job_id})
    acked: list[Message] = []
    calls = 0

    def receive():
        nonlocal calls
        calls += 1
        return [message] if calls == 1 else []

    run_worker(
        repo_factory=lambda: repo,
        receive=receive,
        ack=acked.append,
        should_stop=lambda: calls > 1,
    )

    assert acked == [message]
    assert NoveltyService(repo).result(owner_id, job_id).job.state is JobState.DEGRADED


def test_worker_loop_commits_and_acks_recorded_failure() -> None:
    class BrokenCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            raise RuntimeError("corpus unavailable")

    class CountingRepo(InMemoryNoveltyRepository):
        def __init__(self) -> None:
            super().__init__()
            self.commits = 0
            self.rollbacks = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    class Message:
        def __init__(self, body):
            self.body = body

    repo = CountingRepo()
    _, owner_id, job_id = _service_job(repo)
    message = Message({"ownerId": owner_id, "jobId": job_id})
    acked: list[Message] = []
    calls = 0

    def receive():
        nonlocal calls
        calls += 1
        return [message] if calls == 1 else []

    run_worker(
        repo_factory=lambda: repo,
        receive=receive,
        ack=acked.append,
        should_stop=lambda: calls > 1,
        adapters=NoveltyAdapters(corpus=BrokenCorpus()),
    )

    result = NoveltyService(repo).result(owner_id, job_id)
    assert result.job.state is JobState.FAILED
    assert acked == [message]
    assert repo.commits == 1
    assert repo.rollbacks == 0


def test_sse_snapshot_encodes_progress_event() -> None:
    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)
    event = repo.list_events(owner_id, job_id)[0]

    encoded = encode_sse(event)

    assert encoded.startswith("event: progress\n")
    assert f'"jobId":"{job_id}"' in encoded


def test_api_create_status_and_cancel(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "adaptive literature review agent"},
    )
    job_id = created.json()["jobId"]
    status = client.get(f"/api/novelty/jobs/{job_id}")
    cancelled = client.post(f"/api/novelty/jobs/{job_id}/cancel")

    assert created.status_code == 200
    assert status.json()["job"]["state"] == "degraded"
    assert cancelled.json()["state"] == "degraded"


def test_api_lists_jobs_and_persists_chat_messages(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "adaptive literature review agent"},
    )
    job_id = created.json()["jobId"]
    added = client.post(
        f"/api/novelty/jobs/{job_id}/messages",
        json={"content": "compare against recent RAG evaluation papers"},
    )
    listed = client.get("/api/novelty/jobs")
    messages = client.get(f"/api/novelty/jobs/{job_id}/messages")

    assert created.status_code == 200
    assert added.status_code == 200
    assert listed.json()["jobs"][0]["jobId"] == job_id
    assert [item["content"] for item in messages.json()["messages"]] == [
        "adaptive literature review agent",
        "compare against recent RAG evaluation papers",
    ]


def test_api_rejects_unsupported_manuscript(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryNoveltyRepository())

    resp = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "novelty agent",
            "manuscript": {
                "fileName": "draft.docx",
                "contentType": "application/vnd.openxmlformats",
            },
        },
    )

    assert resp.status_code == 422


def test_api_rejects_blank_topic_before_job_is_created(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "   "},
    )

    assert resp.status_code == 422
    assert repo.list_jobs(principal.user_id) == []
