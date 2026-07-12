from __future__ import annotations

import json
import logging
from io import BytesIO
from urllib.parse import urlparse
from uuid import uuid4

import pytest
from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from backend.app import create_app
from backend.config import Settings
from backend.modules.novelty import controller
from backend.modules.novelty.adapters import (
    SIMILAR_WORK_DETAIL_FIELDS,
    BedrockNoveltyLlmClient,
    EvidenceFormationClient,
    ExternalApiSearchClient,
    NotionApiExportClient,
    NoveltyAdapters,
    NoveltyLlmDraft,
    NoveltySearchPlan,
    RetrievalBundle,
    S3ManuscriptSimilarityClient,
    U2FullSearchCorpusRetrievalClient,
    build_llm_adapter,
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
from backend.modules.novelty.worker import (
    _MANUSCRIPT_DOCMODEL_MAX_ATTEMPTS,
    process_job,
    run_worker,
)


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
    assert "가 'Privacy Preserving RAG'와 유사합니다" in result.items[-1]["summary"]
    parsed_url = urlparse(result.items[-1]["sourceRefs"][0]["url"])
    assert parsed_url.scheme == "https"
    assert parsed_url.hostname == "arxiv.org"


def test_similarity_adapter_reads_pdf_manuscript_from_user_docmodel() -> None:
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

    fake_user_docmodel = _FakeUserDocModel(
        _doc_model(
            "This manuscript presents a robust framework for privacy preserving "
            "retrieval augmented generation evaluation across domain specific "
            "scientific workflows with repeated evidence checking."
        )
    )
    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=object(),
        corpus=FakeCorpus(),
        user_docmodel=fake_user_docmodel,
    ).check(
        "u1",
        {
            "objectKey": "novelty/u1/job/manuscript/scan.pdf",
            "contentType": "application/pdf",
            "jobId": "job",
            "paperId": "userdoc:11111111-1111-4111-8111-111111111111",
            "recordRef": (
                "upload:u1:userdoc-11111111-1111-4111-8111-111111111111:manuscript"
            ),
        },
    )

    assert result.evidenceStatus is EvidenceStatus.SUPPORTED
    assert fake_user_docmodel.polled[0].paper_id.startswith("userdoc:")
    assert any(item["riskType"] == "sentence_similarity" for item in result.items)


def test_similarity_adapter_degrades_pdf_when_docmodel_unavailable() -> None:
    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=object(),
        corpus=object(),
        user_docmodel=_FakeUserDocModel(None),
    ).check(
        "u1",
        {
            "objectKey": "novelty/u1/job/manuscript/scan.pdf",
            "contentType": "application/pdf",
            "jobId": "job",
            "paperId": "userdoc:11111111-1111-4111-8111-111111111111",
            "recordRef": (
                "upload:u1:userdoc-11111111-1111-4111-8111-111111111111:manuscript"
            ),
        },
    )

    assert result.degradedReason == "manuscript_pdf_parse_unavailable"


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


def test_nv5_similarity_signal_is_review_signal_not_plagiarism_verdict() -> None:
    """US-NV5(#255) AC1 — 문장 유사도 경고는 법적 표절 판정이 아닌 검토 신호다.

    검토 신호 프레이밍(제목 '문장 유사성:' + '…유사합니다' 요약 + 근거 sourceRefs)을
    고정하고, 판정형 필드·표절 판정 문구가 응답에 노출되지 않음을 기준 수준에서 검증한다.
    """

    class FakeS3:
        def get_object(self, **kwargs):
            return {
                "Body": BytesIO(
                    b"This manuscript presents a privacy preserving retrieval augmented "
                    b"generation evaluation protocol across domain specific scientific "
                    b"workflows with repeated evidence checking. "
                )
            }

    class FakeCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
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
        {"objectKey": "novelty/u1/job/draft.txt", "contentType": "text/plain", "jobId": "job"},
    )

    similarity_items = [
        item for item in result.items if item["riskType"] == "sentence_similarity"
    ]
    assert similarity_items
    verdict_keys = {"verdict", "plagiarism", "isPlagiarism", "plagiarismScore", "legalVerdict"}
    for item in similarity_items:
        # 검토 신호 프레이밍: 유사성 서술 + 검토용 근거 출처.
        assert item["title"].startswith("문장 유사성: ")
        assert "유사합니다" in item["summary"]
        assert item["sourceRefs"]
        # 판정 프레이밍 금지: 판정형 필드도, 표절 판정 문구도 없다.
        assert not verdict_keys & set(item)
        text_blob = " ".join(str(value) for value in item.values())
        assert "표절" not in text_blob
        assert "plagiar" not in text_blob.lower()


