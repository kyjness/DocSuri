from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceCoverage,
    EvidenceItem,
)
from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.agent_attachments import ATTACHMENT_MAX_COUNT, AgentAttachmentIn
from backend.middleware.agent_quota import enforce_evidence_turn_quota
from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    build_default_user_docmodel_coordinator,
    object_key_for_upload,
    user_docmodel_ref,
)

from .models import (
    TurnAbstainResult,
    TurnErrorResult,
    TurnPendingResult,
    TurnSuccessResult,
)
from .repository import EvidenceRepository
from .service import EvidenceChatService, EvidenceSessionManagementService, TurnResponse
from .streaming import progress_event, turn_sse_stream, wants_event_stream


def _feature_enabled() -> None:
    if os.getenv('EVIDENCE_AGENT_ENABLED', 'true').lower() not in {'1', 'true', 'yes', 'on'}:
        raise HTTPException(status_code=404, detail='not found')


router = APIRouter(
    prefix='/api/evidence',
    tags=['Evidence'],
    dependencies=[Depends(_feature_enabled)],
)


def get_repo() -> EvidenceRepository:
    raise RuntimeError('evidence repository is not wired')


def get_runner() -> Any:
    raise RuntimeError('evidence orchestrator is not wired')


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(status_code=401, detail='authentication required')
    return principal


def get_sqs_enqueue(request: Request):
    return getattr(request.app.state, 'evidence_sqs_enqueue', None)


def get_user_docmodel(request: Request):
    coordinator = getattr(request.app.state, 'user_docmodel', None)
    if coordinator is None:
        coordinator = build_default_user_docmodel_coordinator()
        request.app.state.user_docmodel = coordinator
    return coordinator


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)
RUNNER_DEP = Depends(get_runner)
SQS_ENQUEUE_DEP = Depends(get_sqs_enqueue)
USER_DOCMODEL_DEP = Depends(get_user_docmodel)


# ---------------------------------------------------------------------------
# 요청/응답 스키마
# ---------------------------------------------------------------------------

class TurnCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    topic: str = Field(..., min_length=1, max_length=2000)
    scope: Literal['auto', 'explicit', 'mixed'] | None = Field(
        None, description='auto | explicit | mixed'
    )
    paper_ids: list[str] | None = Field(None, alias='paperIds')
    session_id: str | None = Field(None, alias='sessionId')
    # US-AG5(#297)/US-EV4(#268) — 형식·크기를 요청 파싱 단계에서 검증(422). 종전
    # list[Any]는 아래 EvidenceRequest(list[str]) 생성에서 ValidationError → 500이었다.
    attachments: list[AgentAttachmentIn] = Field(
        default_factory=list, max_length=ATTACHMENT_MAX_COUNT
    )


class TurnResultOut(BaseModel):
    """턴 결과 봉투 — claims/coverage는 **생성 계약 모델을 그대로 싣는다**.

    D5 스키마가 SSOT이고 CI 드리프트 가드가 지킨다. 손 미러 DTO를 두면 스키마
    추가가 4곳 편집(스키마→바인딩→미러→직렬화)이 되고, 하나를 빠뜨리면 필드가
    조용히 떨어진다 — 실제로 v2 필드 4종이 그렇게 떨어졌었다. INV-EV-5(점수·청크
    비노출)는 게이트·조립이 이미 강제한다: 계약 모델에는 그 필드 자체가 없다.
    """

    state: Literal['ok', 'abstain', 'pending', 'error']
    claims: list[EvidenceItem] | None = None
    coverage: EvidenceCoverage | None = None
    answer: str | None = None
    abstain_reason: str | None = Field(None, alias='abstainReason')
    job_id: str | None = Field(None, alias='jobId')
    started_at: datetime | None = Field(None, alias='startedAt')
    error_code: str | None = Field(None, alias='errorCode')

    model_config = ConfigDict(populate_by_name=True)


