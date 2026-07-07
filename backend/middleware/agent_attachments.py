"""US-EV4(#268)·US-AG5(#297) — 에이전트 첨부 공통 검증.

허용 형식·크기 한도를 처리 시작 전에 검증해 422로 즉시 거부한다. FE가 보내는
AgentAttachment 객체 형상을 받아들이되, 공유 계약(EvidenceRequest.attachments =
문서 핸들 문자열 목록)으로의 변환은 각 컨트롤러가 담당한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ALLOWED_ATTACHMENT_KINDS = frozenset({"pdf", "markdown", "text"})
ATTACHMENT_MAX_BYTES = 10 * 1024 * 1024  # US-EV4 크기 한도 — 초과분은 처리 전 거부
ATTACHMENT_MAX_COUNT = 8
# US-EV4 2차 — 동봉 본문 상한. 유사도 어댑터의 S3 읽기 상한(256KiB)과 같은 계열.
ATTACHMENT_TEXT_MAX_CHARS = 262_144


class AgentAttachmentIn(BaseModel):
    """FE AgentAttachment 형상 — status/error 등 표시용 필드는 무시하고 검증만 한다."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=240)
    kind: str
    size_bytes: int = Field(0, ge=0, alias="sizeBytes")
    # US-EV4(#268) 2차 — md/txt 본문을 요청에 동봉해 근거 추출 대상에 포함한다.
    # PDF 본문은 공통 doc-model 파이프라인 경유가 후속(Q6=A) — 지금은 미지원 안내.
    content_text: str | None = Field(
        None, alias="contentText", max_length=ATTACHMENT_TEXT_MAX_CHARS
    )
    object_key: str | None = Field(None, alias="objectKey", max_length=512)
    paper_id: str | None = Field(None, alias="paperId", max_length=128)
    record_ref: str | None = Field(None, alias="recordRef", max_length=512)

    @field_validator("kind")
    @classmethod
    def _allowed_kind(cls, value: str) -> str:
        if value not in ALLOWED_ATTACHMENT_KINDS:
            raise ValueError("PDF, Markdown, TXT 파일만 첨부할 수 있습니다.")
        return value

    @field_validator("size_bytes")
    @classmethod
    def _within_size_limit(cls, value: int) -> int:
        if value > ATTACHMENT_MAX_BYTES:
            raise ValueError("첨부 파일이 크기 한도(10MB)를 초과했습니다.")
        return value


def validated_attachment_dicts(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """dict 저장 형상을 유지하면서 항목별 형식·크기를 검증한다(ValueError → 422)."""
    for item in value:
        try:
            AgentAttachmentIn.model_validate(item)
        except ValidationError as exc:
            first = exc.errors()[0]
            raise ValueError(str(first.get("msg") or "invalid attachment")) from exc
    return value
