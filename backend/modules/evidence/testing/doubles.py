"""LLM 포트 대역 — 대본을 순서대로 돌려준다. 실모델을 타지 않는다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ports.llm import (
    AnswerDraft,
    AnswerRequest,
    AnswerSentence,
    LlmDecision,
    TerminationProposal,
)

__all__ = ["ScriptedAnswer", "ScriptedLlm"]


@dataclass
class ScriptedLlm:
    """`EvidenceDecisionPort` 대역 — 정한 결정을 순서대로, 소진되면 종료를 제안한다.

    `question_kind`는 대본이 빈 뒤 나가는 종료 제안에 실린다. 골든셋처럼 "탐색은 보지 않고
    종료→판단 꼬리만 본다"는 테스트가 그것 하나만 필요로 한다.
    """

    script: list[Any] = field(default_factory=list)
    question_kind: str | None = None
    observations: list[Any] = field(default_factory=list)
    # 무엇을 봤는지만큼 **무엇을 쓸 수 있었는지**도 기록한다 — scope별 도구 노출을 보는
    # 테스트가 필요로 한다. 대역이 포트의 입력 하나를 버리면 대역이 또 갈라진다.
    seen_tools: list[frozenset[str]] = field(default_factory=list)
    raises: Exception | None = None

    def decide(self, observation, tools) -> LlmDecision:
        self.observations.append(observation)
        self.seen_tools.append(frozenset(spec.name for spec in tools))
        if self.raises is not None:
            raise self.raises
        if not self.script:
            return LlmDecision(
                proposal=TerminationProposal(note="done", question_kind=self.question_kind),
                cost_estimate_usd=0.001,
            )
        return LlmDecision(proposal=self.script.pop(0), cost_estimate_usd=0.001)


@dataclass
class ScriptedAnswer:
    """`EvidenceAnswerPort` 대역 — 정한 문장 묶음을, 소진되면 마지막 것을 반복한다.

    `script`가 비어 있으면 요청에 실린 첫 근거 번호를 인용한 문장 하나 + 종합 문장 하나를
    만든다. 판단 층 배선만 보는 테스트가 대본을 안 적어도 되게 하는 기본값이다.
    """

    script: list[tuple[AnswerSentence, ...]] = field(default_factory=list)
    requests: list[AnswerRequest] = field(default_factory=list)
    raises: Exception | None = None
    cost: float | None = 0.02

    def write(self, request: AnswerRequest) -> AnswerDraft:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        if not self.script:
            numbers = tuple(view.number for view in request.evidence)
            return AnswerDraft(
                sentences=(
                    AnswerSentence(text="근거가 이렇게 말한다", refs=numbers[:1]),
                    AnswerSentence(text="갈리는 지점은 조건이다"),
                ),
                cost_estimate_usd=self.cost,
            )
        sentences = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return AnswerDraft(sentences=sentences, cost_estimate_usd=self.cost)
