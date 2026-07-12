from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.middleware.agent_attachments import ATTACHMENT_MAX_COUNT, validated_attachment_dicts


def utc_now() -> datetime:
    return datetime.now(UTC)


class ResearchJobState(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ResearchChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=12000)
    attachments: list[dict[str, Any]] = Field(
        default_factory=list, max_length=ATTACHMENT_MAX_COUNT
    )

    # US-AG5(#297)/US-EV4(#268) — 형식·크기를 처리 전 검증(422). 저장 형상(dict)은 유지.
    @field_validator("attachments")
    @classmethod
    def _validate_attachments(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return validated_attachment_dicts(value)

    @field_validator("content")
    @classmethod
    def _strip_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content is required")
        return stripped


ResearchJobCreateRequest = ResearchChatRequest
ResearchMessageCreateRequest = ResearchChatRequest


class ResearchJob(BaseModel):
    jobId: str = Field(default_factory=lambda: str(uuid4()))
    ownerId: str
    title: str = Field(min_length=1, max_length=120)
    state: ResearchJobState = ResearchJobState.ACTIVE
    createdAt: datetime = Field(default_factory=utc_now)
    updatedAt: datetime = Field(default_factory=utc_now)


class ResearchChatMessage(BaseModel):
    messageId: str = Field(default_factory=lambda: str(uuid4()))
    jobId: str
    ownerId: str
    role: ChatRole
    content: str = Field(min_length=1, max_length=12000)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    # 꼬리질문 좁히기용 — 이 메시지(assistant, state=ok)가 실제로 근거로 쓴 논문 id 목록.
    # user 메시지·성공하지 못한 assistant 메시지는 항상 빈 배열이다.
    resolvedPaperIds: list[str] = Field(default_factory=list)
    createdAt: datetime = Field(default_factory=utc_now)


class ResearchJobCreateResponse(BaseModel):
    jobId: str
    state: ResearchJobState


class ResearchJobSummary(BaseModel):
    jobId: str
    title: str
    state: ResearchJobState
    createdAt: datetime
    updatedAt: datetime


class ResearchJobListResponse(BaseModel):
    jobs: list[ResearchJobSummary] = Field(default_factory=list)


class ResearchJobDetailResponse(BaseModel):
    job: ResearchJob
    messages: list[ResearchChatMessage] = Field(default_factory=list)


class ResearchMessageListResponse(BaseModel):
    messages: list[ResearchChatMessage] = Field(default_factory=list)


def title_from_content(content: str) -> str:
    title = " ".join(content.strip().split())
    return title[:120] or "Untitled research session"
