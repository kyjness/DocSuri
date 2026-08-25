"""세션·턴·트레이스 저장(FD 게이트 Q6=A) — owner-scoped 격리(INV-EV-1).

v1과 달리 **턴 결과가 전용 컬럼**에 있다. v1은 result를 attachments JSONB에
욱여넣고 content를 상태 문자열로 썼는데, 그러면 조회·인덱스가 그 구조에 묶이고
결과 형태를 바꿀 때마다 저장 코드를 따라 고쳐야 한다.

트레이스는 append-only 별도 테이블이다 — 빈도가 높아 턴 행에 실으면 스트리밍 중
결과 쓰기와 경합한다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Double,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
    update,
)
from sqlalchemy.exc import IntegrityError
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
    "in_transaction",
    "EvidenceRepository",
    "EvidenceSessionTable",
    "EvidenceTraceTable",
    "EvidenceTurnTable",
    "InMemoryEvidenceRepository",
    "SessionBusy",
    "SqlEvidenceRepository",
]



def in_transaction(
    repo_factory: Callable[[], EvidenceRepository], fn: Callable[[EvidenceRepository], Any]
) -> Any:
    """짧은 트랜잭션 하나 — 열고, 실행하고, 커밋(예외면 롤백)하고, 닫는다.

    실행자와 이벤트 스트림이 같은 행을 서로 다른 프로세스에서 보므로 "한 번의 접촉 = 한 번의
    커밋"이 이 설계의 load-bearing 불변식이다(`turn_control` docstring). 네 곳이 각자 이 틀을
    베껴 쓰다 한 곳에서 롤백이 빠져 있었다 — 여기 하나만 둔다.
    """
    repo = repo_factory()
    try:
        value = fn(repo)
        repo.commit()
        return value
    except Exception:
        repo.rollback()
        raise
    finally:
        repo.close()


class SessionBusy(Exception):
    """같은 세션에 진행 중 턴이 이미 있다(§5.4) — controller가 409."""


class EvidenceRepository(Protocol):
    def create_session(self, session: EvidenceSession) -> EvidenceSession: ...
    # INV-EV-1: owner 불일치·미존재는 KeyError → controller가 404(SEC-9)
    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession: ...
    def list_sessions(self, owner_id: str, limit: int = 50) -> list[EvidenceSession]: ...
    # 밀려난 턴 요약을 세션에 붙인다(§3.4). 없으면 만들고 있으면 이어 붙인다.
    # 밀려난 턴 요약을 세션에 붙이고 **붙인 결과를 돌려준다** — 호출자가 같은 값을 다시
    # 계산하면 상한이 한쪽에만 걸려 모델이 읽는 값과 DB 값이 갈린다(실제로 갈렸다).
    def append_session_summary(self, owner_id: str, session_id: str, text: str) -> str: ...
    # 요약으로 접은 턴에 도장을 찍는다(§3.4) — 없으면 같은 턴이 매 턴 다시 접힌다.
    def mark_summarized(self, owner_id: str, turn_ids: list[str]) -> None: ...
    # 최근 `keep`건 **밖**의, 아직 안 접힌 턴 (turn_id, topic) — 시간순.
    # 결과 JSON을 역직렬화하지 않는다: 접는 데 필요한 것은 질문 문자열뿐이고, 이 질의는
    # 관찰 창 밖(=오래된) 턴을 보므로 행이 많을 수 있다.
    def unsummarized_before(
        self, owner_id: str, session_id: str, keep: int
    ) -> list[tuple[str, str]]: ...
    def soft_delete_session(self, owner_id: str, session_id: str) -> None: ...
    def soft_delete_all_sessions(self, owner_id: str) -> None: ...
    def add_turn(self, turn: EvidenceTurn) -> EvidenceTurn: ...
    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]: ...
    # 멀티턴 맥락용 — 최근 N턴만(오래된 세션 전체를 역직렬화하지 않는다). 시간순 반환.
    def recent_turns(
        self, owner_id: str, session_id: str, limit: int
    ) -> list[EvidenceTurn]: ...
    def get_turn(self, owner_id: str, turn_id: str) -> EvidenceTurn: ...
    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None: ...
    # 세션당 진행 중 턴은 하나(§5.4) — 있으면 그 턴, 없으면 None.
    def active_turn(self, owner_id: str, session_id: str) -> EvidenceTurn | None: ...
    # 협조적 취소(§5.2). 이미 종단이면 False.
    def request_cancel(self, owner_id: str, turn_id: str) -> bool: ...
    # 실행자가 super-step 경계마다 부른다 — 하트비트를 찍고 취소 플래그를 돌려준다(한 문장).
    def heartbeat(self, owner_id: str, turn_id: str) -> bool: ...
    def append_trace(self, owner_id: str, turn_id: str, row: dict) -> None: ...
    # 이벤트 스트림의 커서 조회 — seq > after_seq만(전체는 after_seq=0).
    def list_trace_after(self, owner_id: str, turn_id: str, after_seq: int) -> list[dict]: ...
    # -- 체크포인트 정리(소유자 무관 유지보수) --------------------------------
    # 아직 정리하지 않은, 종단이고 오래된 턴 id. 정리 후 mark_checkpoints_pruned로 도장을 찍어야
    # 다음 호출에서 빠진다 — 도장이 없으면 같은 id가 영원히 다시 나오고 그 뒤는 영영 안 나온다.
    def expired_turn_ids(self, older_than: datetime, limit: int = 200) -> list[str]: ...
    def mark_checkpoints_pruned(self, turn_ids: list[str]) -> None: ...
    def turn_ids_for_sessions(self, owner_id: str, session_ids: list[str]) -> list[str]: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...


# --- 직렬화 ------------------------------------------------------------------

# 트레이스가 **화면으로 나가는** 키(§5.3). 저장 행은 이보다 넓다 — `stance`는 §7 트레이스로
# 남기지만 진행 표시에 실을 것이 아니고(§5.3: 단계명·논문 제목·건수만), `ownerId`는 내부
# 식별자다. 두 스토어가 각자 투영하면 인메모리에서만 통과하는 모양이 생긴다 — 이 저장소가
# 이름 붙인 "두 스토어가 조용히 갈린다"가 정확히 그것이라, 투영을 한 곳에 둔다.
_TRACE_WIRE_KEYS = ("seq", "tool", "argsSummary", "outcome", "resultSummary", "costUsd", "at")


def trace_wire_row(row: dict) -> dict:
    """저장 행 → 화면 행. **시각의 문자열화도 여기서만 한다.**

    저장은 datetime이고 wire는 ISO 문자열이다. 그 변환을 스토어마다 하면 한쪽이 tz를 빠뜨리는
    식으로 갈리는데, 그 차이는 화면의 단계별 소요 시간에만 나타난다 — SQLite는 naive datetime을
    돌려주므로 오프셋 없는 문자열이 나가고, 브라우저의 `Date.parse`는 그것을 **로컬 시각**으로
    읽는다. Postgres에서는 정상이라 로컬에서만 틀린다. 이 파일이 이름 붙인 "두 스토어가 조용히
    갈린다"의 전형이다.
    """
    projected = {key: row.get(key) for key in _TRACE_WIRE_KEYS}
    at = projected.get("at")
    projected["at"] = _ensure_utc(at).isoformat() if isinstance(at, datetime) else at
    return projected



def _serialize(result: TurnResult) -> tuple[dict | None, str]:
    """(result JSON, status)."""
    if isinstance(result, TurnSuccessResult):
        return _dump(result.outcome), "ok"
    if isinstance(result, TurnAbstainResult):
        return _dump(result.outcome), "abstain"
    if isinstance(result, TurnErrorResult):
        return {"errorCode": result.error_code}, "error"
    return None, "pending"


def _is_pending(result: TurnResult | None) -> bool:
    """"아직 실행 중"의 단일 권위 — SQL 쪽 `status == 'pending'`과 같은 판정이다."""
    return isinstance(result, TurnPendingResult | type(None))


def _dump(outcome: Any) -> dict:
    dump = getattr(outcome, "model_dump", None)
    return dump(mode="json", exclude_none=True) if dump else dict(outcome)


def _upgrade_answer(payload: dict) -> dict:
    """`answer`가 문자열인 옛 행을 새 계약으로 감싼다 — 읽기 전용, DB는 손대지 않는다.

    v3 §4 이전의 `answer`는 근거를 결정론으로 이어붙인 문자열이었고 배포 DB에 그 행이
    남아 있다(2026-08-24: 5건). 새 계약은 객체이고 `extra=forbid`라 그대로 읽으면
    `model_validate`가 던지고, 그 세션 조회 전체가 500이 된다. 옛 문자열은 실제로
    "판단 없는 답"이었으므로 폴백 모양(문장 전부 synthesis · fallback=true)이 사실과 맞다.
    """
    answer = payload.get("answer")
    if not isinstance(answer, str):
        return payload
    from docsuri_shared._generated.dtos.evidence_schema import AnswerSegmentKind

    segments = [
        {"text": line.strip(), "refs": [], "kind": AnswerSegmentKind.synthesis.value}
        for line in answer.splitlines()
        if line.strip()
    ]
    upgraded = {
        "segments": segments,
        "checks": {"demoted": 0, "regenerated": False, "fallback": True},
    }
    return {**payload, "answer": upgraded if segments else None}


def _restore(status: str, payload: dict | None, started_at: datetime | None = None) -> TurnResult:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceAbstainResult,
        EvidenceResult,
    )

    if status == "ok" and payload:
        return TurnSuccessResult(outcome=EvidenceResult.model_validate(_upgrade_answer(payload)))
    if status == "abstain" and payload:
        return TurnAbstainResult(outcome=EvidenceAbstainResult.model_validate(payload))
    if status == "error":
        return TurnErrorResult(error_code=str((payload or {}).get("errorCode", "unknown")))
    return TurnPendingResult(started_at=started_at or _utc_now())


# --- In-Memory (개발·테스트) --------------------------------------------------

class InMemoryEvidenceRepository:
    def __init__(self) -> None:
        self._lock = RLock()
        self._sessions: dict[str, EvidenceSession] = {}
        self._turns: dict[str, list[EvidenceTurn]] = {}
        self._trace: dict[str, list[dict]] = {}
        self._pruned: set[str] = set()

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

    def append_session_summary(self, owner_id: str, session_id: str, text: str) -> str:
        with self._lock:
            # `get_session`을 지난다 — 삭제된 세션을 여기서만 받아주면 두 스토어가 갈리고,
            # 테스트가 보는 것은 인메모리 쪽이라 그 갈림이 초록으로 남는다.
            found = self.get_session(owner_id, session_id)
            found.summary = _joined_summary(found.summary, text)
            return found.summary

    def unsummarized_before(
        self, owner_id: str, session_id: str, keep: int
    ) -> list[tuple[str, str]]:
        with self._lock:
            self.get_session(owner_id, session_id)
            turns = list(self._turns.get(session_id, ()))
        older = turns[: max(0, len(turns) - keep)]
        return [(t.turn_id, t.topic or "") for t in older if t.summarized_at is None]

    def mark_summarized(self, owner_id: str, turn_ids: list[str]) -> None:
        with self._lock:
            stamped = _utc_now()
            for turns in self._turns.values():
                for turn in turns:
                    if turn.turn_id in turn_ids and turn.owner_id == owner_id:
                        turn.summarized_at = stamped

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
            # 호출자가 비워 보내도 턴 단독 조회(폴링)에서 격리가 유지된다.
            turn.owner_id = turn.owner_id or session.owner_id
            if _is_pending(turn.result) and any(
                _is_pending(t.result) for t in self._turns.get(turn.session_id, [])
            ):
                raise SessionBusy(turn.session_id)
            self._turns.setdefault(turn.session_id, []).append(turn)
            session.updated_at = _utc_now()
            return turn

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        self.get_session(owner_id, session_id)
        return list(self._turns.get(session_id, []))

    def recent_turns(
        self, owner_id: str, session_id: str, limit: int
    ) -> list[EvidenceTurn]:
        return self.list_turns(owner_id, session_id)[-limit:]

    def get_turn(self, owner_id: str, turn_id: str) -> EvidenceTurn:
        with self._lock:
            for turns in self._turns.values():
                for turn in turns:
                    if turn.turn_id == turn_id and turn.owner_id == owner_id:
                        return turn
        raise KeyError(turn_id)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        """SQL 경로와 **같은 규칙**: 이미 종단인 턴은 덮지 않는다.

        큐의 at-least-once 재배달로 두 워커가 같은 잡을 처리할 수 있다. 대역이
        이 규칙을 안 지키면 테스트가 통과하는데 실서비스에서만 결과가 뒤집힌다.
        """
        with self._lock:
            for turns in self._turns.values():
                for turn in turns:
                    if turn.turn_id == turn_id and turn.owner_id == owner_id:
                        if not _is_pending(turn.result):
                            log.info(
                                "evidence turn %s already resolved; skipping duplicate update",
                                turn_id,
                            )
                            return
                        turn.result = result
                        return
        raise KeyError(turn_id)

    def active_turn(self, owner_id: str, session_id: str) -> EvidenceTurn | None:
        with self._lock:
            for turn in self._turns.get(session_id, []):
                if turn.owner_id == owner_id and _is_pending(turn.result):
                    return turn
        return None

    def request_cancel(self, owner_id: str, turn_id: str) -> bool:
        with self._lock:
            turn = self.get_turn(owner_id, turn_id)
            if not _is_pending(turn.result):
                return False
            turn.cancel_requested = True
            return True

    def heartbeat(self, owner_id: str, turn_id: str) -> bool:
        with self._lock:
            turn = self.get_turn(owner_id, turn_id)
            turn.heartbeat_at = _utc_now()
            return turn.cancel_requested

    def append_trace(self, owner_id: str, turn_id: str, row: dict) -> None:
        with self._lock:
            self._trace.setdefault(turn_id, []).append({**row, "ownerId": owner_id})

    def list_trace_after(self, owner_id: str, turn_id: str, after_seq: int) -> list[dict]:
        with self._lock:
            rows = [r for r in self._trace.get(turn_id, []) if r.get("ownerId") == owner_id]
        return [trace_wire_row(r) for r in rows if int(r.get("seq", 0)) > after_seq]

    def expired_turn_ids(self, older_than: datetime, limit: int = 200) -> list[str]:
        with self._lock:
            found = [
                t.turn_id
                for turns in self._turns.values()
                for t in turns
                if _is_pending(t.result) is False
                and t.created_at < older_than
                and t.turn_id not in self._pruned
            ]
        return found[:limit]

    def mark_checkpoints_pruned(self, turn_ids: list[str]) -> None:
        with self._lock:
            self._pruned.update(turn_ids)

    def turn_ids_for_sessions(self, owner_id: str, session_ids: list[str]) -> list[str]:
        with self._lock:
            return [
                t.turn_id
                for sid in session_ids
                for t in self._turns.get(sid, [])
                if t.owner_id == owner_id
            ]

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
    # 토큰 예산에서 밀려난 이전 턴들의 요약(설계 §3.4). 한 번 만들어 덧붙인다.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    attachments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=False)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heartbeat_at: Mapped[Any | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 세션 요약으로 접힌 시각(§3.4) — 도장이 없으면 같은 턴이 매 턴 다시 접힌다.
    summarized_at: Mapped[Any] = mapped_column(DateTime(timezone=True), nullable=True)
    checkpoints_pruned_at: Mapped[Any | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # 세션당 pending 하나(§5.4). 003 마이그레이션과 같은 인덱스 — SQLite 테스트에서도
    # 같은 규칙이 서야 잠금 테스트가 실 DB와 같은 길을 밟는다.
    __table_args__ = (
        Index(
            "uq_evidence_turns_session_pending",
            "session_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
            sqlite_where=text("status = 'pending'"),
        ),
    )


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
    # 탐색 방향 선언(§3.2). stance를 안 받는 도구와 이 컬럼 이전의 행은 NULL이다.
    stance: Mapped[str | None] = mapped_column(Text, nullable=True)
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
                summary=ev_session.summary or None,
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

    def append_session_summary(self, owner_id: str, session_id: str, text: str) -> str:
        self.get_session(owner_id, session_id)  # owner 격리(INV-EV-1)
        row = self._s.get(EvidenceSessionTable, session_id)
        row.summary = _joined_summary(row.summary or "", text)
        self._s.flush()
        return row.summary

    def unsummarized_before(
        self, owner_id: str, session_id: str, keep: int
    ) -> list[tuple[str, str]]:
        self.get_session(owner_id, session_id)  # owner 격리(INV-EV-1)
        rows = (
            self._s.query(EvidenceTurnTable.turn_id, EvidenceTurnTable.topic)
            .filter(
                EvidenceTurnTable.session_id == session_id,
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.summarized_at.is_(None),
            )
            .order_by(EvidenceTurnTable.created_at.desc(), EvidenceTurnTable.turn_id.desc())
            .offset(keep)
            .all()
        )
        # offset이 최근 `keep`건을 건너뛴다 — 그 뒤는 오래된 순으로 뒤집어 돌려준다.
        return [(str(r.turn_id), r.topic or "") for r in reversed(rows)]

    def mark_summarized(self, owner_id: str, turn_ids: list[str]) -> None:
        if not turn_ids:
            return
        (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.turn_id.in_(turn_ids),
            )
            .update({EvidenceTurnTable.summarized_at: _utc_now()}, synchronize_session=False)
        )
        self._s.flush()

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
        payload, status = _serialize(turn.result)
        self._s.add(
            EvidenceTurnTable(
                turn_id=turn.turn_id,
                session_id=turn.session_id,
                owner_id=row.owner_id,
                topic=turn.topic,
                status=status,
                result=payload,
                attachments=list(turn.attachments or []),
                created_at=turn.created_at,
                cancel_requested=False,
            )
        )
        row.updated_at = _utc_now()
        try:
            self._s.flush()
        except IntegrityError as exc:
            # 부분 유니크 인덱스가 막았다 — 같은 세션에 pending 턴이 이미 있다(§5.4).
            self._s.rollback()
            raise SessionBusy(turn.session_id) from exc
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

    def recent_turns(
        self, owner_id: str, session_id: str, limit: int
    ) -> list[EvidenceTurn]:
        self.get_session(owner_id, session_id)
        rows = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.session_id == session_id,
            )
            .order_by(EvidenceTurnTable.created_at.desc(), EvidenceTurnTable.turn_id.desc())
            .limit(limit)
            .all()
        )
        return [_turn_from_row(row) for row in reversed(rows)]

    def get_turn(self, owner_id: str, turn_id: str) -> EvidenceTurn:
        row = self._s.get(EvidenceTurnTable, turn_id)
        if row is None or row.owner_id != str(owner_id):
            raise KeyError(turn_id)
        return _turn_from_row(row)

    def update_turn_result(self, owner_id: str, turn_id: str, result: TurnResult) -> None:
        payload, status = _serialize(result)
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

    def active_turn(self, owner_id: str, session_id: str) -> EvidenceTurn | None:
        row = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.session_id == session_id,
                EvidenceTurnTable.status == "pending",
            )
            .first()
        )
        return _turn_from_row(row) if row is not None else None

    def request_cancel(self, owner_id: str, turn_id: str) -> bool:
        self.get_turn(owner_id, turn_id)
        updated = (
            self._s.query(EvidenceTurnTable)
            .filter(
                EvidenceTurnTable.turn_id == turn_id,
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.status == "pending",
            )
            .update({"cancel_requested": True}, synchronize_session=False)
        )
        return bool(updated)

    def heartbeat(self, owner_id: str, turn_id: str) -> bool:
        row = self._s.execute(
            update(EvidenceTurnTable)
            .where(
                EvidenceTurnTable.turn_id == turn_id,
                EvidenceTurnTable.owner_id == owner_id,
            )
            .values(heartbeat_at=_utc_now())
            .returning(EvidenceTurnTable.cancel_requested)
        ).first()
        if row is None:
            raise KeyError(turn_id)
        return bool(row[0])

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
                stance=row.get("stance"),
                # 시각의 권위는 `trace_row`(루프가 기록한 순간)다 — 여기서 삽입 시각을 다시
                # 찍으면 인메모리 스토어와 값이 갈리고, 그 차이는 화면의 단계별 소요 시간에만
                # 나타난다. `ToolCallRecord.at`이 항상 채워지므로 폴백은 두지 않는다.
                created_at=row["at"],
            )
        )
        self._s.flush()

    def list_trace_after(self, owner_id: str, turn_id: str, after_seq: int) -> list[dict]:
        rows = (
            self._s.query(EvidenceTraceTable)
            .filter(
                EvidenceTraceTable.owner_id == owner_id,
                EvidenceTraceTable.turn_id == turn_id,
                EvidenceTraceTable.seq > after_seq,
            )
            .order_by(EvidenceTraceTable.seq.asc())
            .all()
        )
        return [
            trace_wire_row(
                {
                    "seq": row.seq,
                    "tool": row.tool,
                    "argsSummary": row.args_summary,
                    "outcome": row.outcome,
                    "resultSummary": row.result_summary,
                    "costUsd": row.cost_usd,
                    # datetime 그대로 넘긴다 — tz 보정과 문자열화는 `trace_wire_row` 하나가
                    # 한다. 여기서 `.isoformat()`을 부르면 SQLite의 naive datetime이 오프셋
                    # 없이 나가고, 화면이 그것을 로컬 시각으로 읽어 첫 단계 소요 시간이
                    # 사라지거나 누적에 9시간이 뜬다(KST).
                    "at": row.created_at,
                }
            )
            for row in rows
        ]

    def expired_turn_ids(self, older_than: datetime, limit: int = 200) -> list[str]:
        rows = (
            self._s.query(EvidenceTurnTable.turn_id)
            .filter(
                EvidenceTurnTable.status != "pending",
                EvidenceTurnTable.created_at < older_than,
                EvidenceTurnTable.checkpoints_pruned_at.is_(None),
            )
            .order_by(EvidenceTurnTable.created_at.asc())
            .limit(limit)
            .all()
        )
        return [str(row[0]) for row in rows]

    def mark_checkpoints_pruned(self, turn_ids: list[str]) -> None:
        if not turn_ids:
            return
        self._s.execute(
            update(EvidenceTurnTable)
            .where(EvidenceTurnTable.turn_id.in_(turn_ids))
            .values(checkpoints_pruned_at=_utc_now())
        )

    def turn_ids_for_sessions(self, owner_id: str, session_ids: list[str]) -> list[str]:
        if not session_ids:
            return []
        rows = (
            self._s.query(EvidenceTurnTable.turn_id)
            .filter(
                EvidenceTurnTable.owner_id == owner_id,
                EvidenceTurnTable.session_id.in_(session_ids),
            )
            .all()
        )
        return [str(row[0]) for row in rows]

    def commit(self) -> None:
        self._s.commit()

    def rollback(self) -> None:
        self._s.rollback()

    def close(self) -> None:
        self._s.close()


# 세션 요약 상한(문자). 넘으면 **앞을 버린다** — 오래된 턴일수록 후속 질문이 덜 가리키고,
# 뒤를 버리면 방금 밀려난 턴이 사라져 요약이 있으나 마나 해진다.
_MAX_SESSION_SUMMARY_CHARS = 4000


# 접힌 질문 목록의 머리표. 붙일 때마다 다시 쓰면 세션이 길어질수록 요약의 절반이 라벨이 된다
# (30턴 실측: 188자 중 90자가 "이전에 물어본 것: " 아홉 벌이었다).
_SUMMARY_LABEL = "이전에 물어본 것: "


def _joined_summary(existing: str, text: str) -> str:
    """요약을 이어 붙인다 — **다시 만들지 않는다**(§3.4: 매 턴 재요약하지 않는다).

    **머리표와 상한을 이 함수가 소유한다.** 호출자는 맨 질문 목록만 준다 — 두 모듈이 같은
    라벨 문자열을 각자 쓰면 한 글자만 달라져도 조용히 안 맞고, 그러면 접을 때마다 라벨이
    다시 쌓인다(30턴에서 188자 중 90자가 라벨 아홉 벌이었다).

    상한을 넘으면 **앞을 자른다** —
    오래된 질문일수록 후속 질문이 덜 가리킨다. 자를 때 머리표가 함께 잘려 나가면 남는 것이
    맥락 없는 조각이 되므로, 자른 뒤 머리표를 다시 세운다.
    """
    addition = text.strip()
    if not addition:
        return existing.strip()
    if not existing.strip():
        return (_SUMMARY_LABEL + addition)[-_MAX_SESSION_SUMMARY_CHARS:]
    joined = f"{existing.strip()} / {addition}"
    if len(joined) <= _MAX_SESSION_SUMMARY_CHARS:
        return joined
    trimmed = joined[-(_MAX_SESSION_SUMMARY_CHARS - len(_SUMMARY_LABEL)) :]
    return _SUMMARY_LABEL + trimmed.lstrip(" /")


def _session_from_row(row: EvidenceSessionTable) -> EvidenceSession:
    return EvidenceSession(
        session_id=str(row.session_id),
        owner_id=str(row.owner_id),
        title=row.title,
        summary=row.summary or "",
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
        result=_restore(row.status, row.result, _ensure_utc(row.created_at)),
        attachments=list(row.attachments or []),
        created_at=_ensure_utc(row.created_at),
        cancel_requested=bool(row.cancel_requested),
        heartbeat_at=_ensure_utc(row.heartbeat_at) if row.heartbeat_at else None,
        summarized_at=_ensure_utc(row.summarized_at) if row.summarized_at else None,
    )


def _ensure_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
