from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.agent_quota import enforce_evidence_turn_quota
# U11 SSE 스트리밍 코어 재사용(US-EV2/NFR-P6) — research는 FE agent chat의 evidence 표면.
from backend.modules.evidence.streaming import (
    progress_event,
    turn_sse_stream,
    wants_event_stream,
)
from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    build_default_user_docmodel_coordinator,
    object_key_for_upload,
    user_docmodel_ref,
)

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


def get_evidence_orchestrator(request: Request) -> Any:
    bundle = getattr(request.app.state, 'evidence_bundle', None)
    return bundle.orchestrator if bundle else None


def get_user_docmodel(request: Request):
    coordinator = getattr(request.app.state, "user_docmodel", None)
    if coordinator is None:
        coordinator = build_default_user_docmodel_coordinator()
        request.app.state.user_docmodel = coordinator
    return coordinator


PRINCIPAL_DEP = Depends(get_principal)
REPO_DEP = Depends(get_repo)
EVIDENCE_ORCHESTRATOR_DEP = Depends(get_evidence_orchestrator)
USER_DOCMODEL_DEP = Depends(get_user_docmodel)


class AttachmentUploadOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    kind: str = "pdf"
    size_bytes: int = Field(alias="sizeBytes")
    status: str = "ready"
    object_key: str = Field(alias="objectKey")
    paper_id: str = Field(alias="paperId")
    record_ref: str = Field(alias="recordRef")


