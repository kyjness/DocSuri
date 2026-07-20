"""잡·산출물·트레이스·대화 저장 포트(NFR-NV2-12/13).

모든 조회는 owner-scoped다(SECURITY-08). 트레이스는 (job_id, seq) 유일 —
중복 seq 적재는 구현이 거부해야 한다(PBT-RA3). 잡 삭제는 산출물·트레이스·
대화를 함께 지운다(BR-NV18 개정 — cascade).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from ..domain.models import (
    ArtifactRecord,
    NotionConnection,
    NotionExport,
    NoveltyChatMessage,
    NoveltyJob,
    ToolCallRecord,
)

__all__ = ["DuplicateTraceSeqError", "NoveltyStorePort"]


class DuplicateTraceSeqError(Exception):
    """(job_id, seq) 중복 — seq 무결성 위반(BR-RA4)."""


class NoveltyStorePort(Protocol):
    # ── 잡 ──
    def create_job(self, job: NoveltyJob) -> None: ...

    def get_job(self, owner_id: str, job_id: str) -> NoveltyJob | None: ...

    def get_job_for_worker(self, job_id: str) -> NoveltyJob | None: ...

    def list_jobs(self, owner_id: str, *, cursor: str | None, limit: int) -> list[NoveltyJob]: ...

    def update_job(self, job: NoveltyJob) -> None: ...

    def delete_job(self, owner_id: str, job_id: str) -> bool: ...

    def delete_all_jobs(self, owner_id: str) -> int: ...

    def request_cancel(self, owner_id: str, job_id: str) -> bool: ...

    def is_cancel_requested(self, job_id: str) -> bool: ...

    def list_stale_active(self, *, updated_before: datetime, limit: int) -> list[NoveltyJob]: ...

    # ── 산출물 (종류별 최신 검증본) ──
    def save_artifact(self, record: ArtifactRecord) -> None: ...

    def list_artifacts(self, owner_id: str, job_id: str) -> list[ArtifactRecord]: ...

    # ── 결정 트레이스 (FR-46) ──
    def next_trace_seq(self, job_id: str) -> int: ...

    def append_trace(self, record: ToolCallRecord) -> None: ...

    def list_trace(
        self, owner_id: str, job_id: str, *, after_seq: int, limit: int
    ) -> list[ToolCallRecord]: ...

    # ── 잡 내 대화 (FR-44) ──
    def append_message(self, message: NoveltyChatMessage) -> None: ...

    def list_messages(
        self, owner_id: str, job_id: str, *, after: str | None, limit: int
    ) -> list[NoveltyChatMessage]: ...

    # ── Notion export·연결 (루프 밖 — BR-RA12, 승인 게이트 BR-NV17) ──
    def get_export(self, owner_id: str, job_id: str) -> NotionExport | None: ...

    def save_export(self, export: NotionExport) -> None: ...

    def get_notion_connection(self, owner_id: str) -> NotionConnection | None: ...

    def save_notion_connection(self, connection: NotionConnection) -> None: ...

    def delete_notion_connection(self, owner_id: str) -> None: ...
