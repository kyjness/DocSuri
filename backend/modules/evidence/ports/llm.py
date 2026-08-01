"""tool-calling LLM 포트 — 매 턴 다음 도구·인자 또는 종료를 제안한다.

에이전트의 종료 판단은 **제안**이다. 누적 근거가 0건이면 정상 종료로 인정하지
않는다(INV-EV-2) — 판정은 도메인이 한다. 시스템 지시와 도구 결과(신뢰 경계 밖
데이터)의 분리는 어댑터 책임이다(BR-EV-17).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import ImageAttachment, ToolSpec

__all__ = [
    "EvidenceLlmPort",
    "LlmDecision",
    "LlmUnavailable",
    "LoopObservation",
    "PaperView",
    "TerminationProposal",
    "ToolCallProposal",
    "ToolResultView",
]


class LlmUnavailable(RuntimeError):
    """재시도·서킷 브레이커를 지나서도 실패 — fail-closed로 수렴한다(BR-EV-12)."""


@dataclass(frozen=True, slots=True)
class ToolResultView:
    """직전 도구 호출의 관찰 뷰 — 전부 신뢰 경계 밖 데이터.

    `args_summary`는 **그 결과를 낳은 호출의 인자**다. 결과만 보여주면 모델은 자기가
    방금 무엇을 물었는지 몰라 같은 질의를 반복하고, 그 반복이 캡을 태워 근거를 못
    채운 채 종료한다(novelty ⑤3 실측).

    `images`는 가장 최근 결과 1건에만 남는다 — 도메인이 절단한다. 남겨두면 윈도우에서
    밀려날 때까지 매 턴 재전송돼 같은 토큰이 반복 계상된다.
    """

    seq: int
    tool_name: str
    ok: bool
    args_summary: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    images: tuple[ImageAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class PaperView:
    """확보한 논문 1편의 관찰 뷰 — 어디까지 읽었는지가 깊이 판단의 입력이다."""

    paper_id: str
    record_ref: str
    title: str
    origin: str
    scope: str


@dataclass(frozen=True, slots=True)
class LoopObservation:
    """observe 단계 입력(BLM §1.1)."""

    topic: str
    papers: tuple[PaperView, ...]
    recent_results: tuple[ToolResultView, ...]
    evidence_count: int
    cited_paper_count: int
    has_conflicts: bool
    iterations_left: int
    tool_calls_left: int
    cost_left_usd: float
    # 이전 턴 맥락(FR-36 멀티턴) — 후속 질문 해석은 규칙이 아니라 이 관찰 위의 판단이다.
    prior_topics: tuple[str, ...] = ()
    prior_paper_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    tool_name: str
    args: dict[str, Any]
    decision_note: str | None = None


@dataclass(frozen=True, slots=True)
class TerminationProposal:
    """'충분하다' 제안 — 누적 근거가 없으면 수용되지 않는다(INV-EV-2)."""

    note: str | None = None


@dataclass(frozen=True, slots=True)
class LlmDecision:
    proposal: ToolCallProposal | TerminationProposal
    cost_estimate_usd: float | None = None


class EvidenceLlmPort(Protocol):
    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision: ...
