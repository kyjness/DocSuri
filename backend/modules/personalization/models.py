from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class PersonalizationError(Exception):
    pass


class MetadataValidationError(PersonalizationError):
    pass


class BehaviorEventType(StrEnum):
    SEARCH_EXECUTED = "search_executed"
    PAPER_OPENED = "paper_opened"
    LIBRARY_ADDED = "library_added"
    LIBRARY_REMOVED = "library_removed"
    SUMMARY_TRANSLATION_REQUESTED = "summary_translation_requested"
    SOURCE_ANCHOR_CLICKED = "source_anchor_clicked"
    GLOSSARY_UPDATED = "glossary_updated"


class BehaviorSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["paper", "search", "summary", "translation", "source_anchor", "glossary"]
    paperId: str | None = Field(default=None, max_length=128)
    queryHash: str | None = Field(default=None, max_length=128)
    category: str | None = Field(default=None, max_length=64)
    anchorId: str | None = Field(default=None, max_length=128)


class BehaviorEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eventType: BehaviorEventType
    subject: BehaviorSubject
    occurredAt: datetime = Field(default_factory=utc_now)
    source: Literal["backend", "frontend_anchor"] = "backend"
    metadata: dict[str, Any] = Field(default_factory=dict)
    dedupeKey: str = Field(min_length=1, max_length=160)


class BehaviorEvent(BehaviorEventCreate):
    eventId: str = Field(default_factory=lambda: str(uuid4()))
    userId: str


class EventRecordResult(BaseModel):
    recorded: bool
    duplicate: bool = False
    reason: Literal["recorded", "duplicate", "disabled", "degraded"]


class UserInterestProfile(BaseModel):
    userId: str
    categoryWeights: dict[str, float] = Field(default_factory=dict)
    keywordWeights: dict[str, float] = Field(default_factory=dict)
    paperSignals: dict[str, float] = Field(default_factory=dict)
    summaryDefaults: dict[str, str] = Field(default_factory=dict)
    translationDefaults: dict[str, str] = Field(default_factory=dict)
    glossaryVersion: str | None = None
    updatedAt: datetime = Field(default_factory=utc_now)


class PersonalizationSettings(BaseModel):
    userId: str
    enabled: bool = True
    rawEventsDeletedAt: datetime | None = None
    profileResetAt: datetime | None = None
    updatedAt: datetime = Field(default_factory=utc_now)


class PersonalizationDecision(BaseModel):
    enabled: bool
    searchBoosts: dict[str, float] = Field(default_factory=dict)
    summaryDefaults: dict[str, str] = Field(default_factory=dict)
    translationDefaults: dict[str, str] = Field(default_factory=dict)
    reason: Literal["profile_available", "disabled", "no_profile", "degraded"]


class SettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class RecentlyViewedItem(BaseModel):
    arxivId: str
    title: str
    viewedAt: datetime


class RecentlyViewedList(BaseModel):
    items: list[RecentlyViewedItem]


_ALLOWED_METADATA: dict[BehaviorEventType, set[str]] = {
    BehaviorEventType.SEARCH_EXECUTED: {"resultCount", "topCategories", "language", "keywords"},
    BehaviorEventType.PAPER_OPENED: {"entrySurface", "paperCategory", "title"},
    BehaviorEventType.LIBRARY_ADDED: {"paperCategory", "savedSource"},
    BehaviorEventType.LIBRARY_REMOVED: {"paperCategory"},
    BehaviorEventType.SUMMARY_TRANSLATION_REQUESTED: {
        "mode",
        "selectedPersona",
        "translationScope",
    },
    BehaviorEventType.SOURCE_ANCHOR_CLICKED: {"anchorId", "sectionKind"},
    BehaviorEventType.GLOSSARY_UPDATED: {"glossaryVersion", "termCountDelta"},
}
_FORBIDDEN_KEY_PARTS = (
    "password",
    "secret",
    "token",
    "credential",
    "raw",
    "text",
    "content",
    "quote",
    "html",
)


def validate_metadata(event_type: BehaviorEventType, metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = _ALLOWED_METADATA[event_type]
    extra = set(metadata) - allowed
    if extra:
        raise MetadataValidationError(f"unsupported metadata keys: {', '.join(sorted(extra))}")
    for key, value in metadata.items():
        lowered = key.lower()
        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            raise MetadataValidationError(f"forbidden metadata key: {key}")
        if isinstance(value, str) and len(value) > 240:
            raise MetadataValidationError(f"metadata value too long: {key}")
    return dict(metadata)


class ValidatedBehaviorEventCreate(BehaviorEventCreate):
    @field_validator("metadata")
    @classmethod
    def _validate_metadata(cls, metadata: dict[str, Any], info):
        event_type = info.data.get("eventType")
        if event_type is None:
            return metadata
        return validate_metadata(event_type, metadata)
