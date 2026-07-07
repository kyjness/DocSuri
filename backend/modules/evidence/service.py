from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
    EvidenceResult,
)

from .models import (
    AgentRunContext,
    AttachmentInput,
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
    TurnPendingResult,
    TurnResult,
    TurnSuccessResult,
    _new_id,
    _utc_now,
)
from .orchestrator import EvidenceAgentOrchestrator
from .repository import EvidenceRepository

logger = logging.getLogger(__name__)

_SESSION_LIST_MAX = 100
_TITLE_MAX_LEN = 120


# ---------------------------------------------------------------------------
# 서비스 응답 DTO (D5 외부 — 내부 전용)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TurnResponse:
    """채팅 턴 실행 결과 — controller 직렬화용."""
    session_id: str
    turn_id: str
    result: TurnResult
    created_at: datetime


@dataclass(frozen=True)
class SessionSummary:
    """세션 목록 항목."""
    session_id: str
    title: str | None
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# EvidenceChatService — 채팅 턴 오케스트레이션 (FR-36, FR-37)
# ---------------------------------------------------------------------------

class EvidenceChatService:
    """세션 load/create → Agent 실행 위임 → 턴 저장."""

    def __init__(
        self,
        *,
        repo: EvidenceRepository,
        orchestrator: EvidenceAgentOrchestrator,
        sqs_enqueue: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._repo = repo
        self._orchestrator = orchestrator
        self._sqs_enqueue = sqs_enqueue

    def run_turn(
        self,
        *,
        owner_id: str,
        request: EvidenceRequest,
        session_id: str | None = None,
        budget_signal: dict[str, Any] | None = None,
        request_id: str = '',
        attachment_docs: tuple[AttachmentInput, ...] = (),
    ) -> TurnResponse:
        """채팅 턴 1회 실행.

        sqs_enqueue 주입 시 비동기 경로(BR-EV-6): TurnPendingResult 즉시 반환 + SQS enqueue.
        미주입 시 동기 경로: orchestrator 직접 실행.
        """
        session = self._load_or_create_session(owner_id, request, session_id)
        turn = EvidenceTurn(session_id=session.session_id, request=request)
        ctx = AgentRunContext(
            session=session,
            current_turn=turn,
            owner_id=owner_id,
            request_id=request_id,
            budget_signal=budget_signal or {},
            prior_topics=_prior_topics(self._repo, owner_id, session),
            attachment_docs=attachment_docs,
        )

        if self._sqs_enqueue is not None:
            # 비동기 경로(BR-EV-6): pending 상태로 즉시 반환
            job_id = _new_id()
            turn.result = TurnPendingResult(job_id=job_id, started_at=_utc_now())
            turn.job_id = job_id
            self._repo.add_turn(turn)
            self._sqs_enqueue({
                'ownerId': owner_id,
                'sessionId': session.session_id,
                'turnId': turn.turn_id,
                'jobId': job_id,
                'topic': request.topic,
                'scope': (request.scope.value if request.scope else 'auto'),
                'paperIds': list(request.paperIds or []),
                'attachments': list(request.attachments or []),
                'attachmentDocs': _attachment_doc_payloads(attachment_docs),
            })
        else:
            # 동기 경로: async 분기와 달리 add_turn을 빠뜨려 저장된 턴이 0건이었다 —
            # 응답의 turnId를 이후 세션 이력(list_turns)에서 되찾을 수 없었다
            # (PR #338 리뷰 Blocking #1/FR-38).
            result = self._orchestrator.run(ctx, request)
            turn.result = result
            self._repo.add_turn(turn)

        self._repo.commit()
        return TurnResponse(
            session_id=session.session_id,
            turn_id=turn.turn_id,
            result=turn.result,
            created_at=turn.created_at,
        )

    def _load_or_create_session(
        self,
        owner_id: str,
        request: EvidenceRequest,
        session_id: str | None,
    ) -> EvidenceSession:
        if session_id:
            # INV-EV-1: 소유권 불일치 → KeyError → controller 404
            return self._repo.get_session(owner_id, session_id)

        title = _derive_title(request.topic)
        session = EvidenceSession(owner_id=owner_id, title=title)
        return self._repo.create_session(session)


# ---------------------------------------------------------------------------
# EvidenceSessionManagementService — 세션 CRUD (FR-38)
# ---------------------------------------------------------------------------

class EvidenceSessionManagementService:
    """세션 목록·삭제·초기화 — BR-EV-8~10, INV-EV-1."""

    def __init__(self, *, repo: EvidenceRepository) -> None:
        self._repo = repo

    def list_sessions(
        self, owner_id: str, limit: int = 50
    ) -> list[SessionSummary]:
        """BR-EV-10: 본인 active 세션만, updated_at DESC."""
        clamped = max(1, min(limit, _SESSION_LIST_MAX))
        sessions = self._repo.list_sessions(owner_id, clamped)
        return [
            SessionSummary(
                session_id=s.session_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in sessions
        ]

    def get_session(self, owner_id: str, session_id: str) -> EvidenceSession:
        """INV-EV-1: 소유권 불일치 → KeyError → controller 404(SEC-9)."""
        return self._repo.get_session(owner_id, session_id)

    def list_turns(self, owner_id: str, session_id: str) -> list[EvidenceTurn]:
        return self._repo.list_turns(owner_id, session_id)

    def delete_session(self, owner_id: str, session_id: str) -> None:
        """BR-EV-8: 소프트 삭제. INV-EV-1: 소유권 불일치 → KeyError → 404."""
        self._repo.soft_delete_session(owner_id, session_id)
        self._repo.commit()

    def reset_all(self, owner_id: str) -> None:
        """BR-EV-9: 해당 사용자 모든 세션 소프트 삭제."""
        self._repo.soft_delete_all_sessions(owner_id)
        self._repo.commit()


# ---------------------------------------------------------------------------
# EvidenceFormationService — EvidenceFormationPort 구현 (D5, U12 소비)
# ---------------------------------------------------------------------------

class EvidenceFormationService:
    """EvidenceFormationPort 구현체 — U12가 shared/ports 추상으로만 소비.

    U12는 이 클래스를 직접 import 금지. shared.ports.EvidenceFormationPort만 참조.
    순환 차단: U12 → shared/ports ← U11(구현). Trace: D5.
    """

    def __init__(self, *, orchestrator: EvidenceAgentOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def form_evidence(
        self,
        request: EvidenceRequest,
        ctx: Any,
    ) -> EvidenceResult | EvidenceAbstainResult:
        """EvidenceFormationPort 계약 구현.

        Orchestrator는 동기 — asyncio.to_thread로 호출해 이벤트 루프 차단 방지.
        Trace: D5, FR-37, SEC-9.
        """
        budget_signal = getattr(ctx, 'budget_signal', {}) or {}
        owner_id = getattr(ctx, 'owner_id', '')
        request_id = getattr(ctx, 'request_id', '')

        # 임시 세션·턴으로 AgentRunContext 구성 (U12 경로 — 세션 저장 없음)
        session = EvidenceSession(owner_id=owner_id)
        turn = EvidenceTurn(session_id=session.session_id, request=request)
        agent_ctx = AgentRunContext(
            session=session,
            current_turn=turn,
            owner_id=owner_id,
            request_id=request_id,
            budget_signal=budget_signal,
        )

        result = await asyncio.to_thread(self._orchestrator.run, agent_ctx, request)

        if isinstance(result, TurnSuccessResult):
            return result.outcome
        if isinstance(result, TurnAbstainResult):
            return result.outcome
        # TurnErrorResult → 기권으로 수렴(BR-EV-12 fail-closed)
        return EvidenceAbstainResult(state='abstain', abstainReason='llm_unavailable')


# ---------------------------------------------------------------------------
# 헬퍼
# ---------------------------------------------------------------------------

def _derive_title(topic: str) -> str:
    """첫 질문 topic에서 세션 제목 도출."""
    stripped = topic.strip()
    if len(stripped) <= _TITLE_MAX_LEN:
        return stripped
    return stripped[:_TITLE_MAX_LEN - 1] + '…'


def _prior_topics(
    repo: EvidenceRepository, owner_id: str, session: EvidenceSession
) -> tuple[str, ...]:
    """세션의 이전 턴 topic들 — 멀티턴 검색 맥락화(PR #338 리뷰 Blocking #2/FR-37).
    현재 턴은 아직 add_turn 전이라 list_turns에 없다. 새 세션·조회 실패는 ()."""
    try:
        prior = repo.list_turns(owner_id, session.session_id)
    except KeyError:
        return ()
    return tuple(
        t.request.topic for t in prior if t.request is not None and t.request.topic
    )


def _attachment_doc_payloads(attachment_docs: tuple[AttachmentInput, ...]) -> list[dict[str, Any]]:
    from .attachments import attachment_inputs_to_payloads

    return attachment_inputs_to_payloads(attachment_docs)