class TurnOut(BaseModel):
    session_id: str = Field(alias='sessionId')
    turn_id: str = Field(alias='turnId')
    # 세션 상세에서 사용자 메시지를 복원할 원문 질문 — 없으면 화면이 답변만 나열하게 된다.
    topic: str = ''
    result: TurnResultOut
    created_at: datetime = Field(alias='createdAt')

    model_config = ConfigDict(populate_by_name=True)


class AttachmentUploadOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: Literal['pdf'] = 'pdf'
    size_bytes: int = Field(alias='sizeBytes')
    status: Literal['ready'] = 'ready'
    object_key: str = Field(alias='objectKey')
    paper_id: str = Field(alias='paperId')
    record_ref: str = Field(alias='recordRef')


# ---------------------------------------------------------------------------
# 엔드포인트
# ---------------------------------------------------------------------------

@router.post(
    '/turns',
    response_model=TurnOut,
    # NFR-C1: research 경로와 동일 키(agent:evidence:{user})로 일일 쿼터 공유.
    dependencies=[Depends(enforce_evidence_turn_quota)],
)
async def create_turn(
    body: TurnCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
    runner: Any = RUNNER_DEP,
    sqs_enqueue: Any = SQS_ENQUEUE_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> Any:
    """채팅 턴 실행 — FR-36, FR-37, NFR-P6.

    Accept: text/event-stream + 동기 경로 → SSE 스트리밍(US-EV2). 그 외 JSON(TurnOut).
    """
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest, EvidenceScope

    request_id = request.headers.get('x-request-id', '')
    ev_request = EvidenceRequest(
        topic=body.topic,
        scope=body.scope or EvidenceScope.auto,
        paperIds=body.paper_ids or [],
        # 공유 계약(EvidenceRequest.attachments)은 문서 핸들 문자열 목록 — 객체를 id로 변환.
        attachments=[attachment.id for attachment in body.attachments],
    )
    try:
        attachment_docs = await run_in_threadpool(
            _attachment_docs,
            owner_id=principal.user_id,
            scope_id=request_id or 'evidence-turn',
            attachments=body.attachments,
            user_docmodel=user_docmodel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='첨부 PDF 정보가 올바르지 않습니다.') from exc

    service = EvidenceChatService(
        repo=repo,
        runner=runner,
        sqs_enqueue=sqs_enqueue,
    )
    budget_signal = getattr(request.state, 'budget_signal', {})

    # US-EV2/NFR-P6 — 동기 경로는 Accept: text/event-stream 협상 시 SSE 스트리밍으로
    # 완료한다(nfr-design §2.1/§2.2). 비동기 적격(sqs_enqueue 주입) 턴은 SSE 표면에서도
    # 기존 pending/jobId JSON 동작을 그대로 유지한다(BR-EV-6 분기 불변).
    if sqs_enqueue is None and wants_event_stream(request.headers.get('accept')):
        if body.session_id:
            # INV-EV-1: 스트림 시작 전에 소유권을 검증해 404가 HTTP 에러로 남게 한다.
            try:
                repo.get_session(principal.user_id, body.session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail='session not found') from exc

        async def _run_turn(emit):
            return await asyncio.to_thread(
                lambda: service.run_turn(
                    owner_id=principal.user_id,
                    request=ev_request,
                    session_id=body.session_id,
                    budget_signal=budget_signal,
                    request_id=request_id,
                    attachment_docs=attachment_docs,
                    on_progress=emit,
                )
            )

        def _terminal(turn_resp: TurnResponse) -> dict:
            return _turn_out(
                session_id=turn_resp.session_id,
                turn_id=turn_resp.turn_id,
                topic=body.topic,
                result=turn_resp.result,
                created_at=turn_resp.created_at,
            ).model_dump(mode='json', by_alias=True)

        started_payload = {'sessionId': body.session_id} if body.session_id else {}
        initial = [progress_event('started', started_payload)]
        return StreamingResponse(
            turn_sse_stream(
                _run_turn,
                _terminal,
                initial_events=initial,
                observability=getattr(request.app.state, 'observability', None),
                surface='evidence_turns',
            ),
            media_type='text/event-stream',
            headers={'cache-control': 'no-store'},
        )

    try:
        # 루프는 동기다(urllib LLM 호출 + 승격 폴링 sleep). 이벤트 루프에서 직접
        # 돌리면 턴 하나가 앱 전체(검색·요약·헬스체크)를 분 단위로 멈춘다 — SSE
        # 분기가 to_thread를 쓰는 것과 같은 이유로 여기도 스레드풀로 내린다.
        turn_resp: TurnResponse = await run_in_threadpool(
            lambda: service.run_turn(
                owner_id=principal.user_id,
                request=ev_request,
                session_id=body.session_id,
                budget_signal=budget_signal,
                request_id=request_id,
                attachment_docs=attachment_docs,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='session not found') from exc

    return _turn_out(
        session_id=turn_resp.session_id,
        turn_id=turn_resp.turn_id,
        topic=body.topic,
        result=turn_resp.result,
        created_at=turn_resp.created_at,
    )


@router.post('/attachments', response_model=AttachmentUploadOut)
async def upload_attachment(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> AttachmentUploadOut:
    """PR2 — backend PDF upload for evidence attachments."""
    if user_docmodel is None:
        raise HTTPException(status_code=422, detail='PDF 업로드 저장소가 구성되지 않았습니다.')
    file_name = request.query_params.get('fileName') or 'attachment.pdf'
    attachment_id = request.query_params.get('id') or f'att-{uuid4()}'
    content_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
    if content_type != USER_DOCMODEL_PDF_CONTENT_TYPE:
        raise HTTPException(status_code=415, detail='PDF 파일만 업로드할 수 있습니다.')
    data = await request.body()
    object_key = object_key_for_upload(
        module='evidence',
        owner_id=principal.user_id,
        scope_id=attachment_id,
        attachment_id=attachment_id,
        file_name=file_name,
    )
    ref = user_docmodel_ref(
        owner_id=principal.user_id,
        scope_id=attachment_id,
        attachment_id=attachment_id,
        object_key=object_key,
        module='evidence',
    )
    try:
        user_docmodel.upload_pdf(ref, data, file_name=file_name, content_type=content_type)
        user_docmodel.enqueue_build(ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - hide storage internals at the API boundary.
        raise HTTPException(status_code=422, detail='PDF 업로드에 실패했습니다.') from exc
    return AttachmentUploadOut(
        id=attachment_id,
        name=file_name,
        sizeBytes=len(data),
        objectKey=object_key,
        paperId=ref.paper_id,
        recordRef=ref.record_ref,
    )


class SessionOut(BaseModel):
    """세션 목록·상세 항목 — FR-38 재열람 표면."""

    id: str
    title: str | None = None
    createdAt: datetime
    updatedAt: datetime


class SessionDetailOut(SessionOut):
    turns: list[TurnOut] = []


class TraceItemOut(BaseModel):
    """활동 피드 1건(FR-46 파생). 내부 payload·자격증명은 담기지 않는다(INV-EV-5)."""

    seq: int
    tool: str
    argsSummary: str = ''
    outcome: str
    resultSummary: str = ''
    costUsd: float | None = None
    at: str | None = None


@router.get('/sessions', response_model=list[SessionOut])
async def list_sessions(
    limit: int = 20,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> Any:
    """BR-EV-10 — 본인 active 세션만, updated_at DESC."""
    service = EvidenceSessionManagementService(repo=repo)
    return [
        SessionOut(
            id=summary.session_id,
            title=summary.title,
            createdAt=summary.created_at,
            updatedAt=summary.updated_at,
        )
        for summary in service.list_sessions(principal.user_id, limit)
    ]


@router.get('/sessions/{session_id}', response_model=SessionDetailOut)
async def get_session(
    session_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> Any:
    try:
        session = repo.get_session(principal.user_id, session_id)
        turns = repo.list_turns(principal.user_id, session_id)
    except KeyError as exc:
        # INV-EV-1: 타인 세션은 존재 여부도 노출하지 않는다(SEC-9).
        raise HTTPException(status_code=404, detail='session not found') from exc
    return SessionDetailOut(
        id=session.session_id,
        title=session.title,
        createdAt=session.created_at,
        updatedAt=session.updated_at,
        turns=[
            _turn_out(
                session_id=turn.session_id,
                turn_id=turn.turn_id,
                topic=turn.topic,
                result=turn.result,
                created_at=turn.created_at,
            )
            for turn in turns
        ],
    )


@router.get('/turns/{turn_id}/trace', response_model=list[TraceItemOut])
async def get_turn_trace(
    turn_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> Any:
    """활동 피드 복원 — 재접속·비동기 잡은 저장된 트레이스를 읽는다(FD 게이트 Q7=A)."""
    return [TraceItemOut(**row) for row in repo.list_trace(principal.user_id, turn_id)]


@router.delete(
    '/sessions/{session_id}', status_code=204, response_class=Response, response_model=None
)
async def delete_session(
    session_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> Response:
    service = EvidenceSessionManagementService(repo=repo)
    try:
        # commit은 서비스가 소유한다 — 여기서 또 커밋하면 소유가 둘이 된다.
        service.delete_session(principal.user_id, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='session not found') from exc
    return Response(status_code=204)


@router.delete(
    '/sessions', status_code=204, response_class=Response, response_model=None
)
async def reset_sessions(
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> Response:
    """BR-EV-9 — 본인 세션만 초기화(멱등)."""
    EvidenceSessionManagementService(repo=repo).reset_all(principal.user_id)
    return Response(status_code=204)


@router.get('/jobs/{job_id}', response_model=TurnOut)
async def get_job(
    job_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
) -> TurnOut:
    """비동기 잡 폴링 — BR-EV-6, NFR-P6."""
    try:
        turn = repo.get_turn_by_job_id(principal.user_id, job_id)
    except (KeyError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail='job not found') from exc

    return _turn_out(
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        topic=turn.topic,
        result=turn.result,
        created_at=turn.created_at,
    )


# ---------------------------------------------------------------------------
# 직렬화 헬퍼 — INV-EV-5: 내부 필드 비노출
# ---------------------------------------------------------------------------

def _turn_out(
    *, session_id: str, turn_id: str, topic: str, result: Any, created_at: datetime
) -> TurnOut:
    """턴 응답 조립 — 직렬화 규칙이 네 표면(SSE 터미널·동기 응답·상세·잡 폴링)에서
    갈라지지 않도록 한 곳에 둔다."""
    return TurnOut(
        sessionId=session_id,
        turnId=turn_id,
        topic=topic,
        result=_serialize_result(result),
        createdAt=created_at,
    )


def _serialize_result(result: Any) -> TurnResultOut:
    if isinstance(result, TurnSuccessResult):
        outcome = result.outcome
        return TurnResultOut(
            state='ok',
            claims=list(outcome.claims),
            coverage=outcome.coverage,
            answer=outcome.answer,
        )
    if isinstance(result, TurnAbstainResult):
        return TurnResultOut(state='abstain', abstainReason=result.outcome.abstainReason)
    if isinstance(result, TurnPendingResult):
        return TurnResultOut(state='pending', jobId=result.job_id, startedAt=result.started_at)
    if isinstance(result, TurnErrorResult):
        return TurnResultOut(state='error', errorCode=result.error_code)
    return TurnResultOut(state='error', errorCode='unknown')


def _attachment_docs(
    *,
    owner_id: str,
    scope_id: str,
    attachments: list[AgentAttachmentIn],
    user_docmodel: Any,
):
    from .attachments import attachment_inputs_from_dicts

    return attachment_inputs_from_dicts(
        owner_id=owner_id,
        scope_id=scope_id,
        attachments=[item.model_dump(mode='json', by_alias=True) for item in attachments],
        user_docmodel=user_docmodel,
    )


routers = (router,)

