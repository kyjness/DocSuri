"""온디맨드 대화 턴(BLM §5) — 종단 잡에서 사용자의 요청 하나를 처리한다.

조사 재실행이 아니다(NFR-NV2-7): 잡의 거시 상태는 바뀌지 않고(BR-RA5 — 종단 상태
재진입 금지), 응답은 대화 턴으로 돌아간다. 생성물(NoveltyCandidate·ExperimentPlan)은
조사 산출물과 **같은 저장 게이트**를 통과해야 저장·응답된다(BR-RA6) — 그래서 이
모듈은 저장을 직접 하지 않고 `agent_step.execute_step`에만 위임한다.

근거 경계는 공짜로 성립한다: `seed_context`가 복원하는 known_record_refs는 이미
저장된 산출물에서 회수한 출처와 이번 턴 도구 호출로 새로 얻은 출처뿐이므로, 게이트가
그 밖의 인용을 거부한다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ..ports.llm import (
    LoopObservation,
    TerminationProposal,
    ToolResultView,
    fit_result_content,
)
from ..ports.tools import ToolSpec
from . import budget as budget_rules
from .agent_step import (
    SAVE_ARTIFACT_SPEC,
    AgentContext,
    AgentDeps,
    StepResult,
    TraceUnavailable,
    append_agent_message,
    build_observation,
    execute_step,
    persist_progress,
    seed_context,
)
from .models import (
    ARTIFACT_LABELS,
    ArtifactKind,
    ArtifactRecord,
    ChatKind,
    NoveltyChatMessage,
    NoveltyJob,
)

__all__ = ["REPLY_SPEC", "TOOL_REPLY", "TurnOutcome", "run_turn"]

log = logging.getLogger("docsuri.novelty.turn")

# reply는 레지스트리 도구가 아니다 — KNOWN_LOOP_TOOLS에 없으므로 ToolRegistry가
# 이 이름의 등록을 구조적으로 거부한다. 턴이 execute_step 이전에 직접 처리하므로
# 도구 호출 예산을 소비하지 않고 ToolCallRecord도 남기지 않는다(대화 메시지가 기록).
TOOL_REPLY = "reply"

REPLY_SPEC = ToolSpec(
    name=TOOL_REPLY,
    description=(
        "사용자에게 답변하고 이번 턴을 끝낸다. 산출물 생성이 필요 없는 질문이거나, "
        "저장을 마쳤거나, 요청을 수행할 수 없을 때 사용한다."
    ),
    parameters={
        "type": "object",
        "properties": {"content": {"type": "string", "maxLength": 4000}},
        "required": ["content"],
    },
)

# 대화 응답에 근거로 실어 보낼 산출물과 1건당 절단 길이. 조사 결과 전체를 그대로
# 넣으면 입력이 비싸지므로, 계획 수립에 필요한 종류만 고른다(BLM §5.3).
_EVIDENCE_KINDS = (
    ArtifactKind.SIMILAR_WORKS,
    ArtifactKind.GAP_ANALYSIS,
    ArtifactKind.EVIDENCE,
)
_ARTIFACT_PAYLOAD_MAX_CHARS = 3000

_BUDGET_EXHAUSTED_REPLY = (
    "이 조사에 배정된 예산을 모두 사용해서 추가 생성을 할 수 없어요. "
    "새 조사를 시작하면 이어서 도와드릴 수 있습니다."
)
_NO_REPLY_FALLBACK = (
    "요청을 처리하지 못했어요. 조금 더 구체적으로 알려주시면 다시 시도해 볼게요."
)


def _with_object_particle(label: str) -> str:
    """받침 유무에 따라 을/를을 붙인다 — "계획을(를)" 같은 어색한 표기를 쓰지 않는다."""
    last = label.strip()[-1:]
    if not last:
        return label
    code = ord(last)
    has_final = 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0
    return f"{label}{'을' if has_final else '를'}"


@dataclass(slots=True)
class TurnOutcome:
    """턴 결과 — 저장된 답장 메시지와, 생성됐다면 그 산출물 참조."""

    reply: str
    artifact_ref: str | None = None
    saved_kind: ArtifactKind | None = None


def run_turn(
    job: NoveltyJob, message: NoveltyChatMessage, deps: AgentDeps, *, max_steps: int
) -> TurnOutcome:
    """종단 잡의 대화 요청 하나를 처리하고 답장을 저장한다.

    `max_steps`는 잡 예산과 별개의 상한이다 — 완료된 잡에는 반복이 넉넉히 남아 있어
    채팅 한 줄이 잔여 예산을 전부 태울 수 있다. 소비 원장은 여전히 잡의 LoopBudget
    하나이고(execute_step 내부), 이 값은 한 턴의 decide 횟수만 제한한다.
    """
    # 한 번 읽어 문맥 복원과 근거 시드에 함께 쓴다 — 같은 목록을 두 번 조회하지 않는다.
    # 스티어링 윈도우는 승계하지 않는다 — 요청 본문이 곧 이번 턴의 지시다.
    artifacts = deps.store.list_artifacts(job.owner_id, job.job_id)
    context = seed_context(job, deps, artifacts=artifacts, inherit_steering=False)
    _seed_artifacts_as_evidence(artifacts, context)

    budget = job.loop_run.budget if job.loop_run is not None else None
    if budget is None or budget_rules.begin_iteration(budget) is not None:
        # 예산이 없거나 이미 소진 — LLM을 호출하지 않고 안내로 끝낸다.
        return _finish(job, deps, message, _BUDGET_EXHAUSTED_REPLY, kind=ChatKind.NOTICE)

    try:
        return _drive(job, deps, context, message, max_steps=max_steps)
    except TraceUnavailable:
        # 트레이스는 계약이다(NFR-NV2-13) — 기록 없이 계속하지 않는다.
        return _finish(
            job, deps, message,
            "결정 기록을 남길 수 없어 요청을 중단했어요. 잠시 후 다시 시도해 주세요.",
            kind=ChatKind.NOTICE,
        )
    except Exception:  # noqa: BLE001 — 턴 실패가 종단 잡의 결과를 훼손하지 않는다
        log.exception("novelty turn: job %s failed", job.job_id)
        return _finish(
            job, deps, message, "요청을 처리하는 중 문제가 생겼어요. 다시 시도해 주세요.",
            kind=ChatKind.NOTICE,
        )
    finally:
        # 예산 소비는 실패해도 기록돼야 한다 — 잡 상태는 건드리지 않는다(BR-RA5).
        persist_progress(job, deps)


def _drive(
    job: NoveltyJob,
    deps: AgentDeps,
    context: AgentContext,
    message: NoveltyChatMessage,
    *,
    max_steps: int,
) -> TurnOutcome:
    budget = job.loop_run.budget  # type: ignore[union-attr]

    for step in range(max_steps):
        if step > 0 and budget_rules.begin_iteration(budget) is not None:
            break
        decision = deps.llm.decide(
            _observe(job, context, message), _exposed_tools(deps)
        )
        if decision.cost_estimate_usd:
            budget_rules.record_cost(budget, decision.cost_estimate_usd)

        proposal = decision.proposal
        # 어댑터가 propose_termination을 항상 주입하고, 평문 응답도 종료 제안으로
        # 변환된다. 대화 턴에서 "끝났다"는 곧 "답변했다"이므로 reply와 같게 다룬다.
        if isinstance(proposal, TerminationProposal):
            return _finish(
                job, deps, message, proposal.note or _NO_REPLY_FALLBACK,
                kind=ChatKind.AGENT_REPLY, saved=context.last_saved,
            )
        if proposal.tool_name == TOOL_REPLY:
            content = str(proposal.args.get("content") or "").strip()
            return _finish(
                job, deps, message, content or _NO_REPLY_FALLBACK,
                kind=ChatKind.AGENT_REPLY, saved=context.last_saved,
            )

        if execute_step(job, deps, context, proposal) is StepResult.BUDGET_EXHAUSTED:
            break

    # 상한·예산 소진으로 reply 없이 끝났다. 그래도 저장에 성공했다면 요청은 이뤄진
    # 것이다 — 실패로 안내하면 사용자가 이미 만들어진 산출물을 두고 재요청해 쿼터와
    # 예산을 다시 쓴다(로컬 실스택 검증에서 실제로 발생: 계획은 저장됐는데 "마무리하지
    # 못했으니 다시 요청하라"는 안내가 나갔다).
    if context.last_saved is not None:
        saved_kind, _ = context.last_saved
        label = ARTIFACT_LABELS.get(saved_kind, saved_kind.value)
        return _finish(
            job, deps, message, f"요청하신 {_with_object_particle(label)} 만들어 저장했어요.",
            kind=ChatKind.AGENT_REPLY, saved=context.last_saved,
        )
    # 침묵 종료 금지 — 아무것도 만들지 못했으면 사유를 남긴다.
    return _finish(job, deps, message, _exhausted_reply(context), kind=ChatKind.NOTICE)


def _exhausted_reply(context: AgentContext) -> str:
    """마지막 게이트 거부 사유가 있으면 사용자에게 그대로 전한다(FE 재요청 근거)."""
    for view in reversed(context.recent_results):
        if not view.ok and view.error and view.error.startswith("rejected_by_gate"):
            return (
                "요청하신 산출물을 근거 검증에서 통과시키지 못했어요 "
                f"({view.error.split(':')[1].strip()}). 다시 요청해 주시면 보완해 볼게요."
            )
    return "이번 요청은 정해진 시도 횟수 안에 마무리하지 못했어요. 다시 요청해 주세요."


def _seed_artifacts_as_evidence(
    records: list[ArtifactRecord], context: AgentContext
) -> None:
    """저장된 조사 산출물을 근거 입력으로 실어 준다(BLM §5.3).

    산출물 payload는 외부 논문 텍스트에서 파생된 데이터이므로 관찰의 '도구 결과
    데이터' 구획에 들어간다 — 어댑터가 그 구획을 지시로 취급하지 않게 렌더한다.
    """
    by_kind = {record.kind: record for record in records}
    for kind in _EVIDENCE_KINDS:
        record = by_kind.get(kind)
        if record is None:
            continue
        context.result_seq += 1
        context.recent_results.append(
            _artifact_view(context.result_seq, record)
        )


def _artifact_view(seq: int, record: ArtifactRecord) -> ToolResultView:
    return ToolResultView(
        seq=seq,
        tool_name=f"saved_artifact:{record.kind.value}",
        ok=True,
        content=_truncate_payload(record.payload),
    )


def _truncate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """렌더링 전 1차 절단 — 산출물 3종을 그대로 실으면 입력이 과대해진다.

    항목 단위로 줄인다(바이트 절단 아님) — 마지막 행이 중간에서 끊기면 그 행의
    recordRef가 잘린 채 인용돼 게이트에서 거부된다.
    """
    return fit_result_content(payload, _ARTIFACT_PAYLOAD_MAX_CHARS)


def _observe(
    job: NoveltyJob, context: AgentContext, message: NoveltyChatMessage
) -> LoopObservation:
    # 필수 세트는 비운다 — 대화 턴은 필수 산출물을 다시 채우는 자리가 아니고,
    # 모델을 조사로 되돌리지 않는다(BR-RA5).
    return build_observation(job, context, mode="turn", request=message.content)


def _exposed_tools(deps: AgentDeps) -> tuple[ToolSpec, ...]:
    return (*deps.registry.specs(), SAVE_ARTIFACT_SPEC, REPLY_SPEC)


def _finish(
    job: NoveltyJob,
    deps: AgentDeps,
    message: NoveltyChatMessage,
    reply: str,
    *,
    kind: ChatKind,
    saved: tuple[ArtifactKind, str] | None = None,
) -> TurnOutcome:
    """답장을 대화에 남긴다 — 산출물을 만들었으면 그 참조를 함께 건다(BLM §5.5).

    `saved`는 이번 턴에 게이트를 통과한 마지막 저장(context.last_saved) — 저장
    시점에 id를 받아 두므로 참조를 다시 조회하지 않는다. in_reply_to가 이 턴의
    멱등 판정 근거이므로 어떤 종류의 답장(안내 포함)이든 반드시 건다."""
    saved_kind, artifact_ref = saved if saved is not None else (None, None)
    append_agent_message(
        deps.store, job, reply, kind=kind,
        resulting_artifact_ref=artifact_ref, in_reply_to=message.message_id,
    )
    return TurnOutcome(reply=reply, artifact_ref=artifact_ref, saved_kind=saved_kind)
