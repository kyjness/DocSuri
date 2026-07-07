"""QT-10(#259 US-NV9) — novelty 품질 게이트.

SourceRef 무결성 · 소스 정규화 · 잡 상태 전이 · 실험 계획 필수 필드 · Notion export
무결성을 하나의 상시 게이트 모듈로 묶는다. per-source 저하 지표(#259 AC1)는
worker의 `novelty.step_degraded` 방출을 여기서 검증한다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from backend.modules.novelty.adapters import RetrievalBundle, _fallback_experiment_plan
from backend.modules.novelty.models import (
    ALLOWED_TRANSITIONS,
    STATE_PROGRESS,
    TERMINAL_STATES,
    ArtifactKind,
    ArtifactValidationError,
    EvidenceStatus,
    ExportApprovalError,
    ExportStatus,
    InvalidTransitionError,
    JobState,
    NoveltyJobRequest,
    validate_transition,
)
from backend.modules.novelty.repository import InMemoryNoveltyRepository
from backend.modules.novelty.service import NoveltyService
from backend.modules.novelty.validators import normalize_source_key, validate_artifact_payload
from backend.modules.novelty.worker import _payload_from_bundle, process_job


def _natural_job(repo: InMemoryNoveltyRepository) -> tuple[NoveltyService, str, str]:
    owner_id = str(uuid4())
    service = NoveltyService(repo)
    created = service.create_job(
        owner_id,
        NoveltyJobRequest(inputType="natural_language", topic="privacy preserving RAG"),
    )
    return service, owner_id, created.jobId


def test_qt10_supported_bundle_without_source_refs_is_downgraded() -> None:
    payload, reason = _payload_from_bundle(
        RetrievalBundle(items=[{"title": "no refs"}], evidenceStatus=EvidenceStatus.SUPPORTED)
    )

    assert payload["evidenceStatus"] == EvidenceStatus.UNSUPPORTED.value
    assert reason is not None and "sourceRefs" in reason


def test_qt10_source_key_normalization_is_stable() -> None:
    assert normalize_source_key(" DOI ", "10.1234/AbC") == normalize_source_key(
        "doi", "10.1234/abc"
    )
    url_a = normalize_source_key("url", "https://GitHub.com/openai/codex/?b=2&a=1")
    url_b = normalize_source_key("url", "github.com/openai/codex?a=1&b=2")
    assert url_a == url_b


def test_qt10_terminal_states_admit_no_transitions() -> None:
    for terminal in TERMINAL_STATES:
        for target in JobState:
            if target is terminal:
                continue
            with pytest.raises(InvalidTransitionError):
                validate_transition(terminal, target)


def test_qt10_cancel_reachable_everywhere_and_progress_monotone() -> None:
    for state in JobState:
        if state in TERMINAL_STATES:
            continue
        validate_transition(state, JobState.CANCELLED)  # 예외 없음 = 취소 가능

    for current, targets in ALLOWED_TRANSITIONS.items():
        for target in targets:
            if target in {JobState.CANCELLED, JobState.FAILED}:
                continue
            assert STATE_PROGRESS[target] >= STATE_PROGRESS[current]


def test_qt10_experiment_plan_required_fields_enforced() -> None:
    plan = _fallback_experiment_plan("rag eval")
    validate_artifact_payload(ArtifactKind.EXPERIMENT_PLAN, plan)  # 기본 계획은 통과

    with pytest.raises(ArtifactValidationError):
        validate_artifact_payload(
            ArtifactKind.EXPERIMENT_PLAN, {**plan, "researchQuestion": "  "}
        )
    with pytest.raises(ArtifactValidationError):
        validate_artifact_payload(ArtifactKind.EXPERIMENT_PLAN, {**plan, "hypotheses": []})


def test_qt10_notion_export_gate_matrix() -> None:
    repo = InMemoryNoveltyRepository()
    service, owner_id, job_id = _natural_job(repo)

    # 미리보기 없이 승인 금지
    with pytest.raises(ExportApprovalError):
        service.approve_export(owner_id, job_id, approved=True)

    # 승인 없이 실행·완료 금지
    service.preview_export(owner_id, job_id)
    with pytest.raises(ExportApprovalError):
        service.execute_export(owner_id, job_id, notion=None)
    with pytest.raises(ExportApprovalError):
        service.complete_export(owner_id, job_id, "page-x")

    # 승인 후 연결 없음 → 예외가 아니라 FAILED 상태로 남는다(export 무결성)
    service.approve_export(owner_id, job_id, approved=True)
    failed = service.execute_export(owner_id, job_id, notion=None)
    assert failed.status is ExportStatus.FAILED
    assert failed.errorMessage


def test_qt10_worker_emits_per_source_degradation_metrics() -> None:
    class FakeObservability:
        def __init__(self) -> None:
            self.metrics: list[tuple[str, dict]] = []

        def emit_metric(self, name: str, value: float = 1.0, tags: dict | None = None) -> None:
            self.metrics.append((name, tags or {}))

    repo = InMemoryNoveltyRepository()
    _, owner_id, job_id = _natural_job(repo)
    observability = FakeObservability()

    process_job(repo, owner_id, job_id, observability=observability)  # optional evidence 제외

    degraded_sources = {
        tags.get("source")
        for name, tags in observability.metrics
        if name == "novelty.step_degraded"
    }
    assert {
        "U2 full search",
        "GitHub · Hugging Face · Zenodo",
        "Bedrock LLM",
    } <= degraded_sources
