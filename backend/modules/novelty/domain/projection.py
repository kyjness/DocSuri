"""트레이스 → 활동 피드·거시 상태 투영(FR-35, BLM §7). 파생 뷰 — 실패해도 잡 비실패.

트레이스가 SSOT이고 피드는 사용자용 문구로의 best-effort 투영이다. 내부 payload·
민감 정보는 투영 단계에서 제외한다(SEC-9/15) — 입력이 이미 sanitized 요약이지만
투영 문구는 도구·어댑터 내부 상세를 다시 은닉한다(SECURITY-09).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_DATASET_SEARCH,
    TOOL_FORM_EVIDENCE,
    TOOL_GITHUB_SEARCH,
    TOOL_SAVE_ARTIFACT,
    TOOL_VIEW_FIGURE,
)
from .models import JobState, ToolCallRecord, ToolOutcome

__all__ = ["ActivityFeedItem", "describe_state", "project_feed"]


@dataclass(frozen=True, slots=True)
class ActivityFeedItem:
    seq: int
    text: str
    tool: str
    query_summary: str
    occurred_at: datetime


_STATE_LABELS: dict[JobState, str] = {
    JobState.RECEIVED: "접수",
    JobState.INVESTIGATING: "조사 중",
    JobState.REPORTING: "보고 작성 중",
    JobState.COMPLETED: "완료",
    JobState.PARTIAL: "부분 완료",
    JobState.FAILED: "실패",
    JobState.CANCELLED: "취소됨",
}

_TOOL_PHRASES: dict[str, str] = {
    TOOL_CORPUS_SEARCH: "내부 코퍼스에서 유사 연구 검색 중",
    TOOL_FORM_EVIDENCE: "문헌 근거표 형성 중",
    TOOL_GITHUB_SEARCH: "구현체·baseline 단서 탐색 중",
    TOOL_DATASET_SEARCH: "데이터셋 후보 탐색 중",
    TOOL_VIEW_FIGURE: "논문 그림·수식 확인 중",
    TOOL_SAVE_ARTIFACT: "산출물 검증·저장 중",
}


def describe_state(state: JobState) -> str:
    return _STATE_LABELS.get(state, state.value)


def project_feed(records: list[ToolCallRecord]) -> list[ActivityFeedItem]:
    """레코드별 오류는 건너뛴다 — 피드 생성 실패가 잡을 실패시키지 않는다."""
    items: list[ActivityFeedItem] = []
    for record in records:
        try:
            items.append(
                ActivityFeedItem(
                    seq=record.seq,
                    text=_phrase(record),
                    tool=record.tool_name,
                    query_summary=record.args_summary[:200],
                    occurred_at=record.finished_at,
                )
            )
        except Exception:  # noqa: BLE001 — best-effort side path(파생 뷰)
            continue
    return items


def _phrase(record: ToolCallRecord) -> str:
    base = _TOOL_PHRASES.get(record.tool_name, "조사 작업 진행 중")
    if record.outcome is ToolOutcome.OK:
        return base
    if record.outcome is ToolOutcome.REJECTED_BY_GATE:
        return "산출물 검증 미통과 — 보완 중"
    if record.outcome is ToolOutcome.BUDGET_DENIED:
        return "예산 한도 도달"
    return f"{base} — 일시적 오류, 대체 경로 시도"
