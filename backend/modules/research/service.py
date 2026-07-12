from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.concurrency import run_in_threadpool

from backend.modules.user_docmodel import EVIDENCE_PDF_DEGRADED_NOTICE

from .models import (
    ChatRole,
    ResearchChatMessage,
    ResearchJob,
    ResearchJobCreateRequest,
    ResearchJobCreateResponse,
    ResearchJobDetailResponse,
    ResearchJobListResponse,
    ResearchJobState,
    ResearchJobSummary,
    ResearchMessageCreateRequest,
    ResearchMessageListResponse,
    title_from_content,
)
from .repository import ResearchRepository


class ResearchService:
    def __init__(self, repo: ResearchRepository) -> None:
        self._repo = repo

    async def create_job(
        self,
        owner_id: str,
        dto: ResearchJobCreateRequest,
        orchestrator: Any = None,
        user_docmodel: Any = None,
    ) -> ResearchJobCreateResponse:
        job = self._repo.create_job(
            ResearchJob(ownerId=owner_id, title=title_from_content(dto.content))
        )
        await self.add_message(owner_id, job.jobId, dto, orchestrator, user_docmodel)
        # add_message가 처리 완료 후 항상 COMPLETED로 전이시키므로(PR #338 Blocking #3)
        # 응답도 그 최종 상태를 반영해야 한다 — job은 create_job 호출 시점의 스냅샷이라
        # 그대로 두면 항상 ACTIVE로 보고된다.
        return ResearchJobCreateResponse(jobId=job.jobId, state=ResearchJobState.COMPLETED)

    def list_jobs(self, owner_id: str, limit: int = 50) -> ResearchJobListResponse:
        jobs = self._repo.list_jobs(owner_id, max(1, min(limit, 100)))
        return ResearchJobListResponse(
            jobs=[
                ResearchJobSummary(
                    jobId=job.jobId,
                    title=job.title,
                    state=job.state,
                    createdAt=job.createdAt,
                    updatedAt=job.updatedAt,
                )
                for job in jobs
            ]
        )

    def detail(self, owner_id: str, job_id: str) -> ResearchJobDetailResponse:
        return ResearchJobDetailResponse(
            job=self._repo.get_job(owner_id, job_id),
            messages=self._repo.list_messages(owner_id, job_id),
        )

    def delete_job(self, owner_id: str, job_id: str) -> None:
        self._repo.delete_job(owner_id, job_id)

    def delete_all_jobs(self, owner_id: str) -> None:
        self._repo.delete_all_jobs(owner_id)

    async def add_message(
        self,
        owner_id: str,
        job_id: str,
        dto: ResearchMessageCreateRequest,
        orchestrator: Any = None,
        user_docmodel: Any = None,
        on_progress: Any = None,
    ) -> ResearchChatMessage:
        self._repo.get_job(owner_id, job_id)
        history = self._repo.list_messages(owner_id, job_id)
        # 멀티턴 맥락(PR #338 리뷰 Blocking #2/FR-37): 현재 메시지 추가 전 이전 사용자 질문들.
        prior_topics = tuple(
            m.content for m in history if m.role == ChatRole.USER and m.content
        )
        # 꼬리질문 좁히기용 — 가장 최근에 성공한(resolvedPaperIds가 있는) assistant 메시지의
        # 논문 집합. "그 중에서" 류 후속 질문일 때만 orchestrator가 이 집합으로 재검색한다.
        prior_paper_ids: tuple[str, ...] = ()
        for m in reversed(history):
            if m.role == ChatRole.ASSISTANT and m.resolvedPaperIds:
                prior_paper_ids = tuple(m.resolvedPaperIds)
                break
        user_msg = self._repo.add_message(
            ResearchChatMessage(
                jobId=job_id,
                ownerId=owner_id,
                role=ChatRole.USER,
                content=dto.content,
                attachments=dto.attachments,
            )
        )
        if orchestrator is None:
            self._repo.mark_completed(owner_id, job_id)
            return user_msg
        attachment_inputs = await run_in_threadpool(
            _attachment_inputs,
            owner_id,
            job_id,
            dto.attachments,
            user_docmodel,
        )
        result = await _run_evidence(
            orchestrator,
            owner_id,
            dto.content,
            prior_topics,
            attachment_inputs,
            prior_paper_ids,
            on_progress,
        )
        content = _format_turn_result(result)
        assistant_msg = self._repo.add_message(
            ResearchChatMessage(
                jobId=job_id,
                ownerId=owner_id,
                role=ChatRole.ASSISTANT,
                content=content,
                attachments=[],
                resolvedPaperIds=list(_resolved_paper_ids(result)),
            )
        )
        # US-EV4(#268) 2차 — 본문 없이 도착한 첨부(PDF 등)는 비기술 문구로 별도 안내.
        # 성공 결과 content는 FE가 JSON으로 파싱하므로(카드 렌더링, #339) 덧붙이지 않는다.
        notice = _attachment_notice(attachment_inputs)
        if notice:
            self._repo.add_message(
                ResearchChatMessage(
                    jobId=job_id,
                    ownerId=owner_id,
                    role=ChatRole.ASSISTANT,
                    content=notice,
                    attachments=[],
                )
            )
        # 이 요청이 반환되는 시점에는 이미 모든 처리(evidence 추출 포함)가 끝난
        # 상태다 — job.state를 ACTIVE로 남겨두면 FE가 running으로 매핑해 답변이
        # 저장된 뒤에도 폴링을 멈추지 않는다(PR #338 리뷰 Blocking #3).
        self._repo.mark_completed(owner_id, job_id)
        return assistant_msg

    def list_messages(self, owner_id: str, job_id: str) -> ResearchMessageListResponse:
        return ResearchMessageListResponse(messages=self._repo.list_messages(owner_id, job_id))


