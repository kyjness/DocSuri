from __future__ import annotations

from threading import RLock
from typing import Any, Protocol

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import (
    ArtifactKind,
    ArtifactRef,
    ChatRole,
    ExportStatus,
    InputType,
    JobState,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    ProgressEvent,
    utc_now,
)


class NoveltyRepository(Protocol):
    def create_job(self, job: NoveltyJob) -> NoveltyJob: ...
    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob: ...
    def list_jobs(self, owner_id: str, limit: int = 50) -> list[NoveltyJob]: ...
    def update_job(self, owner_id: str, job_id: str, **changes: Any) -> NoveltyJob: ...
    def delete_job(self, owner_id: str, job_id: str) -> None: ...
    def add_event(self, event: ProgressEvent) -> ProgressEvent: ...
    def list_events(
        self, owner_id: str, job_id: str, after_event_id: str | None = None
    ) -> list[ProgressEvent]: ...
    def save_artifact(self, artifact: ArtifactRef) -> ArtifactRef: ...
    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRef]: ...
    def add_message(self, message: NoveltyChatMessage) -> NoveltyChatMessage: ...
    def list_messages(self, owner_id: str, job_id: str) -> list[NoveltyChatMessage]: ...
    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None: ...
    def save_export(self, export: NotionExport) -> NotionExport: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class ArtifactStore(Protocol):
    def put_json(self, object_key: str, payload: dict[str, Any]) -> str: ...
    def get_json(self, object_key: str) -> dict[str, Any] | None: ...


class InMemoryArtifactStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._objects: dict[str, dict[str, Any]] = {}

    def put_json(self, object_key: str, payload: dict[str, Any]) -> str:
        with self._lock:
            self._objects[object_key] = dict(payload)
            return object_key

    def get_json(self, object_key: str) -> dict[str, Any] | None:
        with self._lock:
            payload = self._objects.get(object_key)
            return dict(payload) if payload is not None else None


class InMemoryNoveltyRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[str, NoveltyJob] = {}
        self._events: dict[str, list[ProgressEvent]] = {}
        self._artifacts: dict[str, list[ArtifactRef]] = {}
        self._messages: dict[str, list[NoveltyChatMessage]] = {}
        self._exports: dict[str, NotionExport] = {}

    def create_job(self, job: NoveltyJob) -> NoveltyJob:
        with self._lock:
            self._jobs[job.jobId] = job
            self._events.setdefault(job.jobId, [])
            self._artifacts.setdefault(job.jobId, [])
            self._messages.setdefault(job.jobId, [])
            return job

    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.ownerId != owner_id:
                raise KeyError(job_id)
            return job

    def list_jobs(self, owner_id: str, limit: int = 50) -> list[NoveltyJob]:
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.ownerId == owner_id]
            jobs.sort(key=lambda job: (job.updatedAt, job.createdAt), reverse=True)
            return jobs[:limit]

    def update_job(self, owner_id: str, job_id: str, **changes: Any) -> NoveltyJob:
        with self._lock:
            job = self.get_job(owner_id, job_id)
            updated = job.model_copy(update={**changes, "updatedAt": utc_now()})
            self._jobs[job_id] = updated
            return updated

    def delete_job(self, owner_id: str, job_id: str) -> None:
        with self._lock:
            self.get_job(owner_id, job_id)
            self._jobs.pop(job_id, None)
            self._events.pop(job_id, None)
            self._artifacts.pop(job_id, None)
            self._messages.pop(job_id, None)
            self._exports.pop(job_id, None)

    def add_event(self, event: ProgressEvent) -> ProgressEvent:
        with self._lock:
            self.get_job(event.ownerId, event.jobId)
            self._events.setdefault(event.jobId, []).append(event)
            return event

    def list_events(
        self, owner_id: str, job_id: str, after_event_id: str | None = None
    ) -> list[ProgressEvent]:
        with self._lock:
            self.get_job(owner_id, job_id)
            events = list(self._events.get(job_id, []))
            return _after(events, after_event_id)

    def save_artifact(self, artifact: ArtifactRef) -> ArtifactRef:
        with self._lock:
            self.get_job(artifact.ownerId, artifact.jobId)
            artifacts = self._artifacts.setdefault(artifact.jobId, [])
            artifacts[:] = [item for item in artifacts if item.artifactId != artifact.artifactId]
            artifacts.append(artifact)
            return artifact

    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRef]:
        with self._lock:
            self.get_job(owner_id, job_id)
            return list(self._artifacts.get(job_id, []))

    def add_message(self, message: NoveltyChatMessage) -> NoveltyChatMessage:
        with self._lock:
            self.get_job(message.ownerId, message.jobId)
            self._messages.setdefault(message.jobId, []).append(message)
            return message

    def list_messages(self, owner_id: str, job_id: str) -> list[NoveltyChatMessage]:
        with self._lock:
            self.get_job(owner_id, job_id)
            messages = list(self._messages.get(job_id, []))
            messages.sort(key=lambda item: (item.createdAt, item.messageId))
            return messages

    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None:
        with self._lock:
            self.get_job(owner_id, job_id)
            export = self._exports.get(job_id)
            return export if export and export.ownerId == owner_id else None

    def save_export(self, export: NotionExport) -> NotionExport:
        with self._lock:
            self.get_job(export.ownerId, export.jobId)
            self._exports[export.jobId] = export
            return export

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


