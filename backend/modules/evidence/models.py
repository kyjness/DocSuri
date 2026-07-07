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


@dataclass(frozen=True)
class TurnAbstainResult:
    outcome: EvidenceAbstainResult


@dataclass(frozen=True)
class TurnPendingResult:
    job_id: str
    started_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True)
class TurnErrorResult:
    # 내부 상세 비노출(SEC-9) — errorCode만 반환
    error_code: str


TurnResult = TurnSuccessResult | TurnAbstainResult | TurnPendingResult | TurnErrorResult


@dataclass
class EvidenceTurn:
    turn_id: str = field(default_factory=_new_id)
    session_id: str = ''
    request: EvidenceRequest | None = None
    result: TurnResult | None = None
    created_at: datetime = field(default_factory=_utc_now)
    # 비동기 잡 폴링용 식별자(BR-EV-6) — TurnPendingResult.job_id에서 생성 시 한 번만
    # 복사해온다. result가 terminal로 교체된 뒤에도 get_turn_by_job_id가 계속 조회할 수
    # 있어야 하는데, job_id가 result 안에만 있으면 완료 즉시 사라져 404가 났었다
    # (PR #338 리뷰 Blocking #2).
    job_id: str | None = None


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


@dataclass(frozen=True)
class AgentRunContext:
    session: EvidenceSession
    current_turn: EvidenceTurn
    owner_id: str
    request_id: str
    budget_signal: dict[str, Any] = field(default_factory=dict)
    # 멀티턴 검색 맥락화용 — 같은 세션의 이전 턴 topic들(PR #338 리뷰 Blocking #2/FR-37).
    # 단발 경로(U12 form_evidence)·새 세션은 비어 있다.
    prior_topics: tuple[str, ...] = ()
    # US-EV4(#268) 2차 — 이 턴에 동봉된 첨부 문서들(연구 경로가 채운다).
    attachment_docs: tuple[AttachmentInput, ...] = ()


@dataclass(frozen=True)
class PaperSearchResult:
    records: tuple[Any, ...]  # IndexRecord[]
    query_used: str | None
    scope: str  # EvidenceScope value


@dataclass(frozen=True)
class AttachmentHandle:
    attachment_id: str
    mime_type: str
    size_bytes: int