def test_nv5_ai_style_signal_has_no_verdict_or_authorship_probability() -> None:
    """US-NV5(#255) AC2 — AI 어투 신호는 확정 판정·AI 작성 확률 없이 문체 위험 신호로만
    표시한다. ABSTAINED(기권) 프레이밍과 확률/판정류 필드 부재를 기준 수준에서 고정한다.
    (false positive 고지문은 FE RiskSignalList가 무조건 렌더 — agentChatScreen.test.tsx.)
    """

    class FakeS3:
        def get_object(self, **kwargs):
            sentence = (
                "We delve into a robust framework that aims to underscore the pivotal "
                "role of comprehensive analysis across the evolving landscape of "
                "retrieval systems. "
            )
            return {"Body": BytesIO((sentence * 4).encode("utf-8"))}

    class EmptyCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[], evidenceStatus=EvidenceStatus.ABSTAINED)

    result = S3ManuscriptSimilarityClient(
        bucket="papers",
        prefix="novelty/",
        client=FakeS3(),
        corpus=EmptyCorpus(),
    ).check(
        "u1",
        {"objectKey": "novelty/u1/job/draft.txt", "contentType": "text/plain", "jobId": "job"},
    )

    ai_style_items = [item for item in result.items if item["riskType"] == "ai_style"]
    assert len(ai_style_items) == 1
    item = ai_style_items[0]
    # 문체 위험 신호: 감지 marker 목록을 싣고, 출처 없는 휴리스틱임을 드러낸다.
    assert item["title"] == "AI-style phrasing risk"
    assert item["markers"] and "delve" in item["markers"]
    assert item["sourceRefs"] == []
    # 확정 판정 금지: SUPPORTED 판정으로 승격하지 않고 기권으로 남는다.
    assert item["evidenceStatus"] == EvidenceStatus.ABSTAINED.value
    # AI 작성 확률·판정 필드 부재 — 확률/점수/판정류 키를 노출하지 않는다.
    probability_keys = {
        "probability",
        "aiProbability",
        "aiAuthorshipProbability",
        "authorshipProbability",
        "confidence",
        "score",
        "verdict",
        "isAiGenerated",
        "aiGenerated",
    }
    assert not probability_keys & set(item)
    # corpus 매칭이 없으면 유사성 항목을 날조하지 않고, 번들 전체도 기권으로 남는다.
    assert result.items == ai_style_items
    assert result.evidenceStatus is EvidenceStatus.ABSTAINED


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
        def invoke_model_with_response_stream(self, **kwargs):
            body = json.loads(kwargs["body"].decode("utf-8"))
            assert body["anthropic_version"] == "bedrock-2023-05-31"
            assert body["tool_choice"] == {"type": "tool", "name": "emit_novelty_analysis"}
            assert body["tools"][0]["name"] == "emit_novelty_analysis"
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
            text = json.dumps(payload)
            return {
                "body": [
                    _tool_stream_chunk(text[: len(text) // 2]),
                    _tool_stream_chunk(text[len(text) // 2 :]),
                    _stream_chunk(
                        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}}
                    ),
                ]
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


def test_bedrock_llm_adapter_builds_query_expansion_plan() -> None:
    class FakeBedrock:
        def invoke_model_with_response_stream(self, **kwargs):
            body = json.loads(kwargs["body"].decode("utf-8"))
            assert body["tool_choice"] == {"type": "tool", "name": "emit_novelty_search_plan"}
            assert body["max_tokens"] == 4096
            assert body["tools"][0]["input_schema"]["properties"]["subqueries"]["maxItems"] == 6
            payload = {
                "englishQuery": "BERT-based Korean NLP research ideas",
                "keywords": ["BERT", "Korean NLP", "KLUE"],
                "subqueries": ["KoBERT KLUE benchmark novelty", "Korean BERT dataset bias"],
                "intent": {
                    "goal": "recommend novel paper ideas",
                    "domain": "Korean NLP",
                    "method": "BERT",
                    "constraints": ["public benchmark datasets"],
                },
                "rankingSignals": ["KLUE", "KoBERT", "benchmark dataset"],
            }
            return {"body": [_tool_stream_chunk(json.dumps(payload))]}

    plan = BedrockNoveltyLlmClient(model_id="m", client=FakeBedrock()).plan_search(
        "BERT 알고리즘 아이디어 추천"
    )

    assert plan.englishQuery == "BERT-based Korean NLP research ideas"
    assert plan.keywords == ["BERT", "Korean NLP", "KLUE"]
    assert plan.subqueries[:2] == [
        "BERT-based Korean NLP research ideas",
        "KoBERT KLUE benchmark novelty",
    ]
    assert plan.intent["domain"] == "Korean NLP"
    assert "benchmark dataset" in plan.rankingSignals


def test_build_llm_adapter_uses_configurable_stream_limits(monkeypatch) -> None:
    import boto3

    captured = {}

    def fake_client(service_name, *, region_name, config):
        captured["service_name"] = service_name
        captured["region_name"] = region_name
        captured["config"] = config
        return object()

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    monkeypatch.setenv("DOCSURI_NOVELTY_BEDROCK_READ_TIMEOUT_SECONDS", "720")
    monkeypatch.setenv("DOCSURI_NOVELTY_LLM_MAX_TOKENS", "9000")
    monkeypatch.setenv("DOCSURI_NOVELTY_QUERY_PLAN_MAX_TOKENS", "3000")

    adapter = build_llm_adapter()

    assert captured["service_name"] == "bedrock-runtime"
    assert captured["region_name"] == "ap-northeast-2"
    assert captured["config"].read_timeout == 720.0
    assert isinstance(adapter, BedrockNoveltyLlmClient)
    assert adapter._max_tokens == 9000
    assert adapter._search_plan_max_tokens == 3000


def test_bedrock_llm_adapter_maps_similar_work_detail_columns() -> None:
    captured_bodies: list[dict] = []

    class FakeBedrock:
        def invoke_model_with_response_stream(self, **kwargs):
            captured_bodies.append(json.loads(kwargs["body"].decode("utf-8")))
            payload = {
                "similarWorks": [
                    {
                        "title": "Prior RAG benchmark",
                        "summary": "Grounded baseline.",
                        "problem": {
                            "value": "  benchmark leakage  ",
                            "sourceRefIndexes": [0],
                        },
                        "method": {
                            "value": "contrastive evaluation",
                            "sourceRefIndexes": [0],
                        },
                        # B-001 회귀 — row 출처는 유효해도 칸 자체 근거가 비면 기권
                        "dataset": {"value": "RAG-Bench", "sourceRefIndexes": []},
                        "results": None,
                        # 구형 bare string — 필드별 근거 검증 불가 → 기권
                        "limitations": "small cohort",
                        # overlap 키 자체가 없음 → null(기권)로 정규화되어야 한다
                        "sourceRefIndexes": [0],
                    },
                    {
                        # 유효한 sourceRef가 없는 row — 상세 칸이 전부 기권되어야 한다
                        "title": "Ungrounded speculation",
                        "summary": "No valid refs.",
                        "problem": "invented problem",
                        # 칸 형식은 맞지만 refs가 무효(범위 밖) → 기권
                        "method": {"value": "invented method", "sourceRefIndexes": [99]},
                        "dataset": "invented dataset",
                        "results": "invented results",
                        "limitations": "invented limitations",
                        "overlap": "invented overlap",
                        "sourceRefIndexes": [99],
                    },
                ],
                "noveltyCandidates": [
                    {"title": "Freshness-aware evaluation", "sourceRefIndexes": [0]}
                ],
                "experimentPlan": {
                    "researchQuestion": "How can RAG novelty be evaluated?",
                    "noveltyAngle": "Evaluate freshness against grounded baselines.",
                    "hypotheses": ["Freshness signals improve differentiation."],
                    "baselines": ["Prior RAG benchmark"],
                    "procedure": ["Compare against corpus baselines."],
                    "datasets": ["RAG Evaluation Dataset"],
                    "metrics": ["baseline delta"],
                    "resources": ["Public dataset"],
                    "risks": ["dataset mismatch"],
                    "sourceRefIndexes": [0],
                },
            }
            return {
                "body": [_tool_stream_chunk(json.dumps(payload))]
            }

    corpus_ref = {
        "type": "url",
        "identifier": "2401.00001",
        "title": "Prior RAG benchmark",
        "url": "https://arxiv.org/abs/2401.00001",
    }

    draft = BedrockNoveltyLlmClient(
        model_id="global.anthropic.claude-sonnet-4-6",
        client=FakeBedrock(),
    ).draft(
        topic="RAG novelty evaluation",
        corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [corpus_ref]}]),
        external=RetrievalBundle(items=[]),
    )

    item = draft.similarWorks["items"][0]
    assert item["problem"] == "benchmark leakage"
    assert item["method"] == "contrastive evaluation"
    # B-001 — row 출처가 있어도 칸 자신의 근거가 없으면 기권(null)
    assert item["dataset"] is None
    assert item["results"] is None
    assert item["limitations"] is None
    assert item["overlap"] is None
    # 리뷰 반영 — sourceRef 없는 row는 상세 칸 전부 기권(null): 근거 없는 값 노출 금지
    ungrounded = draft.similarWorks["items"][1]
    assert ungrounded["evidenceStatus"] == EvidenceStatus.ABSTAINED.value
    assert all(ungrounded[column] is None for column in SIMILAR_WORK_DETAIL_FIELDS)
    # 상세 칼럼은 유사 연구 표 전용 — novelty candidates에는 붙지 않는다
    assert "method" not in draft.noveltyCandidates["items"][0]
    # 프롬프트 계약과 추측 금지 지시가 실제 호출 본문에 실려 나간다
    body = captured_bodies[0]
    user_text = captured_bodies[0]["messages"][0]["content"][0]["text"]
    assert '"limitations"' in user_text
    assert body["max_tokens"] == 8192
    assert "at most 3 similarworks" in body["system"].lower()
    assert "never guess" in body["system"].lower()
    assert body["tool_choice"]["name"] == "emit_novelty_analysis"
    schema = body["tools"][0]["input_schema"]["properties"]
    assert schema["similarWorks"]["maxItems"] == 3
    assert schema["noveltyCandidates"]["maxItems"] == 3
    assert schema["experimentPlan"]["properties"]["procedure"]["maxItems"] == 5