def _after(events: list[ProgressEvent], after_event_id: str | None) -> list[ProgressEvent]:
    if after_event_id is None:
        return events
    for index, event in enumerate(events):
        if event.eventId == after_event_id:
            return events[index + 1 :]
    return events


class Base(DeclarativeBase):
    pass


class NoveltyJobTable(Base):
    __tablename__ = "novelty_jobs"

    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    input_type: Mapped[str] = mapped_column(String(32), nullable=False)
    topic: Mapped[str] = mapped_column(String(2000), nullable=False)
    manuscript: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    export_status: Mapped[str] = mapped_column(String(48), nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProgressEventTable(Base):
    __tablename__ = "novelty_progress_events"

    event_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(48), nullable=False)
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    progress_percent: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class NoveltyMessageTable(Base):
    __tablename__ = "novelty_messages"

    message_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(12000), nullable=False)
    attachments: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactTable(Base):
    __tablename__ = "novelty_artifacts"

    artifact_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class NotionExportTable(Base):
    __tablename__ = "novelty_notion_exports"

    export_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(48), nullable=False)
    preview_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notion_page_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    approved_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exported_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


def _job_from_row(row: NoveltyJobTable) -> NoveltyJob:
    return NoveltyJob(
        jobId=row.job_id,
        ownerId=row.owner_id,
        inputType=InputType(row.input_type),
        topic=row.topic,
        manuscript=row.manuscript,
        state=JobState(row.state),
        progressPercent=row.progress_percent,
        exportStatus=ExportStatus(row.export_status),
        errorMessage=row.error_message,
        cancelled=row.cancelled,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
        completedAt=row.completed_at,
    )


def _event_from_row(row: ProgressEventTable) -> ProgressEvent:
    return ProgressEvent(
        eventId=row.event_id,
        jobId=row.job_id,
        ownerId=row.owner_id,
        state=JobState(row.state),
        message=row.message,
        progressPercent=row.progress_percent,
        payload=row.payload,
        createdAt=row.created_at,
    )


def _message_from_row(row: NoveltyMessageTable) -> NoveltyChatMessage:
    return NoveltyChatMessage(
        messageId=row.message_id,
        jobId=row.job_id,
        ownerId=row.owner_id,
        role=ChatRole(row.role),
        content=row.content,
        attachments=row.attachments,
        createdAt=row.created_at,
    )


def _artifact_from_row(row: ArtifactTable) -> ArtifactRef:
    return ArtifactRef(
        artifactId=row.artifact_id,
        jobId=row.job_id,
        ownerId=row.owner_id,
        kind=ArtifactKind(row.kind),
        title=row.title,
        objectKey=row.object_key,
        payload=row.payload,
        createdAt=row.created_at,
    )


