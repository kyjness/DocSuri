from __future__ import annotations

import json
import os

from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from backend.middleware.agent_quota import enforce_novelty_job_quota
from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    build_default_user_docmodel_coordinator,
)

from .adapters import NoveltyAdapters
from .models import (
    CancelJobResponse,
    ChatMessageCreateRequest,
    ChatMessageListResponse,
    CreateJobResponse,
    ExportApprovalError,
    ExportApprovalRequest,
    ExportPreviewResponse,
    InvalidTransitionError,
    JobResultResponse,
    JobState,
    JobStatusResponse,
    ManuscriptContentRequest,
    NotionConnectionRequest,
    NotionConnectionStatusResponse,
    NoveltyChatMessage,
    NoveltyJobListResponse,
    NoveltyJobRequest,
)
from .repository import NoveltyRepository
from .service import NoveltyService
from .streaming import sse_snapshot


def _feature_enabled() -> None:
    if os.getenv("NOVELTY_AGENT_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(
    prefix="/api/novelty",
    tags=["Novelty"],
    dependencies=[Depends(_feature_enabled)],
)


def get_repo() -> NoveltyRepository:
    raise RuntimeError("novelty repository is not wired")


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def _observability(request: Request):
    return getattr(request.app.state, "observability", None)


def _adapters(request: Request) -> NoveltyAdapters | None:
    return getattr(request.app.state, "novelty_adapters", None)


def get_user_docmodel(request: Request):
    coordinator = getattr(request.app.state, "user_docmodel", None)
    if coordinator is None:
        coordinator = build_default_user_docmodel_coordinator()
        request.app.state.user_docmodel = coordinator
    return coordinator


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)
USER_DOCMODEL_DEP = Depends(get_user_docmodel)


@router.post(
    "/jobs",
    response_model=CreateJobResponse,
    # NFR-C1: novelty job은 Bedrock 지출을 유발 — 사용자별 일일 쿼터.
    dependencies=[Depends(enforce_novelty_job_quota)],
)
async def create_job(
    dto: NoveltyJobRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> CreateJobResponse:
    try:
        service = NoveltyService(repo, _observability(request))
        created = service.create_job(principal.user_id, dto)
        # US-NV2(#252) — 원고 본문이 아직 없는 잡은 업로드 완료 시점에 디스패치한다.
        awaiting_manuscript = dto.manuscript is not None and not dto.manuscript.objectKey
        if not awaiting_manuscript:
            _dispatch_job(
                repo,
                principal.user_id,
                created.jobId,
                _observability(request),
                adapters=_adapters(request),
            )
        return created
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/jobs", response_model=NoveltyJobListResponse)
async def list_jobs(
    request: Request,
    limit: int = 50,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> NoveltyJobListResponse:
    return NoveltyService(repo, _observability(request)).list_jobs(principal.user_id, limit)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> JobStatusResponse:
    try:
        return NoveltyService(repo, _observability(request)).status(principal.user_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.delete("/jobs/{job_id}", status_code=204, response_class=Response)
async def delete_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> Response:
    try:
        NoveltyService(repo, _observability(request)).delete_job(principal.user_id, job_id)
        return Response(status_code=204)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.delete("/jobs", status_code=204, response_class=Response)
async def reset_jobs(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> Response:
    """전체 세션 초기화 — US-EV8(#272), SEC-14. 소유 잡 전부 삭제, 멱등(0건도 204)."""
    NoveltyService(repo, _observability(request)).delete_all_jobs(principal.user_id)
    return Response(status_code=204)


@router.post("/jobs/{job_id}/manuscript", response_model=JobStatusResponse)
async def upload_manuscript(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
    user_docmodel=USER_DOCMODEL_DEP,
) -> JobStatusResponse:
    """US-NV2(#252) — 원고 본문 수신 → S3 적재 → objectKey 바인딩 → 잡 디스패치."""
    service = NoveltyService(repo, _observability(request))
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    try:
        if content_type == USER_DOCMODEL_PDF_CONTENT_TYPE:
            current = repo.get_job(principal.user_id, job_id)
            file_name = (
                request.query_params.get("fileName")
                or (current.manuscript.fileName if current.manuscript else None)
                or "manuscript.pdf"
            )
            service.attach_manuscript_pdf(
                principal.user_id,
                job_id,
                file_name=file_name,
                content_type=content_type,
                pdf=await request.body(),
                user_docmodel=user_docmodel,
            )
        elif content_type == "application/json":
            dto = ManuscriptContentRequest.model_validate(await request.json())
            service.attach_manuscript_content(principal.user_id, job_id, dto.contentText)
        else:
            raise HTTPException(status_code=415, detail="지원하지 않는 원고 형식입니다.")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _dispatch_job(
        repo,
        principal.user_id,
        job_id,
        _observability(request),
        adapters=_adapters(request),
    )
    return service.status(principal.user_id, job_id)


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_result(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> JobResultResponse:
    try:
        return NoveltyService(repo, _observability(request)).result(principal.user_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/jobs/{job_id}/events")
async def get_events(
    job_id: str,
    request: Request,
    after: str | None = None,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
):
    try:
        events = repo.list_events(principal.user_id, job_id, after_event_id=after)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    return StreamingResponse(sse_snapshot(events), media_type="text/event-stream")


@router.get("/jobs/{job_id}/messages", response_model=ChatMessageListResponse)
async def get_messages(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> ChatMessageListResponse:
    try:
        return NoveltyService(repo, _observability(request)).list_messages(
            principal.user_id, job_id
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.post("/jobs/{job_id}/messages", response_model=NoveltyChatMessage)
async def add_message(
    job_id: str,
    dto: ChatMessageCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> NoveltyChatMessage:
    try:
        return NoveltyService(repo, _observability(request)).add_message(
            principal.user_id, job_id, dto
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.post("/jobs/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> CancelJobResponse:
    try:
        return NoveltyService(repo, _observability(request)).cancel(principal.user_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/notion/preview", response_model=ExportPreviewResponse)
async def preview_notion_export(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> ExportPreviewResponse:
    try:
        export, preview = NoveltyService(repo, _observability(request)).preview_export(
            principal.user_id, job_id
        )
        return ExportPreviewResponse(export=export, preview=preview)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.post("/jobs/{job_id}/notion/approve")
async def approve_notion_export(
    job_id: str,
    dto: ExportApprovalRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
):
    try:
        service = NoveltyService(repo, _observability(request))
        export = service.approve_export(principal.user_id, job_id, approved=dto.approved)
        if dto.approved:
            # US-NV8(#258) AC3 — 승인 직후 실제 Notion 호출까지 완결(자동 export 없음).
            adapters = _adapters(request) or NoveltyAdapters()
            export = service.execute_export(principal.user_id, job_id, adapters.notion)
        return export
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ExportApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/notion/connection", response_model=NotionConnectionStatusResponse)
async def notion_connection_status(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> NotionConnectionStatusResponse:
    return NoveltyService(repo, _observability(request)).notion_connection_status(
        principal.user_id
    )


@router.put("/notion/connection", response_model=NotionConnectionStatusResponse)
async def save_notion_connection(
    dto: NotionConnectionRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> NotionConnectionStatusResponse:
    try:
        return NoveltyService(repo, _observability(request)).save_notion_connection(
            principal.user_id, dto
        )
    except ValueError as exc:
        # 키 미구성 등 — 비기술 문구만 노출(SEC-5/9)
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/notion/connection", status_code=204, response_class=Response)
async def delete_notion_connection(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> Response:
    NoveltyService(repo, _observability(request)).delete_notion_connection(
        principal.user_id
    )
    return Response(status_code=204)


routers = (router,)


def _dispatch_job(
    repo: NoveltyRepository,
    owner_id: str,
    job_id: str,
    observability=None,
    *,
    adapters: NoveltyAdapters | None = None,
) -> None:
    queue_url = os.getenv("DOCSURI_NOVELTY_JOB_QUEUE_URL")
    if not queue_url:
        from .worker import process_job

        process_job(repo, owner_id, job_id, adapters=adapters, observability=observability)
        return

    commit = getattr(repo, "commit", None)
    if commit is not None:
        commit()

    try:
        import boto3

        sqs = boto3.client(
            "sqs",
            region_name=(
                os.getenv("AWS_REGION")
                or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
            ),
        )
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"ownerId": owner_id, "jobId": job_id}),
            DelaySeconds=1,
        )
    except Exception as exc:  # noqa: BLE001 - dispatch failure must not leave a silent queued job.
        NoveltyService(repo, observability).advance_state(
            owner_id,
            job_id,
            JobState.FAILED,
            "Novelty analysis dispatch failed",
            {"error": type(exc).__name__},
        )
        if commit is not None:
            commit()
        raise HTTPException(status_code=503, detail="novelty job dispatch failed") from exc