def test_bedrock_llm_adapter_logs_raw_preview_on_json_parse_failure(caplog) -> None:
    class FakeBedrock:
        def invoke_model_with_response_stream(self, **kwargs):
            return {
                "body": [
                    _tool_stream_chunk('{"similarWorks": }'),
                    _stream_chunk(
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "max_tokens"},
                        }
                    ),
                ]
            }

    ref = {
        "type": "url",
        "identifier": "2401.00001",
        "url": "https://arxiv.org/abs/2401.00001",
    }

    with caplog.at_level(logging.WARNING):
        draft = BedrockNoveltyLlmClient(model_id="m", client=FakeBedrock()).draft(
            topic="RAG novelty evaluation",
            corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [ref]}]),
            external=RetrievalBundle(items=[]),
        )

    assert draft.degradedReason == "LLM generation unavailable: JSONDecodeError"
    record = next(
        item
        for item in caplog.records
        if item.message.startswith("novelty Bedrock JSON parse failed")
    )
    assert '{"similarWorks": }' in record.message
    assert "stopReason=max_tokens" in record.message
    assert "outputLength=" in record.message
    assert "jsonPos=" in record.message


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

    class CleanEvidence:
        def form(self, owner_id: str, topic: str) -> RetrievalBundle:
            return RetrievalBundle(
                items=[{"title": f"evidence: {topic}", "sourceRefs": [source_ref]}],
                evidenceStatus=EvidenceStatus.SUPPORTED,
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
            evidence=CleanEvidence(),
        ),
    )

    assert NoveltyService(repo).result(owner_id, job_id).job.state is JobState.COMPLETED


