from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
    EvidenceResult,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid4())


class SessionStatus(StrEnum):
    ACTIVE = 'active'
    DELETED = 'deleted'


# TurnResult 변형

@dataclass(frozen=True)
class TurnSuccessResult:
    outcome: EvidenceResult
    # 후속 좁히기(꼬리질문)용 — 이번 턴이 실제로 근거로 쓴 논문 id 집합. 다음 턴의
    # ctx.prior_paper_ids로 이어져 "그 중에서" 같은 질문을 explicit scope로 재검색하게 한다.
    resolved_paper_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnAbstainResult:
    outcome: EvidenceAbstainResult


@dataclass(frozen=True)
class TurnPendingResult:
    """수락됐고 실행자가 돌리는 중 — 폴링·이벤트·취소는 전부 turn_id로 한다."""

    started_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class TurnErrorResult:
    # 내부 상세 비노출(SEC-9) — errorCode만 반환
    error_code: str


TurnResult = TurnSuccessResult | TurnAbstainResult | TurnPendingResult | TurnErrorResult


def to_turn_result(state, reason, *, query_used: str) -> TurnResult:
    """루프 상태 + 종료 사유 → 턴 결과. 러너의 정상 종료와 고아 마감이 같은 길을 쓴다."""
    from .domain.assembler import assemble

    outcome = assemble(state, reason, query_used=query_used)
    if outcome.state == 'ok':
        return TurnSuccessResult(
            outcome=outcome, resolved_paper_ids=state.accumulator.cited_paper_ids
        )
    return TurnAbstainResult(outcome=outcome)


@dataclass
class EvidenceTurn:
    turn_id: str = field(default_factory=_new_id)
    session_id: str = ''
    # v2: 소유자를 턴에도 싣는다 — 잡 폴링은 세션을 거치지 않고 턴을 직접 찾으므로
    # 그 경로에도 owner 격리가 필요하다(INV-EV-1).
    owner_id: str = ''
    topic: str = ''
    attachments: list = field(default_factory=list)
    request: EvidenceRequest | None = None
    result: TurnResult | None = None
    created_at: datetime = field(default_factory=_utc_now)
    # 협조적 취소(v3 §5.2) — API가 세우고 실행자가 super-step 경계에서 읽는다.
    cancel_requested: bool = False
    # 실행자가 살아 있다는 마지막 흔적 — 없으면 created_at이 기준이다(§5.5 고아 마감).
    heartbeat_at: datetime | None = None


@dataclass
class EvidenceSession:
    session_id: str = field(default_factory=_new_id)
    owner_id: str = ''
    title: str | None = None
    turns: list[EvidenceTurn] = field(default_factory=list)
    status: SessionStatus = SessionStatus.ACTIVE
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class AttachmentInput:
    """US-EV4(#268) 2차 — 턴 요청에 동봉된 첨부 문서. text가 있으면(md/txt 본문)
    orchestrator가 추출 대상 문서로 포함하고, 없으면(PDF 등) 미포함 안내 대상이다."""

    name: str
    kind: str
    text: str | None = None
    paper_id: str | None = None
    record_ref: str | None = None
    object_key: str | None = None
    doc_model: Any | None = None
    # 업로드 시 발급된 첨부 id — 실행자가 페이로드에서 재수화할 때 신원 검증의 키다.
    # 없으면 이름으로 대신하는데, 이름은 발급 키가 아니라서 검증이 반드시 실패한다.
    attachment_id: str | None = None


