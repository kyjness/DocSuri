from __future__ import annotations

import logging
from datetime import UTC, datetime
from threading import RLock
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, Uuid
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

log = logging.getLogger('docsuri.evidence.repository')

# ---------------------------------------------------------------------------
# Port (Protocol)
# ---------------------------------------------------------------------------

class EvidenceRepository:
    """세션·턴 저장소 포트 — INV-EV-1(소유권) 강제."""

    def create_session(self, session: EvidenceSession) -> EvidenceSession: ...
    # INV-EV-1: owner_id 불일치 또는 미존재 시 KeyError → controller가 404 반환(SEC-9)
    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession: ...
    # BR-EV-10: 소유자 본인 active 세션만, updated_at DESC
    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]: ...
    # BR-EV-8: 소프트 삭제(status=deleted)
    def soft_delete_session(self, owner_id: str, session_id: str) -> None: ...
    # BR-EV-9: 소유자 전체 세션 소프트 삭제
    def soft_delete_all_sessions(self, owner_id: str) -> None: ...
    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn: ...
    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]: ...
    # 비동기 잡 폴링 — job_id(TurnPendingResult.job_id)로 턴 조회(BR-EV-6)
    def get_turn_by_job_id(self, owner_id: str, job_id: str) -> EvidenceTurn: ...
    # AgentWorker: 비동기 완료 후 pending → final result 교체(BR-EV-6)
    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-Memory (개발·테스트용)
# ---------------------------------------------------------------------------

class InMemoryEvidenceRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, EvidenceSession] = {}
        self._turns: dict[str, list[EvidenceTurn]] = {}

    def create_session(self, session: EvidenceSession) -> EvidenceSession:
        with self._lock:
            self._sessions[session.session_id] = session
            self._turns.setdefault(session.session_id, [])
            return session

    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession:
        with self._lock:
            s = self._sessions.get(session_id)
            # INV-EV-1: 타인 세션 존재 여부 노출 금지(SEC-9) → 동일 KeyError
            if s is None or s.owner_id != owner_id or s.status == SessionStatus.DELETED:
                raise KeyError(session_id)
            return s

    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]:
        with self._lock:
            active = [
                s for s in self._sessions.values()
                if s.owner_id == owner_id and s.status == SessionStatus.ACTIVE
            ]
            active.sort(key=lambda s: s.updated_at, reverse=True)
            return active[:limit]

    def soft_delete_session(self, owner_id: str, session_id: str) -> None:
        with self._lock:
            s = self.get_session(owner_id, session_id)
            s.status = SessionStatus.DELETED
            s.updated_at = _utc_now()

    def soft_delete_all_sessions(self, owner_id: str) -> None:
        with self._lock:
            now = _utc_now()
            for s in self._sessions.values():
                if s.owner_id == owner_id and s.status == SessionStatus.ACTIVE:
                    s.status = SessionStatus.DELETED
                    s.updated_at = now

    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn:
        with self._lock:
            s = self._sessions.get(turn.session_id)
            if s is None or s.status == SessionStatus.DELETED:
                raise KeyError(turn.session_id)
            self._turns.setdefault(turn.session_id, []).append(turn)
            s.updated_at = _utc_now()
            return turn

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        with self._lock:
            self.get_session(owner_id, session_id)
            turns = list(self._turns.get(session_id, []))
            turns.sort(key=lambda t: t.created_at)
            return turns

    def get_turn_by_job_id(self, owner_id: str, job_id: str) -> EvidenceTurn:
        with self._lock:
            for turn_list in self._turns.values():
                for turn in turn_list:
                    if turn.job_id == job_id:
                        s = self._sessions.get(turn.session_id)
                        if s and s.owner_id == owner_id:
                            return turn
            raise KeyError(job_id)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        with self._lock:
            for turn_list in self._turns.values():
                for turn in turn_list:
                    if turn.turn_id == turn_id:
                        s = self._sessions.get(turn.session_id)
                        if not s or s.owner_id != owner_id:
                            raise KeyError(turn_id)
                        # idempotency guard (PR #338 리뷰 Blocking #4): 이미 terminal
                        # 상태인 turn은 덮어쓰지 않는다 — 중복 배달된 job이 먼저 끝난
                        # 결과를 나중 결과로 clobber하는 것을 방지.
                        if not isinstance(turn.result, TurnPendingResult):
                            log.info(
                                'evidence turn %s already resolved; skipping duplicate update',
                                turn_id,
                            )
                            return
                        turn.result = result
                        s.updated_at = _utc_now()
                        return
            raise KeyError(turn_id)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# SQLAlchemy ORM 테이블
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