def test_worker_emits_step_detail_payloads() -> None:
    source_ref = {
        "type": "url",
        "identifier": "2401.00002",
        "url": "https://arxiv.org/abs/2401.00002",
    }

    class TwoItemCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(
                items=[
                    {"title": "A", "sourceRefs": [source_ref]},
                    {"title": "B", "sourceRefs": [source_ref]},
                ],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(repo, owner_id, job_id, adapters=NoveltyAdapters(corpus=TwoItemCorpus()))

    payloads: dict[JobState, list[dict]] = {}
    for event in repo.list_events(owner_id, job_id):
        payloads.setdefault(event.state, []).append(event.payload)

    # US-NV7(#257) — 검색 단계는 시작(도구+쿼리)·완료(count) 이벤트, LLM 단계는 결과 수 동봉
    # US-NV1(#251) — query plan 진행 표시 뒤 자연어 근거형성이 U2 검색보다 먼저 온다
    corpus_events = payloads[JobState.RETRIEVING_CORPUS]
    assert corpus_events[0] == {
        "source": "Bedrock LLM",
        "query": "privacy preserving RAG",
    }
    assert corpus_events[1]["source"] == "Bedrock LLM"
    assert corpus_events[1]["queries"] == ["privacy preserving RAG"]
    assert corpus_events[2] == {
        "source": "U11 evidence formation",
        "query": "privacy preserving RAG",
    }
    assert corpus_events[3]["source"] == "U11 evidence formation"
    assert "reason" not in corpus_events[3]  # Noop evidence는 optional enrichment라 조용히 비운다
    assert corpus_events[4] == {"source": "U2 full search", "query": "privacy preserving RAG"}
    assert corpus_events[-1]["count"] == 2
    external_events = payloads[JobState.SEARCHING_EXTERNAL]
    assert external_events[0]["query"] == "privacy preserving RAG"
    assert external_events[-1]["count"] == 0
    assert "reason" in external_events[-1]  # Noop external은 저하 사유를 실어 보낸다
    assert payloads[JobState.SUMMARIZING_PRIOR_WORK][0]["count"] == 0
    assert payloads[JobState.PLANNING_EXPERIMENT][0]["outputSummary"] == "privacy preserving RAG"


def test_worker_query_planner_failure_degrades_not_fails() -> None:
    source_ref = {
        "type": "url",
        "identifier": "2401.00003",
        "title": "Grounded retrieval",
        "url": "https://arxiv.org/abs/2401.00003",
    }
    calls: list[str] = []

    class BrokenPlannerLlm:
        def plan_search(self, topic: str) -> NoveltySearchPlan:
            del topic
            raise TimeoutError("planner slow")

        def draft(self, *, topic, corpus, external) -> NoveltyLlmDraft:
            del external
            ref = corpus.items[0]["sourceRefs"][0]
            return NoveltyLlmDraft(
                similarWorks={
                    "items": [{"title": "Similar", "sourceRefs": [ref]}],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                noveltyCandidates={
                    "items": [{"title": "Novel", "sourceRefs": [ref]}],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                experimentPlan={
                    "researchQuestion": topic,
                    "noveltyAngle": "Use fallback query results.",
                    "hypotheses": ["Fallback search keeps the job useful."],
                    "baselines": ["Original topic search"],
                    "procedure": ["Run retrieval with the original topic."],
                    "datasets": ["Retrieved corpus"],
                    "metrics": ["evidence coverage"],
                    "resources": ["Corpus evidence"],
                    "risks": ["query rewrite timeout"],
                    "sourceRefs": [ref],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                },
            )

    class OneItemCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            del owner_id
            calls.append(query)
            return RetrievalBundle(
                items=[{"title": "Grounded retrieval", "sourceRefs": [source_ref]}],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    class CleanExternal:
        def search(self, query: str) -> RetrievalBundle:
            del query
            return RetrievalBundle(items=[])

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(
            corpus=OneItemCorpus(),
            external=CleanExternal(),
            llm=BrokenPlannerLlm(),
        ),
    )

    result = NoveltyService(repo).result(owner_id, job_id)
    assert result.job.state is JobState.DEGRADED
    assert calls == ["privacy preserving RAG"]
    assert "LLM query planning unavailable: TimeoutError" in repo.list_events(
        owner_id, job_id
    )[-1].model_dump_json()


def test_worker_uses_expanded_queries_and_reranks_evidence_items() -> None:
    source_ref = {
        "type": "url",
        "identifier": "2401.00003",
        "title": "Korean BERT Benchmark",
        "url": "https://arxiv.org/abs/2401.00003",
    }
    calls: list[str] = []

    class PlanningLlm:
        def plan_search(self, topic: str) -> NoveltySearchPlan:
            return NoveltySearchPlan(
                englishQuery="BERT Korean NLP benchmark ideas",
                keywords=["BERT", "Korean NLP", "benchmark"],
                subqueries=["KoBERT KLUE public dataset", "BERT Korean intent ranking"],
                intent={"domain": "Korean NLP", "method": "BERT"},
                rankingSignals=["KLUE", "public dataset"],
            )

        def draft(self, *, topic, corpus, external) -> NoveltyLlmDraft:
            ref = corpus.items[0]["sourceRefs"][0]
            return NoveltyLlmDraft(
                similarWorks={
                    "items": [
                        {
                            "title": corpus.items[0]["title"],
                            "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                            "sourceRefs": [ref],
                        }
                    ],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                noveltyCandidates={
                    "items": [
                        {
                            "title": "KLUE 기반 오류 유형 차별화",
                            "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                            "sourceRefs": [ref],
                        }
                    ],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                experimentPlan={
                    "researchQuestion": topic,
                    "noveltyAngle": "Korean benchmark intent differences.",
                    "hypotheses": ["Intent-aware reranking improves novelty."],
                    "baselines": ["Korean BERT Benchmark"],
                    "procedure": ["Compare against BERT baseline."],
                    "datasets": ["KLUE"],
                    "metrics": ["baseline delta"],
                    "resources": ["public benchmark"],
                    "risks": ["dataset mismatch"],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
            )

    class RecordingCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            calls.append(query)
            if "KLUE" in query:
                return RetrievalBundle(
                    items=[
                        {
                            "title": "Korean BERT Benchmark",
                            "summary": "KLUE public dataset benchmark for Korean NLP BERT models.",
                            "sourceRefs": [source_ref],
                        }
                    ],
                    evidenceStatus=EvidenceStatus.SUPPORTED,
                )
            return RetrievalBundle(
                items=[
                    {
                        "title": "Generic transformer study",
                        "summary": "General transformer analysis.",
                        "sourceRefs": [
                            {
                                **source_ref,
                                "identifier": "2401.00004",
                                "title": "Generic transformer study",
                                "url": "https://arxiv.org/abs/2401.00004",
                            }
                        ],
                    }
                ],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    class CleanExternal:
        def search(self, query: str) -> RetrievalBundle:
            return RetrievalBundle(items=[])

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(
            corpus=RecordingCorpus(),
            external=CleanExternal(),
            llm=PlanningLlm(),
        ),
    )

    assert calls[:3] == [
        "BERT Korean NLP benchmark ideas",
        "KoBERT KLUE public dataset",
        "BERT Korean intent ranking",
    ]
    evidence = next(
        artifact
        for artifact in NoveltyService(repo).result(owner_id, job_id).artifacts
        if artifact.kind is ArtifactKind.EVIDENCE
    )
    top = evidence.payload["items"][0]
    assert top["title"] == "Korean BERT Benchmark"
    assert top["confidence"] > evidence.payload["items"][1]["confidence"]
    assert "관련 내용이 확인됩니다" in top["evidenceNote"]
    assert top["queryUsed"] == "KoBERT KLUE public dataset"


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


def test_nv5_high_risk_signals_do_not_block_idea_and_plan_generation() -> None:
    """US-NV5(#255) AC3 — 위험 신호가 높아도 novelty 분석을 차단하지 않는다.

    유사도 SUPPORTED 다건 + AI 어투 신호를 함께 주입해도 실험 아이디어 추천
    (FORMING_IDEAS → novelty_candidates)과 실험 계획 생성(PLANNING_EXPERIMENT →
    experiment_plan)이 그대로 진행·산출되고 잡은 완주한다.
    """
    source_ref = {
        "type": "url",
        "identifier": "2401.00001",
        "url": "https://arxiv.org/abs/2401.00001",
    }

    class HighRiskSimilarity:
        def check(self, owner_id: str, manuscript_ref: dict) -> RetrievalBundle:
            items: list[dict] = [
                {
                    "title": f"문장 유사성: Prior work {idx}",
                    "riskType": "sentence_similarity",
                    "summary": f"작성 문장 {idx}가 'Prior work {idx}'와 유사합니다.",
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [source_ref],
                }
                for idx in range(5)
            ]
            items.append(
                {
                    "title": "AI-style phrasing risk",
                    "riskType": "ai_style",
                    "markers": ["delve", "robust framework"],
                    "evidenceStatus": EvidenceStatus.ABSTAINED.value,
                    "sourceRefs": [],
                }
            )
            return RetrievalBundle(items=items, evidenceStatus=EvidenceStatus.SUPPORTED)

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

    process_job(
        repo,
        owner_id,
        created.jobId,
        adapters=NoveltyAdapters(
            corpus=CleanCorpus(),
            external=CleanExternal(),
            llm=CleanLlm(),
            similarity=HighRiskSimilarity(),
        ),
    )

    result = service.result(owner_id, created.jobId)
    # 위험 신호가 많아도 잡은 차단되지 않고 완주한다(모든 어댑터 정상 → 저하도 아님).
    assert result.job.state is JobState.COMPLETED
    artifacts = {artifact.kind: artifact for artifact in result.artifacts}
    assert {
        ArtifactKind.RISK_SIGNALS,
        ArtifactKind.NOVELTY_CANDIDATES,
        ArtifactKind.EXPERIMENT_PLAN,
    } <= set(artifacts)
    # 위험 신호는 신호대로 저장되고,
    risk_items = artifacts[ArtifactKind.RISK_SIGNALS].payload["items"]
    assert {item["riskType"] for item in risk_items} == {"sentence_similarity", "ai_style"}
    # 아이디어 추천·실험 계획은 실제 내용을 담고 산출됐다.
    assert artifacts[ArtifactKind.NOVELTY_CANDIDATES].payload["items"]
    assert artifacts[ArtifactKind.EXPERIMENT_PLAN].payload["researchQuestion"]
    # 유사도 검사 이후 단계(FORMING_IDEAS·PLANNING_EXPERIMENT)를 실제로 통과했다.
    states = {event.state for event in repo.list_events(owner_id, created.jobId)}
    assert {
        JobState.CHECKING_SIMILARITY,
        JobState.FORMING_IDEAS,
        JobState.PLANNING_EXPERIMENT,
    } <= states


def _pdf_manuscript_job(service: NoveltyService, owner_id: str):
    return service.create_job(
        owner_id,
        NoveltyJobRequest(
            inputType="manuscript",
            topic="pdf manuscript",
            manuscript={"fileName": "draft.pdf", "contentType": "application/pdf"},
        ),
    )


def test_worker_manuscript_pdf_reenqueues_until_docmodel_ready() -> None:
    repo = InMemoryNoveltyRepository()
    service = NoveltyService(repo)
    owner_id = str(uuid4())
    created = _pdf_manuscript_job(service, owner_id)

    class NotReadySimilarity:
        def manuscript_doc_model_ready(self, owner_id: str, manuscript_ref: dict) -> bool:
            return False

        def check(self, owner_id: str, manuscript_ref: dict) -> RetrievalBundle:
            raise AssertionError("pipeline must not run while the doc-model is not ready")

    reenqueued: list[tuple[str, str, int]] = []
    process_job(
        repo,
        owner_id,
        created.jobId,
        adapters=NoveltyAdapters(similarity=NotReadySimilarity()),
        attempt=0,
        reenqueue=lambda o, j, a: reenqueued.append((o, j, a)),
    )

    # Re-enqueued with attempt+1; job stays non-terminal (NOT degraded) and the pipeline never ran.
    assert reenqueued == [(owner_id, created.jobId, 1)]
    assert service.result(owner_id, created.jobId).job.state is not JobState.DEGRADED


def test_worker_manuscript_pdf_degrades_after_max_attempts() -> None:
    repo = InMemoryNoveltyRepository()
    service = NoveltyService(repo)
    owner_id = str(uuid4())
    created = _pdf_manuscript_job(service, owner_id)

    class NotReadySimilarity:
        def manuscript_doc_model_ready(self, owner_id: str, manuscript_ref: dict) -> bool:
            return False

        def check(self, owner_id: str, manuscript_ref: dict) -> RetrievalBundle:
            return RetrievalBundle(degradedReason="manuscript_pdf_parse_unavailable")

    reenqueued: list = []
    # At the attempt cap the gate does NOT re-enqueue — the pipeline runs and degrades (bounded).
    process_job(
        repo,
        owner_id,
        created.jobId,
        adapters=NoveltyAdapters(similarity=NotReadySimilarity()),
        attempt=_MANUSCRIPT_DOCMODEL_MAX_ATTEMPTS,
        reenqueue=lambda o, j, a: reenqueued.append((o, j, a)),
    )

    assert reenqueued == []
    assert service.result(owner_id, created.jobId).job.state is JobState.DEGRADED


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


def test_worker_natural_language_forms_evidence_first_and_merges_bundle() -> None:
    calls: list[str] = []
    paper_ref = {
        "type": "paper",
        "identifier": "2401.01234",
        "title": "arXiv:2401.01234",
        "url": "https://arxiv.org/abs/2401.01234",
        "sourceName": "arXiv",
    }

    class RecordingEvidence:
        def form(self, owner_id: str, topic: str) -> RetrievalBundle:
            calls.append(f"evidence:{topic}")
            return RetrievalBundle(
                items=[
                    {
                        "title": "Benchmark reuse inflates scores.",
                        "summary": "benchmark reuse inflates scores",
                        "sourceType": "evidence_claim",
                        "sourceName": "U11 evidence",
                        "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                        "sourceRefs": [paper_ref],
                    }
                ],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    class RewritingLlm:
        def plan_search(self, topic: str) -> NoveltySearchPlan:
            return NoveltySearchPlan(
                englishQuery="rewritten query for corpus search",
                keywords=["rewritten"],
                subqueries=["expanded evidence search"],
                intent={"goal": topic},
                rankingSignals=["rewritten"],
            )

        def draft(self, *, topic, corpus, external) -> NoveltyLlmDraft:
            ref = corpus.items[0]["sourceRefs"][0]
            return NoveltyLlmDraft(
                similarWorks={
                    "items": [{"title": "Similar", "sourceRefs": [ref]}],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                noveltyCandidates={
                    "items": [{"title": "Novel", "sourceRefs": [ref]}],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                    "sourceRefs": [ref],
                },
                experimentPlan={
                    "researchQuestion": topic,
                    "noveltyAngle": "Compare original and expanded evidence.",
                    "hypotheses": ["Expanded search preserves evidence ordering."],
                    "baselines": ["Original query retrieval"],
                    "procedure": ["Compare merged evidence bundles."],
                    "datasets": ["Retrieved corpus"],
                    "metrics": ["evidence coverage"],
                    "resources": ["Corpus evidence"],
                    "risks": ["query drift"],
                    "sourceRefs": [ref],
                    "evidenceStatus": EvidenceStatus.SUPPORTED.value,
                },
            )

    class RecordingCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            calls.append(f"corpus:{query}")
            return RetrievalBundle(
                items=[{"title": "Corpus paper", "sourceRefs": [paper_ref]}],
                evidenceStatus=EvidenceStatus.SUPPORTED,
            )

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(
            corpus=RecordingCorpus(),
            evidence=RecordingEvidence(),
            llm=RewritingLlm(),
        ),
    )

    # US-NV1(#251) AC1 — form_evidence가 원문 질의로 U2 검색보다 먼저 호출된다
    assert calls[:2] == [
        "evidence:privacy preserving RAG",
        "corpus:rewritten query for corpus search",
    ]
    result = NoveltyService(repo).result(owner_id, job_id)
    evidence_artifact = next(
        artifact for artifact in result.artifacts if artifact.kind is ArtifactKind.EVIDENCE
    )
    titles = [item["title"] for item in evidence_artifact.payload["items"]]
    # 근거 묶음이 앞서고(AC1) corpus 결과가 보강한다(AC2)
    assert titles == ["Benchmark reuse inflates scores.", "Corpus paper"]


def test_worker_manuscript_job_skips_evidence_formation() -> None:
    calls: list[str] = []

    class RecordingEvidence:
        def form(self, owner_id: str, topic: str) -> RetrievalBundle:
            calls.append("evidence")
            return RetrievalBundle(items=[])

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

    process_job(
        repo, owner_id, created.jobId, adapters=NoveltyAdapters(evidence=RecordingEvidence())
    )

    assert calls == []  # US-NV1은 자연어 잡 전용 — 원고 잡은 근거형성 선행 없음


def test_worker_treats_evidence_abstain_as_degradation_without_fabrication() -> None:
    class AbstainingEvidence:
        def form(self, owner_id: str, topic: str) -> RetrievalBundle:
            return RetrievalBundle(
                degradedReason="evidence formation abstained: out_of_corpus"
            )

    class OneItemCorpus:
        def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
            return RetrievalBundle(
                items=[
                    {
                        "title": "Corpus paper",
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

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _service_job(repo)

    process_job(
        repo,
        owner_id,
        job_id,
        adapters=NoveltyAdapters(corpus=OneItemCorpus(), evidence=AbstainingEvidence()),
    )

    # Evidence formation은 optional enrichment다: abstain은 날조/저하 없이 corpus만 남긴다.
    result = NoveltyService(repo).result(owner_id, job_id)
    evidence_artifact = next(
        artifact for artifact in result.artifacts if artifact.kind is ArtifactKind.EVIDENCE
    )
    assert [item["title"] for item in evidence_artifact.payload["items"]] == ["Corpus paper"]
    events_json = " ".join(
        event.model_dump_json() for event in repo.list_events(owner_id, job_id)
    )
    assert "evidence formation abstained: out_of_corpus" not in events_json


def test_evidence_formation_client_maps_claims_and_abstain() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
    )
    from docsuri_shared._generated.dtos.evidence_schema import (
        SourceRef as EvidenceSourceRef,
    )

    class OkPort:
        async def form_evidence(self, request, ctx):
            assert request.topic == "rag evaluation"
            assert ctx.owner_id == "u1"
            return EvidenceResult(
                state="ok",
                claims=[
                    EvidenceItem(
                        statement="Benchmark reuse inflates scores.",
                        supporting=[
                            EvidenceSourceRef(
                                paperId="2401.01234",
                                recordRef="rec-1",
                                quote="benchmark reuse inflates scores",
                            )
                        ],
                        conflicting=[
                            EvidenceSourceRef(paperId="2402.09999", recordRef="rec-2")
                        ],
                    ),
                    EvidenceItem(statement="   ", supporting=[], conflicting=[]),
                ],
                coverage=EvidenceCoverage(paperCount=2),
            )

    bundle = EvidenceFormationClient(OkPort()).form("u1", "rag evaluation")

    assert bundle.evidenceStatus is EvidenceStatus.SUPPORTED
    assert len(bundle.items) == 1  # 빈 statement는 탈락
    item = bundle.items[0]
    assert item["title"] == "Benchmark reuse inflates scores."
    assert item["summary"] == "benchmark reuse inflates scores"
    assert item["sourceRefs"][0]["url"] == "https://arxiv.org/abs/2401.01234"
    assert item["conflictingCount"] == 1

    class AbstainPort:
        async def form_evidence(self, request, ctx):
            return EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus")

    degraded = EvidenceFormationClient(AbstainPort()).form("u1", "rag evaluation")
    assert degraded.items == []
    assert degraded.degradedReason is None


def test_evidence_formation_client_does_not_fabricate_arxiv_url_for_userdoc() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
    )
    from docsuri_shared._generated.dtos.evidence_schema import (
        SourceRef as EvidenceSourceRef,
    )

    class UserDocPort:
        async def form_evidence(self, request, ctx):
            return EvidenceResult(
                state="ok",
                claims=[
                    EvidenceItem(
                        statement="Uploaded PDF supports the method claim.",
                        supporting=[
                            EvidenceSourceRef(
                                paperId="userdoc:11111111-1111-4111-8111-111111111111",
                                recordRef=(
                                    "upload:u1:"
                                    "userdoc-11111111-1111-4111-8111-111111111111:att-1"
                                ),
                                quote="method claim",
                            )
                        ],
                        conflicting=[],
                    )
                ],
                coverage=EvidenceCoverage(paperCount=1),
            )

    bundle = EvidenceFormationClient(UserDocPort()).form("u1", "rag evaluation")

    ref = bundle.items[0]["sourceRefs"][0]
    assert ref["type"] == "upload"
    assert ref["identifier"].startswith("userdoc:")
    assert "url" not in ref


class _RecordingNotion:
    def __init__(self) -> None:
        self.calls: list[tuple[dict, dict]] = []

    def export(self, connection: dict, content: dict) -> str:
        self.calls.append((connection, content))
        return "page-abc"


def test_api_notion_connection_and_approved_export_completes(monkeypatch) -> None:
    from cryptography.fernet import Fernet

    from backend.modules.novelty.security import decrypt_secret

    raw_token = "not a real notion integration value"
    monkeypatch.setenv("DOCSURI_NOTION_TOKEN_KEY", Fernet.generate_key().decode())
    repo = InMemoryNoveltyRepository()
    # 요청마다 principal이 새로 뽑히지 않도록 고정 — 연결 저장·조회가 같은 owner여야 한다
    client = _client(monkeypatch, principal=_principal(), repo=repo)
    notion = _RecordingNotion()
    client.app.state.novelty_adapters = NoveltyAdapters(notion=notion)

    job_id = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "rag evaluation"},
    ).json()["jobId"]

    saved = client.put(
        "/api/novelty/notion/connection",
        json={"token": raw_token, "parentPageId": "0" * 32},
    )
    assert saved.status_code == 200
    assert saved.json()["connected"] is True
    assert raw_token not in saved.text  # SEC-12 — 응답에 토큰 미포함
    assert client.get("/api/novelty/notion/connection").json()["connected"] is True

    # SEC-8 — 저장소에는 암호문만 남고 복호화가 원문을 돌려준다
    stored = next(iter(repo._notion_connections.values()))
    assert raw_token not in stored.tokenEncrypted
    assert decrypt_secret(stored.tokenEncrypted) == raw_token

    assert client.post(f"/api/novelty/jobs/{job_id}/notion/preview").status_code == 200
    approved = client.post(
        f"/api/novelty/jobs/{job_id}/notion/approve", json={"approved": True}
    )
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "exported"
    assert body["notionPageId"] == "page-abc"
    assert raw_token not in approved.text

    connection, content = notion.calls[0]
    assert connection["token"] == raw_token  # 복호화된 토큰이 어댑터에 전달된다
    assert connection["parentPageId"] == "0" * 32
    assert content["title"].endswith("_Novelty_분석_결과")
    assert content["title"][:8].isdigit()
    assert content["title"][8] == ":"
    assert content["title"][9:13].isdigit()
    assert content["inputPrompt"] == "rag evaluation"
    assert content["artifacts"] and "payload" in content["artifacts"][0]

    assert client.delete("/api/novelty/notion/connection").status_code == 204
    assert client.get("/api/novelty/notion/connection").json()["connected"] is False


def test_api_approved_export_without_connection_fails_softly(monkeypatch) -> None:
    client = _client(monkeypatch, principal=_principal())
    job_id = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "rag evaluation"},
    ).json()["jobId"]

    client.post(f"/api/novelty/jobs/{job_id}/notion/preview")
    approved = client.post(
        f"/api/novelty/jobs/{job_id}/notion/approve", json={"approved": True}
    )

    # US-NV8 — 연결 없음은 FAILED 상태+비기술 문구로 수렴, 500 아님
    assert approved.status_code == 200
    body = approved.json()
    assert body["status"] == "failed"
    assert "Notion 연결이 없습니다" in body["errorMessage"]


def test_api_notion_connection_is_owner_scoped(monkeypatch) -> None:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("DOCSURI_NOTION_TOKEN_KEY", Fernet.generate_key().decode())
    repo = InMemoryNoveltyRepository()
    owner_a = _principal(str(uuid4()))
    owner_b = _principal(str(uuid4()))
    client_a = _client(monkeypatch, principal=owner_a, repo=repo)
    client_b = _client(monkeypatch, principal=owner_b, repo=repo)

    assert client_a.put(
        "/api/novelty/notion/connection",
        json={"token": "not a real owner scoped notion value", "parentPageId": "a" * 32},
    ).status_code == 200

    assert client_a.get("/api/novelty/notion/connection").json()["connected"] is True
    assert client_b.get("/api/novelty/notion/connection").json()["connected"] is False


def test_notion_api_client_builds_page_request_and_maps_errors() -> None:
    captured: dict = {}

    class OkHttp:
        def post(self, url, headers=None, json=None):
            captured["url"], captured["headers"], captured["json"] = url, headers, json

            class R:
                status_code = 200

                @staticmethod
                def json():
                    return {"id": "page-xyz"}

            return R()

    content = {
        "title": "20260706:1624_Novelty_분석_결과",
        "inputPrompt": "rag",
        "artifacts": [
            {
                "kind": "experiment_plan",
                "title": "Experiment plan",
                "payload": {
                    "items": [{"title": "A", "summary": "B"}],
                    "researchQuestion": "RQ?",
                },
            }
        ],
    }
    page_id = NotionApiExportClient(OkHttp()).export(
        {"token": "tok", "parentPageId": "0" * 32}, content
    )

    assert page_id == "page-xyz"
    assert captured["url"] == "https://api.notion.com/v1/pages"
    assert captured["headers"]["Authorization"] == "Bearer tok"
    assert captured["json"]["parent"] == {"page_id": "0" * 32}
    title = captured["json"]["properties"]["title"]["title"][0]["text"]["content"]
    assert title == "20260706:1624_Novelty_분석_결과"
    blocks = json.dumps(captured["json"]["children"], ensure_ascii=False)
    assert "입력 프롬프트: rag" in blocks
    assert "Experiment plan" in blocks
    assert "A — B" in blocks
    assert "Research question: RQ?" in blocks

    class ErrHttp:
        def post(self, url, headers=None, json=None):
            class R:
                status_code = 403

                @staticmethod
                def json():
                    return {}

            return R()

    with pytest.raises(RuntimeError):
        NotionApiExportClient(ErrHttp()).export(
            {"token": "tok", "parentPageId": "0" * 32}, content
        )


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
    # Pin the fake/live seam: the app-shell wires live Bedrock/HTTP adapters into
    # app.state, and the no-queue dispatch path runs the worker inline — so ambient
    # AWS creds would otherwise decide the terminal state. Noop adapters degrade
    # deterministically regardless of environment.
    client.app.state.novelty_adapters = NoveltyAdapters()

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
    docx_content_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    resp = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "novelty agent",
            "manuscript": {
                "fileName": "draft.docx",
                "contentType": docx_content_type,
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


def _stream_chunk(payload: dict) -> dict:
    return {"chunk": {"bytes": json.dumps(payload).encode("utf-8")}}


def _tool_stream_chunk(partial_json: str) -> dict:
    return _stream_chunk(
        {
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": partial_json},
        }
    )


def test_bedrock_llm_client_invokes_at_cost_guard_warning() -> None:
    """NFR-C1 — agent hard gate는 warning(80%)에서는 Bedrock을 막지 않는다."""
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker
    from docsuri_ops.domain.models import UsageEvent

    class _Invoke:
        called = False

        def invoke_model_with_response_stream(self, **kwargs):
            self.called = True
            return {
                "body": [
                    _tool_stream_chunk("{}")
                ]
            }

    guard = CostGuardCircuitBreaker()
    guard.record_spend(UsageEvent(event_id="seed", amount_usd=1280.0, source="test"))
    ref = {"type": "url", "identifier": "2401.00001", "url": "https://arxiv.org/abs/2401.00001"}
    client = _Invoke()

    draft = BedrockNoveltyLlmClient(model_id="m", client=client, cost_guard=guard).draft(
        topic="t",
        corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [ref]}]),
        external=RetrievalBundle(items=[]),
    )

    assert client.called is True
    assert draft.degradedReason is None


def test_bedrock_llm_client_degrades_without_invoke_when_cost_guard_critical() -> None:
    """NFR-C1 — critical cost guard 상태면 Bedrock 호출 없이 cost_degraded로 저하한다."""
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker
    from docsuri_ops.domain.models import UsageEvent

    class _NoInvoke:
        def invoke_model_with_response_stream(self, **kwargs):
            raise AssertionError("LLM must not be invoked while the cost guard is gated")

    guard = CostGuardCircuitBreaker()
    guard.record_spend(UsageEvent(event_id="seed", amount_usd=1520.0, source="test"))
    ref = {"type": "url", "identifier": "2401.00001", "url": "https://arxiv.org/abs/2401.00001"}

    draft = BedrockNoveltyLlmClient(model_id="m", client=_NoInvoke(), cost_guard=guard).draft(
        topic="t",
        corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [ref]}]),
        external=RetrievalBundle(items=[]),
    )

    assert draft.degradedReason == "cost_degraded"


