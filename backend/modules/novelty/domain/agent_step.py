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
from enum import StrEnum
from typing import Any

from ..ports.llm import (
    LoopObservation,
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
    ArtifactKind,
    ArtifactRecord,
    ChatKind,
    ChatRole,
    NoveltyChatMessage,
    NoveltyJob,
    ToolCallRecord,
    ToolOutcome,
    utc_now,
)

__all__ = [
    "LATE_STEERING_NOTICE",
    "ON_DEMAND_UNAVAILABLE_NOTICE",
    "SAVE_ARTIFACT_SPEC",
    "AgentContext",
    "AgentDeps",
    "StepResult",
    "TraceUnavailable",
    "append_agent_message",
    "build_observation",
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
#
# payload 형태를 스펙에 싣는 이유(로컬 실스택 검증 반영): 종전에는 payload가
# 스키마 없는 {"type": "object"}였다. 모델은 컨테이너 키를 추측할 수밖에 없었고
# similar_works에 {"works": [...]}를 보냈다 — 게이트는 payload["items"]를 읽으므로
# 빈 산출물로 거부됐고, 사유("비어 있다")가 키가 틀렸다는 사실을 알려주지 않아
# 같은 구조로 재시도하다 예산을 소진했다. 그 결과 필수 세트가 영영 완성되지 않았다.
# source_refs의 recordRef는 지어낼 수 없다 — 게이트가 이번 잡이 도구 결과로 확보한
# 집합과 대조한다(BR-NV19). 도구 결과 카드가 같은 이름으로 값을 실어 보내므로,
# 그 값을 그대로 복사하라고 명시한다. 종전에는 카드에 `arxivId`로만 보여서 모델이
# 연결을 알 수 없었고 산출물마다 unknown_source_ref로 거부됐다.
SOURCE_REF_RULE = (
    'source_refs/supporting_refs 항목은 {"paperId": ..., "recordRef": ...} 형태이고, '
    "recordRef는 도구 결과 카드의 recordRef 값을 **그대로 복사**해야 한다 — "
    "지어내거나 URL·제목으로 대체하면 unknown_source_ref로 거부된다."
)

SAVE_ARTIFACT_PAYLOAD_SHAPES = {
    "evidence": (
        "{state, claims[], coverage, abstain_reason(state=abstain일 때 필수)} — "
        "form_evidence 결과를 그대로 넣는다(보통 자동 저장됨)"
    ),
    "similar_works": (
        '{"items": [{artifact_type, title, problem_definition?, method?, dataset?, '
        "result?, limitation?, overlap_with_user_idea?, source_refs[], evidence_status?, "
        "confidence?}]}"
    ),
    "gap_analysis": (
        '{"items": [{area, status(well_covered|partially_covered|open_gap), rationale, '
        "source_refs[], searched_scope_note(open_gap일 때 필수), related_similar_work_ids?}]}"
    ),
    "external_findings": (
        '{"items": [{source_type, canonical_id, title, url, license?, task?, metrics?, '
        "baseline_or_code_hint?}]}"
    ),
    "novelty_candidates": (
        '{"items": [{angle, rationale, excluded_claims, supporting_refs[], '
        "conflicting_refs?, feasibility_notes?}]}"
    ),
    "experiment_plan": (
        "{hypothesis, novelty_angle, baselines[], datasets[], metrics[], procedure[], "
        "risks[], resources[], source_refs[]} — 목록 아님(단일 객체). 배열 필드는 전부 "
        "1개 이상이어야 한다(빈 배열은 거부된다)"
    ),
}

# 어느 kind가 {"items": [...]} 컨테이너인지는 위 표에서 읽는다 — 같은 사실을 두 번
# 쓰면 kind가 늘 때 한쪽만 고쳐져 모델에게 옛 구분을 알려주게 된다.
_ITEMS_CONTAINER_KIND_NAMES = tuple(
    kind for kind, shape in SAVE_ARTIFACT_PAYLOAD_SHAPES.items() if '"items"' in shape
)
_SINGLE_OBJECT_KIND_NAMES = tuple(
    kind for kind in SAVE_ARTIFACT_PAYLOAD_SHAPES if kind not in _ITEMS_CONTAINER_KIND_NAMES
)

SAVE_ARTIFACT_SPEC = ToolSpec(
    name=TOOL_SAVE_ARTIFACT,
    description=(
        "조사 산출물 저장 시도. 결정론 게이트가 SourceRef 실재성·필수 필드·bounded "
        "규칙을 검증하며, 거부 시 기계 판독 사유가 반환된다.\n"
        "payload 형태는 kind마다 다르다 — 아래 형태를 정확히 따를 것. 표 형태 산출물은 "
        '반드시 최상위 키 "items"에 배열을 담는다(다른 이름을 쓰면 형태 오류로 거부된다).\n'
        + "\n".join(f"- {kind}: {shape}" for kind, shape in SAVE_ARTIFACT_PAYLOAD_SHAPES.items())
        + "\n"
        + SOURCE_REF_RULE
    ),
    parameters={
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": sorted(SAVE_ARTIFACT_PAYLOAD_SHAPES),
            },
            "payload": {
                "type": "object",
                # 조사(는/은)를 붙이지 않는다 — kind 이름은 영문 식별자라 목록이
                # 바뀌면 받침이 어긋난다. 화살표 표기는 어떤 조합에도 맞는다.
                "description": (
                    "kind별 형태는 도구 설명 참조. "
                    + "·".join(_ITEMS_CONTAINER_KIND_NAMES)
                    + ' → {"items": [...]} 형태 / '
                    + "·".join(_SINGLE_OBJECT_KIND_NAMES)
                    + " → 단일 객체."
                ),
            },
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

# 같은 판정(온디맨드 불가·종료 후 도착)을 API와 워커·루프가 서로 다른 시점에 내릴 수
# 있다 — 사용자에게는 같은 문구여야 하므로 여기 한 곳에만 둔다.
ON_DEMAND_UNAVAILABLE_NOTICE = "이 조사에서는 추가 생성을 할 수 없어요. 새 조사로 이어가 주세요."
LATE_STEERING_NOTICE = (
    "조사가 종료된 뒤 도착한 메시지입니다 — 다시 보내주시면 이어서 답변해 드릴게요."
)


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
    # 이번 실행에서 마지막으로 게이트를 통과한 저장 — 대화 턴이 답장에 산출물
    # 참조를 걸 때 쓴다(재저장도 저장이다 — saved_kinds 차집합으로는 놓친다).
    last_saved: tuple[ArtifactKind, str] | None = None


class StepResult(StrEnum):
    """한 걸음의 결과 — 종료 의미 부여는 호출자 몫(루프는 partial, 턴은 안내)."""

    CONTINUE = "continue"
    BUDGET_EXHAUSTED = "budget_exhausted"


class TraceUnavailable(Exception):
    """트레이스 기록 불가 지속 — 실행을 계속하지 않는다(NFR-NV2-13)."""


def seed_context(
    job: NoveltyJob,
    deps: AgentDeps,
    *,
    artifacts: list[ArtifactRecord] | None = None,
    inherit_steering: bool = True,
) -> AgentContext:
    """저장된 산출물과 그 출처 핸들, 원고 recordRef, 대화 스티어링을 복원한다.

    재전달 복원(코드 리뷰 반영): crash 후 재실행이 작업·예산을 이중 소진하지 않고,
    저장소가 완성 판정의 단일 진실로 남는다(BR-RA1). 온디맨드 턴도 같은 함수를
    쓴다 — 그래서 턴이 인용할 수 있는 출처는 이미 저장된 산출물에 근거가 있거나
    이번 턴 도구 호출로 새로 얻은 것뿐이고, BR-RA6이 추가 코드 없이 성립한다.

    `artifacts`: 호출자가 같은 목록을 다른 용도로도 쓸 때(턴의 근거 시드) 조회를
    한 번으로 줄이는 주입점 — 미지정이면 여기서 읽는다.
    """
    context = AgentContext()
    if artifacts is None:
        artifacts = deps.store.list_artifacts(job.owner_id, job.job_id)
    for record in artifacts:
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
    # 윈도우만 남으므로 이력 전체를 다시 재생하지는 않는다. 온디맨드 턴은 승계하지
    # 않는다(inherit_steering=False) — 커서 없이 읽으면 가장 오래된 페이지가 잡히고,
    # 이번 요청은 request로 이미 전달되며, 지난 턴의 요청은 살아 있는 지시가 아니다.
    if inherit_steering:
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


def build_observation(
    job: NoveltyJob,
    context: AgentContext,
    *,
    missing_required: frozenset[str] = frozenset(),
    mode: str = "loop",
    request: str | None = None,
) -> LoopObservation:
    """관찰 조립의 단일 정의 — 루프와 대화 턴이 의도한 차이(mode·request·필수 세트)만
    인자로 밝히고, 예산 잔량 계산·노트 윈도우 등 나머지는 여기서 한 번만 유지한다."""
    budget = job.loop_run.budget  # type: ignore[union-attr]
    consumed = budget.consumed
    return LoopObservation(
        topic=job.request.topic,
        input_type=job.request.input_type.value,
        recent_results=tuple(context.recent_results),
        saved_artifact_kinds=frozenset(kind.value for kind in context.saved_kinds),
        missing_required_kinds=missing_required,
        iterations_left=budget.max_iterations - consumed.iterations,
        tool_calls_left=budget.max_tool_calls_total - consumed.tool_calls_total,
        cost_left_usd=max(budget.token_cost_limit_usd - consumed.cost_usd, 0.0),
        notes=tuple(context.notes[-4:]),
        steering=tuple(context.steering),
        mode=mode,
        request=request,
    )


def append_agent_message(
    store: NoveltyStorePort,
    job: NoveltyJob,
    content: str,
    *,
    kind: ChatKind = ChatKind.NOTICE,
    resulting_artifact_ref: str | None = None,
    in_reply_to: str | None = None,
) -> None:
    """에이전트 명의의 대화 메시지를 best-effort로 남긴다 — 침묵 종료 금지의 공용 경로.

    저장 실패가 호출자의 흐름(요청 응답·종단 기록·턴 결과)을 깨지 않는다.
    `in_reply_to`: 특정 사용자 메시지에 대한 답장이면 그 id — 턴 멱등 판정의 근거."""
    try:
        store.append_message(
            NoveltyChatMessage(
                job_id=job.job_id,
                owner_id=job.owner_id,
                role=ChatRole.AGENT,
                kind=kind,
                content=content[:12000],
                resulting_artifact_ref=resulting_artifact_ref,
                in_reply_to=in_reply_to,
            )
        )
    except Exception:  # noqa: BLE001 — 안내 실패가 호출자를 막지 않는다
        log.warning("novelty agent: chat message persist failed for job %s", job.job_id)


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
    artifact_id = deps.store.save_artifact(
        ArtifactRecord(job_id=job.job_id, owner_id=job.owner_id, kind=kind, payload=payload)
    )
    context.saved_kinds.add(kind)
    context.last_saved = (kind, artifact_id)
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
    artifact_id = deps.store.save_artifact(
        ArtifactRecord(
            job_id=job.job_id, owner_id=job.owner_id,
            kind=ArtifactKind.EVIDENCE, payload=snapshot,
        )
    )
    context.saved_kinds.add(ArtifactKind.EVIDENCE)
    context.last_saved = (ArtifactKind.EVIDENCE, artifact_id)
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
