from __future__ import annotations

from datetime import datetime
from threading import RLock
from typing import Protocol

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import (
    BehaviorEvent,
    BehaviorEventType,
    BehaviorSubject,
    PersonalizationSettings,
    UserInterestProfile,
    utc_now,
)


class PersonalizationRepository(Protocol):
    def get_settings(self, user_id: str) -> PersonalizationSettings: ...
    def set_enabled(self, user_id: str, enabled: bool) -> PersonalizationSettings: ...
    def insert_event(self, event: BehaviorEvent) -> bool: ...
    def list_events(self, user_id: str) -> list[BehaviorEvent]: ...
    def delete_events(self, user_id: str) -> int: ...
    def get_profile(self, user_id: str) -> UserInterestProfile | None: ...
    def save_profile(self, profile: UserInterestProfile) -> UserInterestProfile: ...
    def reset_profile(self, user_id: str) -> None: ...
    def purge_events_before(self, cutoff: datetime) -> int: ...
    def list_recent_papers(
        self, user_id: str, limit: int = 50
    ) -> list[tuple[str, str, datetime]]: ...


class InMemoryPersonalizationRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._events: dict[str, BehaviorEvent] = {}
        self._profiles: dict[str, UserInterestProfile] = {}
        self._settings: dict[str, PersonalizationSettings] = {}

    def get_settings(self, user_id: str) -> PersonalizationSettings:
        with self._lock:
            return self._settings.setdefault(user_id, PersonalizationSettings(userId=user_id))

    def set_enabled(self, user_id: str, enabled: bool) -> PersonalizationSettings:
        with self._lock:
            settings = self.get_settings(user_id).model_copy(
                update={"enabled": enabled, "updatedAt": utc_now()}
            )
            self._settings[user_id] = settings
            return settings

    def insert_event(self, event: BehaviorEvent) -> bool:
        key = f"{event.userId}:{event.dedupeKey}"
        with self._lock:
            if key in self._events:
                return False
            self._events[key] = event
            return True

    def list_events(self, user_id: str) -> list[BehaviorEvent]:
        with self._lock:
            return sorted(
                (e for e in self._events.values() if e.userId == user_id),
                key=lambda e: (e.occurredAt, e.eventId),
            )

    def delete_events(self, user_id: str) -> int:
        with self._lock:
            keys = [k for k, e in self._events.items() if e.userId == user_id]
            for key in keys:
                del self._events[key]
            self.reset_profile(user_id)
            settings = self.get_settings(user_id).model_copy(
                update={"rawEventsDeletedAt": utc_now(), "updatedAt": utc_now()}
            )
            self._settings[user_id] = settings
            return len(keys)

    def get_profile(self, user_id: str) -> UserInterestProfile | None:
        with self._lock:
            return self._profiles.get(user_id)

    def save_profile(self, profile: UserInterestProfile) -> UserInterestProfile:
        with self._lock:
            self._profiles[profile.userId] = profile
            return profile

    def reset_profile(self, user_id: str) -> None:
        with self._lock:
            self._profiles.pop(user_id, None)
            settings = self.get_settings(user_id).model_copy(
                update={"profileResetAt": utc_now(), "updatedAt": utc_now()}
            )
            self._settings[user_id] = settings

    def purge_events_before(self, cutoff: datetime) -> int:
        with self._lock:
            keys = [k for k, e in self._events.items() if e.occurredAt < cutoff]
            for key in keys:
                del self._events[key]
            return len(keys)

    def list_recent_papers(
        self, user_id: str, limit: int = 50
    ) -> list[tuple[str, str, datetime]]:
        with self._lock:
            events = [
                e for e in self._events.values()
                if e.userId == user_id and e.eventType == BehaviorEventType.PAPER_OPENED
            ]
            seen: dict[str, tuple[str, str, datetime]] = {}
            for e in sorted(events, key=lambda ev: ev.occurredAt, reverse=True):
                paper_id = e.subject.paperId
                if not paper_id or paper_id in seen:
                    continue
                title = str(e.metadata.get("title") or paper_id)
                seen[paper_id] = (paper_id, title, e.occurredAt)
                if len(seen) >= limit:
                    break
            return list(seen.values())


class Base(DeclarativeBase):
    pass


class BehaviorEventTable(Base):
    __tablename__ = "user_behavior_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject: Mapped[dict] = mapped_column(JSON, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InterestProfileTable(Base):
    __tablename__ = "user_interest_profiles"

    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    category_weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    keyword_weights: Mapped[dict] = mapped_column(JSON, nullable=False)
    paper_signals: Mapped[dict] = mapped_column(JSON, nullable=False)
    summary_defaults: Mapped[dict] = mapped_column(JSON, nullable=False)
    translation_defaults: Mapped[dict] = mapped_column(JSON, nullable=False)
    glossary_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PersonalizationSettingsTable(Base):
    __tablename__ = "personalization_settings"

    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    raw_events_deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _event_from_row(row: BehaviorEventTable) -> BehaviorEvent:
    return BehaviorEvent(
        eventId=row.id,
        userId=row.owner_id,
        eventType=row.event_type,
        subject=BehaviorSubject.model_validate(row.subject),
        occurredAt=row.occurred_at,
        source=row.source,
        metadata=row.metadata_json,
        dedupeKey=row.dedupe_key,
    )