def test_bedrock_llm_client_records_spend_from_usage() -> None:
    """NFR-C1 — 스트림 usage 이벤트의 토큰이 cost guard 지출로 기록된다."""
    from docsuri_ops.cost_guard import CostGuardCircuitBreaker

    class _FakeBedrock:
        def invoke_model_with_response_stream(self, **kwargs):
            return {
                "body": [
                    _stream_chunk(
                        {
                            "type": "message_start",
                            "message": {"usage": {"input_tokens": 1_000_000, "output_tokens": 1}},
                        }
                    ),
                    _tool_stream_chunk(json.dumps({})),
                    _stream_chunk(
                        {
                            "type": "message_delta",
                            "delta": {"stop_reason": "end_turn"},
                            "usage": {"output_tokens": 200_000},
                        }
                    ),
                ]
            }

    guard = CostGuardCircuitBreaker()
    ref = {"type": "url", "identifier": "2401.00001", "url": "https://arxiv.org/abs/2401.00001"}

    BedrockNoveltyLlmClient(model_id="m", client=_FakeBedrock(), cost_guard=guard).draft(
        topic="t",
        corpus=RetrievalBundle(items=[{"title": "Prior", "sourceRefs": [ref]}]),
        external=RetrievalBundle(items=[]),
    )

    # 기본 단가 $3/1M input + $15/1M output → 1M in + 0.2M out = $6
    assert abs(guard.get_budget_state().spend_usd - 6.0) < 1e-9


