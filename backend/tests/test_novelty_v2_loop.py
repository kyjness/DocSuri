"""루프 코어 결정론 검증 — 스크립트 LLM 재생(nfr-design-patterns §7).

completed/partial/게이트 거부 재시도/취소/트레이스 실패 주입 + PBT-RA3
(도구 호출 ↔ ToolCallRecord 1:1, seq 무결).
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.modules.novelty.domain.loop import LoopDeps, run_loop
from backend.modules.novelty.domain.models import (
    AgentLoopRun,
    ArtifactKind,
    ChatKind,
    ChatRole,
    InputType,
    JobState,
    LoopBudget,
    NoveltyChatMessage,
    NoveltyJob,
    NoveltyJobRequest,
    TerminationReason,
    ToolOutcome,
)
from backend.modules.novelty.ports.llm import (
    LlmDecision,
    TerminationProposal,
    ToolCallProposal,
)
from backend.modules.novelty.ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_FORM_EVIDENCE,
    TOOL_SAVE_ARTIFACT,
    ToolRegistry,
    ToolResult,
)
from backend.modules.novelty.settings import TOOL_CAP_GROUPS

from .novelty_v2_fakes import FakeTool, InMemoryNoveltyStore, ScriptedToolCallingLlm

_REFS = ("rec:paper-1", "rec:paper-2")


def _budget(**overrides) -> LoopBudget:
    values = dict(
        max_iterations=24,
        max_tool_calls_total=40,
        max_tool_calls={"search": 12, "form_evidence": 4, "save_artifact": 12},
        tool_cap_groups=dict(TOOL_CAP_GROUPS),
        token_cost_limit_usd=0.5,
    )
    values.update(overrides)
    return LoopBudget(**values)


def _job(
    store: InMemoryNoveltyStore,
    input_type: InputType = InputType.NATURAL_LANGUAGE,
    budget: LoopBudget | None = None,
) -> NoveltyJob:
    job = NoveltyJob(
        owner_id=str(uuid4()),
        request=NoveltyJobRequest(
            input_type=input_type,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
            manuscript_ref=(
                None
                if input_type is InputType.NATURAL_LANGUAGE
                else {"file_name": "draft.pdf", "content_type": "application/pdf"}
            ),
        ),
        loop_run=AgentLoopRun(budget=budget or _budget()),
    )
    store.create_job(job)
    return job


def _evidence_tool() -> FakeTool:
    snapshot = {
        "state": "ok",
        "claims": [{"statement": "s1", "supporting": [], "conflicting": []}],
    }
    return FakeTool(
        TOOL_FORM_EVIDENCE,
        default=ToolResult(
            ok=True,
            content={"evidence": snapshot},
            result_summary="evidence formed: 1 claim",
            record_refs=_REFS,
        ),
    )


def _corpus_tool() -> FakeTool:
    return FakeTool(
        TOOL_CORPUS_SEARCH,
        default=ToolResult(
            ok=True,
            content={"items": [{"title": "Sparse retrieval under DP"}]},
            result_summary="3 findings",
            record_refs=_REFS,
        ),
    )


def _registry(*tools: FakeTool) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    return registry


def _ref(record_ref: str = "rec:paper-1") -> dict:
    return {"paperId": "2401.00001", "recordRef": record_ref}


def _similar_payload() -> dict:
    return {
        "items": [
            {
                "artifact_type": "paper",
                "title": "Sparse retrieval under DP",
                "evidence_status": "supported",
                "source_refs": [_ref()],
            }
        ]
    }


def _gap_payload(**item_overrides) -> dict:
    item = {
        "area": "sparse retrieval + privacy",
        "status": "partially_covered",
        "rationale": "관련 연구 존재하나 결합 평가 부재",
        "source_refs": [_ref()],
    }
    item.update(item_overrides)
    return {"items": [item]}


def _save(kind: str, payload: dict) -> LlmDecision:
    return LlmDecision(
        ToolCallProposal(TOOL_SAVE_ARTIFACT, {"kind": kind, "payload": payload})
    )


def test_happy_path_completes_with_gapless_trace() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "privacy rag"})),
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.COMPLETED
    assert stored.completed_at is not None
    kinds = {rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)}
    # Evidence First 자동 보존 포함 — 필수 세트 완성(BR-RA1).
    assert {
        ArtifactKind.EVIDENCE, ArtifactKind.SIMILAR_WORKS, ArtifactKind.GAP_ANALYSIS
    } <= kinds
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    assert [rec.seq for rec in trace] == list(range(1, len(trace) + 1))
    assert trace[0].tool_name == TOOL_FORM_EVIDENCE  # 선행 강제(BR-NV2)
    assert all(rec.outcome is ToolOutcome.OK for rec in trace)
    assert stored.loop_run.termination_reason is TerminationReason.ARTIFACTS_COMPLETE


def test_budget_exhaustion_ends_partial_keeping_saved_artifacts() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(max_tool_calls_total=3))
    llm = ScriptedToolCallingLlm(
        [
            _save("similar_works", _similar_payload()),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q2"})),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q3"})),  # 총 상한 초과
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.PARTIAL
    kinds = {rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)}
    assert ArtifactKind.SIMILAR_WORKS in kinds  # 검증·저장분 유지(BLM §9)
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    assert trace[-1].outcome is ToolOutcome.BUDGET_DENIED
    # budget_denied 레코드는 실행 없음 — 소비는 상한(3)까지만.
    assert stored.loop_run.budget.consumed.tool_calls_total == 3


def test_cost_exhaustion_ends_partial() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(token_cost_limit_usd=0.4))
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(
                ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q1"}),
                cost_estimate_usd=0.45,
            ),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q2"})),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)
    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    assert store.get_job(job.owner_id, job.job_id).state is JobState.PARTIAL


def test_gate_rejection_recorded_then_retry_succeeds() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    llm = ScriptedToolCallingLlm(
        [
            _save("gap_analysis", _gap_payload(source_refs=[])),  # 거부
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),  # 재시도 성공
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    outcomes = [rec.outcome for rec in trace if rec.tool_name == TOOL_SAVE_ARTIFACT]
    assert outcomes == [ToolOutcome.REJECTED_BY_GATE, ToolOutcome.OK, ToolOutcome.OK]
    # 거부 사유가 다음 관찰에 노출된다(재시도 근거).
    rejected_views = [
        view
        for observation in llm.observations
        for view in observation.recent_results
        if not view.ok
    ]
    assert any("missing_source_refs" in (view.error or "") for view in rejected_views)


def test_cancel_between_turns_is_cooperative() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)

    def cancel_then_search(observation):
        store.request_cancel(job.owner_id, job.job_id)
        return LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))

    llm = ScriptedToolCallingLlm([cancel_then_search])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.CANCELLED
    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.CANCELLED
    # 협조적 취소 — 진행 중이던 도구 호출은 완료되어 트레이스에 남는다(BR-RA8).
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    assert trace[-1].tool_name == TOOL_CORPUS_SEARCH
    assert trace[-1].outcome is ToolOutcome.OK


def test_termination_proposal_without_required_set_is_not_accepted() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(TerminationProposal(note="충분함")),  # 불수용(BR-RA1)
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    assert any(
        any("종료 제안 불수용" in note for note in observation.notes)
        for observation in llm.observations
    )


def test_manuscript_job_has_no_forced_form_evidence() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store, input_type=InputType.MANUSCRIPT)
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_FORM_EVIDENCE, {"topic": "t"})),
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)
    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    # 첫 결정 시점의 관찰이 비어 있다 = 강제 선행 없이 LLM 자율 선택으로 시작.
    assert llm.observations[0].recent_results == ()


def test_natural_job_without_evidence_tool_fails_fast() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    llm = ScriptedToolCallingLlm([])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.FATAL_ERROR
    assert store.get_job(job.owner_id, job.job_id).state is JobState.FAILED


class _FlakyTraceStore(InMemoryNoveltyStore):
    def __init__(self, fail_times: int) -> None:
        super().__init__()
        self._fail_times = fail_times

    def append_trace(self, record) -> None:
        if self._fail_times > 0:
            self._fail_times -= 1
            raise RuntimeError("trace store down")
        super().append_trace(record)


def test_transient_trace_failure_does_not_fail_tool_call() -> None:
    store = _FlakyTraceStore(fail_times=1)  # 첫 시도 실패 → 재시도 성공
    job = _job(store)
    llm = ScriptedToolCallingLlm(
        [_save("similar_works", _similar_payload()), _save("gap_analysis", _gap_payload())]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)
    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    assert [rec.seq for rec in trace] == list(range(1, len(trace) + 1))


def test_persistent_trace_failure_halts_loop() -> None:
    store = _FlakyTraceStore(fail_times=99)
    job = _job(store)
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q1"})),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q2"})),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q3"})),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    # 트레이스는 계약 — 기록 없는 실행을 계속하지 않는다(NFR-NV2-13).
    assert outcome.reason is TerminationReason.FATAL_ERROR
    assert store.get_job(job.owner_id, job.job_id).state is JobState.FAILED


def test_tool_error_returned_to_agent_then_degraded_source_recorded() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    failing = FakeTool(
        TOOL_CORPUS_SEARCH,
        default=ToolResult(ok=False, error="upstream 500", result_summary="corpus error"),
    )
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q1"})),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q2"})),
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), failing))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    stored = store.get_job(job.owner_id, job.job_id)
    # 지속 실패 소스는 저하 기록, 잡은 나머지로 진행(BR-NV16).
    assert TOOL_CORPUS_SEARCH in stored.degraded_sources


# ── PBT-RA3: 실행된 도구 호출 ↔ ToolCallRecord 1:1, seq 무결 ──

_DECISION_POOL = st.sampled_from(
    [
        LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})),
        LlmDecision(ToolCallProposal("unknown_tool", {})),
        _save("similar_works", _similar_payload()),
        _save("gap_analysis", _gap_payload(source_refs=[])),
        _save("gap_analysis", _gap_payload()),
        LlmDecision(TerminationProposal()),
    ]
)


@given(script=st.lists(_DECISION_POOL, max_size=20))
def test_pbt_ra3_trace_one_to_one_and_gapless(script) -> None:
    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(max_iterations=25))
    evidence, corpus = _evidence_tool(), _corpus_tool()
    llm = ScriptedToolCallingLlm(
        [*script, _save("similar_works", _similar_payload()), _save("gap_analysis", _gap_payload())]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(evidence, corpus))

    run_loop(job, deps)

    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=200)
    # seq 무결 — 빈틈없이 단조 증가.
    assert [rec.seq for rec in trace] == list(range(1, len(trace) + 1))

    # 실행된 도구 호출 ↔ 레코드 1:1 — budget_denied 레코드는 실행이 없어야 한다.
    def executed_records(tool_name: str) -> int:
        return sum(
            1
            for rec in trace
            if rec.tool_name == tool_name and rec.outcome is not ToolOutcome.BUDGET_DENIED
        )

    assert executed_records(TOOL_CORPUS_SEARCH) == len(corpus.calls)
    assert executed_records(TOOL_FORM_EVIDENCE) == len(evidence.calls)


def test_notion_can_never_join_registry() -> None:
    registry = ToolRegistry()
    with pytest.raises(ValueError):
        registry.register(FakeTool("notion_export"))


def test_registry_is_deny_by_default_allowlist() -> None:
    # BR-RA12 구조화 — 어휘 밖 도구는 이름 패턴과 무관하게 등록 불가.
    registry = ToolRegistry()
    with pytest.raises(ValueError):
        registry.register(FakeTool("export_to_page"))  # notion 접두사 없이도 거부


def test_notion_cannot_even_be_allowlisted() -> None:
    # 확장 경로(allowed_names)로도 Notion 계열은 합류 불가 — 생성자가 거부.
    with pytest.raises(ValueError):
        ToolRegistry(allowed_names={"corpus_search", "export_to_notion"})
    # 정상 확장은 허용된다(신규 도구의 어휘 확장 경로).
    registry = ToolRegistry(allowed_names={"corpus_search", "mcp_paper_qa"})
    registry.register(FakeTool("mcp_paper_qa"))
    assert "mcp_paper_qa" in registry.names()


# ── 코드 리뷰 반영(1단계) 회귀 테스트 ──


def test_redelivered_job_resumes_from_saved_artifacts() -> None:
    """crash 재전달: 저장된 산출물·출처 핸들을 시드해 작업·예산을 이중 소진하지 않는다."""
    from backend.modules.novelty.domain.models import ArtifactRecord

    store = InMemoryNoveltyStore()
    job = _job(store)
    # 이전 실행이 남긴 검증본 — evidence(자동 보존분) + similar_works.
    evidence_payload = {
        "state": "ok",
        "claims": [
            {"statement": "s1", "supporting": [_ref()], "conflicting": []}
        ],
    }
    for kind, payload in (
        (ArtifactKind.EVIDENCE, evidence_payload),
        (ArtifactKind.SIMILAR_WORKS, _similar_payload()),
    ):
        store.save_artifact(
            ArtifactRecord(job_id=job.job_id, owner_id=job.owner_id, kind=kind, payload=payload)
        )
    evidence_tool = _evidence_tool()
    # 남은 것은 gap 하나 — 이전 실행이 확보한 rec:paper-1을 인용해도 게이트 통과해야 한다.
    llm = ScriptedToolCallingLlm([_save("gap_analysis", _gap_payload())])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(evidence_tool, _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    assert evidence_tool.calls == []  # Evidence First 재강제 없음(이미 보존됨)
    assert any(
        any("재개된 잡" in note for note in observation.notes) for observation in llm.observations
    )


def test_budget_consumption_is_persisted_every_turn() -> None:
    """실행 중 스냅샷이 소비를 반영한다 — crash 재시작이 전액 예산으로 되돌지 않는다."""
    store = InMemoryNoveltyStore()
    job = _job(store)

    observed: dict[str, int] = {}

    def second_decision(observation):
        stored = store.get_job_for_worker(job.job_id)
        observed["tool_calls"] = stored.loop_run.budget.consumed.tool_calls_total
        observed["iterations"] = stored.loop_run.iteration_count
        raise RuntimeError("simulated crash mid-run")

    llm = ScriptedToolCallingLlm(
        [LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q1"})), second_decision]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.FATAL_ERROR
    # 두 번째 결정 시점(중간)에 이미 소비가 영속돼 있다(선행 evidence + corpus 1회).
    assert observed["tool_calls"] >= 2
    stored = store.get_job_for_worker(job.job_id)
    assert stored.loop_run.budget.consumed.tool_calls_total >= 2


def test_concurrent_terminal_write_wins_and_loop_does_not_crash() -> None:
    """스윕 등 다른 기록자가 먼저 종단시킨 잡 — 최초 종단 기록이 승리(BR-RA5)하고
    완주한 루프는 예외 없이 결과만 반환한다."""
    store = InMemoryNoveltyStore()
    job = _job(store)

    def save_gap_after_sweep(observation):
        # 마지막 저장 직전, 외부 기록자가 잡을 FAILED로 종단시킨 상황을 재현.
        store._jobs[job.job_id].state = JobState.FAILED  # noqa: SLF001 — 경합 재현
        return _save("gap_analysis", _gap_payload())

    llm = ScriptedToolCallingLlm(
        [_save("similar_works", _similar_payload()), save_gap_after_sweep]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)  # 예외가 밖으로 새지 않는다

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    assert store.get_job_for_worker(job.job_id).state is JobState.FAILED


def test_manuscript_record_ref_is_citable() -> None:
    """업로드 원고의 recordRef는 실재 출처로 시드된다 — 원고 인용 산출물이 게이트를 통과."""
    store = InMemoryNoveltyStore()
    job = NoveltyJob(
        owner_id=str(uuid4()),
        request=NoveltyJobRequest(
            input_type=InputType.MANUSCRIPT,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
            manuscript_ref={
                "file_name": "draft.pdf",
                "content_type": "application/pdf",
                "record_ref": "upload:o1:j1:manuscript",
            },
        ),
        loop_run=AgentLoopRun(budget=_budget()),
    )
    store.create_job(job)
    manuscript_similar = {
        "items": [
            {
                "artifact_type": "paper",
                "title": "사용자 원고",
                "evidence_status": "supported",
                "source_refs": [
                    {"paperId": "userdoc:abc", "recordRef": "upload:o1:j1:manuscript"}
                ],
            }
        ]
    }
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_FORM_EVIDENCE, {"topic": "t"})),
            _save("similar_works", manuscript_similar),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=20)
    saves = [rec for rec in trace if rec.tool_name == TOOL_SAVE_ARTIFACT]
    assert all(rec.outcome is ToolOutcome.OK for rec in saves)


def test_evidence_auto_save_rejection_is_observable() -> None:
    """자동 보존 거부는 트레이스 요약·다음 관찰 노트로 표면화된다(무기록 실패 금지)."""
    store = InMemoryNoveltyStore()
    job = _job(store)
    empty_evidence = FakeTool(
        TOOL_FORM_EVIDENCE,
        default=ToolResult(
            ok=True,
            content={"evidence": {"state": "ok", "claims": []}},  # 게이트 거부 대상
            result_summary="evidence formed: 0 claims",
            record_refs=_REFS,  # 출처 핸들은 확보 — 스냅샷 형태만 불량인 경우
        ),
    )
    llm = ScriptedToolCallingLlm(
        [
            _save("evidence", {"state": "abstain", "claims": [], "abstain_reason": "few"}),
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(empty_evidence, _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=20)
    assert "auto-save rejected" in trace[0].result_summary
    assert any(
        any("자동 보존 거부" in note for note in observation.notes)
        for observation in llm.observations
    )


def test_observation_result_seq_is_monotonic_past_window() -> None:
    """관찰 뷰 순번은 윈도우(6) 절단 후에도 중복 없이 단조 증가한다."""
    store = InMemoryNoveltyStore()
    job = _job(store)
    searches = [
        LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": f"q{i}"})) for i in range(9)
    ]
    llm = ScriptedToolCallingLlm(
        [
            *searches,
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    last = llm.observations[-1]
    seqs = [view.seq for view in last.recent_results]
    assert seqs == sorted(set(seqs))  # 중복 없음·오름차순
    assert len(seqs) <= 6 and seqs[-1] > 6  # 윈도우 절단 후에도 전역 순번 유지


# ── 대화 스티어링 (FR-44, BLM §6) ───────────────────────────────────────────


def _steer(store, job, content: str, *, role: ChatRole = ChatRole.USER) -> NoveltyChatMessage:
    message = NoveltyChatMessage(
        job_id=job.job_id,
        owner_id=job.owner_id,
        role=role,
        kind=ChatKind.STEERING if role is ChatRole.USER else ChatKind.AGENT_REPLY,
        content=content,
    )
    store.append_message(message)
    return message


def _finish() -> list[LlmDecision]:
    """필수 세트를 채워 루프를 정상 종료시키는 스크립트 꼬리."""
    return [_save("similar_works", _similar_payload()), _save("gap_analysis", _gap_payload())]


def test_steering_message_reaches_the_next_decide_not_the_current_one() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)

    def steer_then_search(observation):
        # 이 턴의 관찰에는 아직 없어야 한다 — 주입은 '다음 decide' 시점이다.
        assert observation.steering == ()
        _steer(store, job, "BM25 계열 위주로 봐줘")
        return LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))

    llm = ScriptedToolCallingLlm([steer_then_search, *_finish()])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    assert llm.observations[0].steering == ()
    assert llm.observations[1].steering == ("BM25 계열 위주로 봐줘",)


def test_steering_persists_across_turns_within_window() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)

    def steer_then_search(observation):
        _steer(store, job, "재현성 있는 baseline 위주")
        return LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))

    llm = ScriptedToolCallingLlm([steer_then_search, *_finish()])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    # 매 턴 새 요청을 만드는 구조라 1회성 주입이면 지시가 곧 사라진다 —
    # 이후 모든 관찰이 계속 지시를 들고 있어야 기능이 성립한다.
    assert all(obs.steering == ("재현성 있는 baseline 위주",) for obs in llm.observations[1:])


def test_steering_window_is_bounded() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    for i in range(5):
        _steer(store, job, f"지시-{i}")

    llm = ScriptedToolCallingLlm(_finish())
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    assert llm.observations[0].steering == ("지시-2", "지시-3", "지시-4")


def test_agent_messages_are_never_drained_as_steering() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    _steer(store, job, "에이전트 답장입니다", role=ChatRole.AGENT)
    _steer(store, job, "사용자 지시입니다")

    llm = ScriptedToolCallingLlm(_finish())
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    # kind가 아니라 role로 거른다 — 아니면 루프가 자기 출력을 되먹는다.
    assert llm.observations[0].steering == ("사용자 지시입니다",)


def test_steering_produces_no_tool_call_record() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    _steer(store, job, "지시")

    llm = ScriptedToolCallingLlm(_finish())
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    # 스티어링은 도구 호출이 아니다 — 트레이스 1:1(BR-RA4)을 깨지 않는다.
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    assert {rec.tool_name for rec in trace} == {
        TOOL_FORM_EVIDENCE, TOOL_SAVE_ARTIFACT,
    }
    # 노트에는 수신 사실만 남고 사용자 문장은 들어가지 않는다(신뢰 구획 보호).
    notes = [note for obs in llm.observations for note in obs.notes]
    assert any("사용자 스티어링 1건 수신" in note for note in notes)
    assert not any("지시" == note for note in notes)


class _SteeringUnavailableStore(InMemoryNoveltyStore):
    def list_messages(self, owner_id, job_id, *, after, limit):
        raise RuntimeError("message store down")


def test_steering_drain_failure_does_not_kill_the_turn() -> None:
    store = _SteeringUnavailableStore()
    job = _job(store)

    llm = ScriptedToolCallingLlm(_finish())
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    # 대화 조회 실패는 best-effort — 조사 자체를 실패시키지 않는다.
    assert outcome.reason is TerminationReason.ARTIFACTS_COMPLETE
    assert all(obs.steering == () for obs in llm.observations)


def test_unknown_steering_cursor_resets_instead_of_wedging() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)
    dropped = _steer(store, job, "곧 사라질 메시지")

    def drop_cursor_anchor(observation):
        # 커서가 가리키던 메시지가 사라진 상황(잡 삭제 경합 등)을 만든다.
        store._messages[job.job_id] = []  # noqa: SLF001 — 커서 유실 주입
        _steer(store, job, "새 지시")
        return LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))

    llm = ScriptedToolCallingLlm([drop_cursor_anchor, *_finish()])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    assert llm.observations[0].steering == (dropped.content,)
    # 커서가 박히지 않고 다시 앵커해 이후 지시를 읽는다.
    assert "새 지시" in llm.observations[-1].steering


def test_late_steering_after_terminal_yields_notice() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store)

    def steer_on_last_turn(observation):
        # 이 턴이 필수 세트를 완성시켜 루프가 끝난다 — 지시는 드레인될 기회가 없다.
        _steer(store, job, "종료 직전에 도착한 지시")
        return _save("gap_analysis", _gap_payload())

    llm = ScriptedToolCallingLlm(
        [_save("similar_works", _similar_payload()), steer_on_last_turn]
    )
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    run_loop(job, deps)

    messages = store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
    notices = [m for m in messages if m.kind is ChatKind.NOTICE]
    # 종단 뒤 도착한 메시지는 읽을 주체가 없다 — 조용히 버리지 않고 안내를 남긴다.
    assert len(notices) == 1
    assert notices[0].role is ChatRole.AGENT


def test_steering_is_not_consumed_when_budget_denies_the_turn() -> None:
    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(max_iterations=1))

    def steer_then_search(observation):
        _steer(store, job, "예산 소진 직전에 보낸 지시")
        return LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))

    llm = ScriptedToolCallingLlm([steer_then_search])
    deps = LoopDeps(store=store, llm=llm, registry=_registry(_evidence_tool(), _corpus_tool()))

    outcome = run_loop(job, deps)

    assert outcome.reason is TerminationReason.BUDGET_EXHAUSTED
    # 드레인 위치 회귀 가드: 예산 검사보다 앞에서 읽으면 커서만 전진하고 decide는
    # 일어나지 않아 지시가 증발한다. 뒤에서 읽으므로 미소비로 남고 안내가 나간다.
    messages = store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
    assert any(m.kind is ChatKind.NOTICE for m in messages)


def test_viewed_figure_is_attached_for_one_turn_then_drops_to_text() -> None:
    """관찰은 최근 결과를 매 턴 다시 싣는다 — 이미지까지 그러면 같은 토큰이 반복 계상된다.

    직전 1턴만 이미지를 남기고, 그 다음 턴부터는 텍스트 content만 남는다(무엇을 봤는지는
    계속 알 수 있고, 다시 보려면 재호출하면 된다 — BR-RA11 비용 계상).
    """
    from backend.modules.novelty.ports.tools import TOOL_VIEW_FIGURE, ImageAttachment

    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(max_tool_calls={**_budget().max_tool_calls, "view_figure": 8}))
    figure_tool = FakeTool(
        TOOL_VIEW_FIGURE,
        default=ToolResult(
            ok=True,
            content={"assetId": "fig-1", "type": "figure"},
            result_summary="figure: figure fig-1",
            images=(
                ImageAttachment(
                    media_type="image/webp", data_b64="QUJD", asset_id="fig-1"
                ),
            ),
        ),
    )
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_VIEW_FIGURE, {"record_ref": "2401.00001"})),
            LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})),
            LlmDecision(TerminationProposal(note="done")),
        ]
    )
    deps = LoopDeps(
        store=store,
        llm=llm,
        registry=_registry(_evidence_tool(), _corpus_tool(), figure_tool),
    )

    run_loop(job, deps)

    # 관찰 0: form_evidence 선행 뒤 첫 결정(아직 그림 없음)
    # 그림 조회 직후 관찰에는 이미지가 실린다.
    after_view = next(
        obs for obs in llm.observations
        if any(view.tool_name == TOOL_VIEW_FIGURE for view in obs.recent_results)
    )
    figure_views = [v for v in after_view.recent_results if v.tool_name == TOOL_VIEW_FIGURE]
    assert figure_views[-1].images  # 직전 결과 = 이미지 있음

    # 그 다음 관찰에서는 같은 결과가 이미지 없이 남는다.
    later = llm.observations[llm.observations.index(after_view) + 1]
    stale = [v for v in later.recent_results if v.tool_name == TOOL_VIEW_FIGURE]
    assert stale and all(view.images == () for view in stale)
    # 텍스트 content는 그대로 — 무엇을 봤는지는 계속 보인다.
    assert stale[-1].content["assetId"] == "fig-1"


def test_image_is_not_resent_when_a_termination_proposal_is_refused() -> None:
    """종료 제안이 거부되면 루프는 도구 실행 없이 decide로 되돈다(loop `_drive`).

    첨부 소비를 도구 실행 뒤에 두면 그 경로에서 같은 그림이 매 반복 재전송돼
    반복 상한까지 같은 토큰이 계상된다 — 관찰 조립이 소비 지점인 이유다.
    """
    from backend.modules.novelty.ports.tools import TOOL_VIEW_FIGURE, ImageAttachment

    store = InMemoryNoveltyStore()
    job = _job(store, budget=_budget(max_tool_calls={**_budget().max_tool_calls, "view_figure": 8}))
    figure_tool = FakeTool(
        TOOL_VIEW_FIGURE,
        default=ToolResult(
            ok=True,
            content={"assetId": "fig-1", "type": "figure"},
            images=(ImageAttachment(media_type="image/webp", data_b64="QUJD", asset_id="fig-1"),),
        ),
    )
    llm = ScriptedToolCallingLlm(
        [
            LlmDecision(ToolCallProposal(TOOL_VIEW_FIGURE, {"record_ref": "2401.00001"})),
            # 필수 산출물이 없어 거부된다 — 도구 실행 없이 다음 decide로 되돈다.
            LlmDecision(TerminationProposal(note="충분")),
            LlmDecision(TerminationProposal(note="정말 충분")),
            _save("similar_works", _similar_payload()),
            _save("gap_analysis", _gap_payload()),
        ]
    )
    deps = LoopDeps(
        store=store,
        llm=llm,
        registry=_registry(_evidence_tool(), _corpus_tool(), figure_tool),
    )

    run_loop(job, deps)

    with_images = [
        obs for obs in llm.observations
        if any(view.images for view in obs.recent_results)
    ]
    # 조회 직후 관찰 딱 한 번 — 거부된 종료 제안이 두 번 되돌아도 재전송되지 않는다.
    assert len(with_images) == 1
