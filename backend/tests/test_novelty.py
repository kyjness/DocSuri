from __future__ import annotations

import json
from io import BytesIO
from urllib.parse import urlparse
from uuid import uuid4

from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from backend.app import create_app
from backend.config import Settings
from backend.modules.accounts.models import Principal, UserRole
from backend.modules.novelty import controller
from backend.modules.novelty.adapters import (
    BedrockNoveltyLlmClient,
    ExternalApiSearchClient,
    NoveltyAdapters,
    NoveltyLlmDraft,
    RetrievalBundle,
    S3ManuscriptSimilarityClient,
    U2FullSearchCorpusRetrievalClient,
)
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


def test_service_rejects_unbound_manuscript_object_key() -> None:
    repo = InMemoryNoveltyRepository()
    service = NoveltyService(repo)

    try:
        service.create_job(
            "u1",
            NoveltyJobRequest(
                inputType="manuscript",
                topic="owner scoped manuscript",
                manuscript={
                    "fileName": "draft.md",
                    "contentType": "text/markdown",
                    "objectKey": "novelty/u2/other-job/draft.md",
                },
            ),
        )
    except ValueError as exc:
        assert "owner and job" in str(exc)
    else:  # pragma: no cover - failure path clarity
        raise AssertionError("cross-owner manuscript objectKey should be rejected")

    assert repo.list_jobs("u1") == []


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
    assert is_safe_external_url("https://news.google.com/search?q=rag") is False
    assert is_safe_external_url("https://zenodo.org/records/123") is True


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


def test_u2_corpus_adapter_maps_full_search_cards_to_source_refs() -> None:
    from discovery.mocks import build_mock_orchestrator

    bundle = build_mock_orchestrator()
    result = U2FullSearchCorpusRetrievalClient(
        bundle.orchestrator,
        bundle.grounding_hook,
    ).full_search("u1", "diffusion protein structure")

    assert result.evidenceStatus is EvidenceStatus.SUPPORTED
    assert result.items
    assert result.items[0]["sourceRefs"][0]["url"].startswith("https://")


def test_similarity_adapter_reads_text_manuscript_and_queries_corpus() -> None:
    class FakeS3:
        def get_object(self, **kwargs):
            assert kwargs["Bucket"] == "papers"
            assert kwargs["Key"] == "novelty/u1/job/draft.txt"
            return {
                "Body": BytesIO(
                    b"This manuscript presents a robust framework for privacy preserving "
                    b"retrieval augmented generation evaluation across domain specific "
                    b"scientific workflows with repeated evidence checking. "
                )
            }

    class FakeCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            assert owner_id == "u1"
            assert "privacy preserving" in query
            return RetrievalBundle(
                items=[
                    {
                        "title": "Privacy Preserving RAG",
                        "sourceRefs": [
                            {
                                "type": "url",
                                "identifier": "2401.00001",
                                "url": "https://arxiv.org/abs/2401.00001",
                            }
                        ],
                    }
                ],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=FakeS3(),
        corpus=FakeCorpus(),
    ).check(
        "u1",
        {
            "objectKey": "novelty/u1/job/draft.txt",
            "contentType": "text/plain",
            "jobId": "job",
        },
    )

    assert result.evidenceStatus is EvidenceStatus.SUPPORTED
    assert any(item["riskType"] == "sentence_similarity" for item in result.items)
    parsed_url = urlparse(result.items[-1]["sourceRefs"][0]["url"])
    assert parsed_url.scheme == "https"
    assert parsed_url.hostname == "arxiv.org"


def test_similarity_adapter_rejects_cross_owner_object_key() -> None:
    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=object(),
        corpus=object(),
    ).check(
        "u1",
        {
            "objectKey": "novelty/u2/job/draft.txt",
            "contentType": "text/plain",
        },
    )

    assert result.degradedReason == "manuscript objectKey is outside owner prefix"


