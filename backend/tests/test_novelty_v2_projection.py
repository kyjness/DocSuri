"""트레이스 → 활동 피드 투영(FR-35) — 파생 뷰, 민감 정보 재은닉(SECURITY-09)."""

from __future__ import annotations

from backend.modules.novelty.domain.models import (
    JobState,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
)
from backend.modules.novelty.domain.projection import describe_state, project_feed


def _record(tool: str, outcome: ToolOutcome, seq: int = 1) -> ToolCallRecord:
    now = utc_now()
    return ToolCallRecord(
        job_id="j1",
        seq=seq,
        tool_name=tool,
        args_summary="query='privacy rag'",
        result_summary="3 findings",
        outcome=outcome,
        started_at=now,
        finished_at=now,
    )


def test_feed_projects_user_phrases_per_tool_and_outcome() -> None:
    records = [
        _record("corpus_search", ToolOutcome.OK, seq=1),
        _record("save_artifact", ToolOutcome.REJECTED_BY_GATE, seq=2),
        _record("github_search", ToolOutcome.ERROR, seq=3),
        _record("corpus_search", ToolOutcome.BUDGET_DENIED, seq=4),
    ]
    feed = project_feed(records)
    assert [item.seq for item in feed] == [1, 2, 3, 4]
    assert "검색 중" in feed[0].text
    assert "검증 미통과" in feed[1].text
    assert "오류" in feed[2].text
    assert "예산 한도" in feed[3].text
    # 내부 상세(도구 어댑터 오류 원문)는 문구에 노출되지 않는다.
    assert "500" not in feed[2].text


def test_unknown_tool_gets_generic_phrase_and_never_raises() -> None:
    feed = project_feed([_record("mystery_tool", ToolOutcome.OK)])
    assert feed and "진행 중" in feed[0].text


def test_state_labels_are_korean_macro_states() -> None:
    assert describe_state(JobState.INVESTIGATING) == "조사 중"
    assert describe_state(JobState.PARTIAL) == "부분 완료"