def _profile_from_row(row: InterestProfileTable) -> UserInterestProfile:
    return UserInterestProfile(
        userId=row.owner_id,
        categoryWeights=row.category_weights,
        keywordWeights=row.keyword_weights,
        paperSignals=row.paper_signals,
        summaryDefaults=row.summary_defaults,
        translationDefaults=row.translation_defaults,
        glossaryVersion=row.glossary_version,
        updatedAt=row.updated_at,
    )


def _settings_from_row(row: PersonalizationSettingsTable) -> PersonalizationSettings:
    return PersonalizationSettings(
        userId=row.owner_id,
        enabled=row.enabled,
        rawEventsDeletedAt=row.raw_events_deleted_at,
        profileResetAt=row.profile_reset_at,
        updatedAt=row.updated_at,
    )


class SqlPersonalizationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get_settings(self, user_id: str) -> PersonalizationSettings:
        row = self._s.get(PersonalizationSettingsTable, user_id)
        if row is None:
            row = PersonalizationSettingsTable(
                owner_id=user_id,
                enabled=True,
                raw_events_deleted_at=None,
                profile_reset_at=None,
                updated_at=utc_now(),
            )
            self._s.add(row)
            self._s.flush()
        return _settings_from_row(row)

    def set_enabled(self, user_id: str, enabled: bool) -> PersonalizationSettings:
        self.get_settings(user_id)
        row = self._s.get(PersonalizationSettingsTable, user_id)
        assert row is not None
        row.enabled = enabled
        row.updated_at = utc_now()
        self._s.flush()
        return _settings_from_row(row)

    def insert_event(self, event: BehaviorEvent) -> bool:
        result = self._s.execute(
            pg_insert(BehaviorEventTable)
            .values(
                id=event.eventId,
                owner_id=event.userId,
                event_type=event.eventType.value,
                subject=event.subject.model_dump(exclude_none=True),
                metadata_json=event.metadata,
                source=event.source,
                dedupe_key=event.dedupeKey,
                occurred_at=event.occurredAt,
                created_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["owner_id", "dedupe_key"])
        )
        self._s.flush()
        return bool(result.rowcount)

    def list_events(self, user_id: str) -> list[BehaviorEvent]:
        rows = (
            self._s.query(BehaviorEventTable)
            .filter(BehaviorEventTable.owner_id == user_id)
            .order_by(BehaviorEventTable.occurred_at.asc(), BehaviorEventTable.id.asc())
            .all()
        )
        return [_event_from_row(row) for row in rows]

    def delete_events(self, user_id: str) -> int:
        deleted = (
            self._s.query(BehaviorEventTable)
            .filter(BehaviorEventTable.owner_id == user_id)
            .delete()
        )
        self.reset_profile(user_id)
        row = self._s.get(PersonalizationSettingsTable, user_id)
        assert row is not None
        row.raw_events_deleted_at = utc_now()
        row.updated_at = utc_now()
        self._s.flush()
        return int(deleted)

    def get_profile(self, user_id: str) -> UserInterestProfile | None:
        row = self._s.get(InterestProfileTable, user_id)
        return _profile_from_row(row) if row else None

    def save_profile(self, profile: UserInterestProfile) -> UserInterestProfile:
        row = self._s.get(InterestProfileTable, profile.userId)
        data = {
            "category_weights": profile.categoryWeights,
            "keyword_weights": profile.keywordWeights,
            "paper_signals": profile.paperSignals,
            "summary_defaults": profile.summaryDefaults,
            "translation_defaults": profile.translationDefaults,
            "glossary_version": profile.glossaryVersion,
            "updated_at": profile.updatedAt,
        }
        if row is None:
            self._s.add(InterestProfileTable(owner_id=profile.userId, **data))
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self._s.flush()
        return profile

    def reset_profile(self, user_id: str) -> None:
        self._s.query(InterestProfileTable).filter(
            InterestProfileTable.owner_id == user_id
        ).delete()
        self.get_settings(user_id)
        row = self._s.get(PersonalizationSettingsTable, user_id)
        assert row is not None
        row.profile_reset_at = utc_now()
        row.updated_at = utc_now()
        self._s.flush()

    def purge_events_before(self, cutoff: datetime) -> int:
        deleted = (
            self._s.query(BehaviorEventTable)
            .filter(BehaviorEventTable.occurred_at < cutoff)
            .delete()
        )
        self._s.flush()
        return int(deleted)

    def list_recent_papers(
        self, user_id: str, limit: int = 50
    ) -> list[tuple[str, str, datetime]]:
        rows = (
            self._s.query(BehaviorEventTable)
            .filter(
                BehaviorEventTable.owner_id == user_id,
                BehaviorEventTable.event_type == BehaviorEventType.PAPER_OPENED.value,
            )
            .order_by(BehaviorEventTable.occurred_at.desc())
            .all()
        )
        seen: dict[str, tuple[str, str, datetime]] = {}
        for row in rows:
            paper_id = row.subject.get('paperId', '')
            if not paper_id or paper_id in seen:
                continue
            title = str(row.metadata_json.get("title") or paper_id)
            seen[paper_id] = (paper_id, title, row.occurred_at)
            if len(seen) >= limit:
                break
        return list(seen.values())
