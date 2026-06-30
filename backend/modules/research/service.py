from __future__ import annotations

from .models import (
    ChatRole,
    ResearchChatMessage,
    ResearchJob,
    ResearchJobCreateRequest,
    ResearchJobCreateResponse,
    ResearchJobDetailResponse,
    ResearchJobListResponse,
    ResearchJobSummary,
    ResearchMessageCreateRequest,
    ResearchMessageListResponse,
    title_from_content,
)
from .repository import ResearchRepository


class ResearchService:
    def __init__(self, repo: ResearchRepository) -> None:
        self._repo = repo

    def create_job(self, owner_id: str, dto: ResearchJobCreateRequest) -> ResearchJobCreateResponse:
        job = self._repo.create_job(
            ResearchJob(ownerId=owner_id, title=title_from_content(dto.content))
        )
        self.add_message(
            owner_id,
            job.jobId,
            dto,
        )
        return ResearchJobCreateResponse(jobId=job.jobId, state=job.state)

    def list_jobs(self, owner_id: str, limit: int = 50) -> ResearchJobListResponse:
        jobs = self._repo.list_jobs(owner_id, max(1, min(limit, 100)))
        return ResearchJobListResponse(
            jobs=[
                ResearchJobSummary(
                    jobId=job.jobId,
                    title=job.title,
                    state=job.state,
                    createdAt=job.createdAt,
                    updatedAt=job.updatedAt,
                )
                for job in jobs
            ]
        )

    def detail(self, owner_id: str, job_id: str) -> ResearchJobDetailResponse:
        return ResearchJobDetailResponse(
            job=self._repo.get_job(owner_id, job_id),
            messages=self._repo.list_messages(owner_id, job_id),
        )

    def delete_job(self, owner_id: str, job_id: str) -> None:
        self._repo.delete_job(owner_id, job_id)

    def add_message(
        self, owner_id: str, job_id: str, dto: ResearchMessageCreateRequest
    ) -> ResearchChatMessage:
        self._repo.get_job(owner_id, job_id)
        return self._repo.add_message(
            ResearchChatMessage(
                jobId=job_id,
                ownerId=owner_id,
                role=ChatRole.USER,
                content=dto.content,
                attachments=dto.attachments,
            )
        )

    def list_messages(self, owner_id: str, job_id: str) -> ResearchMessageListResponse:
        return ResearchMessageListResponse(messages=self._repo.list_messages(owner_id, job_id))
