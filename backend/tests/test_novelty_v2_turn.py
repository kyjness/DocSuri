"""온디맨드 대화 턴(BLM §5) — 같은 저장 게이트·종단 상태 불변·단일 턴 상한."""

from __future__ import annotations

from uuid import uuid4

from backend.modules.novelty.domain.loop import LoopDeps
from backend.modules.novelty.domain.models import (
    AgentLoopRun,
    ArtifactKind,
    ArtifactRecord,
    ChatKind,
    ChatRole,
    InputType,
    JobState,
    LoopBudget,
    NoveltyChatMessage,
    NoveltyJob,
    NoveltyJobRequest,
)
from backend.modules.novelty.domain.turn import TOOL_REPLY, run_turn
from backend.modules.novelty.ports.llm import (
    LlmDecision,
    TerminationProposal,
    ToolCallProposal,
)
from backend.modules.novelty.ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_SAVE_ARTIFACT,
    ToolRegistry,
    ToolResult,
)
from backend.modules.novelty.settings import TOOL_CAP_GROUPS

from .novelty_v2_fakes import FakeTool, InMemoryNoveltyStore, ScriptedToolCallingLlm

_KNOWN_REF = "rec:paper-1"


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


def _ref(record_ref: str = _KNOWN_REF) -> dict:
    return {"paperId": "2401.00001", "recordRef": record_ref}


def _completed_job(store: InMemoryNoveltyStore, *, budget: LoopBudget | None = None) -> NoveltyJob:
    """조사가 끝난 잡 — 산출물과 그 출처가 저장돼 있다."""
    job = NoveltyJob(
        owner_id=str(uuid4()),
        request=NoveltyJobRequest(
            input_type=InputType.NATURAL_LANGUAGE,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
        ),
        loop_run=AgentLoopRun(budget=budget or _budget()),
        state=JobState.COMPLETED,
    )
    store.create_job(job)
    store.save_artifact(
        ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id, kind=ArtifactKind.GAP_ANALYSIS,
            payload={
                "items": [
                    {
                        "area": "sparse retrieval + privacy",
                        "status": "partially_covered",
                        "rationale": "결합 평가 부재",
                        "source_refs": [_ref()],
                    }
                ]
            },
        )
    )
    return job


def _request(store: InMemoryNoveltyStore, job: NoveltyJob, content: str) -> NoveltyChatMessage:
    message = NoveltyChatMessage(
        job_id=job.job_id,
        owner_id=job.owner_id,
        role=ChatRole.USER,
        kind=ChatKind.ON_DEMAND_REQUEST,
        content=content,
    )
    store.append_message(message)
    return message


def _plan_payload(record_ref: str = _KNOWN_REF) -> dict:
    return {
        "hypothesis": "DP 노이즈 하에서 sparse retrieval이 dense보다 견고하다",
        "novelty_angle": "프라이버시 예산별 검색 방식 비교",
        "baselines": ["BM25", "DPR"],
        "datasets": ["MS MARCO"],
        "metrics": ["nDCG@10"],
        "procedure": ["ε 값을 바꿔가며 두 방식을 평가한다"],
        "risks": ["노이즈 주입 구현 차이"],
        "resources": ["GPU 1대"],
        "source_refs": [_ref(record_ref)],
    }


def _reply(content: str) -> LlmDecision:
    return LlmDecision(ToolCallProposal(TOOL_REPLY, {"content": content}))


def _save_plan(record_ref: str = _KNOWN_REF) -> LlmDecision:
    return LlmDecision(
        ToolCallProposal(
            TOOL_SAVE_ARTIFACT,
            {"kind": "experiment_plan", "payload": _plan_payload(record_ref)},
        )
    )


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            TOOL_CORPUS_SEARCH,
            default=ToolResult(ok=True, content={"items": []}, record_refs=("rec:new",)),
        )
    )
    return registry


def _deps(store, llm) -> LoopDeps:
    return LoopDeps(store=store, llm=llm, registry=_registry())


def _messages(store, job) -> list[NoveltyChatMessage]:
    return store.list_messages(job.owner_id, job.job_id, after=None, limit=50)


