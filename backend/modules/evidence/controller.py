from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAnswer,
    EvidenceCoverage,
    EvidenceItem,
)
from docsuri_shared.authz import Principal
from docsuri_shared.observability import emit_metric
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.agent_attachments import ATTACHMENT_MAX_COUNT, AgentAttachmentIn
from backend.middleware.agent_quota import (
    enforce_evidence_turn_quota,
    refund_evidence_turn_quota,
)
from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    build_default_user_docmodel_coordinator,
    object_key_for_upload,
    user_docmodel_ref,
)

from .checkpoints import TurnCheckpoints
from .models import (
    TurnAbstainResult,
    TurnErrorResult,
    TurnPendingResult,
    TurnSuccessResult,
)
from .repository import EvidenceRepository, SessionBusy, in_transaction
from .service import (
    DispatchFailed,
    EvidenceChatService,
    EvidenceSessionManagementService,
    TurnResponse,
)
from .settings import TurnExecutionSettings
from .streaming import turn_events_stream


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


def get_checkpoints() -> TurnCheckpoints | None:
    """턴 체크포인트 — 없으면 None(고아 마감을 못 할 뿐, 라우트는 산다).

    러너를 받던 자리다. 러너는 미구성 배포에서 raise하므로, 스레드 하나 지우려던 세션 삭제까지
    500이 됐다.
    """
    return None


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, 'principal', None)
    if principal is None:
        raise HTTPException(status_code=401, detail='authentication required')
    return principal


def get_dispatch(request: Request):
    """턴 실행자에게 넘기는 함수 — SQS enqueue거나 프로세스 내 실행자(wiring이 정한다).

    여기서 raise하지 않는다 — 의존성 단계의 503은 그 앞에서 이미 증가한 쿼터를 되돌릴 길이
    없다. 핸들러가 None을 보고 503 + 환불한다.
    """
    return getattr(request.app.state, 'evidence_dispatch', None)


def get_repo_factory(request: Request):
    """스트림이 폴링마다 여는 짧은 세션의 공장 — 요청 스코프 repo를 스트림 내내 쥐지 않는다."""
    factory = getattr(request.app.state, 'evidence_repo_factory', None)
    if factory is None:
        raise HTTPException(status_code=503, detail='evidence repository is not configured')
    return factory


def get_execution_settings(request: Request) -> TurnExecutionSettings:
    settings = getattr(request.app.state, 'evidence_execution', None)
    return settings if settings is not None else TurnExecutionSettings.defaults()


def get_user_docmodel(request: Request):
    coordinator = getattr(request.app.state, 'user_docmodel', None)
    if coordinator is None:
        coordinator = build_default_user_docmodel_coordinator()
        request.app.state.user_docmodel = coordinator
    return coordinator


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)
CHECKPOINTS_DEP = Depends(get_checkpoints)
DISPATCH_DEP = Depends(get_dispatch)
REPO_FACTORY_DEP = Depends(get_repo_factory)
EXECUTION_DEP = Depends(get_execution_settings)
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
    answer: EvidenceAnswer | None = None
    abstain_reason: str | None = Field(None, alias='abstainReason')
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