async def _run_evidence(
    orchestrator: Any,
    owner_id: str,
    topic: str,
    prior_topics: tuple[str, ...] = (),
    attachment_inputs: tuple[Any, ...] = (),
    prior_paper_ids: tuple[str, ...] = (),
    on_progress: Any = None,
) -> Any:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest, EvidenceScope
    from pydantic import ValidationError

    from backend.modules.evidence.models import AgentRunContext, EvidenceSession, EvidenceTurn

    try:
        # research content 한도(12000) > evidence topic 한도(2000)라, 긴 메시지가 여기서
        # EvidenceRequest Pydantic 검증에 걸려 HTTP 500이 나던 걸 degrade로 막는다
        # (PR #338 리뷰 Blocking #3/SEC-5). controller 경로는 경계(2000)에서 422로 처리.
        request = EvidenceRequest(topic=topic, scope=EvidenceScope.auto, paperIds=[])
    except ValidationError:
        return None
    session = EvidenceSession(owner_id=owner_id)
    turn = EvidenceTurn(session_id=session.session_id, request=request)
    ctx = AgentRunContext(
        session=session,
        current_turn=turn,
        owner_id=owner_id,
        request_id='',
        budget_signal={'state': 'ok'},
        prior_topics=prior_topics,
        attachment_docs=attachment_inputs,
        prior_paper_ids=prior_paper_ids,
    )
    if on_progress is None:
        # 2-인자 호출 유지 — on_progress를 모르는 기존 테스트 스텁/구버전 orchestrator 호환.
        return await asyncio.to_thread(orchestrator.run, ctx, request)
    return await asyncio.to_thread(orchestrator.run, ctx, request, on_progress)


def _resolved_paper_ids(result: Any) -> tuple[str, ...]:
    from backend.modules.evidence.models import TurnSuccessResult

    if isinstance(result, TurnSuccessResult):
        return result.resolved_paper_ids
    return ()


def _format_turn_result(result: Any) -> str:
    from backend.modules.evidence.models import TurnAbstainResult, TurnSuccessResult

    if isinstance(result, TurnSuccessResult):
        return json.dumps(result.outcome.model_dump(), ensure_ascii=False)
    if isinstance(result, TurnAbstainResult):
        return f'[abstain] {result.outcome.abstainReason}'
    return '[error] evidence_unavailable'


def _attachment_inputs(
    owner_id: str,
    job_id: str,
    attachments: list[dict[str, Any]],
    user_docmodel: Any = None,
) -> tuple[Any, ...]:
    """검증된 첨부 dict → orchestrator 입력(US-EV4 #268 2차)."""
    from backend.modules.evidence.attachments import attachment_inputs_from_dicts

    return attachment_inputs_from_dicts(
        owner_id=owner_id,
        scope_id=job_id,
        attachments=attachments,
        user_docmodel=user_docmodel,
    )


def _attachment_notice(attachment_inputs: tuple[Any, ...]) -> str:
    """PDF DocModel이 준비되지 않은 첨부를 계약 문구로 알린다(SEC-5 — 내부 상세 미노출)."""
    from backend.modules.evidence.attachments import unresolved_pdf_names

    if not unresolved_pdf_names(attachment_inputs):
        return ''
    return EVIDENCE_PDF_DEGRADED_NOTICE
