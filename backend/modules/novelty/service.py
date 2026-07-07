from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any

from backend.modules.user_docmodel import (
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    object_key_for_upload,
    user_docmodel_ref,
)

from .models import (
    STATE_PROGRESS,
    SUPPORTED_MANUSCRIPT_CONTENT_TYPES,
    TERMINAL_STATES,
    ArtifactKind,
    ArtifactRef,
    CancelJobResponse,
    ChatMessageCreateRequest,
    ChatMessageListResponse,
    ChatRole,
    CreateJobResponse,
    ExportApprovalError,
    ExportStatus,
    InputType,
    JobResultResponse,
    JobState,
    JobStatusResponse,
    ManuscriptRef,
    NotionConnection,
    NotionConnectionRequest,
    NotionConnectionStatusResponse,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    NoveltyJobListResponse,
    NoveltyJobRequest,
    NoveltyJobSummary,
    ProgressEvent,
    utc_now,
    validate_transition,
)
from .repository import NoveltyRepository
from .security import decrypt_secret, encrypt_secret
from .validators import validate_artifact_payload

_KST = timezone(timedelta(hours=9))


def _notion_export_title() -> str:
    return f"{utc_now().astimezone(_KST):%Y%m%d:%H%M}_Novelty_분석_결과"


def _emit_metric(observability, name: str, value: float = 1.0, tags: dict | None = None) -> None:
    emit = getattr(observability, "emit_metric", None)
    if emit is None:
        return
    try:
        emit(name, value, tags or {})
    except Exception:
        pass


def _validate_manuscript_ref(
    owner_id: str,
    job_id: str,
    manuscript: ManuscriptRef,
) -> ManuscriptRef:
    if not manuscript.objectKey:
        return manuscript
    expected_prefix = f"novelty/{owner_id}/{job_id}/"
    if not manuscript.objectKey.startswith(expected_prefix):
        raise ValueError("manuscript objectKey must be issued for this owner and job")
    return manuscript