@router.post(
    "/jobs",
    response_model=ResearchJobCreateResponse,
    # NFR-C1: create_job도 내부적으로 add_message → orchestrator.run()을 실행해 Bedrock을
    # 호출한다 — 여기를 게이트하지 않으면 새 세션을 계속 만드는 것만으로 일일 쿼터를
    # 완전히 우회할 수 있다(PR #364 리뷰 지적, 병합 시 누락됨).
    dependencies=[Depends(enforce_evidence_turn_quota)],
)
async def create_job(
    dto: ResearchJobCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
    orchestrator: Any = EVIDENCE_ORCHESTRATOR_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> Any:
    # US-EV2/NFR-P6 — Accept: text/event-stream 협상 시 동기 SSE 스트리밍으로 완료.
    if wants_event_stream(request.headers.get("accept")):
        return _stream_create_job(request, dto, principal, repo, orchestrator, user_docmodel)
    try:
        return await ResearchService(repo).create_job(
            principal.user_id,
            dto,
            orchestrator,
            user_docmodel,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="첨부 PDF 정보가 올바르지 않습니다.") from exc


@router.post("/attachments", response_model=AttachmentUploadOut)
async def upload_attachment(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> AttachmentUploadOut:
    if user_docmodel is None:
        raise HTTPException(status_code=422, detail="PDF 업로드 저장소가 구성되지 않았습니다.")
    file_name = request.query_params.get("fileName") or "attachment.pdf"
    attachment_id = request.query_params.get("id") or f"att-{uuid4()}"
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != USER_DOCMODEL_PDF_CONTENT_TYPE:
        raise HTTPException(status_code=415, detail="PDF 파일만 업로드할 수 있습니다.")
    data = await request.body()
    object_key = object_key_for_upload(
        module="evidence",
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
        module="evidence",
    )
    try:
        user_docmodel.upload_pdf(ref, data, file_name=file_name, content_type=content_type)
        user_docmodel.enqueue_build(ref)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - hide storage internals at the API boundary.
        raise HTTPException(status_code=422, detail="PDF 업로드에 실패했습니다.") from exc
    return AttachmentUploadOut(
        id=attachment_id,
        name=file_name,
        sizeBytes=len(data),
        objectKey=object_key,
        paperId=ref.paper_id,
        recordRef=ref.record_ref,
    )


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


@router.delete("/jobs", status_code=204, response_class=Response)
async def reset_jobs(
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
) -> Response:
    """전체 세션 초기화 — US-EV8(#272), SEC-14. 소유 잡·대화 이력 전부 삭제, 멱등(0건도 204)."""
    ResearchService(repo).delete_all_jobs(principal.user_id)
    return Response(status_code=204)


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


@router.post(
    "/jobs/{job_id}/messages",
    response_model=ResearchChatMessage,
    # NFR-C1: evidence 턴은 Bedrock 지출을 유발 — 사용자별 일일 쿼터.
    dependencies=[Depends(enforce_evidence_turn_quota)],
)
async def add_message(
    job_id: str,
    dto: ResearchMessageCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    repo: ResearchRepository = REPO_DEP,
    orchestrator: Any = EVIDENCE_ORCHESTRATOR_DEP,
    user_docmodel: Any = USER_DOCMODEL_DEP,
) -> Any:
    # US-EV2/NFR-P6 — Accept: text/event-stream 협상 시 동기 SSE 스트리밍으로 완료.
    if wants_event_stream(request.headers.get("accept")):
        try:
            repo.get_job(principal.user_id, job_id)  # 스트림 전 소유권/존재 검증(404 유지)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        return _stream_add_message(
            request, job_id, dto, principal, repo, orchestrator, user_docmodel
        )
    try:
        return await ResearchService(repo).add_message(
            principal.user_id,
            job_id,
            dto,
            orchestrator,
            user_docmodel,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="첨부 PDF 정보가 올바르지 않습니다.") from exc


# ---------------------------------------------------------------------------
# US-EV2/NFR-P6 — 동기 SSE 스트리밍 (U11 evidence 스트리밍 코어 재사용)
# 진행 이벤트는 단계명·건수만(C-2/INV-EV-3) — 최종 claims는 검증 후 터미널 result에만.
# 터미널 payload는 JSON 경로와 동일한 응답 본문(계약 불변).
# ---------------------------------------------------------------------------

def _stream_create_job(
    request: Request,
    dto: ResearchJobCreateRequest,
    principal: Principal,
    repo: ResearchRepository,
    orchestrator: Any,
    user_docmodel: Any,
) -> StreamingResponse:
    from .models import ResearchJob, ResearchJobState, title_from_content

    service = ResearchService(repo)
    job = repo.create_job(
        ResearchJob(ownerId=principal.user_id, title=title_from_content(dto.content))
    )

    async def _run(emit):
        await service.add_message(
            principal.user_id, job.jobId, dto, orchestrator, user_docmodel, on_progress=emit
        )
        return ResearchJobCreateResponse(jobId=job.jobId, state=ResearchJobState.COMPLETED)

    return _turn_stream_response(request, _run, initial_payload={"jobId": job.jobId})


def _stream_add_message(
    request: Request,
    job_id: str,
    dto: ResearchMessageCreateRequest,
    principal: Principal,
    repo: ResearchRepository,
    orchestrator: Any,
    user_docmodel: Any,
) -> StreamingResponse:
    service = ResearchService(repo)

    async def _run(emit):
        return await service.add_message(
            principal.user_id, job_id, dto, orchestrator, user_docmodel, on_progress=emit
        )

    return _turn_stream_response(request, _run, initial_payload={"jobId": job_id})


def _turn_stream_response(
    request: Request, run: Any, *, initial_payload: dict
) -> StreamingResponse:
    return StreamingResponse(
        turn_sse_stream(
            run,
            lambda result: result.model_dump(mode="json"),
            # 즉시 first-token(NFR-P6 TTFB) + jobId 동봉 — 스트림이 중간에 끊겨도
            # FE가 스냅샷 폴링으로 복구할 수 있는 앵커.
            initial_events=[progress_event("started", initial_payload)],
            observability=getattr(request.app.state, "observability", None),
            surface="research",
        ),
        media_type="text/event-stream",
        headers={"cache-control": "no-store"},
    )


routers = (router,)
