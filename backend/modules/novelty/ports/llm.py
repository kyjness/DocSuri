"""tool-calling LLM 포트 — 매 턴 다음 도구·인자 또는 종료 제안을 결정한다.

에이전트의 종료 판단은 제안일 뿐 판정 권위가 아니다(BR-RA1) — 수용 여부는
domain.loop이 저장 게이트 기준으로 판정한다. 시스템 지시와 도구 결과(신뢰 경계
밖 데이터)의 분리는 어댑터 책임이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import ToolSpec

__all__ = [
    "LlmDecision",
    "LoopObservation",
    "TerminationProposal",
    "ToolCallProposal",
    "ToolCallingLlmPort",
    "ToolResultView",
]


@dataclass(frozen=True, slots=True)
class ToolResultView:
    """직전 도구 호출의 관찰 뷰 — content는 신뢰 경계 밖 데이터."""

    seq: int
    tool_name: str
    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LoopObservation:
    """observe 단계 입력(BLM §2): 도구 결과·산출물 현황·남은 예산 요약."""

    topic: str
    input_type: str
    recent_results: tuple[ToolResultView, ...]
    saved_artifact_kinds: frozenset[str]
    missing_required_kinds: frozenset[str]
    iterations_left: int
    tool_calls_left: int
    cost_left_usd: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    tool_name: str
    args: dict[str, Any]
    decision_note: str | None = None


@dataclass(frozen=True, slots=True)
class TerminationProposal:
    """에이전트의 '충분하다' 제안 — 게이트가 판정한다(BR-RA1)."""

    note: str | None = None


@dataclass(frozen=True, slots=True)
class LlmDecision:
    proposal: ToolCallProposal | TerminationProposal
    cost_estimate_usd: float | None = None


class ToolCallingLlmPort(Protocol):
    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision: ...