class CancelTurnOut(BaseModel):
    turn_id: str = Field(alias='turnId')
    state: Literal['ok', 'abstain', 'pending', 'error']
    cancel_requested: bool = Field(alias='cancelRequested')

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
    status_code=202,
    # NFR-C1: research 경로와 동일 키(agent:evidence:{user})로 일일 쿼터 공유.
    dependencies=[Depends(enforce_evidence_turn_quota)],
)
async def create_turn(
    body: TurnCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
    dispatch: Any = DISPATCH_DEP,
    execution: TurnExecutionSettings = EXECUTION_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> Any:
    """턴 수락 — FR-36, FR-37, v3 §5.1. 실행은 항상 백그라운드다.

    202 + pending 턴을 돌려주고, 진행은 `GET /turns/{id}/events`, 결과는 같은 스트림의
    `result` 프레임 또는 `GET /turns/{id}`로 본다. 같은 세션에 진행 중 턴이 있으면 409.
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
        # 첨부 해석은 수락 앞에 있다(PDF 빌드 대기 포함) — 실행자로 옮기는 것은 별건.
        attachment_docs = await run_in_threadpool(
            _attachment_docs,
            owner_id=principal.user_id,
            scope_id=request_id or 'evidence-turn',
            attachments=body.attachments,
            user_docmodel=user_docmodel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='첨부 PDF 정보가 올바르지 않습니다.') from exc

    if dispatch is None:
        # 실행자 미구성(repo-only). 쿼터는 "실행할 권리"라 되돌린다.
        await refund_evidence_turn_quota(request)
        raise HTTPException(status_code=503, detail='지금은 질문을 받을 수 없습니다.')
    service = _chat_service(repo, checkpoints, execution, dispatch=dispatch)
    try:
        turn_resp: TurnResponse = await run_in_threadpool(
            lambda: service.accept_turn(
                owner_id=principal.user_id,
                request=ev_request,
                session_id=body.session_id,
                request_id=request_id,
                attachment_docs=attachment_docs,
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='session not found') from exc
    except SessionBusy as exc:
        # 쿼터는 "실행할 권리"다 — 수락되지 않은 턴은 세지 않는다.
        await refund_evidence_turn_quota(request)
        raise HTTPException(
            status_code=409, detail='이 대화에서 아직 진행 중인 질문이 있습니다.'
        ) from exc
    except DispatchFailed as exc:
        await refund_evidence_turn_quota(request)
        raise HTTPException(
            status_code=503, detail='지금은 질문을 받을 수 없습니다. 잠시 후 다시 시도해 주세요.'
        ) from exc

    return _turn_out(
        session_id=turn_resp.session_id,
        turn_id=turn_resp.turn_id,
        topic=body.topic,
        result=turn_resp.result,
        created_at=turn_resp.created_at,
    )


@router.get('/turns/{turn_id}', response_model=TurnOut)
async def get_turn(
    turn_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
    execution: TurnExecutionSettings = EXECUTION_DEP,
) -> TurnOut:
    """폴링 폴백(§5.1) — 스트림이 끊겼을 때의 복구 좌표. 실행자가 죽은 턴은 여기서 마감된다."""
    service = _chat_service(repo, checkpoints, execution)
    try:
        turn = await run_in_threadpool(service.get_turn, principal.user_id, turn_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='turn not found') from exc
    return _turn_out(
        session_id=turn.session_id,
        turn_id=turn.turn_id,
        topic=turn.topic,
        result=turn.result,
        created_at=turn.created_at,
    )


@router.get('/turns/{turn_id}/events')
async def turn_events(
    turn_id: str,
    request: Request,
    after: int = 0,
    principal: Principal = PRINCIPAL_DEP,
    repo_factory: Any = REPO_FACTORY_DEP,
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
    execution: TurnExecutionSettings = EXECUTION_DEP,
) -> Any:
    """진행 이벤트 SSE(§5.3) — 트레이스 행을 tail한다. `after`는 마지막으로 받은 seq."""
    owner_id = principal.user_id

    # 스트림이 열리기 **전에** 404를 HTTP 오류로 낸다 — 제너레이터 안에서 나면 SSE error
    # 프레임이 되어 클라이언트가 "없는 턴"과 "일시 오류"를 구분하지 못한다.
    try:
        turn = await run_in_threadpool(
            in_transaction, repo_factory, lambda repo: repo.get_turn(owner_id, turn_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='turn not found') from exc

    def _poll_once(repo: EvidenceRepository):
        # 상태를 **먼저** 읽는다. 실행자는 트레이스를 결과보다 먼저 커밋하므로, 종단을 본 뒤
        # 읽은 행 목록은 완결이다. 반대로 하면 두 문장 사이에 커밋된 마지막 행이 result 프레임
        # 뒤로 밀려 영영 흐르지 않는다.
        current = _chat_service(repo, checkpoints, execution).get_turn(owner_id, turn_id)
        # 종단 여부는 행을 읽기 **전**에 확정한다 — 객체를 공유하는 저장소(인메모리)에서는
        # 나중에 보면 실행자가 그 사이 바꾼 값이 보인다.
        pending = isinstance(current.result, TurnPendingResult)
        rows = repo.list_trace_after(owner_id, turn_id, after_seq=after_seq_holder[0])
        return rows, current, pending

    after_seq_holder = [max(after, 0)]

    def poll(after_seq: int):
        after_seq_holder[0] = after_seq
        rows, current, pending = in_transaction(repo_factory, _poll_once)
        terminal = None
        if not pending:
            terminal = _turn_out(
                session_id=current.session_id,
                turn_id=current.turn_id,
                topic=current.topic,
                result=current.result,
                created_at=current.created_at,
            ).model_dump(mode='json', by_alias=True)
        return rows, terminal

    return StreamingResponse(
        turn_events_stream(
            poll,
            turn_id=turn_id,
            session_id=turn.session_id,
            after_seq=max(after, 0),
            poll_seconds=execution.poll_seconds,
            observability=getattr(request.app.state, 'observability', None),
        ),
        media_type='text/event-stream',
        headers={'cache-control': 'no-store'},
    )


@router.post('/turns/{turn_id}/cancel', response_model=CancelTurnOut)
async def cancel_turn(
    turn_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
    execution: TurnExecutionSettings = EXECUTION_DEP,
) -> CancelTurnOut:
    """협조적 취소(§5.2) — 플래그만 세운다. 실행자가 super-step 경계에서 읽고 부분 답을 만든다."""
    service = _chat_service(repo, checkpoints, execution)
    try:
        turn = await run_in_threadpool(service.get_turn, principal.user_id, turn_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail='turn not found') from exc
    if not isinstance(turn.result, TurnPendingResult):
        raise HTTPException(status_code=409, detail='이미 끝난 질문입니다.')
    accepted = await run_in_threadpool(service.request_cancel, principal.user_id, turn_id)
    if not accepted:
        # get_turn과 UPDATE 사이에 끝났다 — 취소된 것처럼 답하면 화면이 "취소 중…"에 갇힌다.
        raise HTTPException(status_code=409, detail='이미 끝난 질문입니다.')
    emit_metric(
        getattr(request.app.state, 'observability', None),
        'evidence.turn_cancelled',
        1.0,
        {'surface': 'evidence_turns'},
    )
    return CancelTurnOut(turnId=turn_id, state='pending', cancelRequested=True)


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
    rows = repo.list_trace_after(principal.user_id, turn_id, after_seq=0)
    return [TraceItemOut(**row) for row in rows]


@router.delete(
    '/sessions/{session_id}', status_code=204, response_class=Response, response_model=None
)
async def delete_session(
    session_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: EvidenceRepository = REPO_DEP,
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
) -> Response:
    service = EvidenceSessionManagementService(repo=repo, checkpoints=checkpoints)
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
    checkpoints: TurnCheckpoints | None = CHECKPOINTS_DEP,
) -> Response:
    """BR-EV-9 — 본인 세션만 초기화(멱등)."""
    EvidenceSessionManagementService(repo=repo, checkpoints=checkpoints).reset_all(
        principal.user_id
    )
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 직렬화 헬퍼 — INV-EV-5: 내부 필드 비노출
# ---------------------------------------------------------------------------

def _chat_service(
    repo: EvidenceRepository,
    checkpoints: TurnCheckpoints | None,
    execution: TurnExecutionSettings,
    *,
    dispatch: Any = None,
) -> EvidenceChatService:
    return EvidenceChatService(
        repo=repo,
        dispatch=dispatch,
        checkpoints=checkpoints,
        stale_after=execution.stale_after,
    )


def _turn_out(
    *,
    session_id: str,
    turn_id: str,
    topic: str,
    result: Any,
    created_at: datetime,
) -> TurnOut:
    """턴 응답 조립 — 직렬화 규칙이 네 표면(수락·폴링·스트림 터미널·세션 상세)에서
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
        return TurnResultOut(state='pending', startedAt=result.started_at)
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