def test_similarity_adapter_rejects_cross_job_object_key() -> None:
    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=object(),
        corpus=object(),
    ).check(
        "u1",
        {
            "objectKey": "novelty/u1/other-job/draft.txt",
            "contentType": "text/plain",
            "jobId": "job",
        },
    )

    assert result.degradedReason == "manuscript objectKey is outside job prefix"


def test_external_adapter_queries_public_api_sources() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

        def raise_for_status(self) -> None:
            return None

    class FakeHttp:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict]] = []

        def get(self, url: str, *, params: dict, headers: dict):
            self.calls.append((url, params))
            host = urlparse(url).hostname
            if host == "api.github.com":
                return Response(
                    {
                        "items": [
                            {
                                "full_name": "docsuri/novelty-baseline",
                                "html_url": "https://github.com/docsuri/novelty-baseline",
                                "description": "Novelty baseline",
                                "updated_at": "2026-07-01T00:00:00Z",
                                "stargazers_count": 7,
                                "language": "Python",
                                "license": {"spdx_id": "MIT"},
                            }
                        ]
                    }
                )
            if host == "huggingface.co":
                return Response(
                    [
                        {
                            "id": "docsuri/rag-eval",
                            "tags": ["rag", "evaluation"],
                            "downloads": 3,
                            "likes": 2,
                        }
                    ]
                )
            if host == "zenodo.org":
                return Response(
                    {
                        "hits": {
                            "hits": [
                                {
                                    "id": "123",
                                    "doi": "10.5281/zenodo.123",
                                    "links": {"html": "https://zenodo.org/records/123"},
                                    "metadata": {
                                        "title": "RAG Evaluation Dataset",
                                        "description": "<p>Dataset for RAG evaluation.</p>",
                                        "publication_date": "2026-06-30",
                                        "keywords": ["rag"],
                                    },
                                }
                            ]
                        }
                    }
                )
            raise AssertionError(f"unexpected external API call: {url}")

    http = FakeHttp()
    result = ExternalApiSearchClient(http).search("privacy preserving RAG")

    assert result.evidenceStatus is EvidenceStatus.SUPPORTED
    assert {url for url, _ in http.calls} == {
        "https://api.github.com/search/repositories",
        "https://huggingface.co/api/datasets",
        "https://zenodo.org/api/records",
    }
    assert {item["sourceType"] for item in result.items} == {"github_repo", "dataset"}
    assert all(item["sourceRefs"] for item in result.items)


def test_bedrock_llm_adapter_maps_source_ref_indexes_only() -> None:
    class FakeBedrock:
        def invoke_model(self, **kwargs):
            body = json.loads(kwargs["body"].decode("utf-8"))
            assert body["anthropic_version"] == "bedrock-2023-05-31"
            payload = {
                "similarWorks": [
                    {
                        "title": "Prior RAG benchmark",
                        "summary": "Grounded baseline.",
                        "sourceRefIndexes": [0],
                        "url": "https://invented.example/not-used",
                    }
                ],
                "noveltyCandidates": [
                    {
                        "title": "Freshness-aware evaluation",
                        "rationale": "Compare recent dataset evidence against corpus baselines.",
                        "sourceRefIndexes": [1],
                    }
                ],
                "experimentPlan": {
                    "researchQuestion": "How can RAG novelty be evaluated?",
                    "noveltyAngle": "Evaluate freshness against grounded baselines.",
                    "hypotheses": ["Freshness signals improve differentiation."],
                    "baselines": ["Prior RAG benchmark"],
                    "procedure": ["Compare against corpus and dataset baselines."],
                    "datasets": ["RAG Evaluation Dataset"],
                    "metrics": ["baseline delta"],
                    "resources": ["Public dataset and evaluation script"],
                    "risks": ["dataset mismatch"],
                    "sourceRefIndexes": [1],
                },
            }
            return {
                "body": BytesIO(
                    json.dumps(
                        {"content": [{"type": "text", "text": json.dumps(payload)}]}
                    ).encode("utf-8")
                )
            }

    corpus_ref = {
        "type": "url",
        "identifier": "2401.00001",
        "title": "Prior RAG benchmark",
        "url": "https://arxiv.org/abs/2401.00001",
    }
    dataset_ref = {
        "type": "url",
        "identifier": "10.5281/zenodo.123",
        "title": "RAG Evaluation Dataset",
        "url": "https://zenodo.org/records/123",
    }

    draft = BedrockNoveltyLlmClient(
        model_id="global.anthropic.claude-sonnet-4-6",
        client=FakeBedrock(),
    ).draft(
        topic="RAG novelty evaluation",
        corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [corpus_ref]}]),
        external=RetrievalBundle(items=[{"title": "Dataset", "sourceRefs": [dataset_ref]}]),
    )

    assert draft.degradedReason is None
    assert draft.similarWorks["items"][0]["sourceRefs"] == [corpus_ref]
    assert draft.noveltyCandidates["items"][0]["sourceRefs"] == [dataset_ref]
    assert draft.experimentPlan["metrics"] == ["baseline delta"]
    assert draft.experimentPlan["sourceRefs"] == [dataset_ref]
    assert "Novelty score" not in draft.experimentPlan["metrics"]