class EvidenceSessionTable(Base):
    # 전용 테이블(evidence/migrations/001) — PR #338 리뷰 Blocking #1: research_jobs를
    # 재사용하면 evidence 세션이 /api/research/jobs에 노출되고, evidence의
    # status='deleted'가 ResearchJobState(연구 전용 enum, DELETED 없음)를 깨뜨렸음.
    __tablename__ = 'evidence_sessions'

    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='active')
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


class EvidenceTurnTable(Base):
    # 전용 테이블(evidence/migrations/001) — research_messages 재사용 시 필요했던
    # role='turn' 구분자가 더 이상 필요 없음(이 테이블엔 evidence turn만 존재).
    __tablename__ = 'evidence_turns'

    turn_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    session_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False, index=True)
    content: Mapped[str] = mapped_column(String(12000), nullable=False, default='')
    attachments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)


# ---------------------------------------------------------------------------
# SQL Repository
# ---------------------------------------------------------------------------

class SqlEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

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
        if row is None or row.owner_id != owner_id or row.status == SessionStatus.DELETED:
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
        row = self._s.get(EvidenceSessionTable, session_id)
        if row is None or row.owner_id != owner_id or row.status == SessionStatus.DELETED:
            raise KeyError(session_id)
        row.status = SessionStatus.DELETED
        row.updated_at = _utc_now()
        self._s.flush()

    def soft_delete_all_sessions(self, owner_id: str) -> None:
        now = _utc_now()
        (
            self._s.query(EvidenceSessionTable)
            .filter(
                EvidenceSessionTable.owner_id == owner_id,
                EvidenceSessionTable.status == SessionStatus.ACTIVE,
            )
            .update({'status': SessionStatus.DELETED, 'updated_at': now}, synchronize_session=False)
        )
        self._s.flush()

    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn:
        row = self._s.get(EvidenceSessionTable, turn.session_id)
        if row is None or row.status == SessionStatus.DELETED:
            raise KeyError(turn.session_id)
        attachments = _pack_turn(turn)
        result_state = _result_state(turn.result)
        self._s.add(
            EvidenceTurnTable(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                owner_id=row.owner_id,
                content=result_state or '',
                attachments=attachments,
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
        # job_id는 attachments[0]['job_id']에 생성 시점부터 고정 저장된다(result 내부가
        # 아님) — PR #338 리뷰 Blocking #2: job_id가 TurnPendingResult 안에만 있으면
        # update_turn_result가 terminal 결과로 교체할 때 job_id 자체가 사라져서, 완료
        # 직후부터 이 조회가 영원히 404가 됐음. content='pending' 조건도 함께 제거해
        # pending이든 완료든 동일한 job_id로 조회 가능하게 함.
        row = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.attachments[0]['job_id'].as_string() == job_id,
            )
            .first()
        )
        if row is None:
            raise KeyError(job_id)
        return _turn_from_row(row)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        row = self._s.get(EvidenceTurnTable, turn_id)
        if row is None or row.owner_id != str(owner_id):
            raise KeyError(turn_id)

        data, state = _serialize_result(result)
        attachments = list(row.attachments or [])
        if attachments:
            attachments[0] = {**attachments[0], 'result': data, 'result_state': state}
        else:
            attachments = [{'result': data, 'result_state': state}]

        # idempotency guard (PR #338 리뷰 Blocking #4): content='pending' 조건부 UPDATE로
        # 원자적으로 처리한다. SQS at-least-once 중복 배달로 두 worker가 동시에 같은
        # job을 처리해도, 먼저 커밋된 terminal 결과가 나중 결과로 clobber되지 않는다 —
        # 단순 SELECT 후 조건 확인은 두 트랜잭션이 모두 'pending'을 본 뒤 커밋하는
        # race를 못 막으므로, WHERE 절이 포함된 UPDATE 문 자체로 원자성을 보장한다.
        updated = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.turn_id == turn_id,
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.content == 'pending',
            )
            .update({'attachments': attachments, 'content': state or ''}, synchronize_session=False)
        )
        if not updated:
            log.info('evidence turn %s already resolved; skipping duplicate update', turn_id)
            return

        session_row = self._s.get(EvidenceSessionTable, row.session_id)
        if session_row:
            session_row.updated_at = _ensure_utc(datetime.now(UTC))

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()

    def close(self) -> None:
        self._s.close()


