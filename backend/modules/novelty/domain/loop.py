"""루프 코어(BLM §0~§2) — observe→decide→act, 종료 판정(BR-RA1). 어댑터 무지.

불변 조건:
- 예산 검사는 act 직전 정확히 1회(domain.budget 단일 경로).
- 실행된 모든 도구 호출은 ToolCallRecord 1:1(BR-RA4). 기록 실패는 도구 호출을
  실패시키지 않되, 지속 실패 시 루프를 중단한다(NFR-NV2-13 — 트레이스는 계약).
- 정상 종료의 판정 권위는 저장 게이트다 — 필수 세트(BR-RA1)가 전부 게이트 통과·
  저장되어야 completed. 에이전트의 종료 제안은 수용 여부만 판정된다.
- 취소는 협조적(BR-RA8): 진행 중 도구 호출 완료 후 턴 경계에서 탈출.
- 자연어 잡은 루프 시작 전 form_evidence를 강제한다(BR-NV2, Evidence First).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from ..ports.llm import (
    LoopObservation,
    TerminationProposal,
    ToolCallingLlmPort,
    ToolCallProposal,
    ToolResultView,
)
from ..ports.store import NoveltyStorePort
from ..ports.tools import (
    TOOL_FORM_EVIDENCE,
    TOOL_SAVE_ARTIFACT,
    ToolContext,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from . import budget as budget_rules
from .gate import GateRejectionReason, evaluate_artifact
from .models import (
    REQUIRED_ARTIFACT_KINDS,
    ArtifactKind,
    ArtifactRecord,
    ChatKind,
    ChatRole,
    InputType,
    InvalidTransitionError,
    JobState,
    NoveltyChatMessage,
    NoveltyJob,
    TerminationReason,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
    validate_transition,
)

__all__ = ["SAVE_ARTIFACT_SPEC", "LoopDeps", "LoopOutcome", "run_loop"]

log = logging.getLogger("docsuri.novelty.loop")

# save_artifact는 레지스트리 도구가 아니라 루프가 직접 게이트로 처리한다 —
# 우회 저장 경로를 만들지 않기 위해(BR-RA2). LLM에는 이 스펙으로 노출된다.
SAVE_ARTIFACT_SPEC = ToolSpec(
    name=TOOL_SAVE_ARTIFACT,
    description=(
        "조사 산출물 저장 시도. 결정론 게이트가 SourceRef 실재성·필수 필드·bounded "
        "규칙을 검증하며, 거부 시 기계 판독 사유가 반환된다. "
        "kind: evidence|similar_works|gap_analysis|external_findings|"
        "novelty_candidates|experiment_plan"
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {"type": "string"},
            "payload": {"type": "object"},
        },
        "required": ["kind", "payload"],
    },
)

_RECENT_RESULTS_WINDOW = 6
_TRACE_FAILURE_HALT_AFTER = 2
_TOOL_DEGRADED_AFTER = 2
# 스티어링 롤링 윈도우(BLM §6) — 매 턴 새 요청을 만드는 구조라 대화 이력이 없다.
# 1회성 주입이면 지시가 한 턴만 살고 사라지므로 최근 N건을 계속 함께 보여준다.
_STEERING_WINDOW = 3
_STEERING_MAX_CHARS = 400
_STEERING_FETCH_LIMIT = 20


@dataclass(slots=True)
class LoopDeps:
    store: NoveltyStorePort
    llm: ToolCallingLlmPort
    registry: ToolRegistry


@dataclass(slots=True)
class LoopOutcome:
    reason: TerminationReason
    final_state: JobState
    detail: str | None = None


@dataclass(slots=True)
class _LoopState:
    """한 실행의 가변 문맥 — 실재 출처 핸들·최근 결과·연속 실패 카운터."""

    known_record_refs: set[str] = field(default_factory=set)
    recent_results: list[ToolResultView] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    saved_kinds: set[ArtifactKind] = field(default_factory=set)
    trace_failures: int = 0
    tool_failures: dict[str, int] = field(default_factory=dict)
    result_seq: int = 0  # 관찰 뷰 순번 — 윈도우 절단과 무관하게 단조 증가
    steering: list[str] = field(default_factory=list)  # 사용자 지시 롤링 윈도우
    steering_cursor: str | None = None  # 마지막으로 읽은 대화 메시지


def run_loop(job: NoveltyJob, deps: LoopDeps) -> LoopOutcome:
    """잡 하나의 자율 루프를 종단 상태까지 구동한다. 워커가 실행 잠금을 쥔 채 호출."""
    run = job.loop_run
    if run is None:
        raise ValueError("job.loop_run must be allocated before run_loop")
    state = _seed_state(job, deps)
    run.started_at = run.started_at or utc_now()
    _transition(job, JobState.INVESTIGATING, deps)

    try:
        outcome = _drive(job, deps, state)
    except _TraceUnavailable:
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
    _notice_unconsumed_steering(job, deps, state)
    return outcome


def _notice_unconsumed_steering(job: NoveltyJob, deps: LoopDeps, state: _LoopState) -> None:
    """종료 직전에 도착해 소비되지 못한 사용자 메시지에 안내를 남긴다.

    루프가 끝나면 잡은 종단이라 더 읽을 주체가 없고, 저장만 된 메시지는 도달
    불가가 된다(조용한 유실). 자동 재실행은 하지 않는다 — 사용자가 모르는 사이에
    예산을 쓰게 되므로, 다시 보내달라고 안내만 한다.
    """
    if _drain_steering(job, deps, state) == 0:
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


def _seed_state(job: NoveltyJob, deps: LoopDeps) -> _LoopState:
    """재전달 복원(코드 리뷰 반영): 이미 게이트를 통과해 저장된 산출물과 그 출처 핸들,
    원고 잡의 원고 recordRef를 시드한다 — crash 후 재실행이 작업·예산을 이중 소진하지
    않고, 저장소가 완성 판정의 단일 진실로 남는다(BR-RA1)."""
    state = _LoopState()
    for record in deps.store.list_artifacts(job.owner_id, job.job_id):
        state.saved_kinds.add(record.kind)
        _collect_record_refs(record.payload, state.known_record_refs)
    manuscript = job.request.manuscript_ref
    if manuscript is not None and manuscript.record_ref:
        # 업로드 원고도 실재 출처다 — 게이트가 원고 인용을 거부하지 않게 시드(FR-47 방향).
        state.known_record_refs.add(manuscript.record_ref)
    if state.saved_kinds:
        state.notes.append(
            "재개된 잡 — 이미 저장된 산출물: "
            + ", ".join(sorted(kind.value for kind in state.saved_kinds))
        )
    # 대화도 승계한다 — 크래시 전에 받은 사용자 지시가 재실행에서 사라지지 않게.
    # 윈도우만 남으므로 이력 전체를 다시 재생하지는 않는다.
    _drain_steering(job, deps, state)
    return state


def _drain_steering(job: NoveltyJob, deps: LoopDeps, state: _LoopState) -> int:
    """새 사용자 메시지를 읽어 스티어링 윈도우에 반영하고, 소비한 건수를 돌려준다.

    (FR-44, BLM §6)

    호출 위치가 계약이다 — 예산 검사 통과 후, decide 직전. 턴 맨 앞에서 읽으면
    예산이 그 턴을 거부했을 때 커서만 전진해 지시가 유실된다("다음 decide 시점"
    주입이 성립하지 않는다). 진행 중 도구 호출을 끊지 않는 것도 같은 이유다.

    필터는 kind가 아니라 role이다 — 에이전트 답장·시스템 안내가 같은 테이블에
    쌓이므로 kind로 거르면 루프가 자기 출력을 되먹는다.
    """
    try:
        messages = deps.store.list_messages(
            job.owner_id, job.job_id, after=state.steering_cursor, limit=_STEERING_FETCH_LIMIT
        )
    except KeyError:
        # 커서가 가리키던 메시지가 사라졌다 — 풀어서 다음 턴에 다시 앵커한다.
        # 통째로 삼키면 커서가 박힌 채 스티어링이 조용히 죽는다.
        log.warning("novelty loop: steering cursor lost for job %s; re-anchoring", job.job_id)
        state.steering_cursor = None
        return 0
    except Exception:  # noqa: BLE001 — 대화 조회 실패가 턴을 죽이지 않는다(다음 턴 재시도)
        log.warning("novelty loop: steering read failed for job %s", job.job_id)
        return 0
    if not messages:
        return 0
    state.steering_cursor = messages[-1].message_id
    fresh = [
        message.content[:_STEERING_MAX_CHARS]
        for message in messages
        if message.role is ChatRole.USER
    ]
    if not fresh:
        return 0
    state.steering.extend(fresh)
    del state.steering[:-_STEERING_WINDOW]
    # 노트에는 사용자 문장을 넣지 않는다 — 시스템 노트는 신뢰 구획이고, 본문은
    # 별도의 사용자 지시 구획으로만 전달된다(prompt injection 경계).
    state.notes.append(f"사용자 스티어링 {len(fresh)}건 수신 — 사용자 지시 구획 참조")
    log.info("novelty loop: job %s consumed %d steering message(s)", job.job_id, len(fresh))
    return len(fresh)


def _collect_record_refs(node: Any, into: set[str]) -> None:
    """산출물 payload에서 recordRef 핸들을 결정론적으로 회수(재전달 시 실재성 집합 복원)."""
    if isinstance(node, dict):
        ref = node.get("recordRef")
        if isinstance(ref, str) and ref:
            into.add(ref)
        for value in node.values():
            _collect_record_refs(value, into)
    elif isinstance(node, list):
        for item in node:
            _collect_record_refs(item, into)


class _TraceUnavailable(Exception):
    """트레이스 기록 불가 지속 — 실행을 계속하지 않는다(NFR-NV2-13)."""


def _drive(job: NoveltyJob, deps: LoopDeps, state: _LoopState) -> LoopOutcome:
    budget = job.loop_run.budget  # type: ignore[union-attr]

    # Evidence First(BR-NV2) — 자연어 잡은 첫 act가 form_evidence로 강제된다.
    # 재전달로 evidence가 이미 저장돼 있으면 반복하지 않는다(예산 보호).
    if (
        job.request.input_type is InputType.NATURAL_LANGUAGE
        and ArtifactKind.EVIDENCE not in state.saved_kinds
    ):
        outcome = _forced_form_evidence(job, deps, state)
        _persist_progress(job, deps)
        if outcome is not None:
            return outcome

    while True:
        if deps.store.is_cancel_requested(job.job_id):
            return LoopOutcome(TerminationReason.CANCELLED, JobState.CANCELLED)
        if budget_rules.begin_iteration(budget) is not None:
            return _budget_exhausted()

        _drain_steering(job, deps, state)
        decision = deps.llm.decide(_observe(job, state), _exposed_tools(deps))
        if decision.cost_estimate_usd:
            budget_rules.record_cost(budget, decision.cost_estimate_usd)

        proposal = decision.proposal
        if isinstance(proposal, TerminationProposal):
            if _required_complete(state):
                return LoopOutcome(TerminationReason.ARTIFACTS_COMPLETE, JobState.COMPLETED)
            missing = _missing_kinds(state)
            state.notes.append(
                f"종료 제안 불수용 — 필수 산출물 미완성: {', '.join(sorted(missing))}"
            )
            _persist_progress(job, deps)
            continue

        outcome = _act(job, deps, state, proposal)
        # 예산 소비·진행 상황을 매 턴 영속(코드 리뷰 반영) — crash 재시작이 전액
        # 예산으로 되돌지 않고, 실행 중 API 조회가 실시간 소비를 보여준다.
        _persist_progress(job, deps)
        if outcome is not None:
            return outcome
        if _required_complete(state):
            return LoopOutcome(TerminationReason.ARTIFACTS_COMPLETE, JobState.COMPLETED)


def _persist_progress(job: NoveltyJob, deps: LoopDeps) -> None:
    """루프 진행 스냅샷 영속 — 실패해도 턴을 죽이지 않는다(다음 턴·종단에서 재시도)."""
    job.updated_at = utc_now()
    try:
        deps.store.update_job(job)
    except Exception:  # noqa: BLE001 — 진행 영속은 best-effort, 종단 기록이 최종 권위
        log.warning("novelty loop: progress persist failed for job %s", job.job_id)


def _act(
    job: NoveltyJob,
    deps: LoopDeps,
    state: _LoopState,
    proposal: ToolCallProposal,
) -> LoopOutcome | None:
    """act 한 번: 예산 검사(단일 지점) → 실행 → 트레이스 1:1. 종단이면 LoopOutcome."""
    budget = job.loop_run.budget  # type: ignore[union-attr]
    started = utc_now()
    denial = budget_rules.check_and_consume_tool_call(budget, proposal.tool_name)
    if denial is not None:
        _record(
            job, deps, state, proposal,
            result_summary=f"budget denied: {denial.reason}: {denial.detail}",
            outcome=ToolOutcome.BUDGET_DENIED, started=started,
        )
        if denial.reason is budget_rules.BudgetDenialReason.TOOL_CAP_EXHAUSTED:
            # 도구별 캡 소진은 해당 도구만 막는다 — 잔여 예산으로 다른 도구 진행 가능.
            state.notes.append(f"도구 캡 소진: {denial.detail} — 다른 도구를 사용하라")
            return None
        return _budget_exhausted()

    if proposal.tool_name == TOOL_SAVE_ARTIFACT:
        result = _execute_save(job, deps, state, proposal.args)
    else:
        result = _execute_tool(job, deps, state, proposal)

    if result.cost_usd:
        budget_rules.record_cost(budget, result.cost_usd)
    state.result_seq += 1
    state.recent_results.append(
        ToolResultView(
            seq=state.result_seq,
            tool_name=proposal.tool_name,
            ok=result.ok,
            content=result.content,
            error=result.error,
        )
    )
    del state.recent_results[:-_RECENT_RESULTS_WINDOW]

    if result.ok:
        state.tool_failures.pop(proposal.tool_name, None)
        record_outcome = ToolOutcome.OK
    elif result.gate_rejection_code is not None:
        record_outcome = ToolOutcome.REJECTED_BY_GATE
    else:
        record_outcome = ToolOutcome.ERROR
        failures = state.tool_failures.get(proposal.tool_name, 0) + 1
        state.tool_failures[proposal.tool_name] = failures
        if failures >= _TOOL_DEGRADED_AFTER:
            # source별 저하(BR-NV16) — 잡은 계속, 저하 사실만 남긴다.
            job.degraded_sources[proposal.tool_name] = (result.error or "repeated failure")[:200]

    _record(
        job, deps, state, proposal,
        result_summary=result.result_summary or (result.error or "")[:500],
        outcome=record_outcome, started=started,
        cost=result.cost_usd,
    )
    return None


def _execute_tool(
    job: NoveltyJob, deps: LoopDeps, state: _LoopState, proposal: ToolCallProposal
) -> ToolResult:
    tool = deps.registry.get(proposal.tool_name)
    if tool is None:
        return ToolResult(ok=False, error=f"unknown tool: {proposal.tool_name}")
    try:
        result = tool.invoke(
            proposal.args, ToolContext(owner_id=job.owner_id, job_id=job.job_id)
        )
    except Exception as exc:  # 도구 실패는 에이전트에 오류로 반환(BR-NV16)
        return ToolResult(ok=False, error=f"{type(exc).__name__}: {exc}"[:500])
    state.known_record_refs.update(result.record_refs)
    if proposal.tool_name == TOOL_FORM_EVIDENCE and result.ok:
        auto_save_note = _auto_save_evidence(job, deps, state, result)
        result = replace(
            result,
            result_summary=f"{result.result_summary}; {auto_save_note}".strip("; "),
        )
    return result


def _execute_save(
    job: NoveltyJob, deps: LoopDeps, state: _LoopState, args: dict[str, Any]
) -> ToolResult:
    """save_artifact — 항상 게이트 경유(BR-RA2). 거부는 기계 판독 사유로 반환."""
    raw_kind = str(args.get("kind", ""))
    try:
        kind = ArtifactKind(raw_kind)
    except ValueError:
        return ToolResult(
            ok=False,
            error=f"rejected_by_gate: unsupported_kind: {raw_kind[:40]}",
            gate_rejection_code=GateRejectionReason.UNSUPPORTED_KIND.value,
        )
    payload = args.get("payload")
    if not isinstance(payload, dict):
        return ToolResult(
            ok=False,
            error="rejected_by_gate: invalid_shape: payload must be object",
            gate_rejection_code=GateRejectionReason.INVALID_SHAPE.value,
        )
    rejection = evaluate_artifact(kind, payload, frozenset(state.known_record_refs))
    if rejection is not None:
        return ToolResult(
            ok=False,
            content={"rejected": {"reason": rejection.reason.value, "detail": rejection.detail}},
            error=f"rejected_by_gate: {rejection.reason.value}: {rejection.detail}",
            result_summary=f"save rejected: {rejection.reason.value}",
            gate_rejection_code=rejection.reason.value,
        )
    deps.store.save_artifact(
        ArtifactRecord(job_id=job.job_id, owner_id=job.owner_id, kind=kind, payload=payload)
    )
    state.saved_kinds.add(kind)
    return ToolResult(
        ok=True,
        content={"saved": kind.value},
        result_summary=f"saved {kind.value}",
    )


def _auto_save_evidence(
    job: NoveltyJob, deps: LoopDeps, state: _LoopState, result: ToolResult
) -> str:
    """form_evidence 성공 시 EvidenceSnapshot(포트 결과의 내부 보존본)을 게이트 경유로
    저장한다 — 별도 save_artifact 호출 불요, 게이트 우회 아님. 결과(성공·거부)는
    트레이스 요약과 다음 관찰 노트로 표면화한다(무기록 실패 금지 — 코드 리뷰 반영)."""
    snapshot = result.content.get("evidence")
    if not isinstance(snapshot, dict):
        state.notes.append(
            "evidence 자동 보존 불가(결과 형태 비정상) — save_artifact(evidence)로 저장하라"
        )
        return "evidence auto-save skipped: malformed content"
    rejection = evaluate_artifact(
        ArtifactKind.EVIDENCE, snapshot, frozenset(state.known_record_refs)
    )
    if rejection is not None:
        state.notes.append(
            f"evidence 자동 보존 거부({rejection.reason.value}) — 보완 후 "
            "save_artifact(evidence)로 저장하라"
        )
        return f"evidence auto-save rejected: {rejection.reason.value}"
    deps.store.save_artifact(
        ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id,
            kind=ArtifactKind.EVIDENCE, payload=snapshot,
        )
    )
    state.saved_kinds.add(ArtifactKind.EVIDENCE)
    return "evidence saved"


def _forced_form_evidence(
    job: NoveltyJob, deps: LoopDeps, state: _LoopState
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
    outcome = _act(job, deps, state, proposal)
    if outcome is not None:
        return outcome
    last = state.recent_results[-1] if state.recent_results else None
    evidence = last.content.get("evidence") if last is not None and last.ok else None
    if isinstance(evidence, dict) and evidence.get("state") == "abstain":
        state.notes.append("근거형성 기권(abstain) — 보강 탐색 목적으로만 진행하거나 조기 종료")
    return None


def _record(
    job: NoveltyJob,
    deps: LoopDeps,
    state: _LoopState,
    proposal: ToolCallProposal,
    *,
    result_summary: str,
    outcome: ToolOutcome,
    started: datetime,
    cost: float | None = None,
) -> None:
    """도구 호출 1:1 트레이스(BR-RA4). 실패는 호출을 실패시키지 않되 지속 시 중단."""
    fields: dict[str, Any] = {
        "job_id": job.job_id,
        "tool_name": proposal.tool_name,
        "args_summary": _summarize_args(proposal.args),
        "decision_note": proposal.decision_note or None,
        "result_summary": result_summary[:2000],
        "outcome": outcome,
        "cost_estimate_usd": cost,
        "started_at": started,
        "finished_at": utc_now(),
    }
    for _ in range(2):  # 1회 재시도
        try:
            seq = deps.store.next_trace_seq(job.job_id)
            deps.store.append_trace(ToolCallRecord(seq=seq, **fields))
            state.trace_failures = 0
            return
        except Exception:  # noqa: BLE001 — 기록 실패 자체는 호출을 실패시키지 않는다
            continue
    state.trace_failures += 1
    if state.trace_failures >= _TRACE_FAILURE_HALT_AFTER:
        raise _TraceUnavailable


def _observe(job: NoveltyJob, state: _LoopState) -> LoopObservation:
    budget = job.loop_run.budget  # type: ignore[union-attr]
    consumed = budget.consumed
    observation = LoopObservation(
        topic=job.request.topic,
        input_type=job.request.input_type.value,
        recent_results=tuple(state.recent_results),
        saved_artifact_kinds=frozenset(kind.value for kind in state.saved_kinds),
        missing_required_kinds=frozenset(_missing_kinds(state)),
        iterations_left=budget.max_iterations - consumed.iterations,
        tool_calls_left=budget.max_tool_calls_total - consumed.tool_calls_total,
        cost_left_usd=max(budget.token_cost_limit_usd - consumed.cost_usd, 0.0),
        notes=tuple(state.notes[-4:]),
        steering=tuple(state.steering),
    )
    return observation


def _exposed_tools(deps: LoopDeps) -> tuple[ToolSpec, ...]:
    return (*deps.registry.specs(), SAVE_ARTIFACT_SPEC)


def _required_complete(state: _LoopState) -> bool:
    return REQUIRED_ARTIFACT_KINDS <= state.saved_kinds


def _missing_kinds(state: _LoopState) -> set[str]:
    return {kind.value for kind in REQUIRED_ARTIFACT_KINDS - state.saved_kinds}


def _budget_exhausted() -> LoopOutcome:
    # 예산 소진 — 그 시점까지 검증·저장된 산출물로 부분 완료(BLM §9).
    return LoopOutcome(TerminationReason.BUDGET_EXHAUSTED, JobState.PARTIAL)


def _transition(
    job: NoveltyJob, target: JobState, deps: LoopDeps, *, terminal: bool = False
) -> None:
    validate_transition(job.state, target)
    job.state = target
    job.updated_at = utc_now()
    if terminal:
        job.completed_at = utc_now()
    deps.store.update_job(job)


def _summarize_args(args: dict[str, Any]) -> str:
    """트레이스용 sanitized 인자 요약 — 값 절단으로 원문 통짜 저장을 막는다(SEC-9/15)."""
    parts: list[str] = []
    for key, value in list(args.items())[:8]:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(type(value).__name__)
        if len(text) > 120:
            text = text[:120] + "…"
        parts.append(f"{key}={text}")
    summary = ", ".join(parts)
    return summary[:2000]
