from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class NoveltyError(Exception):
    pass


class InvalidTransitionError(NoveltyError):
    pass


class ArtifactValidationError(NoveltyError):
    pass


class ExportApprovalError(NoveltyError):
    pass


class InputType(StrEnum):
    NATURAL_LANGUAGE = "natural_language"
    MANUSCRIPT = "manuscript"


class JobState(StrEnum):
    QUEUED = "queued"
    RETRIEVING_CORPUS = "retrieving_corpus"
    SEARCHING_EXTERNAL = "searching_external"
    SUMMARIZING_PRIOR_WORK = "summarizing_prior_work"
    CHECKING_SIMILARITY = "checking_similarity"
    FORMING_IDEAS = "forming_ideas"
    PLANNING_EXPERIMENT = "planning_experiment"
    EXPORTING_NOTION = "exporting_notion"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ArtifactKind(StrEnum):
    EVIDENCE = "evidence"
    SIMILAR_WORKS = "similar_works"
    EXTERNAL_FINDINGS = "external_findings"
    RISK_SIGNALS = "risk_signals"
    NOVELTY_CANDIDATES = "novelty_candidates"
    EXPERIMENT_PLAN = "experiment_plan"
    EXPORT_STATUS = "export_status"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class EvidenceStatus(StrEnum):
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
        "text/markdown",
        "text/plain",
    }
)


class ManuscriptRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1, max_length=240)
    contentType: str = Field(min_length=1, max_length=120)
    objectKey: str | None = Field(default=None, max_length=512)

    @field_validator("contentType")
    @classmethod
    def _normalize_content_type(cls, value: str) -> str:
        return value.strip().lower()


class NoveltyJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputType: InputType
    topic: str = Field(min_length=3, max_length=2000)
    manuscript: ManuscriptRef | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    exportToNotion: bool = False

    @field_validator("topic")
    @classmethod
    def _strip_topic(cls, value: str) -> str:
        stripped = value.strip()
        if len(stripped) < 3:
            raise ValueError("topic must be at least 3 characters")
        return stripped

    @model_validator(mode="after")
    def _manuscript_required_for_manuscript_input(self):
        if self.inputType is InputType.MANUSCRIPT and self.manuscript is None:
            raise ValueError("manuscript is required for manuscript input")
        return self


class NoveltyJob(BaseModel):
    jobId: str = Field(default_factory=lambda: str(uuid4()))
    ownerId: str
    inputType: InputType
    topic: str
    manuscript: ManuscriptRef | None = None
    state: JobState = JobState.QUEUED
    progressPercent: int = Field(default=0, ge=0, le=100)
    exportStatus: ExportStatus = ExportStatus.NOT_REQUESTED
    errorMessage: str | None = None
    cancelled: bool = False
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)
    completedAt: datetime | None = None


class NoveltyChatMessage(BaseModel):
    messageId: str = Field(default_factory=lambda: str(uuid4()))
    jobId: str
    ownerId: str
    role: ChatRole
    content: str = Field(min_length=1, max_length=12000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utc_now)


class ProgressEvent(BaseModel):
    eventId: str = Field(default_factory=lambda: str(uuid4()))
    jobId: str
    ownerId: str
    state: JobState
    message: str
    progressPercent: int = Field(ge=0, le=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime = Field(default_factory=utc_now)


class ArtifactRef(BaseModel):
    artifactId: str = Field(default_factory=lambda: str(uuid4()))
    jobId: str
    ownerId: str
    kind: ArtifactKind
    title: str = Field(min_length=1, max_length=240)
    objectKey: str
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: datetime = Field(default_factory=utc_now)


class NotionExport(BaseModel):
    exportId: str = Field(default_factory=lambda: str(uuid4()))
    jobId: str
    ownerId: str
    status: ExportStatus = ExportStatus.NOT_REQUESTED
    previewObjectKey: str | None = None
    notionPageId: str | None = None
    approvedAt: datetime | None = None
    exportedAt: datetime | None = None
    errorMessage: str | None = None
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class CreateJobResponse(BaseModel):
    jobId: str
    state: JobState


class NoveltyJobSummary(BaseModel):
    jobId: str
    inputType: InputType
    topic: str
    state: JobState
    progressPercent: int
    exportStatus: ExportStatus
    createdAt: datetime
    updatedAt: datetime
    completedAt: datetime | None = None


class NoveltyJobListResponse(BaseModel):
    jobs: list[NoveltyJobSummary] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    job: NoveltyJob
    events: list[ProgressEvent] = Field(default_factory=list)


class JobResultResponse(BaseModel):
    job: NoveltyJob
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    export: NotionExport | None = None


class CancelJobResponse(BaseModel):
    jobId: str
    state: JobState


class ExportPreviewResponse(BaseModel):
    export: NotionExport
    preview: dict[str, Any]


class ExportApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True


class ChatMessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=12000)
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=8)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content is required")
        return stripped


class ChatMessageListResponse(BaseModel):
    messages: list[NoveltyChatMessage] = Field(default_factory=list)


STATE_PROGRESS: dict[JobState, int] = {
    JobState.QUEUED: 0,
    JobState.RETRIEVING_CORPUS: 15,
    JobState.SEARCHING_EXTERNAL: 30,
    JobState.SUMMARIZING_PRIOR_WORK: 45,
    JobState.CHECKING_SIMILARITY: 55,
    JobState.FORMING_IDEAS: 70,
    JobState.PLANNING_EXPERIMENT: 85,
    JobState.EXPORTING_NOTION: 92,
    JobState.COMPLETED: 100,
    JobState.DEGRADED: 100,
    JobState.FAILED: 100,
    JobState.CANCELLED: 100,
}

TERMINAL_STATES = frozenset(
    {JobState.COMPLETED, JobState.DEGRADED, JobState.FAILED, JobState.CANCELLED}
)

ALLOWED_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.QUEUED: frozenset({JobState.RETRIEVING_CORPUS, JobState.CANCELLED, JobState.FAILED}),
    JobState.RETRIEVING_CORPUS: frozenset(
        {JobState.SEARCHING_EXTERNAL, JobState.CANCELLED, JobState.FAILED, JobState.DEGRADED}
    ),
    JobState.SEARCHING_EXTERNAL: frozenset(
        {JobState.SUMMARIZING_PRIOR_WORK, JobState.CANCELLED, JobState.FAILED, JobState.DEGRADED}
    ),
    JobState.SUMMARIZING_PRIOR_WORK: frozenset(
        {JobState.CHECKING_SIMILARITY, JobState.FORMING_IDEAS, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.CHECKING_SIMILARITY: frozenset(
        {JobState.FORMING_IDEAS, JobState.CANCELLED, JobState.FAILED, JobState.DEGRADED}
    ),
    JobState.FORMING_IDEAS: frozenset(
        {JobState.PLANNING_EXPERIMENT, JobState.CANCELLED, JobState.FAILED}
    ),
    JobState.PLANNING_EXPERIMENT: frozenset(
        {
            JobState.EXPORTING_NOTION,
            JobState.COMPLETED,
            JobState.DEGRADED,
            JobState.CANCELLED,
            JobState.FAILED,
        }
    ),
    JobState.EXPORTING_NOTION: frozenset(
        {JobState.COMPLETED, JobState.DEGRADED, JobState.CANCELLED, JobState.FAILED}
    ),
}


def validate_transition(current: JobState, target: JobState) -> None:
    if current == target:
        return
    if current in TERMINAL_STATES:
        raise InvalidTransitionError(f"job is terminal: {current}")
    if target == JobState.CANCELLED:
        return
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransitionError(f"invalid transition: {current} -> {target}")