def test_turn_replies_without_saving_when_user_asks_a_question() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "여백 분석에서 가장 근거가 약한 항목이 뭐야?")
    llm = ScriptedToolCallingLlm([_reply("세 번째 항목의 근거가 가장 얇습니다.")])

    outcome = run_turn(job, message, _deps(store, llm), max_steps=4)

    assert outcome.artifact_ref is None
    reply = _messages(store, job)[-1]
    assert reply.role is ChatRole.AGENT
    assert reply.kind is ChatKind.AGENT_REPLY
    assert reply.resulting_artifact_ref is None
    # 산출물은 늘지 않는다 — 질문에 답만 한 턴이다.
    assert {rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)} == {
        ArtifactKind.GAP_ANALYSIS
    }


def test_turn_generates_experiment_plan_through_the_same_gate() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "이 여백으로 실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_save_plan(), _reply("실험 계획을 만들었어요.")])

    outcome = run_turn(job, message, _deps(store, llm), max_steps=4)

    kinds = {rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)}
    assert ArtifactKind.EXPERIMENT_PLAN in kinds
    reply = _messages(store, job)[-1]
    # 응답은 대화 턴으로 돌아가고 산출물 참조가 걸린다(BLM §5.5).
    assert reply.kind is ChatKind.AGENT_REPLY
    assert reply.resulting_artifact_ref == outcome.artifact_ref
    assert outcome.artifact_ref is not None


def test_turn_plan_citing_unknown_record_ref_is_rejected_then_retry_succeeds() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm(
        [
            _save_plan("rec:does-not-exist"),  # 게이트 거부
            _save_plan(),                       # 저장된 산출물에 실재하는 출처
            _reply("보완해서 만들었어요."),
        ]
    )

    run_turn(job, message, _deps(store, llm), max_steps=4)

    # 대화 경로라고 검증을 생략하지 않는다(BR-RA6) — 인용 가능한 출처는 저장된
    # 산출물에서 회수된 것뿐이다.
    rejected = [
        view
        for obs in llm.observations
        for view in obs.recent_results
        if not view.ok and (view.error or "").startswith("rejected_by_gate")
    ]
    assert rejected
    kinds = {rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)}
    assert ArtifactKind.EXPERIMENT_PLAN in kinds


def test_turn_gate_rejection_surfaces_as_notice_when_steps_exhausted() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_save_plan("rec:nope"), _save_plan("rec:nope")])

    run_turn(job, message, _deps(store, llm), max_steps=2)

    reply = _messages(store, job)[-1]
    # 침묵 종료 금지 — 사유가 사용자에게 전달돼야 재요청 판단이 가능하다.
    assert reply.kind is ChatKind.NOTICE
    assert "unknown_source_ref" in reply.content or "근거" in reply.content
    assert ArtifactKind.EXPERIMENT_PLAN not in {
        rec.kind for rec in store.list_artifacts(job.owner_id, job.job_id)
    }


def test_turn_never_changes_job_state() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    before = store.get_job_for_worker(job.job_id)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_save_plan(), _reply("완료")])

    run_turn(job, message, _deps(store, llm), max_steps=4)

    after = store.get_job_for_worker(job.job_id)
    # 종단 상태 재진입 금지(BR-RA5) — 생성은 대화 턴으로만 처리된다.
    assert after.state is JobState.COMPLETED
    assert after.completed_at == before.completed_at
    assert after.loop_run.termination_reason == before.loop_run.termination_reason


def test_turn_respects_max_steps_even_with_budget_remaining() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "계속 찾아봐")
    search = LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"}))
    llm = ScriptedToolCallingLlm([search] * 10)

    run_turn(job, message, _deps(store, llm), max_steps=3)

    # 잔여 예산이 넉넉해도 한 턴은 단일 턴이다(NFR-NV2-7).
    assert len(llm.observations) == 3
    assert store.get_job_for_worker(job.job_id).loop_run.budget.consumed.tool_calls_total == 3


def test_turn_refuses_without_an_llm_call_when_budget_exhausted() -> None:
    store = InMemoryNoveltyStore()
    # 조사가 반복 상한을 다 쓰고 끝난 잡(partial로 흔한 상태).
    spent = _budget(max_iterations=1)
    spent.consumed.iterations = 1
    job = _completed_job(store, budget=spent)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([])  # 호출되면 "exhausted"로 죽는다

    run_turn(job, message, _deps(store, llm), max_steps=4)

    assert llm.observations == []
    reply = _messages(store, job)[-1]
    assert reply.kind is ChatKind.NOTICE


