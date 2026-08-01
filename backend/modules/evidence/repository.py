"""세션·턴·트레이스 저장(FD 게이트 Q6=A) — owner-scoped 격리(INV-EV-1).

v1과 달리 **턴 결과가 전용 컬럼**에 있다. v1은 result를 attachments JSONB에
욱여넣고 content를 상태 문자열로 썼는데, 그러면 조회·인덱스가 그 구조에 묶이고
결과 형태를 바꿀 때마다 저장 코드를 따라 고쳐야 한다.

트레이스는 append-only 별도 테이블이다 — 빈도가 높아 턴 행에 실으면 스트리밍 중
결과 쓰기와 경합한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Double,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .models import (
    EvidenceSession,
    EvidenceTurn,
    SessionStatus,
    TurnAbstainResult,
    TurnErrorResult,
    TurnPendingResult,
    TurnResult,
    TurnSuccessResult,
    _utc_now,
)

log = logging.getLogger("docsuri.evidence.repository")

__all__ = [
    "Base",
    "EvidenceRepository",
    "EvidenceSessionTable",
    "EvidenceTraceTable",
    "EvidenceTurnTable",
    "InMemoryEvidenceRepository",
    "SqlEvidenceRepository",
    "TraceRow",
]


class TraceRow(dict):
    """트레이스 1건의 저장·조회 형태. 활동 피드가 그대로 읽는다."""


class EvidenceRepository(Protocol):
    def create_session(self, session: EvidenceSession) -> EvidenceSession: ...
    # INV-EV-1: owner 불일치·미존재는 KeyError → controller가 404(SEC-9)
    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession: ...
    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]: ...
    def soft_delete_session(self, owner_id: str, session_id: str) -> None: ...
    def soft_delete_all_sessions(self, owner_id: str) -> None: ...
    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn: ...
    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]: ...
    def get_turn_by_job_id(self, owner_id: str, job_id: str) -> EvidenceTurn: ...
    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None: ...
    def append_trace(self, owner_id: str, turn_id: str, row: dict) -> None: ...
    def list_trace(self, owner_id: str, turn_id: str) -> list[dict]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


# --- 직렬화 ------------------------------------------------------------------

def _serialize(result: TurnResult) -> tuple[dict | None, str, str | None]:
    """(result JSON, status, job_id)."""
    if isinstance(result, TurnSuccessResult):
        return _dump(result.outcome), "ok", None
    if isinstance(result, TurnAbstainResult):
        return _dump(result.outcome), "abstain", None
    if isinstance(result, TurnPendingResult):
        return None, "pending", result.job_id
    if isinstance(result, TurnErrorResult):
        return {"errorCode": result.error_code}, "error", None
    return None, "pending", None


def _dump(outcome: Any) -> dict:
    dump = getattr(outcome, "model_dump", None)
    return dump(mode="json", exclude_none=True) if dump else dict(outcome)


def _restore(status: str, payload: dict | None, job_id: str | None) -> TurnResult:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceResult,
    )

    if status == "ok" and payload:
        return TurnSuccessResult(outcome=EvidenceResult.model_validate(payload))
    if status == "abstain" and payload:
        return TurnAbstainResult(outcome=EvidenceAbstainResult.model_validate(payload))
    if status == "error":
        return TurnErrorResult(error_code=str((payload or {}).get("errorCode", "unknown")))
    return TurnPendingResult(job_id=job_id or "", started_at=_utc_now())


# --- In-Memory (개발·테스트) --------------------------------------------------

class InMemoryEvidenceRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, EvidenceSession] = {}
        self._turns: dict[str, list[EvidenceTurn]] = {}
        self._trace: dict[str, list[dict]] = {}

    def create_session(self, session: EvidenceSession) -> EvidenceSession:
        with self._lock:
            self._sessions[session.session_id] = session
            self._turns.setdefault(session.session_id, [])
            return session

    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession:
        with self._lock:
            found = self._sessions.get(session_id)
            if found is None or found.owner_id != owner_id or found.status is SessionStatus.DELETED:
                raise KeyError(session_id)
            return found

    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]:
        with self._lock:
            active = [
                s for s in self._sessions.values()
                if s.owner_id == owner_id and s.status is SessionStatus.ACTIVE
            ]
        return sorted(active, key=lambda s: s.updated_at, reverse=True)[:limit]

    def soft_delete_session(self, owner_id: str, session_id: str) -> None:
        with self._lock:
            found = self.get_session(owner_id, session_id)
            found.status = SessionStatus.DELETED
            found.updated_at = _utc_now()

    def soft_delete_all_sessions(self, owner_id: str) -> None:
        with self._lock:
            for session in self._sessions.values():
                if session.owner_id == owner_id:
                    session.status = SessionStatus.DELETED

    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn:
        with self._lock:
            session = self._sessions.get(turn.session_id)
            if session is None or session.status is SessionStatus.DELETED:
                raise KeyError(turn.session_id)
            # 소유자는 세션이 권위다 — SQL 경로가 세션 행에서 가져오는 것과 같다.
            # 호출자가 비워 보내도 턴 단독 조회(잡 폴링)에서 격리가 유지된다.
            turn.owner_id = turn.owner_id or session.owner_id
            self._turns.setdefault(turn.session_id, []).append(turn)
            session.updated_at = _utc_now()
            return turn

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        self.get_session(owner_id, session_id)
        return list(self._turns.get(session_id, []))

    def get_turn_by_job_id(self, owner_id: str, job_id: str) -> EvidenceTurn:
        with self._lock:
            for turns in self._turns.values():
                for turn in turns:
                    if turn.job_id == job_id and turn.owner_id == owner_id:
                        return turn
        raise KeyError(job_id)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        """SQL 경로와 **같은 규칙**: 이미 종단인 턴은 덮지 않는다.

        큐의 at-least-once 재배달로 두 워커가 같은 잡을 처리할 수 있다. 대역이
        이 규칙을 안 지키면 테스트가 통과하는데 실서비스에서만 결과가 뒤집힌다.
        """
        with self._lock:
            for turns in self._turns.values():
                for turn in turns:
                    if turn.turn_id == turn_id and turn.owner_id == owner_id:
                        if not isinstance(turn.result, TurnPendingResult | type(None)):
                            log.info(
                                "evidence turn %s already resolved; skipping duplicate update",
                                turn_id,
                            )
                            return
                        turn.result = result
                        return
        raise KeyError(turn_id)

    def append_trace(self, owner_id: str, turn_id: str, row: dict) -> None:
        with self._lock:
            self._trace.setdefault(turn_id, []).append({**row, "ownerId": owner_id})

    def list_trace(self, owner_id: str, turn_id: str) -> list[dict]:
        with self._lock:
            return [r for r in self._trace.get(turn_id, []) if r.get("ownerId") == owner_id]

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


# --- SQL ---------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class EvidenceSessionTable(Base):
    __tablename__ = "evidence_sessions"

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceTurnTable(Base):
    __tablename__ = "evidence_turns"

    turn_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    job_id: Mapped[str | None] = mapped_column(Uuid(as_uuid=False), nullable=True)
    attachments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceTraceTable(Base):
    __tablename__ = "evidence_trace"

    trace_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    turn_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(Text, nullable=False)
    args_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    result_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost_usd: Mapped[float | None] = mapped_column(Double, nullable=True)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class SqlEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # -- 세션 ---------------------------------------------------------------
    def create_session(self, ev_session: EvidenceSession) -> EvidenceSession:
        self._s.add(
            EvidenceSessionTable(
                session_id=ev_session.session_id,
                owner_id=ev_session.owner_id,
                title=ev_session.title,
                status=ev_session.status.value,
                created_at=ev_session.created_at,
                updated_at=ev_session.updated_at,
            )
        )
        self._s.flush()
        return ev_session

    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession:
        row = self._s.get(EvidenceSessionTable, session_id)
        if row is None or row.owner_id != str(owner_id) or row.status == SessionStatus.DELETED:
            raise KeyError(session_id)
        return _session_from_row(row)

    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]:
        rows = (
            self._s.query(EvidenceSessionTable)
            .filter(
                EvidenceSessionTable.owner_id == owner_id,
                EvidenceSessionTable.status == SessionStatus.ACTIVE,
            )
            .order_by(EvidenceSessionTable.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [_session_from_row(row) for row in rows]

    def soft_delete_session(self, owner_id: str, session_id: str) -> None:
        self.get_session(owner_id, session_id)
        (
            self._s.query(EvidenceSessionTable)
            .filter(
                EvidenceSessionTable.session_id == session_id,
                EvidenceSessionTable.owner_id == owner_id,
            )
            .update(
                {"status": SessionStatus.DELETED, "updated_at": _utc_now()},
                synchronize_session=False,
            )
        )
        self._s.flush()

    def soft_delete_all_sessions(self, owner_id: str) -> None:
        (
            self._s.query(EvidenceSessionTable)
            .filter(
                EvidenceSessionTable.owner_id == owner_id,
                EvidenceSessionTable.status == SessionStatus.ACTIVE,
            )
            .update(
                {"status": SessionStatus.DELETED, "updated_at": _utc_now()},
                synchronize_session=False,
            )
        )
        self._s.flush()

    # -- 턴 -----------------------------------------------------------------
    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn:
        row = self._s.get(EvidenceSessionTable, turn.session_id)
        if row is None or row.status == SessionStatus.DELETED:
            raise KeyError(turn.session_id)
        payload, status, job_id = _serialize(turn.result)
        self._s.add(
            EvidenceTurnTable(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                owner_id=row.owner_id,
                topic=turn.topic,
                status=status,
                result=payload,
                # 빈 문자열을 UUID 컬럼에 넣으면 실 DB만 터진다(인메모리·SQLite는
                # 통과시킨다). 동기 경로의 pending 자리표시자가 그 형태였다.
                job_id=(turn.job_id or job_id) or None,
                attachments=list(turn.attachments or []),
                created_at=turn.created_at,
            )
        )
        row.updated_at = _utc_now()
        self._s.flush()
        return turn

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        self.get_session(owner_id, session_id)
        rows = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.session_id == session_id,
            )
            .order_by(EvidenceTurnTable.created_at.asc(), EvidenceTurnTable.turn_id.asc())
            .all()
        )
        return [_turn_from_row(row) for row in rows]

    def get_turn_by_job_id(self, owner_id: str, job_id: str) -> EvidenceTurn:
        row = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.job_id == job_id,
            )
            .first()
        )
        if row is None:
            raise KeyError(job_id)
        return _turn_from_row(row)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        payload, status, _job = _serialize(result)
        # 조건부 UPDATE로 원자성을 보장한다 — 큐의 at-least-once 재배달로 두 워커가
        # 같은 잡을 처리해도 먼저 확정된 결과가 덮이지 않는다(v1 선례 승계).
        updated = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.turn_id == turn_id,
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.status == "pending",
            )
            .update({"status": status, "result": payload}, synchronize_session=False)
        )
        if not updated:
            log.info("evidence turn %s already resolved; skipping duplicate update", turn_id)

    # -- 트레이스 ------------------------------------------------------------
    def append_trace(self, owner_id: str, turn_id: str, row: dict) -> None:
        self._s.add(
            EvidenceTraceTable(
                turn_id=turn_id,
                owner_id=owner_id,
                seq=int(row.get("seq", 0)),
                tool=str(row.get("tool", "")),
                args_summary=str(row.get("argsSummary", "")),
                outcome=str(row.get("outcome", "")),
                result_summary=str(row.get("resultSummary", "")),
                cost_usd=row.get("costUsd"),
                created_at=_utc_now(),
            )
        )
        self._s.flush()

    def list_trace(self, owner_id: str, turn_id: str) -> list[dict]:
        rows = (
            self._s.query(EvidenceTraceTable)
            .filter(
                EvidenceTraceTable.owner_id == owner_id,
                EvidenceTraceTable.turn_id == turn_id,
            )
            .order_by(EvidenceTraceTable.seq.asc())
            .all()
        )
        return [
            {
                "seq": row.seq,
                "tool": row.tool,
                "argsSummary": row.args_summary,
                "outcome": row.outcome,
                "resultSummary": row.result_summary,
                "costUsd": row.cost_usd,
                "at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()

    def close(self) -> None:
        self._s.close()


def _session_from_row(row: EvidenceSessionTable) -> EvidenceSession:
    return EvidenceSession(
        session_id=str(row.session_id),
        owner_id=str(row.owner_id),
        title=row.title,
        status=SessionStatus(row.status),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _turn_from_row(row: EvidenceTurnTable) -> EvidenceTurn:
    return EvidenceTurn(
        turn_id=str(row.turn_id),
        session_id=str(row.session_id),
        owner_id=str(row.owner_id),
        topic=row.topic or "",
        result=_restore(row.status, row.result, str(row.job_id) if row.job_id else None),
        job_id=str(row.job_id) if row.job_id else None,
        attachments=list(row.attachments or []),
        created_at=_ensure_utc(row.created_at),
    )


def _ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
