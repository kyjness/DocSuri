from __future__ import annotations

from typing import Any

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
from .validators import validate_artifact_payload


def _emit_metric(observability, name: str, value: float = 1.0, tags: dict | None = None) -> None:
    emit = getattr(observability, "emit_metric", None)
    if emit is None:
        return
    try:
        emit(name, value, tags or {})
    except Exception:
        pass


class NoveltyService:
    def __init__(self, repo: NoveltyRepository, observability=None) -> None:
        self._repo = repo
        self._observability = observability

    def create_job(self, owner_id: str, dto: NoveltyJobRequest) -> CreateJobResponse:
        if dto.inputType is InputType.MANUSCRIPT:
            assert dto.manuscript is not None
            if dto.manuscript.contentType not in SUPPORTED_MANUSCRIPT_CONTENT_TYPES:
                raise ValueError("only PDF, Markdown, and plain text manuscripts are supported")
        job = self._repo.create_job(
            NoveltyJob(
                ownerId=owner_id,
                inputType=dto.inputType,
                topic=dto.topic,
                manuscript=dto.manuscript,
            )
        )
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
            "title": f"Novelty analysis: {job.topic[:120]}",
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
