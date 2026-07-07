from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
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
from .service import EvidenceChatService, TurnResponse


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


def get_orchestrator() -> Any:
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
ORCHESTRATOR_DEP = Depends(get_orchestrator)
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


class SourceRefOut(BaseModel):
    paper_id: str = Field(alias='paperId')
    record_ref: str = Field(alias='recordRef')
    anchor: str | None = None
    quote: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class EvidenceItemOut(BaseModel):
    statement: str
    supporting: list[SourceRefOut]
    conflicting: list[SourceRefOut]


class EvidenceCoverageOut(BaseModel):
    paper_count: int = Field(alias='paperCount')
    query_used: str | None = Field(None, alias='queryUsed')

    model_config = ConfigDict(populate_by_name=True)


class TurnResultOut(BaseModel):
    """INV-EV-5: 벡터 점수·청크 ID·LLM 내부 미노출."""
    state: Literal['ok', 'abstain', 'pending', 'error']
    claims: list[EvidenceItemOut] | None = None
    coverage: EvidenceCoverageOut | None = None
    abstain_reason: str | None = Field(None, alias='abstainReason')
    job_id: str | None = Field(None, alias='jobId')
    started_at: datetime | None = Field(None, alias='startedAt')
    error_code: str | None = Field(None, alias='errorCode')

    model_config = ConfigDict(populate_by_name=True)


class TurnOut(BaseModel):
    session_id: str = Field(alias='sessionId')
    turn_id: str = Field(alias='turnId')
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
    orchestrator: Any = ORCHESTRATOR_DEP,
    sqs_enqueue: Any = SQS_ENQUEUE_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> TurnOut:
    """채팅 턴 실행 — FR-36, FR-37, NFR-P6."""
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

    try:
        turn_resp: TurnResponse = EvidenceChatService(
            repo=repo,
            orchestrator=orchestrator,
            sqs_enqueue=sqs_enqueue,
        ).run_turn(
            owner_id=principal.user_id,
            request=ev_request,
            session_id=body.session_id,
            budget_signal=getattr(request.state, 'budget_signal', {}),
            request_id=request_id,
            attachment_docs=attachment_docs,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='session not found') from exc

    return TurnOut(
        sessionId=turn_resp.session_id,
        turnId=turn_resp.turn_id,
        result=_serialize_result(turn_resp.result),
        createdAt=turn_resp.created_at,
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

    return TurnOut(
        sessionId=turn.session_id,
        turnId=turn.turn_id,
        result=_serialize_result(turn.result),
        createdAt=turn.created_at,
    )


# ---------------------------------------------------------------------------
# 직렬화 헬퍼 — INV-EV-5: 내부 필드 비노출
# ---------------------------------------------------------------------------

def _serialize_result(result: Any) -> TurnResultOut:
    if isinstance(result, TurnSuccessResult):
        outcome = result.outcome
        return TurnResultOut(
            state='ok',
            claims=[
                EvidenceItemOut(
                    statement=item.statement,
                    supporting=[
                        SourceRefOut(
                            paperId=ref.paperId,
                            recordRef=ref.recordRef,
                            anchor=ref.anchor,
                            quote=ref.quote,
                        )
                        for ref in item.supporting
                    ],
                    conflicting=[
                        SourceRefOut(
                            paperId=ref.paperId,
                            recordRef=ref.recordRef,
                            anchor=ref.anchor,
                            quote=ref.quote,
                        )
                        for ref in item.conflicting
                    ],
                )
                for item in outcome.claims
            ],
            coverage=EvidenceCoverageOut(
                paperCount=outcome.coverage.paperCount,
                queryUsed=outcome.coverage.queryUsed,
            ),
        )

    if isinstance(result, TurnAbstainResult):
        return TurnResultOut(
            state='abstain',
            abstainReason=result.outcome.abstainReason,
        )

    if isinstance(result, TurnPendingResult):
        return TurnResultOut(
            state='pending',
            jobId=result.job_id,
            startedAt=result.started_at,
        )

    if isinstance(result, TurnErrorResult):
        return TurnResultOut(
            state='error',
            errorCode=result.error_code,
        )

    return TurnResultOut(state='pending')


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
