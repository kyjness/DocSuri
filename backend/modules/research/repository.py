from __future__ import annotations

from threading import RLock
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import (
    ChatRole,
    ResearchChatMessage,
    ResearchJob,
    ResearchJobState,
    utc_now,
)


class ResearchRepository(Protocol):
    def create_job(self, job: ResearchJob) -> ResearchJob: ...
    def get_job(self, owner_id: str, job_id: str) -> ResearchJob: ...
    def list_jobs(self, owner_id: str, limit: int = 50) -> list[ResearchJob]: ...
    def delete_job(self, owner_id: str, job_id: str) -> None: ...
    def add_message(self, message: ResearchChatMessage) -> ResearchChatMessage: ...
    def list_messages(self, owner_id: str, job_id: str) -> list[ResearchChatMessage]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


class InMemoryResearchRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._jobs: dict[str, ResearchJob] = {}
        self._messages: dict[str, list[ResearchChatMessage]] = {}

    def create_job(self, job: ResearchJob) -> ResearchJob:
        with self._lock:
            self._jobs[job.jobId] = job
            self._messages.setdefault(job.jobId, [])
            return job

    def get_job(self, owner_id: str, job_id: str) -> ResearchJob:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.ownerId != owner_id:
                raise KeyError(job_id)
            return job

    def list_jobs(self, owner_id: str, limit: int = 50) -> list[ResearchJob]:
        with self._lock:
            jobs = [job for job in self._jobs.values() if job.ownerId == owner_id]
            jobs.sort(key=lambda job: (job.updatedAt, job.createdAt), reverse=True)
            return jobs[:limit]

    def delete_job(self, owner_id: str, job_id: str) -> None:
        with self._lock:
            self.get_job(owner_id, job_id)
            self._jobs.pop(job_id, None)
            self._messages.pop(job_id, None)

    def add_message(self, message: ResearchChatMessage) -> ResearchChatMessage:
        with self._lock:
            job = self.get_job(message.ownerId, message.jobId)
            self._messages.setdefault(message.jobId, []).append(message)
            self._jobs[message.jobId] = job.model_copy(update={"updatedAt": utc_now()})
            return message

    def list_messages(self, owner_id: str, job_id: str) -> list[ResearchChatMessage]:
        with self._lock:
            self.get_job(owner_id, job_id)
            messages = list(self._messages.get(job_id, []))
            messages.sort(key=lambda item: (item.createdAt, item.messageId))
            return messages

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


class Base(DeclarativeBase):
    pass


class ResearchJobTable(Base):
    __tablename__ = "research_jobs"

    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class ResearchMessageTable(Base):
    __tablename__ = "research_messages"

    message_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(12000), nullable=False)
    attachments: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


def _job_from_row(row: ResearchJobTable) -> ResearchJob:
    return ResearchJob(
        jobId=row.job_id,
        ownerId=row.owner_id,
        title=row.title,
        state=ResearchJobState(row.state),
        createdAt=row.created_at,
        updatedAt=row.updated_at,
    )


def _message_from_row(row: ResearchMessageTable) -> ResearchChatMessage:
    return ResearchChatMessage(
        messageId=row.message_id,
        jobId=row.job_id,
        ownerId=row.owner_id,
        role=ChatRole(row.role),
        content=row.content,
        attachments=row.attachments,
        createdAt=row.created_at,
    )


class SqlResearchRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create_job(self, job: ResearchJob) -> ResearchJob:
        self._s.add(
            ResearchJobTable(
                job_id=job.jobId,
                owner_id=job.ownerId,
                title=job.title,
                state=job.state.value,
                created_at=job.createdAt,
                updated_at=job.updatedAt,
            )
        )
        self._s.flush()
        return job

    def get_job(self, owner_id: str, job_id: str) -> ResearchJob:
        row = self._s.get(ResearchJobTable, job_id)
        if row is None or row.owner_id != owner_id:
            raise KeyError(job_id)
        return _job_from_row(row)

    def list_jobs(self, owner_id: str, limit: int = 50) -> list[ResearchJob]:
        rows = (
            self._s.query(ResearchJobTable)
            .filter(ResearchJobTable.owner_id == owner_id)
            .order_by(ResearchJobTable.updated_at.desc(), ResearchJobTable.created_at.desc())
            .limit(limit)
            .all()
        )
        return [_job_from_row(row) for row in rows]

    def delete_job(self, owner_id: str, job_id: str) -> None:
        row = self._s.get(ResearchJobTable, job_id)
        if row is None or row.owner_id != owner_id:
            raise KeyError(job_id)
        (
            self._s.query(ResearchMessageTable)
            .filter(
                ResearchMessageTable.owner_id == owner_id,
                ResearchMessageTable.job_id == job_id,
            )
            .delete(synchronize_session=False)
        )
        self._s.delete(row)
        self._s.flush()

    def add_message(self, message: ResearchChatMessage) -> ResearchChatMessage:
        row = self._s.get(ResearchJobTable, message.jobId)
        if row is None or row.owner_id != message.ownerId:
            raise KeyError(message.jobId)
        self._s.add(
            ResearchMessageTable(
                message_id=message.messageId,
                job_id=message.jobId,
                owner_id=message.ownerId,
                role=message.role.value,
                content=message.content,
                attachments=message.attachments,
                created_at=message.createdAt,
            )
        )
        row.updated_at = utc_now()
        self._s.flush()
        return message

    def list_messages(self, owner_id: str, job_id: str) -> list[ResearchChatMessage]:
        self.get_job(owner_id, job_id)
        rows = (
            self._s.query(ResearchMessageTable)
            .filter(
                ResearchMessageTable.owner_id == owner_id,
                ResearchMessageTable.job_id == job_id,
            )
            .order_by(ResearchMessageTable.created_at.asc(), ResearchMessageTable.message_id.asc())
            .all()
        )
        return [_message_from_row(row) for row in rows]

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()

    def close(self) -> None:
        self._s.close()