# ---------------------------------------------------------------------------
# 직렬화 헬퍼
# ---------------------------------------------------------------------------

def _session_from_row(row: EvidenceSessionTable) -> EvidenceSession:
    return EvidenceSession(
        session_id=row.session_id,
        owner_id=row.owner_id,
        title=row.title,
        turns=[],
        status=SessionStatus(row.status),
        created_at=_ensure_utc(row.created_at),
        updated_at=_ensure_utc(row.updated_at),
    )


def _turn_from_row(row: EvidenceTurnTable) -> EvidenceTurn:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

    payload = (row.attachments or [{}])[0]
    request_data = payload.get('request')
    request = EvidenceRequest.model_validate(request_data) if request_data else None
    result = _deserialize_result(payload.get('result'), payload.get('result_state'))
    return EvidenceTurn(
        turn_id=row.turn_id,
        session_id=row.session_id,
        request=request,
        result=result,
        created_at=_ensure_utc(row.created_at),
        job_id=payload.get('job_id'),
    )


def _pack_turn(turn: EvidenceTurn) -> list[dict]:
    result_data, result_state = _serialize_result(turn.result)
    # job_id는 'result' 안이 아니라 최상위에 한 번만 기록한다 — update_turn_result가
    # terminal 결과로 교체해도 이 키는 그대로 남아(dict 병합 시 result/result_state만
    # 덮어씀) get_turn_by_job_id가 완료 후에도 계속 조회 가능하다(PR #338 Blocking #2).
    job_id = turn.result.job_id if isinstance(turn.result, TurnPendingResult) else None
    return [{
        'request': turn.request.model_dump() if turn.request else None,
        'job_id': job_id,
        'result': result_data,
        'result_state': result_state,
    }]


def _result_state(result: TurnResult | None) -> str | None:
    if isinstance(result, TurnSuccessResult):
        return 'success'
    if isinstance(result, TurnAbstainResult):
        return 'abstain'
    if isinstance(result, TurnPendingResult):
        return 'pending'
    if isinstance(result, TurnErrorResult):
        return 'error'
    return None


def _serialize_result(result: TurnResult | None) -> tuple[dict | None, str | None]:
    if result is None:
        return None, None
    if isinstance(result, TurnSuccessResult):
        return {'type': 'success', 'outcome': result.outcome.model_dump()}, 'success'
    if isinstance(result, TurnAbstainResult):
        return {'type': 'abstain', 'outcome': result.outcome.model_dump()}, 'abstain'
    if isinstance(result, TurnPendingResult):
        return {
            'type': 'pending',
            'job_id': result.job_id,
            'started_at': result.started_at.isoformat(),
        }, 'pending'
    if isinstance(result, TurnErrorResult):
        return {'type': 'error', 'error_code': result.error_code}, 'error'
    return None, None


def _deserialize_result(data: dict | None, state: str | None) -> TurnResult | None:
    if data is None or state is None:
        return None
    if state == 'success':
        from docsuri_shared._generated.dtos.evidence_schema import EvidenceResult
        return TurnSuccessResult(outcome=EvidenceResult.model_validate(data['outcome']))
    if state == 'abstain':
        from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult
        return TurnAbstainResult(outcome=EvidenceAbstainResult.model_validate(data['outcome']))
    if state == 'pending':
        return TurnPendingResult(
            job_id=data['job_id'],
            started_at=datetime.fromisoformat(data['started_at']),
        )
    if state == 'error':
        return TurnErrorResult(error_code=data['error_code'])
    return None


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