def test_api_reset_deletes_only_own_jobs(monkeypatch) -> None:
    """US-EV8(#272) 전체 초기화 — 소유 잡 전부 삭제(멱등), 타 사용자 잡 보존."""
    owner_a = _principal()
    owner_b = _principal()
    repo = InMemoryNoveltyRepository()
    client_a = _client(monkeypatch, owner_a, repo)
    client_b = _client(monkeypatch, owner_b, repo)

    client_a.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "reset target job one"},
    )
    client_a.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "reset target job two"},
    )
    kept = client_b.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "surviving job"},
    ).json()["jobId"]

    assert client_a.delete("/api/novelty/jobs").status_code == 204
    assert client_a.get("/api/novelty/jobs").json()["jobs"] == []
    assert client_b.get(f"/api/novelty/jobs/{kept}").status_code == 200
    # 멱등 — 이미 비어 있어도 204.
    assert client_a.delete("/api/novelty/jobs").status_code == 204


def test_sql_delete_job_and_reset_purge_child_rows() -> None:
    """US-EV8(#272)/SEC-14 — SQL 삭제는 이벤트·메시지 등 자식 행까지 제거(고아 금지 회귀)."""
    from backend.db import make_engine, make_session_factory
    from backend.modules.novelty.models import ChatMessageCreateRequest
    from backend.modules.novelty.repository import (
        ArtifactTable,
        Base,
        NotionExportTable,
        NoveltyJobTable,
        NoveltyMessageTable,
        ProgressEventTable,
        SqlNoveltyRepository,
    )

    engine = make_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = make_session_factory(engine)()
    repo = SqlNoveltyRepository(session)
    service = NoveltyService(repo)
    owner = str(uuid4())

    first = service.create_job(
        owner, NoveltyJobRequest(inputType="natural_language", topic="cascade delete first")
    )
    service.create_job(
        owner, NoveltyJobRequest(inputType="natural_language", topic="cascade delete second")
    )
    service.record_event(repo.get_job(owner, first.jobId), "cascade seed event")
    service.add_message(owner, first.jobId, ChatMessageCreateRequest(content="history row"))
    assert session.query(ProgressEventTable).count() > 0
    assert session.query(NoveltyMessageTable).count() > 0

    service.delete_job(owner, first.jobId)

    assert session.query(ProgressEventTable).filter_by(job_id=first.jobId).count() == 0
    assert session.query(NoveltyMessageTable).filter_by(job_id=first.jobId).count() == 0

    service.delete_all_jobs(owner)

    for table in (
        NoveltyJobTable,
        ProgressEventTable,
        NoveltyMessageTable,
        ArtifactTable,
        NotionExportTable,
    ):
        assert session.query(table).count() == 0


