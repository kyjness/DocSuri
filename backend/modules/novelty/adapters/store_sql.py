"""SqlNoveltyStore — postgres 잡·산출물·트레이스·대화 저장(TD-NV2-5). RDS 동일 스키마.

메서드 단위 짧은 트랜잭션 — 트레이스 내구성(FR-46)을 위해 레코드는 즉시 커밋된다.
(job_id, seq) 복합 PK가 seq 유일성을 DB 수준에서 강제하고, 위반은
DuplicateTraceSeqError로 변환된다. 자식 삭제는 dialect 중립을 위해 명시 실행
(SQLite 테스트 호환 — postgres에서는 FK cascade도 함께 동작).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    String,
    Uuid,
    delete,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from ..domain.models import (
    TERMINAL_STATES,
    ArtifactKind,
    ArtifactRecord,
    InvalidTransitionError,
    NotionConnection,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    ToolCallRecord,
)
from ..ports.store import DuplicateTraceSeqError

__all__ = ["NoveltyV2Base", "SqlNoveltyStore"]

_TERMINAL_STATE_VALUES = frozenset(state.value for state in TERMINAL_STATES)


class NoveltyV2Base(DeclarativeBase):
    pass


class NoveltyJobV2Table(NoveltyV2Base):
    __tablename__ = "novelty_jobs"

    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    request: Mapped[dict] = mapped_column(JSON, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    loop_run: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    degraded_sources: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ToolCallRecordTable(NoveltyV2Base):
    __tablename__ = "novelty_tool_call_records"

    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args_summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    decision_note: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    result_summary: Mapped[str] = mapped_column(String(2000), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    started_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class ArtifactV2Table(NoveltyV2Base):
    __tablename__ = "novelty_artifacts"

    artifact_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class MessageV2Table(NoveltyV2Base):
    __tablename__ = "novelty_messages"

    message_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(12000), nullable=False)
    resulting_artifact_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class NotionExportTable(NoveltyV2Base):
    __tablename__ = "novelty_notion_exports"

    export_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    job_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    preview_object_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    notion_page_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    approved_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exported_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class NotionConnectionTable(NoveltyV2Base):
    __tablename__ = "novelty_notion_connections"

    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    token_encrypted: Mapped[str] = mapped_column(String(2000), nullable=False)
    parent_page_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlNoveltyStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory
        # 잡별 마지막 seq 캐시 — 트레이스 1건당 SELECT+INSERT 2왕복을 1왕복으로.
        # 다중 워커 경합은 (job_id, seq) PK가 잡고, 충돌 시 캐시를 무효화해 재동기화한다.
        self._trace_seq_cache: dict[str, int] = {}

    # ── 잡 ──
    def create_job(self, job: NoveltyJob) -> None:
        with self._session_factory() as session:
            session.add(_job_row(job))
            session.commit()

    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob | None:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job_id)
            if row is None or row.owner_id != owner_id:
                return None
            return _job_model(row)

    def get_job_for_worker(self, job_id: str) -> NoveltyJob | None:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job_id)
            return None if row is None else _job_model(row)

    def list_jobs(self, owner_id: str, *, cursor: str | None, limit: int) -> list[NoveltyJob]:
        with self._session_factory() as session:
            stmt = (
                select(NoveltyJobV2Table)
                .where(NoveltyJobV2Table.owner_id == owner_id)
                .order_by(NoveltyJobV2Table.created_at.desc(), NoveltyJobV2Table.job_id.desc())
            )
            if cursor is not None:
                anchor = session.get(NoveltyJobV2Table, cursor)
                if anchor is None or anchor.owner_id != owner_id:
                    # 앵커 소실(삭제 등) — 조용한 절단 대신 무효 커서를 표면화한다.
                    raise KeyError(f"unknown cursor: {cursor}")
                stmt = stmt.where(
                    (NoveltyJobV2Table.created_at < anchor.created_at)
                    | (
                        (NoveltyJobV2Table.created_at == anchor.created_at)
                        & (NoveltyJobV2Table.job_id < anchor.job_id)
                    )
                )
            rows = session.scalars(stmt.limit(limit)).all()
            return [_job_model(row) for row in rows]

    def update_job(self, job: NoveltyJob) -> None:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job.job_id)
            if row is None:
                raise KeyError(job.job_id)
            # 종단 상태 재진입 금지(BR-RA5)를 저장 수준에서도 강제 — 최초 종단 기록 승리
            # (예: stale 스윕과 완주 워커의 경합에서 이중 종단 기록 차단).
            if row.state in _TERMINAL_STATE_VALUES and row.state != job.state.value:
                raise InvalidTransitionError(f"job is terminal: {row.state}")
            data = _job_row(job)
            for attr in (
                "request",
                "state",
                "loop_run",
                "degraded_sources",
                "error_message",
                "created_at",
                "updated_at",
                "completed_at",
            ):
                setattr(row, attr, getattr(data, attr))
            # 취소 플래그는 단방향 래치 — 워커의 낡은 스냅샷이 동시 취소 요청을 덮지 못한다.
            row.cancel_requested = row.cancel_requested or data.cancel_requested
            session.commit()

    def delete_job(self, owner_id: str, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job_id)
            if row is None or row.owner_id != owner_id:
                return False
            for table in (
                ToolCallRecordTable,
                ArtifactV2Table,
                MessageV2Table,
                NotionExportTable,
            ):
                session.execute(delete(table).where(table.job_id == job_id))
            session.delete(row)
            session.commit()
            self._trace_seq_cache.pop(job_id, None)
            return True

    def delete_all_jobs(self, owner_id: str) -> int:
        """소유 잡 전부를 한 트랜잭션으로 벌크 삭제 — 잡당 개별 삭제의 왕복 제거."""
        with self._session_factory() as session:
            job_ids = session.scalars(
                select(NoveltyJobV2Table.job_id).where(NoveltyJobV2Table.owner_id == owner_id)
            ).all()
            if not job_ids:
                return 0
            for table in (
                ToolCallRecordTable,
                ArtifactV2Table,
                MessageV2Table,
                NotionExportTable,
            ):
                session.execute(delete(table).where(table.job_id.in_(job_ids)))
            result = session.execute(
                delete(NoveltyJobV2Table).where(NoveltyJobV2Table.owner_id == owner_id)
            )
            session.commit()
            for job_id in job_ids:
                self._trace_seq_cache.pop(job_id, None)
            return int(result.rowcount or 0)

    def request_cancel(self, owner_id: str, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job_id)
            if row is None or row.owner_id != owner_id:
                return False
            row.cancel_requested = True
            session.commit()
            return True

    def is_cancel_requested(self, job_id: str) -> bool:
        with self._session_factory() as session:
            row = session.get(NoveltyJobV2Table, job_id)
            return bool(row and row.cancel_requested)

    def list_stale_active(self, *, updated_before: Any, limit: int) -> list[NoveltyJob]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(NoveltyJobV2Table)
                .where(
                    NoveltyJobV2Table.state.in_(("received", "investigating", "reporting")),
                    NoveltyJobV2Table.updated_at < updated_before,
                )
                .order_by(NoveltyJobV2Table.updated_at.asc())
                .limit(limit)
            ).all()
            return [_job_model(row) for row in rows]

    # ── 산출물 ──
    def save_artifact(self, record: ArtifactRecord) -> None:
        with self._session_factory() as session:
            existing = session.scalars(
                select(ArtifactV2Table).where(
                    ArtifactV2Table.job_id == record.job_id,
                    ArtifactV2Table.kind == record.kind.value,
                )
            ).first()
            if existing is not None:
                existing.payload = record.payload
                existing.created_at = record.created_at
            else:
                session.add(
                    ArtifactV2Table(
                        artifact_id=record.artifact_id,
                        job_id=record.job_id,
                        owner_id=record.owner_id,
                        kind=record.kind.value,
                        payload=record.payload,
                        created_at=record.created_at,
                    )
                )
            session.commit()

    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRecord]:
        with self._session_factory() as session:
            # owner 격리는 행 필터로 같은 왕복에서 강제 — 선행 소유권 조회 불필요.
            rows = session.scalars(
                select(ArtifactV2Table)
                .where(
                    ArtifactV2Table.job_id == job_id,
                    ArtifactV2Table.owner_id == owner_id,
                )
                .order_by(ArtifactV2Table.created_at.asc(), ArtifactV2Table.artifact_id.asc())
            ).all()
            return [
                ArtifactRecord(
                    artifact_id=row.artifact_id,
                    job_id=row.job_id,
                    owner_id=row.owner_id,
                    kind=ArtifactKind(row.kind),
                    payload=row.payload,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    # ── 트레이스 ──
    def next_trace_seq(self, job_id: str) -> int:
        cached = self._trace_seq_cache.get(job_id)
        if cached is not None:
            return cached + 1
        with self._session_factory() as session:
            last = session.scalars(
                select(ToolCallRecordTable.seq)
                .where(ToolCallRecordTable.job_id == job_id)
                .order_by(ToolCallRecordTable.seq.desc())
                .limit(1)
            ).first()
            return (last or 0) + 1

    def append_trace(self, record: ToolCallRecord) -> None:
        with self._session_factory() as session:
            session.add(
                ToolCallRecordTable(
                    job_id=record.job_id,
                    seq=record.seq,
                    tool_name=record.tool_name,
                    args_summary=record.args_summary,
                    decision_note=record.decision_note,
                    result_summary=record.result_summary,
                    outcome=record.outcome.value,
                    cost_estimate_usd=record.cost_estimate_usd,
                    started_at=record.started_at,
                    finished_at=record.finished_at,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                # 다른 기록자와 충돌 — 캐시를 버리고 호출자 재시도가 DB에서 재동기화.
                self._trace_seq_cache.pop(record.job_id, None)
                raise DuplicateTraceSeqError(f"{record.job_id}:{record.seq}") from exc
            self._trace_seq_cache[record.job_id] = record.seq

    def list_trace(
        self, owner_id: str, job_id: str, *, after_seq: int, limit: int
    ) -> list[ToolCallRecord]:
        with self._session_factory() as session:
            # 트레이스 테이블엔 owner 컬럼이 없으므로 잡 조인으로 같은 왕복에서 격리.
            rows = session.scalars(
                select(ToolCallRecordTable)
                .join(
                    NoveltyJobV2Table,
                    NoveltyJobV2Table.job_id == ToolCallRecordTable.job_id,
                )
                .where(
                    ToolCallRecordTable.job_id == job_id,
                    NoveltyJobV2Table.owner_id == owner_id,
                    ToolCallRecordTable.seq > after_seq,
                )
                .order_by(ToolCallRecordTable.seq.asc())
                .limit(limit)
            ).all()
            return [
                ToolCallRecord(
                    job_id=row.job_id,
                    seq=row.seq,
                    tool_name=row.tool_name,
                    args_summary=row.args_summary,
                    decision_note=row.decision_note,
                    result_summary=row.result_summary,
                    outcome=row.outcome,
                    cost_estimate_usd=row.cost_estimate_usd,
                    started_at=row.started_at,
                    finished_at=row.finished_at,
                )
                for row in rows
            ]

    # ── 대화 ──
    def append_message(self, message: NoveltyChatMessage) -> None:
        with self._session_factory() as session:
            session.add(
                MessageV2Table(
                    message_id=message.message_id,
                    job_id=message.job_id,
                    owner_id=message.owner_id,
                    role=message.role.value,
                    kind=message.kind.value,
                    content=message.content,
                    resulting_artifact_ref=message.resulting_artifact_ref,
                    created_at=message.created_at,
                )
            )
            session.commit()

    def list_messages(
        self, owner_id: str, job_id: str, *, after: str | None, limit: int
    ) -> list[NoveltyChatMessage]:
        with self._session_factory() as session:
            stmt = (
                select(MessageV2Table)
                .where(
                    MessageV2Table.job_id == job_id,
                    MessageV2Table.owner_id == owner_id,
                )
                .order_by(MessageV2Table.created_at.asc(), MessageV2Table.message_id.asc())
            )
            if after is not None:
                # 커서 경로만 선행 소유권 확인 — 비소유자 커서 탐침에 KeyError로
                # 존재 여부가 노출되지 않게 한다(무커서 폴링 핫패스는 단일 쿼리).
                if not self._owns(session, owner_id, job_id):
                    return []
                anchor = session.get(MessageV2Table, after)
                if anchor is None or anchor.job_id != job_id:
                    raise KeyError(f"unknown cursor: {after}")
                stmt = stmt.where(
                    (MessageV2Table.created_at > anchor.created_at)
                    | (
                        (MessageV2Table.created_at == anchor.created_at)
                        & (MessageV2Table.message_id > anchor.message_id)
                    )
                )
            rows = session.scalars(stmt.limit(limit)).all()
            return [
                NoveltyChatMessage(
                    message_id=row.message_id,
                    job_id=row.job_id,
                    owner_id=row.owner_id,
                    role=row.role,
                    kind=row.kind,
                    content=row.content,
                    resulting_artifact_ref=row.resulting_artifact_ref,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    # ── Notion export·연결 ──
    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None:
        with self._session_factory() as session:
            row = session.scalars(
                select(NotionExportTable).where(
                    NotionExportTable.job_id == job_id,
                    NotionExportTable.owner_id == owner_id,
                )
            ).first()
            if row is None:
                return None
            return NotionExport(
                export_id=row.export_id,
                job_id=row.job_id,
                owner_id=row.owner_id,
                status=row.status,
                preview_object_key=row.preview_object_key,
                notion_page_id=row.notion_page_id,
                error_message=row.error_message,
                approved_at=row.approved_at,
                exported_at=row.exported_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    def save_export(self, export: NotionExport) -> None:
        with self._session_factory() as session:
            row = session.scalars(
                select(NotionExportTable).where(NotionExportTable.job_id == export.job_id)
            ).first()
            if row is None:
                row = NotionExportTable(
                    export_id=export.export_id,
                    job_id=export.job_id,
                    owner_id=export.owner_id,
                    created_at=export.created_at,
                    status=export.status.value,
                    updated_at=export.updated_at,
                )
                session.add(row)
            row.status = export.status.value
            row.preview_object_key = export.preview_object_key
            row.notion_page_id = export.notion_page_id
            row.error_message = export.error_message
            row.approved_at = export.approved_at
            row.exported_at = export.exported_at
            row.updated_at = export.updated_at
            session.commit()

    def get_notion_connection(self, owner_id: str) -> NotionConnection | None:
        with self._session_factory() as session:
            row = session.get(NotionConnectionTable, owner_id)
            if row is None:
                return None
            return NotionConnection(
                owner_id=row.owner_id,
                token_encrypted=row.token_encrypted,
                parent_page_id=row.parent_page_id,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )

    def save_notion_connection(self, connection: NotionConnection) -> None:
        with self._session_factory() as session:
            row = session.get(NotionConnectionTable, connection.owner_id)
            if row is None:
                session.add(
                    NotionConnectionTable(
                        owner_id=connection.owner_id,
                        token_encrypted=connection.token_encrypted,
                        parent_page_id=connection.parent_page_id,
                        created_at=connection.created_at,
                        updated_at=connection.updated_at,
                    )
                )
            else:
                row.token_encrypted = connection.token_encrypted
                row.parent_page_id = connection.parent_page_id
                row.updated_at = connection.updated_at
            session.commit()

    def delete_notion_connection(self, owner_id: str) -> None:
        with self._session_factory() as session:
            session.execute(
                delete(NotionConnectionTable).where(NotionConnectionTable.owner_id == owner_id)
            )
            session.commit()

    @staticmethod
    def _owns(session: Session, owner_id: str, job_id: str) -> bool:
        row = session.get(NoveltyJobV2Table, job_id)
        return row is not None and row.owner_id == owner_id


def _job_row(job: NoveltyJob) -> NoveltyJobV2Table:
    return NoveltyJobV2Table(
        job_id=job.job_id,
        owner_id=job.owner_id,
        request=job.request.model_dump(mode="json"),
        state=job.state.value,
        loop_run=job.loop_run.model_dump(mode="json") if job.loop_run else None,
        degraded_sources=dict(job.degraded_sources),
        cancel_requested=job.cancel_requested,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
    )


def _job_model(row: NoveltyJobV2Table) -> NoveltyJob:
    return NoveltyJob(
        job_id=row.job_id,
        owner_id=row.owner_id,
        request=row.request,
        state=row.state,
        loop_run=row.loop_run,
        degraded_sources=row.degraded_sources or {},
        cancel_requested=row.cancel_requested,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )
