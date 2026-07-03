from __future__ import annotations

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from backend.modules.accounts.models import Principal

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


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)


@router.post("/jobs", response_model=CreateJobResponse)
async def create_job(
    dto: NoveltyJobRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: NoveltyRepository = REPO_DEP,
) -> CreateJobResponse:
    try:
        service = NoveltyService(repo, _observability(request))
        created = service.create_job(principal.user_id, dto)
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
        export = NoveltyService(repo, _observability(request)).approve_export(
            principal.user_id, job_id, approved=dto.approved
        )
        return export
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ExportApprovalError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