def test_api_manuscript_upload_binds_key_and_dispatches(monkeypatch) -> None:
    """US-NV2(#252) — 원고 잡 생성(본문 없음) → 디스패치 보류(queued 유지) → 본문 업로드
    → S3 적재(유사도 어댑터 프리픽스 규약) → objectKey 바인딩 → 분석 시작."""
    import boto3

    puts: list[dict] = []

    class FakeS3:
        def __init__(self) -> None:
            self.objects: dict[str, bytes] = {}

        def put_object(self, **kwargs):
            puts.append(kwargs)
            self.objects[kwargs["Key"]] = kwargs["Body"]
            return {}

        def get_object(self, **kwargs):
            body = self.objects.get(kwargs["Key"], b"")
            return {"Body": BytesIO(body if isinstance(body, bytes) else bytes(body))}

    fake = FakeS3()
    monkeypatch.setenv("DOCSURI_NOVELTY_ARTIFACT_BUCKET", "papers")
    monkeypatch.delenv("DOCSURI_NOVELTY_JOB_QUEUE_URL", raising=False)
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: fake)

    principal = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, principal, repo)

    created = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "manuscript novelty flow",
            "manuscript": {"fileName": "draft.md", "contentType": "text/markdown"},
        },
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]
    # 본문 업로드 전 — 디스패치 보류(QUEUED 유지)
    assert client.get(f"/api/novelty/jobs/{job_id}").json()["job"]["state"] == "queued"

    uploaded = client.post(
        f"/api/novelty/jobs/{job_id}/manuscript",
        json={"contentText": "# Draft\nprivacy preserving retrieval evaluation."},
    )

    assert uploaded.status_code == 200
    assert puts and puts[0]["Key"] == f"novelty/{principal.user_id}/{job_id}/manuscript.md"
    assert repo.get_job(principal.user_id, job_id).manuscript.objectKey == puts[0]["Key"]
    # 큐 미구성 → 인라인 워커가 잡을 진행시킨다(더는 queued가 아니다).
    assert client.get(f"/api/novelty/jobs/{job_id}").json()["job"]["state"] != "queued"