def test_worker_completes_when_adapters_are_not_degraded() -> None:
    source_ref = {
        "type": "url",
        "identifier": "2401.00001",
        "url": "https://arxiv.org/abs/2401.00001",
    }

    class CleanCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[{"title": query, "sourceRefs": [source_ref]}])

    class CleanExternal:
        def search(self, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[{"title": query, "sourceRefs": [source_ref]}])

    class CleanLlm:
        def draft(self, *, topic, corpus, external) -> NoveltyLlmDraft:
            return NoveltyLlmDraft(
                similarWorks={
                    "items": [
                        {
                            "title": "Prior work",
                            "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                            "sourceRefs": [source_ref],
                        }
                    ],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [source_ref],
                },
                noveltyCandidates={
                    "items": [
                        {
                            "title": "Novel candidate",
                            "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                            "sourceRefs": [source_ref],
                        }
                    ],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [source_ref],
                },
                experimentPlan={
                    "researchQuestion": topic,
                    "noveltyAngle": "Evaluate against grounded prior work.",
                    "hypotheses": ["Grounded difference improves novelty."],
                    "baselines": ["Prior work"],
                    "procedure": ["Run baseline comparison."],
                    "datasets": ["RAG Evaluation Dataset"],
                    "metrics": ["baseline delta"],
                    "resources": ["Evaluation script"],
                    "risks": ["dataset mismatch"],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [source_ref],
                },
            )

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(
            corpus=CleanCorpus(),
            external=CleanExternal(),
            llm=CleanLlm(),
        ),
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
            manuscript={"fileName": "draft.md", "contentType": "text/markdown"},
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


def test_worker_loop_acks_missing_job_message_as_stale() -> None:
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
    message = Message({"ownerId": "u1", "jobId": "missing"})
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
    assert repo.commits == 1
    assert repo.rollbacks == 0


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
                "fileName": "draft.pdf",
                "contentType": "application/pdf",
            },
        },
    )

    assert resp.status_code == 422


def test_api_marks_job_failed_when_sqs_dispatch_fails(monkeypatch) -> None:
    class BrokenSqs:
        def send_message(self, **kwargs):
            del kwargs
            raise RuntimeError("sqs down")

    import boto3

    principal = _principal()
    repo = InMemoryNoveltyRepository()
    monkeypatch.setenv(
        "DOCSURI_NOVELTY_JOB_QUEUE_URL",
        "https://sqs.ap-northeast-2.amazonaws.com/123/docsuri-novelty-agent-job-queue",
    )
    monkeypatch.setattr(boto3, "client", lambda *_args, **_kwargs: BrokenSqs())
    client = _client(monkeypatch, principal, repo)

    resp = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "adaptive literature review agent"},
    )

    jobs = repo.list_jobs(principal.user_id)
    assert resp.status_code == 503
    assert jobs[0].state is JobState.FAILED


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
