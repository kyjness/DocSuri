"""Novelty Agent v2 도메인 엔티티 — domain-entities.md가 SSOT.

거시 상태(BR-RA5)·3중 예산(BR-RA3)·결정 트레이스(BR-RA4)의 구조를 정의한다.
SourceRef·EvidenceItem 등 근거 계약은 docsuri_shared에서 소비만 한다(BR-NV1 — 재정의 금지).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceCoverage,
    EvidenceItem,
    EvidenceRequest,
    SourceRef,
)

__all__ = [
    "ALLOWED_TRANSITIONS",
    "REQUIRED_ARTIFACT_KINDS",
    "SUPPORTED_MANUSCRIPT_CONTENT_TYPES",
    "TERMINAL_STATES",
    "AgentLoopRun",
    "ArtifactKind",
    "ArtifactRecord",
    "BudgetConsumed",
    "ChatKind",
    "ChatRole",
    "EvidenceCoverage",
    "EvidenceItem",
    "EvidenceRequest",
    "EvidenceSnapshot",
    "EvidenceStatus",
    "ExperimentPlan",
    "ExportStatus",
    "ExternalFinding",
    "GapAnalysis",
    "GapItem",
    "GapStatus",
    "InputType",
    "InvalidTransitionError",
    "JobState",
    "LoopBudget",
    "ManuscriptRef",
    "NotionConnection",
    "NotionExport",
    "NoveltyCandidate",
    "NoveltyChatMessage",
    "NoveltyError",
    "NoveltyJob",
    "NoveltyJobRequest",
    "SimilarWorkItem",
    "SourceRef",
    "TerminationReason",
    "ToolCallRecord",
    "ToolOutcome",
    "utc_now",
    "validate_transition",
]


def utc_now() -> datetime:
    return datetime.now(UTC)


class NoveltyError(Exception):
    pass


class InvalidTransitionError(NoveltyError):
    pass


class InputType(StrEnum):
    NATURAL_LANGUAGE = "natural_language"
    MANUSCRIPT = "manuscript"


class JobState(StrEnum):
    """거시 진행 상태(FR-35 개정) — 구 11종 enum 대체."""

    RECEIVED = "received"
    INVESTIGATING = "investigating"
    REPORTING = "reporting"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TerminationReason(StrEnum):
    """AgentLoopRun 종료 사유 — 종단 시 필수(BLM §2)."""

    ARTIFACTS_COMPLETE = "artifacts_complete"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    FATAL_ERROR = "fatal_error"


class ToolOutcome(StrEnum):
    """ToolCallRecord.outcome(FR-46)."""

    OK = "ok"
    ERROR = "error"
    REJECTED_BY_GATE = "rejected_by_gate"
    BUDGET_DENIED = "budget_denied"


class ArtifactKind(StrEnum):
    EVIDENCE = "evidence"
    SIMILAR_WORKS = "similar_works"
    GAP_ANALYSIS = "gap_analysis"
    EXTERNAL_FINDINGS = "external_findings"
    NOVELTY_CANDIDATES = "novelty_candidates"
    EXPERIMENT_PLAN = "experiment_plan"


class GapStatus(StrEnum):
    WELL_COVERED = "well_covered"
    PARTIALLY_COVERED = "partially_covered"
    OPEN_GAP = "open_gap"


class ChatRole(StrEnum):
    USER = "user"
    AGENT = "agent"


class ChatKind(StrEnum):
    """잡 내 대화 메시지 종류(FR-44)."""

    STEERING = "steering"
    ON_DEMAND_REQUEST = "on_demand_request"
    AGENT_REPLY = "agent_reply"
    NOTICE = "notice"


class EvidenceStatus(StrEnum):
    """유사 연구 표 셀의 근거 상태(BR-NV9 승계) — 근거 없으면 셀을 채우지 않는다."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    ABSTAINED = "abstained"


class ExportStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    PREVIEW_READY = "preview_ready"
    APPROVED = "approved"
    EXPORTING = "exporting"
    EXPORTED = "exported"
    FAILED = "failed"


SUPPORTED_MANUSCRIPT_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "text/markdown",
        "text/plain",
    }
)

# 기본 세트(BR-RA1) — 전부 게이트 통과·저장되어야 completed.
REQUIRED_ARTIFACT_KINDS = frozenset(
    {ArtifactKind.EVIDENCE, ArtifactKind.SIMILAR_WORKS, ArtifactKind.GAP_ANALYSIS}
)

TERMINAL_STATES = frozenset(
    {JobState.COMPLETED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELLED}
)