def test_api_manuscript_pdf_upload_binds_userdoc_contract(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, principal, repo)
    fake_user_docmodel = _FakeUserDocModel(None)
    client.app.dependency_overrides[controller.get_user_docmodel] = (
        lambda: fake_user_docmodel
    )
    monkeypatch.delenv("DOCSURI_NOVELTY_JOB_QUEUE_URL", raising=False)

    created = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "pdf manuscript novelty flow",
            "manuscript": {"fileName": "draft.pdf", "contentType": "application/pdf"},
        },
    )
    assert created.status_code == 200
    job_id = created.json()["jobId"]

    uploaded = client.post(
        f"/api/novelty/jobs/{job_id}/manuscript?fileName=draft.pdf",
        content=b"%PDF-1.4",
        headers={"content-type": "application/pdf"},
    )

    assert uploaded.status_code == 200
    manuscript = repo.get_job(principal.user_id, job_id).manuscript
    assert manuscript is not None
    assert manuscript.objectKey == f"novelty/{principal.user_id}/{job_id}/manuscript/draft.pdf"
    assert manuscript.paperId is not None and manuscript.paperId.startswith("userdoc:")
    assert manuscript.recordRef is not None
    assert manuscript.recordRef.startswith(f"upload:{principal.user_id}:userdoc-")
    assert fake_user_docmodel.uploads[0]["pdf"] == b"%PDF-1.4"
    assert fake_user_docmodel.enqueued[0].payload()["kind"] == "BUILD_USER_DOC_MODEL"
    assert "arxivRef" not in fake_user_docmodel.enqueued[0].payload()


def test_api_manuscript_upload_guards(monkeypatch) -> None:
    """US-NV2(#252) — 소유자 격리(404) · 비원고 잡(422) · 중복 업로드(422)."""
    import boto3

    class FakeS3:
        def put_object(self, **kwargs):
            return {}

        def get_object(self, **kwargs):
            return {"Body": BytesIO(b"draft body")}

    monkeypatch.setenv("DOCSURI_NOVELTY_ARTIFACT_BUCKET", "papers")
    monkeypatch.delenv("DOCSURI_NOVELTY_JOB_QUEUE_URL", raising=False)
    monkeypatch.setattr(boto3, "client", lambda *_a, **_k: FakeS3())

    owner = _principal()
    repo = InMemoryNoveltyRepository()
    client = _client(monkeypatch, owner, repo)
    intruder = _client(monkeypatch, _principal(), repo)

    manuscript_job = client.post(
        "/api/novelty/jobs",
        json={
            "inputType": "manuscript",
            "topic": "guard checks",
            "manuscript": {"fileName": "draft.txt", "contentType": "text/plain"},
        },
    ).json()["jobId"]
    text_job = client.post(
        "/api/novelty/jobs",
        json={"inputType": "natural_language", "topic": "plain topic job"},
    ).json()["jobId"]

    payload = {"contentText": "guard body"}
    assert (
        intruder.post(f"/api/novelty/jobs/{manuscript_job}/manuscript", json=payload).status_code
        == 404
    )
    assert (
        client.post(f"/api/novelty/jobs/{text_job}/manuscript", json=payload).status_code == 422
    )
    assert (
        client.post(f"/api/novelty/jobs/{manuscript_job}/manuscript", json=payload).status_code
        == 200
    )
    assert (
        client.post(f"/api/novelty/jobs/{manuscript_job}/manuscript", json=payload).status_code
        == 422
    )
