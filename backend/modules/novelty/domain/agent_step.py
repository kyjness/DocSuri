"""에이전트 한 걸음의 공용 기계 — 자율 루프와 온디맨드 대화 턴이 함께 쓴다.

여기 모인 이유는 하나다: **저장 게이트와 결정 트레이스에 경로가 둘이면 안 된다.**
- `execute_save`가 산출물 저장의 유일한 관문이다(BR-RA2 — 게이트를 우회하는 저장
  경로를 만들지 않는다). 대화 응답 경로라고 검증을 생략하지 않는다(BR-RA6).
- `execute_step`이 예산 검사(단일 지점)·실행·`ToolCallRecord` 1:1 기록(BR-RA4)을
  한 묶음으로 수행한다. 호출자가 루프든 턴이든 같은 규칙을 받는다.

어댑터는 모른다 — 저장소·LLM·도구는 전부 포트로 들어온다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from typing import Any

from ..ports.llm import ToolCallingLlmPort, ToolCallProposal, ToolResultView
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
    ArtifactKind,
    ArtifactRecord,
    ChatRole,
    NoveltyJob,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
)

__all__ = [
    "SAVE_ARTIFACT_SPEC",
    "AgentContext",
    "AgentDeps",
    "StepResult",
    "TraceUnavailable",
    "collect_record_refs",
    "drain_steering",
    "execute_save",
    "execute_step",
    "persist_progress",
    "seed_context",
    "summarize_args",
]

log = logging.getLogger("docsuri.novelty.loop")

# save_artifact는 레지스트리 도구가 아니라 호출자가 직접 게이트로 처리한다 —
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

RECENT_RESULTS_WINDOW = 6
TRACE_FAILURE_HALT_AFTER = 2
TOOL_DEGRADED_AFTER = 2
# 스티어링 롤링 윈도우(BLM §6) — 매 턴 새 요청을 만드는 구조라 대화 이력이 없다.
# 1회성 주입이면 지시가 한 턴만 살고 사라지므로 최근 N건을 계속 함께 보여준다.
STEERING_WINDOW = 3
STEERING_MAX_CHARS = 400
STEERING_FETCH_LIMIT = 20


@dataclass(slots=True)
class AgentDeps:
    store: NoveltyStorePort
    llm: ToolCallingLlmPort
    registry: ToolRegistry


@dataclass(slots=True)
class AgentContext:
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


class StepResult(str, Enum):
    """한 걸음의 결과 — 종료 의미 부여는 호출자 몫(루프는 partial, 턴은 안내)."""

    CONTINUE = "continue"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TraceUnavailable(Exception):
    """트레이스 기록 불가 지속 — 실행을 계속하지 않는다(NFR-NV2-13)."""


def seed_context(job: NoveltyJob, deps: AgentDeps) -> AgentContext:
    """저장된 산출물과 그 출처 핸들, 원고 recordRef, 대화 스티어링을 복원한다.

    재전달 복원(코드 리뷰 반영): crash 후 재실행이 작업·예산을 이중 소진하지 않고,
    저장소가 완성 판정의 단일 진실로 남는다(BR-RA1). 온디맨드 턴도 같은 함수를
    쓴다 — 그래서 턴이 인용할 수 있는 출처는 이미 저장된 산출물에 근거가 있거나
    이번 턴 도구 호출로 새로 얻은 것뿐이고, BR-RA6이 추가 코드 없이 성립한다.
    """
    context = AgentContext()
    for record in deps.store.list_artifacts(job.owner_id, job.job_id):
        context.saved_kinds.add(record.kind)
        collect_record_refs(record.payload, context.known_record_refs)
    manuscript = job.request.manuscript_ref
    if manuscript is not None and manuscript.record_ref:
        # 업로드 원고도 실재 출처다 — 게이트가 원고 인용을 거부하지 않게 시드(FR-47 방향).
        context.known_record_refs.add(manuscript.record_ref)
    if context.saved_kinds:
        context.notes.append(
            "재개된 잡 — 이미 저장된 산출물: "
            + ", ".join(sorted(kind.value for kind in context.saved_kinds))
        )
    # 대화도 승계한다 — 크래시 전에 받은 사용자 지시가 재실행에서 사라지지 않게.
    # 윈도우만 남으므로 이력 전체를 다시 재생하지는 않는다.
    drain_steering(job, deps, context)
    return context


def collect_record_refs(node: Any, into: set[str]) -> None:
    """산출물 payload에서 recordRef 핸들을 결정론적으로 회수(재전달 시 실재성 집합 복원)."""
    if isinstance(node, dict):
        ref = node.get("recordRef")
        if isinstance(ref, str) and ref:
            into.add(ref)
        for value in node.values():
            collect_record_refs(value, into)
    elif isinstance(node, list):
        for item in node:
            collect_record_refs(item, into)


def drain_steering(job: NoveltyJob, deps: AgentDeps, context: AgentContext) -> int:
    """새 사용자 메시지를 읽어 스티어링 윈도우에 반영하고, 소비한 건수를 돌려준다.

    (FR-44, BLM §6)

    호출 위치가 계약이다 — 예산 검사 통과 후, decide 직전. 턴 맨 앞에서 읽으면
    예산이 그 턴을 거부했을 때 커서만 전진해 지시가 유실된다("다음 decide 시점"
    주입이 성립하지 않는다). 진행 중 도구 호출을 끊지 않는 것도 같은 이유다.

    필터는 kind가 아니라 role이다 — 에이전트 답장·시스템 안내가 같은 테이블에
    쌓이므로 kind로 거르면 에이전트가 자기 출력을 되먹는다.
    """
    try:
        messages = deps.store.list_messages(
            job.owner_id, job.job_id, after=context.steering_cursor, limit=STEERING_FETCH_LIMIT
        )
    except KeyError:
        # 커서가 가리키던 메시지가 사라졌다 — 풀어서 다음 턴에 다시 앵커한다.
        # 통째로 삼키면 커서가 박힌 채 스티어링이 조용히 죽는다.
        log.warning("novelty agent: steering cursor lost for job %s; re-anchoring", job.job_id)
        context.steering_cursor = None
        return 0
    except Exception:  # noqa: BLE001 — 대화 조회 실패가 턴을 죽이지 않는다(다음 턴 재시도)
        log.warning("novelty agent: steering read failed for job %s", job.job_id)
        return 0
    if not messages:
        return 0
    context.steering_cursor = messages[-1].message_id
    fresh = [
        message.content[:STEERING_MAX_CHARS]
        for message in messages
        if message.role is ChatRole.USER
    ]
    if not fresh:
        return 0
    context.steering.extend(fresh)
    del context.steering[:-STEERING_WINDOW]
    # 노트에는 사용자 문장을 넣지 않는다 — 시스템 노트는 신뢰 구획이고, 본문은
    # 별도의 사용자 지시 구획으로만 전달된다(prompt injection 경계).
    context.notes.append(f"사용자 스티어링 {len(fresh)}건 수신 — 사용자 지시 구획 참조")
    log.info("novelty agent: job %s consumed %d steering message(s)", job.job_id, len(fresh))
    return len(fresh)


def persist_progress(job: NoveltyJob, deps: AgentDeps) -> None:
    """진행 스냅샷 영속 — 실패해도 턴을 죽이지 않는다(다음 턴·종단에서 재시도)."""
    job.updated_at = utc_now()
    try:
        deps.store.update_job(job)
    except Exception:  # noqa: BLE001 — 진행 영속은 best-effort, 종단 기록이 최종 권위
        log.warning("novelty agent: progress persist failed for job %s", job.job_id)


def execute_step(
    job: NoveltyJob,
    deps: AgentDeps,
    context: AgentContext,
    proposal: ToolCallProposal,
) -> StepResult:
    """한 걸음: 예산 검사(단일 지점) → 실행 → 트레이스 1:1(BR-RA4)."""
    budget = job.loop_run.budget  # type: ignore[union-attr]
    started = utc_now()
    denial = budget_rules.check_and_consume_tool_call(budget, proposal.tool_name)
    if denial is not None:
        record_trace(
            job, deps, context, proposal,
            result_summary=f"budget denied: {denial.reason}: {denial.detail}",
            outcome=ToolOutcome.BUDGET_DENIED, started=started,
        )
        if denial.reason is budget_rules.BudgetDenialReason.TOOL_CAP_EXHAUSTED:
            # 도구별 캡 소진은 해당 도구만 막는다 — 잔여 예산으로 다른 도구 진행 가능.
            context.notes.append(f"도구 캡 소진: {denial.detail} — 다른 도구를 사용하라")
            return StepResult.CONTINUE
        return StepResult.BUDGET_EXHAUSTED

    if proposal.tool_name == TOOL_SAVE_ARTIFACT:
        result = execute_save(job, deps, context, proposal.args)
    else:
        result = execute_tool(job, deps, context, proposal)

    if result.cost_usd:
        budget_rules.record_cost(budget, result.cost_usd)
    context.result_seq += 1
    context.recent_results.append(
        ToolResultView(
            seq=context.result_seq,
            tool_name=proposal.tool_name,
            ok=result.ok,
            content=result.content,
            error=result.error,
        )
    )
    del context.recent_results[:-RECENT_RESULTS_WINDOW]

    if result.ok:
        context.tool_failures.pop(proposal.tool_name, None)
        record_outcome = ToolOutcome.OK
    elif result.gate_rejection_code is not None:
        record_outcome = ToolOutcome.REJECTED_BY_GATE
    else:
        record_outcome = ToolOutcome.ERROR
        failures = context.tool_failures.get(proposal.tool_name, 0) + 1
        context.tool_failures[proposal.tool_name] = failures
        if failures >= TOOL_DEGRADED_AFTER:
            # source별 저하(BR-NV16) — 잡은 계속, 저하 사실만 남긴다.
            job.degraded_sources[proposal.tool_name] = (result.error or "repeated failure")[:200]

    record_trace(
        job, deps, context, proposal,
        result_summary=result.result_summary or (result.error or "")[:500],
        outcome=record_outcome, started=started,
        cost=result.cost_usd,
    )
    return StepResult.CONTINUE


def execute_tool(
    job: NoveltyJob, deps: AgentDeps, context: AgentContext, proposal: ToolCallProposal
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
    context.known_record_refs.update(result.record_refs)
    if proposal.tool_name == TOOL_FORM_EVIDENCE and result.ok:
        auto_save_note = auto_save_evidence(job, deps, context, result)
        result = replace(
            result,
            result_summary=f"{result.result_summary}; {auto_save_note}".strip("; "),
        )
    return result


def execute_save(
    job: NoveltyJob, deps: AgentDeps, context: AgentContext, args: dict[str, Any]
) -> ToolResult:
    """save_artifact — 산출물 저장의 유일한 관문(BR-RA2/RA6). 거부는 기계 판독 사유로 반환."""
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
    rejection = evaluate_artifact(kind, payload, frozenset(context.known_record_refs))
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
    context.saved_kinds.add(kind)
    return ToolResult(
        ok=True,
        content={"saved": kind.value},
        result_summary=f"saved {kind.value}",
    )


def auto_save_evidence(
    job: NoveltyJob, deps: AgentDeps, context: AgentContext, result: ToolResult
) -> str:
    """form_evidence 성공 시 EvidenceSnapshot(포트 결과의 내부 보존본)을 게이트 경유로
    저장한다 — 별도 save_artifact 호출 불요, 게이트 우회 아님. 결과(성공·거부)는
    트레이스 요약과 다음 관찰 노트로 표면화한다(무기록 실패 금지 — 코드 리뷰 반영)."""
    snapshot = result.content.get("evidence")
    if not isinstance(snapshot, dict):
        context.notes.append(
            "evidence 자동 보존 불가(결과 형태 비정상) — save_artifact(evidence)로 저장하라"
        )
        return "evidence auto-save skipped: malformed content"
    rejection = evaluate_artifact(
        ArtifactKind.EVIDENCE, snapshot, frozenset(context.known_record_refs)
    )
    if rejection is not None:
        context.notes.append(
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
    context.saved_kinds.add(ArtifactKind.EVIDENCE)
    return "evidence saved"


def record_trace(
    job: NoveltyJob,
    deps: AgentDeps,
    context: AgentContext,
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
        "args_summary": summarize_args(proposal.args),
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
            context.trace_failures = 0
            return
        except Exception:  # noqa: BLE001 — 기록 실패 자체는 호출을 실패시키지 않는다
            continue
    context.trace_failures += 1
    if context.trace_failures >= TRACE_FAILURE_HALT_AFTER:
        raise TraceUnavailable


def summarize_args(args: dict[str, Any]) -> str:
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