# Progress State Rules(business-rules.md). received -> cancelled는 워커 픽업 전
# 협조적 취소 경로로 허용한다(취소 신호는 어느 활성 상태에서든 수신 가능).
ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.RECEIVED: frozenset({JobState.INVESTIGATING, JobState.CANCELLED, JobState.FAILED}),
    JobState.INVESTIGATING: frozenset(
        {JobState.REPORTING, JobState.PARTIAL, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.REPORTING: frozenset(
        {JobState.COMPLETED, JobState.PARTIAL, JobState.CANCELLED, JobState.FAILED}
    ),
}


def validate_transition(current: JobState, target: JobState) -> None:
    """허용 전이만 통과(PBT-NV4). 종단 상태 재진입 금지 — 온디맨드 생성은
    종단 상태를 유지한 채 대화 턴으로 처리한다(BR-RA5)."""
    if current == target:
        return
    if current in TERMINAL_STATES:
        raise InvalidTransitionError(f"job is terminal: {current}")
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"invalid transition: {current} -> {target}")


class ManuscriptRef(BaseModel):
    """owner-scoped 원고 첨부 핸들. 원고는 '내 주제가 이미 연구됐나'의 입력으로만
    쓴다 — 위험 신호 산출은 폐기(FR-34)."""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=1, max_length=120)
    object_key: str | None = Field(default=None, max_length=512)
    paper_id: str | None = Field(default=None, max_length=128)
    record_ref: str | None = Field(default=None, max_length=512)

    @field_validator("content_type")
    @classmethod
    def _normalize_content_type(cls, value: str) -> str:
        return value.strip().lower()


class NoveltyJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_type: InputType
    topic: str = Field(min_length=3, max_length=2000)
    evidence_request: EvidenceRequest
    manuscript_ref: ManuscriptRef | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    export_target: str | None = Field(default=None, max_length=512)

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("topic must be at least 3 characters")
        return stripped

    @model_validator(mode="after")
    def _manuscript_required_for_manuscript_input(self):
        if self.input_type is InputType.MANUSCRIPT and self.manuscript_ref is None:
            raise ValueError("manuscript_ref is required for manuscript input")
        return self


class BudgetConsumed(BaseModel):
    """소비량 — 단조 증가만 허용(PBT-RA2). 갱신은 domain.budget이 담당."""

    iterations: int = Field(default=0, ge=0)
    tool_calls_total: int = Field(default=0, ge=0)
    tool_calls: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = Field(default=0.0, ge=0.0)


class LoopBudget(BaseModel):
    """3중 한도(FR-45, BR-RA3). 수치는 설정 주입(NFR §3 시작값) — 도메인에 상수 금지.
    비용 판정은 U6 get_budget_state() 단일 권위이며 본 한도는 per-job 배분치다."""

    model_config = ConfigDict(extra="forbid")

    max_iterations: int = Field(ge=1)
    max_tool_calls_total: int = Field(ge=1)
    # 캡 그룹별 상한(NFR §3: 탐색류는 corpus/github/dataset 합산 캡). 키는 캡 그룹명.
    max_tool_calls: dict[str, int] = Field(default_factory=dict)
    # 도구명 → 캡 그룹명. 미등록 도구는 총 상한만 적용.
    tool_cap_groups: dict[str, str] = Field(default_factory=dict)
    token_cost_limit_usd: float = Field(gt=0.0)
    consumed: BudgetConsumed = Field(default_factory=BudgetConsumed)


