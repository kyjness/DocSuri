"""Novelty v2 API — 잡 접수/조회(커서 폴링)/취소 플래그/잡 귀속 대화 + Notion export.

API는 루프를 실행하지 않는다(NFR-NV2-5·6·10) — 접수는 큐 적재까지, 실행은 워커.
진행 표시는 거시 상태 + 트레이스 파생 활동 피드(FR-35, 커서 방식 — 오프셋 금지).
대화 메시지의 kind는 클라이언트가 아니라 서버가 확정한다(FR-44) — 실행 중 잡으로
가면 스티어링, 종단 잡으로 가면 온디맨드 요청이다. Notion export는 preview→승인
게이트 경로만 존재하고 루프 도구가 아니다(BR-RA12).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from docsuri_shared.authz import Principal

# v1 승계 API 메트릭 — 방출은 공유 best-effort 헬퍼(포트 시그니처 강제).
from docsuri_shared.observability import emit_metric as _emit_metric
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.middleware.agent_attachments import ATTACHMENT_MAX_BYTES
from backend.middleware.agent_quota import (
    enforce_novelty_job_quota,
    enforce_novelty_turn_quota,
)
from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    object_key_for_upload,
    user_docmodel_ref,
)

from .domain.agent_step import ON_DEMAND_UNAVAILABLE_NOTICE, append_agent_message
from .domain.models import (
    ON_DEMAND_ELIGIBLE_STATES,
    TERMINAL_STATES,
    AgentLoopRun,
    ChatKind,
    ChatRole,
    ExportStatus,
    InputType,
    JobState,
    ManuscriptRef,
    NotionConnection,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    NoveltyJobRequest,
    utc_now,
)
from .domain.projection import describe_state, project_feed
from .ports.queue import KIND_TURN
from .ports.store import NoveltyStorePort
from .security import decrypt_secret, encrypt_secret
from .settings import NoveltySettings

log = logging.getLogger("docsuri.novelty.api")


def _feature_enabled() -> None:
    if os.getenv("NOVELTY_AGENT_ENABLED", "true").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(
    prefix="/api/novelty",
    tags=["Novelty"],
    dependencies=[Depends(_feature_enabled)],
)


# ── DI 심(wiring이 override) ──


def get_store() -> NoveltyStorePort:
    raise RuntimeError("novelty store is not wired")


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def _settings(request: Request) -> NoveltySettings:
    settings = getattr(request.app.state, "novelty_settings", None)
    return settings if settings is not None else NoveltySettings.from_env()


def _queue(request: Request):
    return getattr(request.app.state, "novelty_queue", None)


def _cost_guard(request: Request):
    return getattr(request.app.state, "cost_guard", None)


def _observability(request: Request):
    return getattr(request.app.state, "observability", None)


def _notion_client(request: Request):
    client = getattr(request.app.state, "novelty_notion_client", None)
    if client is None:
        from .adapters.notion import build_notion_client

        client = build_notion_client()
        request.app.state.novelty_notion_client = client
    return client


PRINCIPAL_DEP = Depends(get_principal)
STORE_DEP = Depends(get_store)


# ── FE 계약 DTO (camelCase) ──


class ManuscriptRefDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fileName: str = Field(min_length=1, max_length=240)
    contentType: str = Field(min_length=1, max_length=120)
    objectKey: str | None = Field(default=None, max_length=512)


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inputType: InputType
    topic: str = Field(min_length=3, max_length=2000)
    manuscript: ManuscriptRefDTO | None = None
    constraints: dict[str, Any] = Field(default_factory=dict)
    exportTarget: str | None = Field(default=None, max_length=512)


class LoopView(BaseModel):
    iterations: int = 0
    toolCalls: int = 0
    costUsd: float = 0.0
    terminationReason: str | None = None


class JobView(BaseModel):
    jobId: str
    inputType: InputType
    topic: str
    state: JobState
    stateLabel: str
    cancelRequested: bool = False
    degradedSources: dict[str, str] = Field(default_factory=dict)
    loop: LoopView | None = None
    artifactKinds: list[str] = Field(default_factory=list)
    errorMessage: str | None = None
    createdAt: datetime
    updatedAt: datetime
    completedAt: datetime | None = None


class CreateJobResponse(BaseModel):
    jobId: str
    state: JobState


class JobListResponse(BaseModel):
    jobs: list[JobView] = Field(default_factory=list)
    nextCursor: str | None = None


class FeedItemDTO(BaseModel):
    seq: int
    text: str
    tool: str
    querySummary: str
    occurredAt: datetime


class FeedResponse(BaseModel):
    items: list[FeedItemDTO] = Field(default_factory=list)
    nextCursor: int


class ArtifactDTO(BaseModel):
    kind: str
    payload: dict[str, Any]
    createdAt: datetime


class ExportView(BaseModel):
    jobId: str
    status: ExportStatus
    notionPageId: str | None = None
    errorMessage: str | None = None
    approvedAt: datetime | None = None
    exportedAt: datetime | None = None


class JobResultResponse(BaseModel):
    job: JobView
    artifacts: list[ArtifactDTO] = Field(default_factory=list)
    export: ExportView | None = None


class CancelJobResponse(BaseModel):
    jobId: str
    state: JobState
    cancelRequested: bool


class ChatMessageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=12000)
    # 서버가 kind를 확정하므로 이 값은 무시된다. 필드를 지우면 extra="forbid"에
    # 걸려 기존 클라이언트가 422가 되므로 호환을 위해 남긴다.
    kind: ChatKind = ChatKind.STEERING


class ChatMessageDTO(BaseModel):
    messageId: str
    jobId: str
    role: ChatRole
    kind: ChatKind
    content: str
    resultingArtifactRef: str | None = None
    createdAt: datetime


class ChatMessageListResponse(BaseModel):
    messages: list[ChatMessageDTO] = Field(default_factory=list)
    nextCursor: str | None = None


class NotionConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=256)
    parentPageId: str = Field(min_length=32, max_length=36, pattern=r"^[0-9a-fA-F-]{32,36}$")


class NotionConnectionStatusResponse(BaseModel):
    connected: bool
    parentPageId: str | None = None
    updatedAt: datetime | None = None


class ExportApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool = True


class ExportPreviewResponse(BaseModel):
    export: ExportView
    preview: dict[str, Any]


# ── 잡 수명주기 ──


def _require_dispatchable(request: Request) -> None:
    """접수 가능성 선행 검사 — 쿼터 의존성보다 먼저 실행되어 503 거부가 일일
    쿼터를 소비하지 않게 한다(코드 리뷰 반영, 의존성은 선언 순서대로 실행)."""
    if _queue(request) is None:
        raise HTTPException(status_code=503, detail={"error": "queue_unavailable"})
    guard = _cost_guard(request)
    if guard is not None and _budget_critical(guard):
        # U6 단일 비용 권위 — 예산 저하 모드에서는 신규 잡을 기권한다(BLM §1.4/§9).
        raise HTTPException(status_code=503, detail={"error": "budget_degraded"})


@router.post(
    "/jobs",
    response_model=CreateJobResponse,
    # NFR-C1: novelty job은 LLM 지출 유발 — 사용자별 일일 쿼터(배선 감사 대상 라우트
    # 의존성 유지). _require_dispatchable이 앞서 실행된다.
    dependencies=[Depends(_require_dispatchable), Depends(enforce_novelty_job_quota)],
)
async def create_job(
    dto: CreateJobRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> CreateJobResponse:
    queue = _queue(request)  # _require_dispatchable이 존재를 보장
    if dto.inputType is InputType.NATURAL_LANGUAGE and dto.manuscript is not None:
        # 자연어 잡의 원고 첨부는 적재 조건이 성립하지 않는다(영구 대기 방지).
        raise HTTPException(
            status_code=422, detail="자연어 입력 잡에는 원고를 첨부할 수 없습니다."
        )
    settings = _settings(request)
    manuscript_ref = None
    if dto.manuscript is not None:
        manuscript_ref = ManuscriptRef(
            file_name=dto.manuscript.fileName,
            content_type=dto.manuscript.contentType,
            object_key=dto.manuscript.objectKey,
        )
    try:
        domain_request = NoveltyJobRequest(
            input_type=dto.inputType,
            topic=dto.topic,
            evidence_request={"topic": dto.topic},
            manuscript_ref=manuscript_ref,
            constraints=dto.constraints,
            export_target=dto.exportTarget,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job = NoveltyJob(
        owner_id=principal.user_id,
        request=domain_request,
        loop_run=AgentLoopRun(budget=settings.build_loop_budget()),
    )
    store.create_job(job)
    # 원고 본문이 아직 없는 잡은 업로드 완료 시점에 적재한다(US-NV2 승계).
    awaiting_manuscript = manuscript_ref is not None and not manuscript_ref.object_key
    if not awaiting_manuscript:
        _enqueue_or_fail(store, queue, job)
    _emit_metric(_observability(request), "novelty.job_created")
    return CreateJobResponse(jobId=job.job_id, state=job.state)


def _enqueue_or_fail(store: NoveltyStorePort, queue: Any, job: NoveltyJob) -> None:
    """적재 실패를 조용한 RECEIVED 방치로 두지 않는다 — FAILED 수렴 + 503(v1 의미)."""
    try:
        queue.enqueue(job.job_id, job.owner_id)
    except Exception as exc:  # noqa: BLE001 — 실패는 상태로 수렴, 내부 상세 비노출
        job.state = JobState.FAILED
        job.error_message = "job dispatch failed"
        job.updated_at = utc_now()
        job.completed_at = utc_now()
        try:
            store.update_job(job)
        except Exception:  # noqa: BLE001 — 상태 수렴 실패 시 stale 스윕이 처리
            log.exception("novelty api: failed to persist dispatch failure")
        raise HTTPException(
            status_code=503, detail={"error": "dispatch_failed"}
        ) from exc


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs(
    request: Request,
    cursor: str | None = None,
    limit: int = 50,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> JobListResponse:
    page_size = min(max(limit, 1), 100)
    try:
        # 한 건 더 조회해 다음 페이지 존재를 확정 — 총량이 page_size의 정확한
        # 배수일 때 빈 마지막 페이지 왕복이 생기지 않는다.
        jobs = store.list_jobs(principal.user_id, cursor=cursor, limit=page_size + 1)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc
    has_more = len(jobs) > page_size
    jobs = jobs[:page_size]
    # 목록 뷰는 산출물 종류 조회를 생략한다(N+1 방지) — 상세·결과 조회가 담당.
    views = [_job_view(job, store, include_artifacts=False) for job in jobs]
    return JobListResponse(
        jobs=views, nextCursor=jobs[-1].job_id if has_more else None
    )


@router.get("/jobs/{job_id}", response_model=JobView)
async def get_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> JobView:
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_view(job, store)


@router.get("/jobs/{job_id}/feed", response_model=FeedResponse)
async def get_feed(
    job_id: str,
    request: Request,
    cursor: int = 0,
    limit: int = 50,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> FeedResponse:
    """활동 피드(FR-35) — 트레이스의 파생 투영. 커서=마지막 seq."""
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    records = store.list_trace(
        principal.user_id, job_id, after_seq=max(cursor, 0), limit=min(max(limit, 1), 200)
    )
    items = [
        FeedItemDTO(
            seq=item.seq,
            text=item.text,
            tool=item.tool,
            querySummary=item.query_summary,
            occurredAt=item.occurred_at,
        )
        for item in project_feed(records)
    ]
    return FeedResponse(
        items=items, nextCursor=items[-1].seq if items else max(cursor, 0)
    )


@router.get("/jobs/{job_id}/result", response_model=JobResultResponse)
async def get_result(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> JobResultResponse:
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    artifacts = store.list_artifacts(principal.user_id, job_id)
    export = store.get_export(principal.user_id, job_id)
    return JobResultResponse(
        job=_job_view(job, store),
        artifacts=[
            ArtifactDTO(kind=rec.kind.value, payload=rec.payload, createdAt=rec.created_at)
            for rec in artifacts
        ],
        export=_export_view(export) if export else None,
    )


@router.post("/jobs/{job_id}/cancel", response_model=CancelJobResponse)
async def cancel_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> CancelJobResponse:
    """협조적 취소(BR-RA8) — 플래그만 세운다. 워커가 턴 경계에서 확인·탈출한다."""
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.state in {JobState.COMPLETED, JobState.PARTIAL, JobState.FAILED, JobState.CANCELLED}:
        raise HTTPException(status_code=409, detail="job is terminal")
    store.request_cancel(principal.user_id, job_id)
    _emit_metric(_observability(request), "novelty.job_cancelled")
    return CancelJobResponse(jobId=job_id, state=job.state, cancelRequested=True)


@router.delete("/jobs/{job_id}", status_code=204, response_class=Response)
async def delete_job(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> Response:
    if not store.delete_job(principal.user_id, job_id):
        raise HTTPException(status_code=404, detail="job not found")
    return Response(status_code=204)


@router.delete("/jobs", status_code=204, response_class=Response)
async def reset_jobs(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> Response:
    """전체 세션 초기화(SEC-14 승계) — 소유 잡 전부 벌크 삭제(트레이스·대화 cascade), 멱등."""
    store.delete_all_jobs(principal.user_id)
    return Response(status_code=204)


@router.post("/jobs/{job_id}/manuscript", response_model=JobView)
async def upload_manuscript(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> JobView:
    """PDF 원고 적재(US-NV2 승계) — userdoc 파이프라인 위임(BR-NV1, 파싱 재구현 금지).
    적재 완료 시점에 잡을 큐에 넣는다. v1의 JSON 본문 경로는 v2에서 제거."""
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    manuscript = job.request.manuscript_ref
    if job.request.input_type is not InputType.MANUSCRIPT or manuscript is None:
        raise HTTPException(status_code=422, detail="원고 업로드는 원고 입력 잡에서만 가능합니다.")
    if manuscript.object_key:
        raise HTTPException(status_code=409, detail="이미 원고가 업로드된 잡입니다.")
    if job.state is not JobState.RECEIVED:
        raise HTTPException(status_code=409, detail="이미 분석이 시작된 잡입니다.")
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != USER_DOCMODEL_PDF_CONTENT_TYPE:
        raise HTTPException(status_code=415, detail="지원하지 않는 원고 형식입니다.")
    declared_size = request.headers.get("content-length")
    if declared_size and declared_size.isdigit() and int(declared_size) > ATTACHMENT_MAX_BYTES:
        # 본문을 읽기 전에 거부 — 대용량 원고의 메모리 적재 차단(요청 남용 방어).
        raise HTTPException(status_code=413, detail="원고 크기 한도를 초과했습니다.")
    coordinator = getattr(request.app.state, "user_docmodel", None)
    if coordinator is None:
        raise HTTPException(
            status_code=503, detail={"error": "manuscript_storage_unavailable"}
        )
    queue = _queue(request)
    if queue is None:
        raise HTTPException(status_code=503, detail={"error": "queue_unavailable"})

    file_name = request.query_params.get("fileName") or manuscript.file_name
    pdf = await request.body()
    if len(pdf) > ATTACHMENT_MAX_BYTES:
        # Content-Length가 없거나 거짓인 경우의 이중 방어.
        raise HTTPException(status_code=413, detail="원고 크기 한도를 초과했습니다.")
    object_key = object_key_for_upload(
        module="novelty",
        owner_id=principal.user_id,
        scope_id=job_id,
        attachment_id="manuscript",
        file_name=file_name,
    )
    ref = user_docmodel_ref(
        owner_id=principal.user_id,
        scope_id=job_id,
        attachment_id="manuscript",
        object_key=object_key,
        module="novelty",
    )
    coordinator.upload_pdf(ref, pdf, file_name=file_name, content_type=content_type)
    coordinator.enqueue_build(ref)
    job.request.manuscript_ref = manuscript.model_copy(
        update={
            "file_name": file_name,
            "object_key": object_key,
            "paper_id": ref.paper_id,
            "record_ref": ref.record_ref,
        }
    )
    job.updated_at = utc_now()
    store.update_job(job)
    queue.enqueue(job_id, principal.user_id)
    _emit_metric(_observability(request), "novelty.manuscript_uploaded")
    return _job_view(job, store)


# ── 잡 내 대화 (FR-44) ──


@router.get("/jobs/{job_id}/messages", response_model=ChatMessageListResponse)
async def get_messages(
    job_id: str,
    request: Request,
    after: str | None = None,
    limit: int = 100,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> ChatMessageListResponse:
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    try:
        messages = store.list_messages(
            principal.user_id, job_id, after=after, limit=min(max(limit, 1), 200)
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail="invalid cursor") from exc
    return ChatMessageListResponse(
        messages=[_message_dto(message) for message in messages],
        nextCursor=messages[-1].message_id if messages else after,
    )


@router.post("/jobs/{job_id}/messages", response_model=ChatMessageDTO)
async def add_message(
    job_id: str,
    dto: ChatMessageCreateRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> ChatMessageDTO:
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    # kind는 서버가 확정한다 — 클라이언트가 USER 역할 행에 agent_reply·notice
    # 라벨을 붙일 수 있으면 kind로 렌더링하는 순간 위조 표면이 된다. 값의 의미는
    # "서버가 이 메시지를 어디로 보냈는가"이고, 실제 결과(산출물 생성 여부)는
    # 에이전트 답장의 resulting_artifact_ref가 담는다(BLM §5.5).
    terminal = job.state in TERMINAL_STATES
    on_demand = job.state in ON_DEMAND_ELIGIBLE_STATES
    if on_demand:
        # 온디맨드 턴만 LLM 지출을 유발한다 — 가드를 라우트 의존성이 아니라 여기서
        # 부른다. 라우트에 걸면 큐 장애 시 스티어링(행 하나 쓰기)까지 503이 된다.
        _require_dispatchable(request)
        await enforce_novelty_turn_quota(request)
    message = NoveltyChatMessage(
        job_id=job_id,
        owner_id=principal.user_id,
        role=ChatRole.USER,
        kind=ChatKind.ON_DEMAND_REQUEST if terminal else ChatKind.STEERING,
        content=dto.content,
    )
    store.append_message(message)
    if on_demand:
        # 저장이 먼저다 — 적재가 실패해도 큐에 고아 참조가 남지 않는다.
        _enqueue_turn(request, store, job, message)
    elif terminal:
        # 실패·취소 잡은 근거가 될 산출물이 없다(BLM §5.1) — 워커를 깨우지 않고
        # 즉시 안내한다. 조용히 삼키지 않는다.
        append_agent_message(store, job, ON_DEMAND_UNAVAILABLE_NOTICE)
    return _message_dto(message)


def _enqueue_turn(
    request: Request, store: NoveltyStorePort, job: NoveltyJob, message: NoveltyChatMessage
) -> None:
    """온디맨드 턴을 워커에 넘긴다 — API는 실행하지 않는다(NFR-NV2-1)."""
    queue = _queue(request)  # _require_dispatchable이 존재를 보장
    try:
        queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    except Exception as exc:  # noqa: BLE001 — 적재 실패는 안내로 수렴, 잡 상태 불변
        append_agent_message(store, job, "요청을 접수하지 못했어요. 잠시 후 다시 시도해 주세요.")
        raise HTTPException(status_code=503, detail={"error": "dispatch_failed"}) from exc
    _emit_metric(_observability(request), "novelty.turn_requested")


# ── Notion export (루프 밖 — preview→승인 게이트, BR-NV17/RA12) ──


@router.post("/jobs/{job_id}/notion/preview", response_model=ExportPreviewResponse)
async def preview_notion_export(
    job_id: str,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> ExportPreviewResponse:
    job = store.get_job(principal.user_id, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    preview = _export_content(store, principal.user_id, job_id, include_payload=False)
    export = store.get_export(principal.user_id, job_id) or NotionExport(
        job_id=job_id, owner_id=principal.user_id
    )
    export.status = ExportStatus.PREVIEW_READY
    export.updated_at = utc_now()
    store.save_export(export)
    _emit_metric(_observability(request), "novelty.export_preview_created")
    return ExportPreviewResponse(export=_export_view(export), preview=preview)


@router.post("/jobs/{job_id}/notion/approve", response_model=ExportView)
async def approve_notion_export(
    job_id: str,
    dto: ExportApprovalRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> ExportView:
    export = store.get_export(principal.user_id, job_id)
    if not dto.approved:
        if export is None:
            raise HTTPException(status_code=409, detail="export preview is required")
        export.status = ExportStatus.NOT_REQUESTED
        export.updated_at = utc_now()
        store.save_export(export)
        return _export_view(export)
    # PBT-NV7 — preview 없이 approved/exported 도달 불가.
    if export is None or export.status is not ExportStatus.PREVIEW_READY:
        raise HTTPException(status_code=409, detail="export preview is required")
    export.status = ExportStatus.APPROVED
    export.approved_at = utc_now()
    export.updated_at = utc_now()
    store.save_export(export)
    _emit_metric(_observability(request), "novelty.export_approved")
    # 승인 직후 실제 export까지 완결(자동 export 없음 — 승인이 유일한 트리거).
    return _export_view(_execute_export(request, store, principal.user_id, job_id, export))


@router.get("/notion/connection", response_model=NotionConnectionStatusResponse)
async def notion_connection_status(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> NotionConnectionStatusResponse:
    connection = store.get_notion_connection(principal.user_id)
    if connection is None:
        return NotionConnectionStatusResponse(connected=False)
    return NotionConnectionStatusResponse(
        connected=True, parentPageId=connection.parent_page_id, updatedAt=connection.updated_at
    )


@router.put("/notion/connection", response_model=NotionConnectionStatusResponse)
async def save_notion_connection(
    dto: NotionConnectionRequest,
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> NotionConnectionStatusResponse:
    """토큰은 암호화 저장(SEC-8), 응답 미포함(SEC-12)."""
    try:
        encrypted = encrypt_secret(dto.token)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    connection = NotionConnection(
        owner_id=principal.user_id,
        token_encrypted=encrypted,
        parent_page_id=dto.parentPageId,
    )
    store.save_notion_connection(connection)
    _emit_metric(_observability(request), "novelty.notion_connection_saved")
    return NotionConnectionStatusResponse(
        connected=True, parentPageId=connection.parent_page_id, updatedAt=connection.updated_at
    )


@router.delete("/notion/connection", status_code=204, response_class=Response)
async def delete_notion_connection(
    request: Request,
    principal: Principal = PRINCIPAL_DEP,
    store: NoveltyStorePort = STORE_DEP,
) -> Response:
    store.delete_notion_connection(principal.user_id)
    _emit_metric(_observability(request), "novelty.notion_connection_deleted")
    return Response(status_code=204)


routers = (router,)


# ── 내부 헬퍼 ──


def _budget_critical(guard: Any) -> bool:
    try:
        from docsuri_ops.cost_guard import is_cost_critical

        return bool(is_cost_critical(guard.get_budget_state()))
    except Exception:  # noqa: BLE001 — 비용 판정 불가 시 접수를 막지 않는다(권위는 U6)
        return False


def _job_view(
    job: NoveltyJob, store: NoveltyStorePort, *, include_artifacts: bool = True
) -> JobView:
    artifacts = store.list_artifacts(job.owner_id, job.job_id) if include_artifacts else []
    run = job.loop_run
    loop_view = None
    if run is not None:
        loop_view = LoopView(
            iterations=run.iteration_count,
            toolCalls=run.budget.consumed.tool_calls_total,
            costUsd=round(run.budget.consumed.cost_usd, 6),
            terminationReason=(
                run.termination_reason.value if run.termination_reason else None
            ),
        )
    return JobView(
        jobId=job.job_id,
        inputType=job.request.input_type,
        topic=job.request.topic,
        state=job.state,
        stateLabel=describe_state(job.state),
        cancelRequested=job.cancel_requested,
        degradedSources=job.degraded_sources,
        loop=loop_view,
        artifactKinds=[rec.kind.value for rec in artifacts],
        errorMessage=job.error_message,
        createdAt=job.created_at,
        updatedAt=job.updated_at,
        completedAt=job.completed_at,
    )


def _message_dto(message: NoveltyChatMessage) -> ChatMessageDTO:
    return ChatMessageDTO(
        messageId=message.message_id,
        jobId=message.job_id,
        role=message.role,
        kind=message.kind,
        content=message.content,
        resultingArtifactRef=message.resulting_artifact_ref,
        createdAt=message.created_at,
    )


def _export_view(export: NotionExport) -> ExportView:
    return ExportView(
        jobId=export.job_id,
        status=export.status,
        notionPageId=export.notion_page_id,
        errorMessage=export.error_message,
        approvedAt=export.approved_at,
        exportedAt=export.exported_at,
    )


def _export_title() -> str:
    return f"DocSuri Novelty 조사 보고 ({utc_now().date().isoformat()})"


def _export_content(
    store: NoveltyStorePort, owner_id: str, job_id: str, *, include_payload: bool
) -> dict[str, Any]:
    """preview와 실제 export가 같은 조립을 공유한다 — 승인한 것과 내보내는 것의 구조 일치."""
    job = store.get_job(owner_id, job_id)
    artifacts = store.list_artifacts(owner_id, job_id)
    return {
        "title": _export_title(),
        "inputPrompt": job.request.topic if job else "",
        "jobId": job_id,
        "artifacts": [
            {"kind": rec.kind.value, **({"payload": rec.payload} if include_payload else {})}
            for rec in artifacts
        ],
    }


def _execute_export(
    request: Request,
    store: NoveltyStorePort,
    owner_id: str,
    job_id: str,
    export: NotionExport,
) -> NotionExport:
    observability = _observability(request)
    connection = store.get_notion_connection(owner_id)
    if connection is None:
        return _fail_export(
            store, export, "Notion 연결이 없습니다. 먼저 연결 토큰을 등록해 주세요.",
            observability=observability,
        )
    export.status = ExportStatus.EXPORTING
    export.updated_at = utc_now()
    store.save_export(export)
    content = _export_content(store, owner_id, job_id, include_payload=True)
    try:
        token = decrypt_secret(connection.token_encrypted)
        page_id = _notion_client(request).export(
            {"token": token, "parentPageId": connection.parent_page_id}, content
        )
    except Exception:  # noqa: BLE001 — 외부 실패는 상태로 수렴, 내부 상세 비노출(SEC-9)
        return _fail_export(
            store,
            export,
            "Notion 내보내기에 실패했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
            observability=observability,
        )
    export.status = ExportStatus.EXPORTED
    export.notion_page_id = page_id
    export.exported_at = utc_now()
    export.updated_at = utc_now()
    store.save_export(export)
    _emit_metric(observability, "novelty.notion_export_completed")
    return export


def _fail_export(
    store: NoveltyStorePort,
    export: NotionExport,
    message: str,
    *,
    observability: Any = None,
) -> NotionExport:
    export.status = ExportStatus.FAILED
    export.error_message = message
    export.updated_at = utc_now()
    store.save_export(export)
    _emit_metric(observability, "novelty.notion_export_failed")
    return export
