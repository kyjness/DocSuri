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
    # 꼬리질문 좁히기용 — 직전 턴이 실제로 근거로 쓴 논문 id 집합(TurnSuccessResult.
    # resolved_paper_ids가 그대로 이어진다). "그 중에서" 류 후속 질문 감지 시에만
    # explicit scope로 전환해 이 집합으로 검색을 제한한다. 단발 경로·새 세션은 비어 있다.
    prior_paper_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaperSearchResult:
    records: tuple[Any, ...]  # IndexRecord[]
    query_used: str | None
    scope: str  # EvidenceScope value


@dataclass(frozen=True)
class LiteralMatch:
    """정확 문구가 발견된 위치 하나 — LLM을 거치지 않으므로 그 자체로 grounded."""

    paper_id: str
    # DocModel Section/Block id(문단 단위) — 실제 "줄 번호"는 DocModel 계약상 존재하지
    # 않는다(docmodel_schema.py: "page numbers are intentionally out of scope"). 문단
    # 단위가 이 시스템에서 낼 수 있는 최선의 위치 표현이다.
    anchor: str | None
    quote: str


@dataclass(frozen=True)
class LiteralSearchResult:
    phrase: str
    matches: tuple[LiteralMatch, ...]


@dataclass(frozen=True)
class AttachmentHandle:
    attachment_id: str
    mime_type: str
    size_bytes: int