def test_turn_termination_proposal_becomes_the_reply() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "요약해줘")
    # 어댑터는 평문 응답을 종료 제안으로 바꾼다 — 대화 턴에서는 그게 곧 답변이다.
    llm = ScriptedToolCallingLlm([LlmDecision(TerminationProposal(note="여백은 세 가지입니다."))])

    run_turn(job, message, _deps(store, llm), max_steps=4)

    reply = _messages(store, job)[-1]
    assert reply.kind is ChatKind.AGENT_REPLY
    assert reply.content == "여백은 세 가지입니다."


def test_turn_seeds_stored_artifacts_as_untrusted_tool_data() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_reply("네")])

    run_turn(job, message, _deps(store, llm), max_steps=4)

    observation = llm.observations[0]
    # 산출물 payload는 외부 논문 파생 데이터다 — '도구 결과' 구획으로 들어간다.
    assert any(
        view.tool_name == "saved_artifact:gap_analysis" for view in observation.recent_results
    )
    # 요청 본문과 실행 맥락이 관찰에 실린다.
    assert observation.mode == "turn"
    assert observation.request == "실험 계획 짜줘"
    # 대화 턴은 조사 재실행이 아니다 — 필수 산출물 미완성 목록을 들이밀지 않는다.
    assert observation.missing_required_kinds == frozenset()


def test_turn_does_not_replay_past_conversation_as_live_steering() -> None:
    """지난 턴의 요청·답장이 이번 턴의 '사용자 지시'로 되살아나면 안 된다.

    커서 없이 대화를 읽으면 가장 오래된 페이지가 잡혀, 이미 처리된 옛 요청이 살아
    있는 지시로 렌더되고 이번 요청은 request와 스티어링에 중복으로 실린다
    (코드 리뷰 반영 — 턴은 스티어링 윈도우를 승계하지 않는다).
    """
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    _request(store, job, "지난 턴의 요청 — BM25만 봐줘")
    message = _request(store, job, "이번 요청 — 실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_reply("네")])

    run_turn(job, message, _deps(store, llm), max_steps=4)

    observation = llm.observations[0]
    assert observation.steering == ()
    assert observation.request == "이번 요청 — 실험 계획 짜줘"


def test_turn_reply_points_back_at_the_request_it_answers() -> None:
    """답장은 어느 요청에 대한 것인지 남긴다 — 워커 멱등 판정의 근거다."""
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "실험 계획 짜줘")
    llm = ScriptedToolCallingLlm([_save_plan(), _reply("만들었어요")])

    run_turn(job, message, _deps(store, llm), max_steps=4)

    reply = _messages(store, job)[-1]
    assert reply.in_reply_to == message.message_id


def test_turn_reply_carries_artifact_ref_even_when_kind_was_already_saved() -> None:
    """이미 있는 kind를 갱신 저장해도 답장에 산출물 참조가 붙어야 한다.

    "이번에 새로 생긴 kind"로 판정하면 재저장이 참조 없이 나가 화면에 카드가
    안 붙는다 — 저장 시점에 받은 artifact_id가 판정 근거여야 한다.
    """
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    first = _request(store, job, "실험 계획 짜줘")
    run_turn(job, first, _deps(store, ScriptedToolCallingLlm([_save_plan(), _reply("v1")])),
             max_steps=4)
    saved_id = next(
        rec.artifact_id
        for rec in store.list_artifacts(job.owner_id, job.job_id)
        if rec.kind is ArtifactKind.EXPERIMENT_PLAN
    )

    second = _request(store, job, "계획 다시 짜줘")
    outcome = run_turn(
        job, second, _deps(store, ScriptedToolCallingLlm([_save_plan(), _reply("v2")])),
        max_steps=4,
    )

    assert outcome.artifact_ref == saved_id
    assert _messages(store, job)[-1].resulting_artifact_ref == saved_id


def test_turn_records_tool_calls_but_reply_leaves_no_trace() -> None:
    store = InMemoryNoveltyStore()
    job = _completed_job(store)
    message = _request(store, job, "더 찾아보고 알려줘")
    llm = ScriptedToolCallingLlm(
        [LlmDecision(ToolCallProposal(TOOL_CORPUS_SEARCH, {"query": "q"})), _reply("찾았어요")]
    )

    run_turn(job, message, _deps(store, llm), max_steps=4)

    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=50)
    # 실행된 도구는 1:1로 기록되고(BR-RA4), reply는 도구가 아니므로 기록되지 않는다.
    assert [rec.tool_name for rec in trace] == [TOOL_CORPUS_SEARCH]
