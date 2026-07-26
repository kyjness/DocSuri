"""v2 워커 — 큐 소비→잠금→루프 실행, 멱등·stale 감지·픽업 전 취소·crash 수렴."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

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
    TerminationReason,
    utc_now,
)
from backend.modules.novelty.domain.turn import TOOL_REPLY
from backend.modules.novelty.ports.llm import LlmDecision, ToolCallProposal
from backend.modules.novelty.ports.queue import KIND_TURN, QueuedJob
from backend.modules.novelty.ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_FORM_EVIDENCE,
    TOOL_SAVE_ARTIFACT,
    ToolRegistry,
    ToolResult,
)
from backend.modules.novelty.settings import TOOL_CAP_GROUPS, NoveltySettings
from backend.modules.novelty.worker import WorkerDeps, process_message, sweep_stale_jobs

from .novelty_v2_fakes import (
    FakeTool,
    InMemoryJobQueue,
    InMemoryNoveltyStore,
    ScriptedToolCallingLlm,
)

_REFS = ("rec:paper-1",)


def _settings(**overrides) -> NoveltySettings:
    from dataclasses import replace

    base = NoveltySettings(
        llm_provider="openai",
        openai_api_key="k",
        openai_model="m",
        openai_input_usd_per_mtok=0.15,
        openai_output_usd_per_mtok=0.60,
        bedrock_model_id="b",
        region_name=None,
        queue_url="redis://test",
        sqs_queue_url=None,
        github_token=None,
        external_timeout_seconds=5.0,
        lock_ttl_seconds=120.0,
        stale_after_seconds=900.0,
        max_iterations=24,
        max_tool_calls_total=40,
        max_search_calls=12,
        max_form_evidence_calls=4,
        max_view_figure_calls=8,
        max_save_artifact_calls=12,
        job_cost_limit_usd=0.5,
        max_turn_steps=4,
    )
    return replace(base, **overrides)


def _budget() -> LoopBudget:
    return LoopBudget(
        max_iterations=24,
        max_tool_calls_total=40,
        max_tool_calls={"search": 12},
        tool_cap_groups=dict(TOOL_CAP_GROUPS),
        token_cost_limit_usd=0.5,
    )


def _job(store: InMemoryNoveltyStore, *, with_run: bool = True) -> NoveltyJob:
    job = NoveltyJob(
        owner_id=str(uuid4()),
        request=NoveltyJobRequest(
            input_type=InputType.NATURAL_LANGUAGE,
            topic="privacy preserving RAG",
            evidence_request={"topic": "privacy preserving RAG"},
        ),
        loop_run=AgentLoopRun(budget=_budget()) if with_run else None,
    )
    store.create_job(job)
    return job


def _ref() -> dict:
    return {"paperId": "2401.00001", "recordRef": "rec:paper-1"}


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        FakeTool(
            TOOL_FORM_EVIDENCE,
            default=ToolResult(
                ok=True,
                content={
                    "evidence": {
                        "state": "ok",
                        "claims": [{"statement": "s", "supporting": [], "conflicting": []}],
                    }
                },
                record_refs=_REFS,
                result_summary="evidence formed",
            ),
        )
    )
    registry.register(
        FakeTool(
            TOOL_CORPUS_SEARCH,
            default=ToolResult(ok=True, content={"items": []}, record_refs=_REFS),
        )
    )
    return registry


def _happy_script() -> ScriptedToolCallingLlm:
    similar = {
        "items": [
            {
                "artifact_type": "paper",
                "title": "Sparse retrieval under DP",
                "evidence_status": "supported",
                "source_refs": [_ref()],
            }
        ]
    }
    gap = {
        "items": [
            {
                "area": "sparse retrieval + privacy",
                "status": "partially_covered",
                "rationale": "결합 평가 부재",
                "source_refs": [_ref()],
            }
        ]
    }
    return ScriptedToolCallingLlm(
        [
            LlmDecision(
                ToolCallProposal(TOOL_SAVE_ARTIFACT, {"kind": "similar_works", "payload": similar})
            ),
            LlmDecision(
                ToolCallProposal(TOOL_SAVE_ARTIFACT, {"kind": "gap_analysis", "payload": gap})
            ),
        ]
    )


def _deps(store, queue, llm) -> WorkerDeps:
    return WorkerDeps(
        store=store, queue=queue, llm=llm, registry=_registry(), settings=_settings(),
        sleep=lambda _seconds: None,  # 경합 백오프는 계약이 아니라 대기 — 테스트에서 생략
    )


def test_worker_runs_job_to_completion_with_trace(monkeypatch) -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    queue.enqueue(job.job_id, job.owner_id)
    deps = _deps(store, queue, _happy_script())

    message = queue.consume(0)
    process_message(deps, message)

    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.COMPLETED
    assert stored.loop_run.termination_reason is TerminationReason.ARTIFACTS_COMPLETE
    trace = store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=20)
    assert [rec.seq for rec in trace] == list(range(1, len(trace) + 1))
    assert trace[0].tool_name == TOOL_FORM_EVIDENCE  # Evidence First
    # 잠금은 해제되어 재획득 가능(멱등).
    assert queue.acquire(job.job_id, ttl_seconds=1) is True


def test_terminal_job_redelivery_is_acked_idempotently() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    job.state = JobState.INVESTIGATING
    store.update_job(job)
    job.state = JobState.COMPLETED
    store.update_job(job)
    queue.enqueue(job.job_id, job.owner_id)
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))
    assert store.get_job(job.owner_id, job.job_id).state is JobState.COMPLETED


def test_lock_contention_returns_message_to_queue() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    queue.enqueue(job.job_id, job.owner_id)
    assert queue.acquire(job.job_id, ttl_seconds=60) is True  # 다른 워커의 리스
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))
    # 실행되지 않았고(트레이스 없음) 잡 상태 불변.
    assert store.get_job(job.owner_id, job.job_id).state is JobState.RECEIVED
    # ack 생략에 기대지 않고 명시적으로 큐에 되돌린다 — 리스를 쥔 워커가 끝난 뒤
    # 재전달되어야 하며, 그때까지 메시지가 유실되거나 방치되면 안 된다.
    requeued = queue.consume(0)
    assert requeued is not None and requeued.job_id == job.job_id
    assert deps._contention_counts[job.job_id] == 1  # noqa: SLF001 — 백오프 카운터 계약


def test_contention_counter_resets_after_successful_pickup() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    queue.enqueue(job.job_id, job.owner_id)
    assert queue.acquire(job.job_id, ttl_seconds=60) is True
    deps = _deps(store, queue, _happy_script())

    process_message(deps, queue.consume(0))
    assert deps._contention_counts[job.job_id] == 1  # noqa: SLF001
    queue.release(job.job_id)  # 앞선 워커 종료
    process_message(deps, queue.consume(0))
    # 백오프는 연속 경합에만 걸린다 — 한 번 집어 실행하면 다음 경합은 다시 1초부터.
    assert job.job_id not in deps._contention_counts  # noqa: SLF001
    assert store.get_job(job.owner_id, job.job_id).state is JobState.COMPLETED


def test_contention_backoff_is_per_job_not_global() -> None:
    """잡 A의 경합이 무관한 잡 B의 대기를 키우면 안 된다 — 한 잡의 더블탭이 다른
    사용자의 요청을 지수적으로 늦추게 된다(코드 리뷰 반영)."""
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job_a, job_b = _job(store), _job(store)
    for job in (job_a, job_b):
        queue.enqueue(job.job_id, job.owner_id)
        assert queue.acquire(job.job_id, ttl_seconds=60) is True
    slept: list[float] = []
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))
    deps.sleep = slept.append

    # A가 세 번 연속 경합해 백오프가 커진 뒤, B가 처음 경합한다.
    for _ in range(3):
        process_message(deps, queue.consume(0))
        queue.consume(0)  # A가 되돌아온 뒤 B가 앞에 오도록 자리 정리
        queue.enqueue(job_a.job_id, job_a.owner_id)
    slept.clear()
    b_message = QueuedJob(job_id=job_b.job_id, owner_id=job_b.owner_id)
    process_message(deps, b_message)

    assert deps._contention_counts[job_b.job_id] == 1  # noqa: SLF001
    assert slept == [1.0]  # A의 누적과 무관하게 B는 첫 백오프


def test_cancel_before_pickup_finalizes_without_loop() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    store.request_cancel(job.owner_id, job.job_id)
    queue.enqueue(job.job_id, job.owner_id)
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))
    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.CANCELLED
    assert stored.loop_run.termination_reason is TerminationReason.CANCELLED
    assert store.list_trace(job.owner_id, job.job_id, after_seq=0, limit=5) == []


def test_llm_crash_marks_job_failed_not_worker() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _job(store)
    queue.enqueue(job.job_id, job.owner_id)

    class _ExplodingLlm:
        def decide(self, observation, tools):
            raise RuntimeError("llm hard down")

    deps = _deps(store, queue, _ExplodingLlm())
    process_message(deps, queue.consume(0))  # 예외가 밖으로 새지 않는다
    stored = store.get_job(job.owner_id, job.job_id)
    assert stored.state is JobState.FAILED


def test_stale_sweep_fails_abandoned_jobs_but_spares_locked() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    stale = _job(store)
    stale.state = JobState.INVESTIGATING
    stale.updated_at = utc_now() - timedelta(seconds=3600)
    store.update_job(stale)

    running = _job(store)
    running.state = JobState.INVESTIGATING
    running.updated_at = utc_now() - timedelta(seconds=3600)
    store.update_job(running)
    assert queue.acquire(running.job_id, ttl_seconds=600) is True  # 유효 리스 보유

    deps = _deps(store, queue, ScriptedToolCallingLlm([]))
    swept = sweep_stale_jobs(deps)

    assert swept == 1
    assert store.get_job(stale.owner_id, stale.job_id).state is JobState.FAILED
    assert store.get_job(running.owner_id, running.job_id).state is JobState.INVESTIGATING


# ── 코드 리뷰 반영(3단계) 회귀 테스트 ──


def test_stale_sweep_also_fails_never_picked_up_received_jobs() -> None:
    """큐 메시지가 유실된 RECEIVED 잡도 수렴 경로를 가진다(영구 방치 금지)."""
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    lost = _job(store)  # RECEIVED인 채 메시지 없음
    lost.updated_at = utc_now() - timedelta(seconds=3600)
    store.update_job(lost)

    deps = _deps(store, queue, ScriptedToolCallingLlm([]))
    swept = sweep_stale_jobs(deps)

    assert swept == 1
    stored = store.get_job(lost.owner_id, lost.job_id)
    assert stored.state is JobState.FAILED
    assert "never picked up" in (stored.error_message or "")


def test_lease_heartbeat_renews_in_background() -> None:
    """리스 하트비트 — 턴 길이와 무관하게 주기 갱신(중간 만료 방지)."""
    import time as time_mod

    from backend.modules.novelty.worker import _LeaseHeartbeat

    class _RecordingQueue:
        def __init__(self) -> None:
            self.renews: list[tuple[str, float]] = []

        def renew(self, job_id: str, ttl_seconds: float) -> bool:
            self.renews.append((job_id, ttl_seconds))
            return True

    queue = _RecordingQueue()
    with _LeaseHeartbeat(queue, "job-1", ttl_seconds=1.5):  # interval = max(0.5, 1.0) = 1.0s
        time_mod.sleep(1.3)
    assert len(queue.renews) >= 1
    assert queue.renews[0] == ("job-1", 1.5)


# ── 온디맨드 대화 턴 (BLM §5) ──────────────────────────────────────────────


def _terminal_job(store, state=JobState.COMPLETED, *, with_run: bool = True) -> NoveltyJob:
    job = _job(store, with_run=with_run)
    job.state = JobState.INVESTIGATING
    store.update_job(job)
    job.state = state
    store.update_job(job)
    store.save_artifact(
        ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id, kind=ArtifactKind.GAP_ANALYSIS,
            payload={
                "items": [
                    {
                        "area": "a",
                        "status": "partially_covered",
                        "rationale": "r",
                        "source_refs": [_ref()],
                    }
                ]
            },
        )
    )
    return job


def _ask(store, job, content="실험 계획 짜줘") -> NoveltyChatMessage:
    message = NoveltyChatMessage(
        job_id=job.job_id, owner_id=job.owner_id, role=ChatRole.USER,
        kind=ChatKind.ON_DEMAND_REQUEST, content=content,
    )
    store.append_message(message)
    return message


def _reply_script(text="답변입니다") -> ScriptedToolCallingLlm:
    return ScriptedToolCallingLlm(
        [LlmDecision(ToolCallProposal(TOOL_REPLY, {"content": text}))]
    )


def test_turn_message_runs_on_terminal_job_without_state_change() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store)
    message = _ask(store, job)
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    deps = _deps(store, queue, _reply_script())

    process_message(deps, queue.consume(0))

    assert store.get_job(job.owner_id, job.job_id).state is JobState.COMPLETED
    messages = store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
    assert messages[-1].role is ChatRole.AGENT
    assert messages[-1].content == "답변입니다"
    assert queue.acquire(job.job_id, ttl_seconds=1) is True  # 잠금 해제됨


def test_turn_on_failed_job_yields_notice_only() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store, JobState.FAILED)
    message = _ask(store, job)
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))  # 호출되면 죽는다

    process_message(deps, queue.consume(0))

    # BLM §5.1은 완료/부분 완료만 대상으로 한다 — LLM을 부르지 않고 안내만 남긴다.
    messages = store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
    assert messages[-1].kind is ChatKind.NOTICE


def test_turn_on_job_without_loop_run_yields_notice() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store, with_run=False)
    message = _ask(store, job)
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))

    messages = store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
    assert messages[-1].kind is ChatKind.NOTICE


def test_turn_redelivery_is_idempotent_no_duplicate_reply() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store)
    message = _ask(store, job)
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    deps = _deps(store, queue, _reply_script())

    process_message(deps, queue.consume(0))
    before = len(store.list_messages(job.owner_id, job.job_id, after=None, limit=20))

    # 워커 crash 후 recover_processing으로 같은 턴이 다시 올 수 있다.
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    process_message(deps, queue.consume(0))

    after = len(store.list_messages(job.owner_id, job.job_id, after=None, limit=20))
    # 중복 답장도, 중복 과금도 없다 — 답장이 in_reply_to로 이 턴을 가리키는지로 판정한다.
    assert after == before


def test_each_of_two_queued_requests_gets_its_own_reply() -> None:
    """사용자가 연달아 두 번 요청하면 둘 다 답을 받아야 한다.

    멱등 판정을 "대상 뒤에 아무 에이전트 행"으로 하면, 먼저 처리된 A의 답장이
    B의 답장으로 오인돼 B가 조용히 삼켜진다 — 쿼터는 이미 썼는데 답은 없다
    (코드 리뷰 반영). in_reply_to가 판정 근거여야 한다.
    """
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store)
    first = _ask(store, job, "실험 계획 짜줘")
    second = _ask(store, job, "방향 제안도 해줘")
    for message in (first, second):
        queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    deps = _deps(store, queue, _reply_script())

    process_message(deps, queue.consume(0))
    deps.llm = _reply_script("두 번째 답변입니다")
    process_message(deps, queue.consume(0))

    replies = [
        m
        for m in store.list_messages(job.owner_id, job.job_id, after=None, limit=20)
        if m.role is ChatRole.AGENT
    ]
    assert [m.in_reply_to for m in replies] == [first.message_id, second.message_id]


def test_turn_lock_contention_returns_message_to_queue() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store)
    message = _ask(store, job)
    queue.enqueue(job.job_id, job.owner_id, kind=KIND_TURN, message_id=message.message_id)
    assert queue.acquire(job.job_id, ttl_seconds=60) is True  # 앞선 턴이 실행 중
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))

    requeued = queue.consume(0)
    assert requeued is not None and requeued.kind == KIND_TURN
    assert requeued.message_id == message.message_id


def test_loop_message_still_drops_terminal_jobs() -> None:
    store, queue = InMemoryNoveltyStore(), InMemoryJobQueue()
    job = _terminal_job(store)
    queue.enqueue(job.job_id, job.owner_id)  # kind=loop
    deps = _deps(store, queue, ScriptedToolCallingLlm([]))

    process_message(deps, queue.consume(0))

    assert store.get_job(job.owner_id, job.job_id).state is JobState.COMPLETED
    assert store.list_messages(job.owner_id, job.job_id, after=None, limit=20) == []