def _export_from_row(row: NotionExportTable) -> NotionExport:
    return NotionExport(
        exportId=row.export_id,
        jobId=row.job_id,
        ownerId=row.owner_id,
        status=ExportStatus(row.status),
        previewObjectKey=row.preview_object_key,
        notionPageId=row.notion_page_id,
        errorMessage=row.error_message,
        approvedAt=row.approved_at,
        exportedAt=row.exported_at,
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


class SqlNoveltyRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create_job(self, job: NoveltyJob) -> NoveltyJob:
        self._s.add(
            NoveltyJobTable(
                job_id=job.jobId,
                owner_id=job.ownerId,
                input_type=job.inputType.value,
                topic=job.topic,
                manuscript=job.manuscript.model_dump(mode="json") if job.manuscript else None,
                state=job.state.value,
                progress_percent=job.progressPercent,
                export_status=job.exportStatus.value,
                error_message=job.errorMessage,
                cancelled=job.cancelled,
                created_at=job.createdAt,
                updated_at=job.updatedAt,
                completed_at=job.completedAt,
            )
        )
        self._s.flush()
        return job

    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob:
        row = self._s.get(NoveltyJobTable, job_id)
        if row is None or row.owner_id != owner_id:
            raise KeyError(job_id)
        return _job_from_row(row)

    def list_jobs(self, owner_id: str, limit: int = 50) -> list[NoveltyJob]:
        rows = (
            self._s.query(NoveltyJobTable)
            .filter(NoveltyJobTable.owner_id == owner_id)
            .order_by(NoveltyJobTable.updated_at.desc(), NoveltyJobTable.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_job_from_row(row) for row in rows]

    def update_job(self, owner_id: str, job_id: str, **changes: Any) -> NoveltyJob:
        row = self._s.get(NoveltyJobTable, job_id)
        if row is None or row.owner_id != owner_id:
            raise KeyError(job_id)
        mapping = {
            "state": "state",
            "progressPercent": "progress_percent",
            "exportStatus": "export_status",
            "errorMessage": "error_message",
            "cancelled": "cancelled",
            "completedAt": "completed_at",
        }
        for key, value in changes.items():
            column = mapping.get(key)
            if column is None:
                continue
            if hasattr(value, "value"):
                value = value.value
            setattr(row, column, value)
        row.updated_at = utc_now()
        self._s.flush()
        return _job_from_row(row)

    def delete_job(self, owner_id: str, job_id: str) -> None:
        row = self._s.get(NoveltyJobTable, job_id)
        if row is None or row.owner_id != owner_id:
            raise KeyError(job_id)
        self._s.delete(row)
        self._s.flush()

    def add_event(self, event: ProgressEvent) -> ProgressEvent:
        self.get_job(event.ownerId, event.jobId)
        self._s.add(
            ProgressEventTable(
                event_id=event.eventId,
                job_id=event.jobId,
                owner_id=event.ownerId,
                state=event.state.value,
                message=event.message,
                progress_percent=event.progressPercent,
                payload=event.payload,
                created_at=event.createdAt,
            )
        )
        self._s.flush()
        return event

    def list_events(
        self, owner_id: str, job_id: str, after_event_id: str | None = None
    ) -> list[ProgressEvent]:
        self.get_job(owner_id, job_id)
        rows = (
            self._s.query(ProgressEventTable)
            .filter(
                ProgressEventTable.owner_id == owner_id,
                ProgressEventTable.job_id == job_id,
            )
            .order_by(ProgressEventTable.created_at.asc(), ProgressEventTable.event_id.asc())
            .all()
        )
        return _after([_event_from_row(row) for row in rows], after_event_id)

    def save_artifact(self, artifact: ArtifactRef) -> ArtifactRef:
        self.get_job(artifact.ownerId, artifact.jobId)
        row = self._s.get(ArtifactTable, artifact.artifactId)
        data = {
            "job_id": artifact.jobId,
            "owner_id": artifact.ownerId,
            "kind": artifact.kind.value,
            "title": artifact.title,
            "object_key": artifact.objectKey,
            "payload": artifact.payload,
            "created_at": artifact.createdAt,
        }
        if row is None:
            self._s.add(ArtifactTable(artifact_id=artifact.artifactId, **data))
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self._s.flush()
        return artifact

    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRef]:
        self.get_job(owner_id, job_id)
        rows = (
            self._s.query(ArtifactTable)
            .filter(ArtifactTable.owner_id == owner_id, ArtifactTable.job_id == job_id)
            .order_by(ArtifactTable.created_at.asc(), ArtifactTable.artifact_id.asc())
            .all()
        )
        return [_artifact_from_row(row) for row in rows]

    def add_message(self, message: NoveltyChatMessage) -> NoveltyChatMessage:
        self.get_job(message.ownerId, message.jobId)
        self._s.add(
            NoveltyMessageTable(
                message_id=message.messageId,
                job_id=message.jobId,
                owner_id=message.ownerId,
                role=message.role.value,
                content=message.content,
                attachments=message.attachments,
                created_at=message.createdAt,
            )
        )
        self._s.flush()
        return message

    def list_messages(self, owner_id: str, job_id: str) -> list[NoveltyChatMessage]:
        self.get_job(owner_id, job_id)
        rows = (
            self._s.query(NoveltyMessageTable)
            .filter(NoveltyMessageTable.owner_id == owner_id, NoveltyMessageTable.job_id == job_id)
            .order_by(NoveltyMessageTable.created_at.asc(), NoveltyMessageTable.message_id.asc())
            .all()
        )
        return [_message_from_row(row) for row in rows]

    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None:
        self.get_job(owner_id, job_id)
        row = (
            self._s.query(NotionExportTable)
            .filter(NotionExportTable.owner_id == owner_id, NotionExportTable.job_id == job_id)
            .one_or_none()
        )
        return _export_from_row(row) if row else None

    def save_export(self, export: NotionExport) -> NotionExport:
        self.get_job(export.ownerId, export.jobId)
        row = self._s.get(NotionExportTable, export.exportId)
        data = {
            "job_id": export.jobId,
            "owner_id": export.ownerId,
            "status": export.status.value,
            "preview_object_key": export.previewObjectKey,
            "notion_page_id": export.notionPageId,
            "error_message": export.errorMessage,
            "approved_at": export.approvedAt,
            "exported_at": export.exportedAt,
            "created_at": export.createdAt,
            "updated_at": utc_now(),
        }
        if row is None:
            self._s.add(NotionExportTable(export_id=export.exportId, **data))
        else:
            for key, value in data.items():
                setattr(row, key, value)
        self._s.flush()
        return export.model_copy(update={"updatedAt": data["updated_at"]})

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()

    def close(self) -> None:
        self._s.close()