class AgentLoopRun(BaseModel):
    """한 잡의 자율 루프 실행 상태 — 예산 집행·종료 사유의 SSOT."""

    iteration_count: int = Field(default=0, ge=0)
    tool_call_counts: dict[str, int] = Field(default_factory=dict)
    budget: LoopBudget
    termination_reason: TerminationReason | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ToolCallRecord(BaseModel):
    """결정 트레이스 단위 레코드(FR-46, BR-RA4). 실행된 도구 호출과 1:1, seq 단조.

    요약 필드는 sanitized — 원고 원문·근거 전문·자격증명 미포함(SEC-9/15).
    길이 상한은 '요약'임을 모델 수준에서 강제하는 안전망이다."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    seq: int = Field(ge=1)
    tool_name: str = Field(min_length=1, max_length=64)
    args_summary: str = Field(max_length=2000)
    decision_note: str | None = Field(default=None, max_length=2000)
    result_summary: str = Field(max_length=2000)
    outcome: ToolOutcome
    cost_estimate_usd: float | None = Field(default=None, ge=0.0)
    started_at: datetime
    finished_at: datetime


class EvidenceSnapshot(BaseModel):
    """EvidenceFormationPort 결과의 내부 보존본(승계). PROVISIONAL 필드는 있으면
    소비하되 필수로 의존하지 않는다(BR-NV3)."""

    state: str = Field(pattern=r"^(ok|abstain)$")
    claims: list[EvidenceItem] = Field(default_factory=list)
    coverage: EvidenceCoverage | None = None
    abstain_reason: str | None = None
    contract_version: str | None = None


class SimilarWorkItem(BaseModel):
    """유사 연구 표의 한 행(승계). 근거가 있을 때만 셀을 채운다(BR-NV9)."""

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    artifact_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    problem_definition: str | None = None
    method: str | None = None
    dataset: str | None = None
    result: str | None = None
    limitation: str | None = None
    overlap_with_user_idea: str | None = None
    source_refs: list[SourceRef] = Field(default_factory=list)
    evidence_status: EvidenceStatus = EvidenceStatus.ABSTAINED
    confidence: str | None = None


class GapItem(BaseModel):
    """여백 분석 항목(FR-32). 모든 판정에 source_refs 필수(BR-RA10),
    open_gap은 '부재 증명'이 아니라 탐색 범위 내 미발견 — searched_scope_note 필수."""

    gap_id: str = Field(default_factory=lambda: str(uuid4()))
    area: str = Field(min_length=1, max_length=500)
    status: GapStatus
    rationale: str = Field(min_length=1)
    source_refs: list[SourceRef] = Field(default_factory=list)
    searched_scope_note: str | None = None
    related_similar_work_ids: list[str] = Field(default_factory=list)


class GapAnalysis(BaseModel):
    items: list[GapItem] = Field(default_factory=list)


class ExternalFinding(BaseModel):
    """GitHub·데이터셋 검색 결과의 정규화 artifact(승계). 뉴스는 제외(BR-NV7)."""

    source_type: str = Field(pattern=r"^(github|dataset)$")
    canonical_id: str = Field(min_length=1, max_length=512)
    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=1000)
    license: str | None = None
    task: str | None = None
    metrics: list[str] = Field(default_factory=list)
    baseline_or_code_hint: str | None = None
    normalized_at: datetime = Field(default_factory=utc_now)


class NoveltyCandidate(BaseModel):
    """차별화 방향 제안 — 온디맨드 전용(FR-32 개정). bounded 생성 규칙(BR-NV11)과
    저장 게이트(BR-RA2)를 동일 적용한다."""

    candidate_id: str = Field(default_factory=lambda: str(uuid4()))
    angle: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    supporting_refs: list[SourceRef] = Field(default_factory=list)
    conflicting_refs: list[SourceRef] = Field(default_factory=list)
    feasibility_notes: str | None = None
    excluded_claims: str = Field(min_length=1)


class ExperimentPlan(BaseModel):
    """실험 계획 — 온디맨드 전용(FR-33 개정). 필수 9필드(BR-NV12)."""

    hypothesis: str = Field(min_length=1)
    novelty_angle: str = Field(min_length=1)
    baselines: list[str] = Field(min_length=1)
    datasets: list[str] = Field(min_length=1)
    metrics: list[str] = Field(min_length=1)
    procedure: list[str] = Field(min_length=1)
    risks: list[str] = Field(min_length=1)
    resources: list[str] = Field(min_length=1)
    source_refs: list[SourceRef] = Field(min_length=1)


class ArtifactRecord(BaseModel):
    """산출물 저장 단위 — 종류별 최신 검증본(구 stage_snapshots 대체).
    저장은 항상 결정론 게이트(domain.gate)를 통과한 뒤에만 이뤄진다(BR-RA2)."""

    artifact_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    owner_id: str
    kind: ArtifactKind
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class NoveltyChatMessage(BaseModel):
    """잡 내 멀티턴 대화(FR-44)의 영속 모델. 루프의 스티어링 소비는 ⑤ 3단계."""

    message_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    owner_id: str
    role: ChatRole
    kind: ChatKind
    content: str = Field(min_length=1, max_length=12000)
    resulting_artifact_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class NoveltyJob(BaseModel):
    """루트 aggregate. artifacts는 종류별 최신 검증본 참조 목록."""

    job_id: str = Field(default_factory=lambda: str(uuid4()))
    owner_id: str
    request: NoveltyJobRequest
    state: JobState = JobState.RECEIVED
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    loop_run: AgentLoopRun | None = None
    degraded_sources: dict[str, str] = Field(default_factory=dict)
    cancel_requested: bool = False
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class NotionExport(BaseModel):
    """승계 — preview/approval 없이 exported 도달 불가(PBT-NV7), 루프 도구 아님(BR-RA12)."""

    export_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    owner_id: str
    status: ExportStatus = ExportStatus.NOT_REQUESTED
    preview_object_key: str | None = None
    notion_page_id: str | None = None
    approved_at: datetime | None = None
    exported_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class NotionConnection(BaseModel):
    """승계 — 토큰은 암호화 저장(SEC-8), 응답 미포함(SEC-12)."""

    owner_id: str
    token_encrypted: str
    parent_page_id: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
