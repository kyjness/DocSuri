from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    attachments: list[dict[str, Any]] = Field(default_factory=list, max_length=8)

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