class NoveltyService:
    def __init__(self, repo: NoveltyRepository, observability=None) -> None:
        self._repo = repo
        self._observability = observability

    def create_job(self, owner_id: str, dto: NoveltyJobRequest) -> CreateJobResponse:
        if dto.inputType is InputType.MANUSCRIPT:
            assert dto.manuscript is not None
            if dto.manuscript.contentType not in SUPPORTED_MANUSCRIPT_CONTENT_TYPES:
                raise ValueError("only Markdown, plain text, and PDF manuscripts are supported")
        job = NoveltyJob(
            ownerId=owner_id,
            inputType=dto.inputType,
            topic=dto.topic,
            manuscript=dto.manuscript,
        )
        if job.manuscript is not None:
            job = job.model_copy(
                update={
                    "manuscript": _validate_manuscript_ref(
                        owner_id,
                        job.jobId,
                        job.manuscript,
                    )
                }
            )
        job = self._repo.create_job(job)
        self.record_event(job, "Novelty analysis job queued")
        self.add_message(
            owner_id,
            job.jobId,
            ChatMessageCreateRequest(
                content=job.topic,
                attachments=(
                    [job.manuscript.model_dump(mode="json")] if job.manuscript else []
                ),
            ),
        )
        _emit_metric(self._observability, "novelty.job_created")
        return CreateJobResponse(jobId=job.jobId, state=job.state)

    def list_jobs(self, owner_id: str, limit: int = 50) -> NoveltyJobListResponse:
        jobs = self._repo.list_jobs(owner_id, max(1, min(limit, 100)))
        return NoveltyJobListResponse(
            jobs=[
                NoveltyJobSummary(
                    jobId=job.jobId,
                    inputType=job.inputType,
                    topic=job.topic,
                    state=job.state,
                    progressPercent=job.progressPercent,
                    exportStatus=job.exportStatus,
                    createdAt=job.createdAt,
                    updatedAt=job.updatedAt,
                    completedAt=job.completedAt,
                )
                for job in jobs
            ]
        )

    def status(self, owner_id: str, job_id: str) -> JobStatusResponse:
        return JobStatusResponse(
            job=self._repo.get_job(owner_id, job_id),
            events=self._repo.list_events(owner_id, job_id),
        )

    def result(self, owner_id: str, job_id: str) -> JobResultResponse:
        return JobResultResponse(
            job=self._repo.get_job(owner_id, job_id),
            artifacts=self._repo.list_artifacts(owner_id, job_id),
            export=self._repo.get_export(owner_id, job_id),
        )

    def advance_state(
        self,
        owner_id: str,
        job_id: str,
        state: JobState,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> NoveltyJob:
        current = self._repo.get_job(owner_id, job_id)
        validate_transition(current.state, state)
        completed_at = utc_now() if state in TERMINAL_STATES else None
        job = self._repo.update_job(
            owner_id,
            job_id,
            state=state,
            progressPercent=STATE_PROGRESS[state],
            completedAt=completed_at,
        )
        self.record_event(job, message, payload)
        _emit_metric(self._observability, "novelty.state_changed", tags={"state": state.value})
        return job

    def cancel(self, owner_id: str, job_id: str) -> CancelJobResponse:
        job = self._repo.get_job(owner_id, job_id)
        if job.state not in TERMINAL_STATES:
            validate_transition(job.state, JobState.CANCELLED)
            job = self._repo.update_job(
                owner_id,
                job_id,
                state=JobState.CANCELLED,
                progressPercent=100,
                cancelled=True,
                completedAt=utc_now(),
            )
            self.record_event(job, "Novelty analysis cancelled")
            _emit_metric(self._observability, "novelty.job_cancelled")
        return CancelJobResponse(jobId=job.jobId, state=job.state)

    def delete_job(self, owner_id: str, job_id: str) -> None:
        self._repo.delete_job(owner_id, job_id)

    def delete_all_jobs(self, owner_id: str) -> None:
        self._repo.delete_all_jobs(owner_id)

    def attach_manuscript_content(self, owner_id: str, job_id: str, text: str) -> NoveltyJob:
        """US-NV2(#252) — 원고 본문을 S3에 적재하고 objectKey를 잡에 바인딩한다.

        업로드 전 원고 잡은 QUEUED로 대기하며(디스패치 보류), 이 호출이 성공해야
        분석이 시작될 수 있다. 실패 문구는 비기술 표현만 노출(SEC-5/9).
        """
        from .adapters import store_manuscript_text

        job = self._repo.get_job(owner_id, job_id)
        if job.inputType is not InputType.MANUSCRIPT or job.manuscript is None:
            raise ValueError("원고 업로드는 원고(manuscript) 입력 잡에서만 가능합니다.")
        if job.manuscript.objectKey:
            raise ValueError("이미 원고가 업로드된 잡입니다.")
        if job.state is not JobState.QUEUED:
            raise ValueError("이미 분석이 시작된 잡입니다.")
        if job.manuscript.contentType == USER_DOCMODEL_PDF_CONTENT_TYPE:
            raise ValueError("PDF 원고는 PDF 파일로 업로드해 주세요.")
        object_key = store_manuscript_text(
            owner_id, job_id, job.manuscript.contentType, text
        )
        manuscript = job.manuscript.model_copy(update={"objectKey": object_key})
        updated = self._repo.update_job(owner_id, job_id, manuscript=manuscript)
        _emit_metric(self._observability, "novelty.manuscript_uploaded")
        return updated

    def attach_manuscript_pdf(
        self,
        owner_id: str,
        job_id: str,
        *,
        file_name: str,
        content_type: str,
        pdf: bytes,
        user_docmodel: Any = None,
    ) -> NoveltyJob:
        """PR2 — PDF 원고를 S3에 적재하고 userdoc DocModel 빌드를 enqueue한다."""
        job = self._repo.get_job(owner_id, job_id)
        if user_docmodel is None:
            raise ValueError("원고 저장소가 구성되지 않아 파일 분석을 시작할 수 없습니다.")
        if job.inputType is not InputType.MANUSCRIPT or job.manuscript is None:
            raise ValueError("원고 업로드는 원고(manuscript) 입력 잡에서만 가능합니다.")
        if job.manuscript.contentType != USER_DOCMODEL_PDF_CONTENT_TYPE:
            raise ValueError("PDF 원고 업로드는 PDF 입력 잡에서만 가능합니다.")
        if job.manuscript.objectKey:
            raise ValueError("이미 원고가 업로드된 잡입니다.")
        if job.state is not JobState.QUEUED:
            raise ValueError("이미 분석이 시작된 잡입니다.")

        object_key = object_key_for_upload(
            module="novelty",
            owner_id=owner_id,
            scope_id=job_id,
            attachment_id="manuscript",
            file_name=file_name,
        )
        ref = user_docmodel_ref(
            owner_id=owner_id,
            scope_id=job_id,
            attachment_id="manuscript",
            object_key=object_key,
            module="novelty",
        )
        user_docmodel.upload_pdf(ref, pdf, file_name=file_name, content_type=content_type)
        user_docmodel.enqueue_build(ref)
        manuscript = job.manuscript.model_copy(
            update={
                "fileName": file_name,
                "objectKey": object_key,
                "paperId": ref.paper_id,
                "recordRef": ref.record_ref,
            }
        )
        updated = self._repo.update_job(owner_id, job_id, manuscript=manuscript)
        _emit_metric(self._observability, "novelty.manuscript_uploaded")
        return updated

    def add_message(
        self, owner_id: str, job_id: str, dto: ChatMessageCreateRequest
    ) -> NoveltyChatMessage:
        self._repo.get_job(owner_id, job_id)
        message = self._repo.add_message(
            NoveltyChatMessage(
                jobId=job_id,
                ownerId=owner_id,
                role=ChatRole.USER,
                content=dto.content,
                attachments=dto.attachments,
            )
        )
        self._repo.update_job(owner_id, job_id)
        return message

    def list_messages(self, owner_id: str, job_id: str) -> ChatMessageListResponse:
        return ChatMessageListResponse(messages=self._repo.list_messages(owner_id, job_id))

    def save_artifact(
        self,
        owner_id: str,
        job_id: str,
        kind: ArtifactKind,
        title: str,
        payload: dict[str, Any],
    ) -> ArtifactRef:
        self._repo.get_job(owner_id, job_id)
        validate_artifact_payload(kind, payload)
        artifact = ArtifactRef(
            jobId=job_id,
            ownerId=owner_id,
            kind=kind,
            title=title,
            objectKey=f"novelty/{owner_id}/{job_id}/{kind.value}.json",
            payload=payload,
        )
        return self._repo.save_artifact(artifact)

    def record_event(
        self, job: NoveltyJob, message: str, payload: dict[str, Any] | None = None
    ) -> ProgressEvent:
        return self._repo.add_event(
            ProgressEvent(
                jobId=job.jobId,
                ownerId=job.ownerId,
                state=job.state,
                progressPercent=job.progressPercent,
                message=message,
                payload=payload or {},
            )
        )

    def preview_export(self, owner_id: str, job_id: str) -> tuple[NotionExport, dict[str, Any]]:
        job = self._repo.get_job(owner_id, job_id)
        artifacts = self._repo.list_artifacts(owner_id, job_id)
        preview = {
            "title": _notion_export_title(),
            "inputPrompt": job.topic,
            "jobId": job.jobId,
            "artifacts": [
                {"kind": artifact.kind.value, "title": artifact.title}
                for artifact in artifacts
            ],
        }
        export = self._repo.get_export(owner_id, job_id) or NotionExport(
            jobId=job_id,
            ownerId=owner_id,
        )
        export = export.model_copy(
            update={
                "status": ExportStatus.PREVIEW_READY,
                "previewObjectKey": f"novelty/{owner_id}/{job_id}/notion-preview.json",
                "updatedAt": utc_now(),
            }
        )
        self._repo.save_export(export)
        self._repo.update_job(owner_id, job_id, exportStatus=ExportStatus.PREVIEW_READY)
        _emit_metric(self._observability, "novelty.export_preview_created")
        return export, preview

    def approve_export(self, owner_id: str, job_id: str, *, approved: bool) -> NotionExport:
        export = self._repo.get_export(owner_id, job_id)
        if not approved:
            if export is None:
                raise ExportApprovalError("export preview is required before approval")
            export = export.model_copy(update={"status": ExportStatus.NOT_REQUESTED})
            self._repo.save_export(export)
            self._repo.update_job(owner_id, job_id, exportStatus=ExportStatus.NOT_REQUESTED)
            return export
        if export is None or export.status is not ExportStatus.PREVIEW_READY:
            raise ExportApprovalError("export preview is required before approval")
        export = export.model_copy(
            update={
                "status": ExportStatus.APPROVED,
                "approvedAt": utc_now(),
                "updatedAt": utc_now(),
            }
        )
        self._repo.save_export(export)
        self._repo.update_job(owner_id, job_id, exportStatus=ExportStatus.APPROVED)
        _emit_metric(self._observability, "novelty.export_approved")
        return export

    def complete_export(self, owner_id: str, job_id: str, notion_page_id: str) -> NotionExport:
        export = self._repo.get_export(owner_id, job_id)
        if export is None or export.status not in {ExportStatus.APPROVED, ExportStatus.EXPORTING}:
            raise ExportApprovalError("export cannot complete without preview approval")
        export = export.model_copy(
            update={
                "status": ExportStatus.EXPORTED,
                "notionPageId": notion_page_id,
                "exportedAt": utc_now(),
                "updatedAt": utc_now(),
            }
        )
        self._repo.save_export(export)
        self._repo.update_job(owner_id, job_id, exportStatus=ExportStatus.EXPORTED)
        return export

    def save_notion_connection(
        self, owner_id: str, dto: NotionConnectionRequest
    ) -> NotionConnectionStatusResponse:
        """US-NV8(#258) AC2 — 명시 연결 토큰 암호화 저장(SEC-8). 응답에 토큰 미포함(SEC-12)."""
        connection = NotionConnection(
            ownerId=owner_id,
            tokenEncrypted=encrypt_secret(dto.token),
            parentPageId=dto.parentPageId,
        )
        saved = self._repo.save_notion_connection(connection)
        _emit_metric(self._observability, "novelty.notion_connection_saved")
        return NotionConnectionStatusResponse(
            connected=True, parentPageId=saved.parentPageId, updatedAt=saved.updatedAt
        )

    def notion_connection_status(self, owner_id: str) -> NotionConnectionStatusResponse:
        connection = self._repo.get_notion_connection(owner_id)
        if connection is None:
            return NotionConnectionStatusResponse(connected=False)
        return NotionConnectionStatusResponse(
            connected=True,
            parentPageId=connection.parentPageId,
            updatedAt=connection.updatedAt,
        )

    def delete_notion_connection(self, owner_id: str) -> None:
        self._repo.delete_notion_connection(owner_id)
        _emit_metric(self._observability, "novelty.notion_connection_deleted")

    def execute_export(self, owner_id: str, job_id: str, notion: Any) -> NotionExport:
        """US-NV8(#258) AC3 — 승인된 export만 실제 Notion 호출로 완결. 실패는 FAILED+비기술 문구.

        자동 export 없음 — preview→approve를 거친 상태(APPROVED)에서만 호출된다.
        """
        export = self._repo.get_export(owner_id, job_id)
        if export is None or export.status is not ExportStatus.APPROVED:
            raise ExportApprovalError("export cannot start without preview approval")
        connection = self._repo.get_notion_connection(owner_id)
        if connection is None:
            return self._fail_export(
                export, "Notion 연결이 없습니다. 먼저 연결 토큰을 등록해 주세요."
            )
        export = export.model_copy(
            update={"status": ExportStatus.EXPORTING, "updatedAt": utc_now()}
        )
        self._repo.save_export(export)
        self._repo.update_job(owner_id, job_id, exportStatus=ExportStatus.EXPORTING)
        try:
            token = decrypt_secret(connection.tokenEncrypted)
            page_id = notion.export(
                {"token": token, "parentPageId": connection.parentPageId},
                self._export_content(owner_id, job_id),
            )
        except Exception:  # noqa: BLE001 - 외부 호출 실패는 상태로 수렴, 내부 상세 비노출(SEC-9)
            _emit_metric(self._observability, "novelty.notion_export_failed")
            return self._fail_export(
                export,
                "Notion 내보내기에 실패했습니다. 연결 상태를 확인한 뒤 다시 시도해 주세요.",
            )
        _emit_metric(self._observability, "novelty.notion_export_completed")
        return self.complete_export(owner_id, job_id, page_id)

    def _fail_export(self, export: NotionExport, message: str) -> NotionExport:
        failed = export.model_copy(
            update={
                "status": ExportStatus.FAILED,
                "errorMessage": message,
                "updatedAt": utc_now(),
            }
        )
        self._repo.save_export(failed)
        self._repo.update_job(failed.ownerId, failed.jobId, exportStatus=ExportStatus.FAILED)
        return failed

    def _export_content(self, owner_id: str, job_id: str) -> dict[str, Any]:
        """export 본문 — preview(kind/title 목록)와 달리 아티팩트 payload까지 싣는다."""
        job = self._repo.get_job(owner_id, job_id)
        artifacts = self._repo.list_artifacts(owner_id, job_id)
        return {
            "title": _notion_export_title(),
            "inputPrompt": job.topic,
            "jobId": job.jobId,
            "artifacts": [
                {"kind": artifact.kind.value, "title": artifact.title, "payload": artifact.payload}
                for artifact in artifacts
            ],
        }
