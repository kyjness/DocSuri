"""루프 코어(BLM §0~§2) — observe→decide→act, 종료 판정(BR-RA1). 어댑터 무지.

한 걸음의 기계(예산·게이트·트레이스)는 `agent_step`에 있고 온디맨드 대화 턴과
공유한다 — 저장 게이트와 트레이스에 경로가 둘이면 안 되기 때문이다(BR-RA2/RA4).
이 모듈은 그 위에서 "잡 하나를 종단까지 끌고 가는" 규칙만 담당한다.

불변 조건:
- 예산 검사는 act 직전 정확히 1회(domain.budget 단일 경로).
- 실행된 모든 도구 호출은 ToolCallRecord 1:1(BR-RA4). 기록 실패는 도구 호출을
  실패시키지 않되, 지속 실패 시 루프를 중단한다(NFR-NV2-13 — 트레이스는 계약).
- 정상 종료의 판정 권위는 저장 게이트다 — 필수 세트(BR-RA1)가 전부 게이트 통과·
  저장되어야 completed. 에이전트의 종료 제안은 수용 여부만 판정된다.
- 취소는 협조적(BR-RA8): 진행 중 도구 호출 완료 후 턴 경계에서 탈출.
- 자연어 잡은 루프 시작 전 form_evidence를 강제한다(BR-NV2, Evidence First).
- 사용자 스티어링은 예산 통과 후 decide 직전에 주입한다(BLM §6 — 자세한 근거는
  `agent_step.drain_steering`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..ports.llm import LoopObservation, TerminationProposal, ToolCallProposal
from ..ports.tools import TOOL_FORM_EVIDENCE, ToolSpec
from . import budget as budget_rules
from .agent_step import (
    SAVE_ARTIFACT_SPEC,
    AgentContext,
    AgentDeps,
    StepResult,
    TraceUnavailable,
    drain_steering,
    execute_step,
    persist_progress,
    seed_context,
)
from .models import (
    REQUIRED_ARTIFACT_KINDS,
    ArtifactKind,
    ChatKind,
    ChatRole,
    InputType,
    InvalidTransitionError,
    JobState,
    NoveltyChatMessage,
    NoveltyJob,
    TerminationReason,
    utc_now,
    validate_transition,
)

# LoopDeps는 AgentDeps의 이름일 뿐이다 — 워커·테스트의 기존 진입점을 보존한다.
LoopDeps = AgentDeps

__all__ = ["SAVE_ARTIFACT_SPEC", "LoopDeps", "LoopOutcome", "run_loop"]

log = logging.getLogger("docsuri.novelty.loop")


@dataclass(slots=True)
class LoopOutcome:
    reason: TerminationReason
    final_state: JobState
    detail: str | None = None


def run_loop(job: NoveltyJob, deps: AgentDeps) -> LoopOutcome:
    """잡 하나의 자율 루프를 종단 상태까지 구동한다. 워커가 실행 잠금을 쥔 채 호출."""
    run = job.loop_run
    if run is None:
        raise ValueError("job.loop_run must be allocated before run_loop")
    context = seed_context(job, deps)
    run.started_at = run.started_at or utc_now()
    _transition(job, JobState.INVESTIGATING, deps)

    try:
        outcome = _drive(job, deps, context)
    except TraceUnavailable:
        outcome = LoopOutcome(
            TerminationReason.FATAL_ERROR, JobState.FAILED, "decision trace unavailable"
        )
    except Exception as exc:  # 저장소 등 복구 불가 실패 — fatal(BLM §2 (d))
        outcome = LoopOutcome(TerminationReason.FATAL_ERROR, JobState.FAILED, str(exc)[:500])

    run.termination_reason = outcome.reason
    run.ended_at = utc_now()
    if outcome.detail and outcome.final_state is JobState.FAILED:
        job.error_message = outcome.detail
    try:
        if outcome.final_state is JobState.COMPLETED and job.state is JobState.INVESTIGATING:
            # 보고 조립(BLM §0) — 1단계에서는 저장된 산출물 참조가 곧 보고이므로 전이만.
            _transition(job, JobState.REPORTING, deps)
        _transition(job, outcome.final_state, deps, terminal=True)
    except InvalidTransitionError:
        # 다른 기록자(예: stale 스윕)가 먼저 종단시킴 — 결과를 덮어쓰지 않는다.
        log.warning(
            "novelty loop: job %s already terminal (%s); dropping %s",
            job.job_id, job.state, outcome.final_state,
        )
    except Exception:  # noqa: BLE001 — 종단 기록 실패는 스윕이 수렴시킨다(잡 비종단 유지)
        log.exception("novelty loop: failed to persist terminal state for job %s", job.job_id)
    _notice_unconsumed_steering(job, deps, context)
    return outcome


def _notice_unconsumed_steering(
    job: NoveltyJob, deps: AgentDeps, context: AgentContext
) -> None:
    """종료 직전에 도착해 소비되지 못한 사용자 메시지에 안내를 남긴다.

    루프가 끝나면 잡은 종단이라 더 읽을 주체가 없고, 저장만 된 메시지는 도달
    불가가 된다(조용한 유실). 자동 재실행은 하지 않는다 — 사용자가 모르는 사이에
    예산을 쓰게 되므로, 다시 보내달라고 안내만 한다.
    """
    if drain_steering(job, deps, context) == 0:
        return
    try:
        deps.store.append_message(
            NoveltyChatMessage(
                job_id=job.job_id,
                owner_id=job.owner_id,
                role=ChatRole.AGENT,
                kind=ChatKind.NOTICE,
                content=(
                    "조사가 종료된 뒤 도착한 메시지입니다 — 다시 보내주시면 "
                    "이어서 답변해 드릴게요."
                ),
            )
        )
    except Exception:  # noqa: BLE001 — 안내 실패가 종단 결과를 바꾸지 않는다
        log.warning("novelty loop: late-steering notice failed for job %s", job.job_id)


def _drive(job: NoveltyJob, deps: AgentDeps, context: AgentContext) -> LoopOutcome:
    budget = job.loop_run.budget  # type: ignore[union-attr]

    # Evidence First(BR-NV2) — 자연어 잡은 첫 act가 form_evidence로 강제된다.
    # 재전달로 evidence가 이미 저장돼 있으면 반복하지 않는다(예산 보호).
    if (
        job.request.input_type is InputType.NATURAL_LANGUAGE
        and ArtifactKind.EVIDENCE not in context.saved_kinds
    ):
        outcome = _forced_form_evidence(job, deps, context)
        persist_progress(job, deps)
        if outcome is not None:
            return outcome

    while True:
        if deps.store.is_cancel_requested(job.job_id):
            return LoopOutcome(TerminationReason.CANCELLED, JobState.CANCELLED)
        if budget_rules.begin_iteration(budget) is not None:
            return _budget_exhausted()

        drain_steering(job, deps, context)
        decision = deps.llm.decide(_observe(job, context), _exposed_tools(deps))
        if decision.cost_estimate_usd:
            budget_rules.record_cost(budget, decision.cost_estimate_usd)

        proposal = decision.proposal
        if isinstance(proposal, TerminationProposal):
            if _required_complete(context):
                return LoopOutcome(TerminationReason.ARTIFACTS_COMPLETE, JobState.COMPLETED)
            missing = _missing_kinds(context)
            context.notes.append(
                f"종료 제안 불수용 — 필수 산출물 미완성: {', '.join(sorted(missing))}"
            )
            persist_progress(job, deps)
            continue

        result = execute_step(job, deps, context, proposal)
        # 예산 소비·진행 상황을 매 턴 영속(코드 리뷰 반영) — crash 재시작이 전액
        # 예산으로 되돌지 않고, 실행 중 API 조회가 실시간 소비를 보여준다.
        persist_progress(job, deps)
        if result is StepResult.BUDGET_EXHAUSTED:
            return _budget_exhausted()
        if _required_complete(context):
            return LoopOutcome(TerminationReason.ARTIFACTS_COMPLETE, JobState.COMPLETED)


def _forced_form_evidence(
    job: NoveltyJob, deps: AgentDeps, context: AgentContext
) -> LoopOutcome | None:
    if deps.store.is_cancel_requested(job.job_id):
        return LoopOutcome(TerminationReason.CANCELLED, JobState.CANCELLED)
    if deps.registry.get(TOOL_FORM_EVIDENCE) is None:
        return LoopOutcome(
            TerminationReason.FATAL_ERROR, JobState.FAILED,
            "evidence tool unavailable for natural-language job",
        )
    proposal = ToolCallProposal(
        tool_name=TOOL_FORM_EVIDENCE,
        args={"topic": job.request.topic},
        decision_note="Evidence First — 자연어 잡 선행 강제(BR-NV2)",
    )
    if execute_step(job, deps, context, proposal) is StepResult.BUDGET_EXHAUSTED:
        return _budget_exhausted()
    last = context.recent_results[-1] if context.recent_results else None
    evidence = last.content.get("evidence") if last is not None and last.ok else None
    if isinstance(evidence, dict) and evidence.get("state") == "abstain":
        context.notes.append("근거형성 기권(abstain) — 보강 탐색 목적으로만 진행하거나 조기 종료")
    return None


def _observe(job: NoveltyJob, context: AgentContext) -> LoopObservation:
    budget = job.loop_run.budget  # type: ignore[union-attr]
    consumed = budget.consumed
    observation = LoopObservation(
        topic=job.request.topic,
        input_type=job.request.input_type.value,
        recent_results=tuple(context.recent_results),
        saved_artifact_kinds=frozenset(kind.value for kind in context.saved_kinds),
        missing_required_kinds=frozenset(_missing_kinds(context)),
        iterations_left=budget.max_iterations - consumed.iterations,
        tool_calls_left=budget.max_tool_calls_total - consumed.tool_calls_total,
        cost_left_usd=max(budget.token_cost_limit_usd - consumed.cost_usd, 0.0),
        notes=tuple(context.notes[-4:]),
        steering=tuple(context.steering),
    )
    return observation


def _exposed_tools(deps: AgentDeps) -> tuple[ToolSpec, ...]:
    return (*deps.registry.specs(), SAVE_ARTIFACT_SPEC)


def _required_complete(context: AgentContext) -> bool:
    return REQUIRED_ARTIFACT_KINDS <= context.saved_kinds


def _missing_kinds(context: AgentContext) -> set[str]:
    return {kind.value for kind in REQUIRED_ARTIFACT_KINDS - context.saved_kinds}


def _budget_exhausted() -> LoopOutcome:
    # 예산 소진 — 그 시점까지 검증·저장된 산출물로 부분 완료(BLM §9).
    return LoopOutcome(TerminationReason.BUDGET_EXHAUSTED, JobState.PARTIAL)


def _transition(
    job: NoveltyJob, target: JobState, deps: AgentDeps, *, terminal: bool = False
) -> None:
    validate_transition(job.state, target)
    job.state = target
    job.updated_at = utc_now()
    if terminal:
        job.completed_at = utc_now()
    deps.store.update_job(job)
