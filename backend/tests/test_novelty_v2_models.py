"""Novelty v2 도메인 모델 게이트 — PBT-NV1(SourceRef 왕복)·PBT-NV4(거시 상태 전이).

설계 근거: novelty-agent-v2 domain-entities.md, business-rules.md Progress State Rules.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.modules.novelty.domain.models import (
    ALLOWED_TRANSITIONS,
    REQUIRED_ARTIFACT_KINDS,
    TERMINAL_STATES,
    AgentLoopRun,
    ArtifactKind,
    GapItem,
    GapStatus,
    InputType,
    InvalidTransitionError,
    JobState,
    LoopBudget,
    NoveltyJobRequest,
    SourceRef,
    TerminationReason,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
    validate_transition,
)

_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters=".-_/: "),
    min_size=1,
    max_size=80,
).map(str.strip).filter(bool)


# ── PBT-NV1: SourceRef 왕복 — serialize/deserialize 후 identity·anchor 보존 ──


@given(
    paper_id=_ids,
    record_ref=_ids,
    anchor=st.none() | _ids,
    quote=st.none() | st.text(min_size=1, max_size=200),
)
def test_pbt_nv1_source_ref_roundtrip(paper_id, record_ref, anchor, quote) -> None:
    ref = SourceRef(paperId=paper_id, recordRef=record_ref, anchor=anchor, quote=quote)
    restored = SourceRef.model_validate_json(ref.model_dump_json())
    assert restored == ref
    # FR-47 — 객체 앵커(표·그림·수식 id)도 anchor 문자열로 수용된다.
    assert restored.anchor == anchor


# ── PBT-NV4: 거시 상태 전이 유효성 · 종단 재진입 금지 ──


@given(current=st.sampled_from(JobState), target=st.sampled_from(JobState))
def test_pbt_nv4_transition_validity(current: JobState, target: JobState) -> None:
    allowed = (
        current == target
        or (current not in TERMINAL_STATES and target in ALLOWED_TRANSITIONS[current])
    )
    if allowed:
        validate_transition(current, target)
    else:
        with pytest.raises(InvalidTransitionError):
            validate_transition(current, target)


def test_terminal_states_admit_no_transitions() -> None:
    for terminal in TERMINAL_STATES:
        for target in JobState:
            if target is terminal:
                continue
            with pytest.raises(InvalidTransitionError):
                validate_transition(terminal, target)


def test_cancel_and_fail_reachable_from_every_active_state() -> None:
    for state in JobState:
        if state in TERMINAL_STATES:
            continue
        validate_transition(state, JobState.CANCELLED)
        validate_transition(state, JobState.FAILED)


def test_macro_states_replace_legacy_enum() -> None:
    assert set(JobState) == {
        JobState.RECEIVED,
        JobState.INVESTIGATING,
        JobState.REPORTING,
        JobState.COMPLETED,
        JobState.PARTIAL,
        JobState.FAILED,
        JobState.CANCELLED,
    }
    assert set(TerminationReason) == {
        TerminationReason.ARTIFACTS_COMPLETE,
        TerminationReason.BUDGET_EXHAUSTED,
        TerminationReason.CANCELLED,
        TerminationReason.FATAL_ERROR,
    }


def test_required_artifact_set_is_the_v2_base_set() -> None:
    # BR-RA1 — EvidenceSnapshot + 유사 연구 표 + GapAnalysis.
    assert REQUIRED_ARTIFACT_KINDS == {
        ArtifactKind.EVIDENCE,
        ArtifactKind.SIMILAR_WORKS,
        ArtifactKind.GAP_ANALYSIS,
    }


# ── 엔티티 구조 규칙 ──


def test_job_request_requires_manuscript_ref_for_manuscript_input() -> None:
    with pytest.raises(ValueError):
        NoveltyJobRequest(
            input_type=InputType.MANUSCRIPT,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
        )


def test_tool_call_record_summary_lengths_are_bounded() -> None:
    # BR-RA4 — 트레이스는 sanitized '요약'만. 원문 통짜 저장을 모델이 거부한다.
    now = utc_now()
    with pytest.raises(ValueError):
        ToolCallRecord(
            job_id="j1",
            seq=1,
            tool_name="corpus_search",
            args_summary="x" * 2001,
            result_summary="ok",
            outcome=ToolOutcome.OK,
            started_at=now,
            finished_at=now,
        )


def test_open_gap_item_carries_scope_note_field() -> None:
    # 게이트(BR-RA10)가 강제할 필드가 모델에 존재하는지의 구조 확인.
    item = GapItem(
        area="sparse retrieval + privacy",
        status=GapStatus.OPEN_GAP,
        rationale="탐색 범위 내 직접 결합 연구 미발견",
        searched_scope_note="corpus_search 3회·github_search 1회 범위",
    )
    assert item.searched_scope_note


def test_loop_run_budget_values_are_injected_not_defaulted() -> None:
    # BR-RA3 — 도메인에 예산 상수 없음: LoopBudget은 값 없이 생성 불가.
    with pytest.raises(ValueError):
        LoopBudget()  # type: ignore[call-arg]
    run = AgentLoopRun(
        budget=LoopBudget(
            max_iterations=24, max_tool_calls_total=40, token_cost_limit_usd=0.5
        )
    )
    assert run.termination_reason is None


def test_loop_run_computed_fields_mirror_consumed() -> None:
    # iteration_count/tool_call_counts는 budget.consumed의 파생 뷰 — 이중 장부 금지.
    run = AgentLoopRun(
        budget=LoopBudget(max_iterations=24, max_tool_calls_total=40, token_cost_limit_usd=0.5)
    )
    run.budget.consumed.iterations = 3
    run.budget.consumed.tool_calls = {"corpus_search": 2, "save_artifact": 1}
    assert run.iteration_count == 3
    assert run.tool_call_counts == {"corpus_search": 2, "save_artifact": 1}
    dumped = run.model_dump(mode="json")  # 직렬화에도 포함(엔티티 계약 유지)
    assert dumped["iteration_count"] == 3
    assert dumped["tool_call_counts"]["corpus_search"] == 2
