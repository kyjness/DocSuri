from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.modules.accounts.models import Principal

from .models import (
    ResearchChatMessage,
    ResearchJobCreateRequest,
    ResearchJobCreateResponse,
    ResearchJobDetailResponse,
    ResearchJobListResponse,
    ResearchMessageCreateRequest,
    ResearchMessageListResponse,
)
from .repository import ResearchRepository
from .service import ResearchService


def _feature_enabled() -> None:
    if os.getenv("RESEARCH_AGENT_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(
    prefix="/api/research",
    tags=["Research"],
    dependencies=[Depends(_feature_enabled)],
)


def get_repo() -> ResearchRepository:
    raise RuntimeError("research repository is not wired")


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)


@router.post("/jobs", response_model=ResearchJobCreateResponse)
async def create_job(
    dto: ResearchJobCreateRequest,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> ResearchJobCreateResponse:
    return ResearchService(repo).create_job(principal.user_id, dto)


@router.get("/jobs", response_model=ResearchJobListResponse)
async def list_jobs(
    limit: int = 50,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> ResearchJobListResponse:
    return ResearchService(repo).list_jobs(principal.user_id, limit)


@router.get("/jobs/{job_id}", response_model=ResearchJobDetailResponse)
async def get_job(
    job_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> ResearchJobDetailResponse:
    try:
        return ResearchService(repo).detail(principal.user_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.delete("/jobs/{job_id}", status_code=204, response_class=Response)
async def delete_job(
    job_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> Response:
    try:
        ResearchService(repo).delete_job(principal.user_id, job_id)
        return Response(status_code=204)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.get("/jobs/{job_id}/messages", response_model=ResearchMessageListResponse)
async def get_messages(
    job_id: str,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> ResearchMessageListResponse:
    try:
        return ResearchService(repo).list_messages(principal.user_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


@router.post("/jobs/{job_id}/messages", response_model=ResearchChatMessage)
async def add_message(
    job_id: str,
    dto: ResearchMessageCreateRequest,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> ResearchChatMessage:
    try:
        return ResearchService(repo).add_message(principal.user_id, job_id, dto)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc


routers = (router,)

