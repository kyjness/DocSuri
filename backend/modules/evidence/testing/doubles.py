"""LLM 포트 대역 — 대본을 순서대로 돌려준다. 실모델을 타지 않는다."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..ports.llm import (
    AnswerDraft,
    AnswerRequest,
    AnswerSentence,
    ExtractionDraft,
    LlmDecision,
    TerminationProposal,
)

__all__ = ["NoHits", "NoItems", "ScriptedAnswer", "ScriptedLlm", "ScriptedSearch"]


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


@dataclass
class ScriptedSearch:
    """`CorpusSearchPort` 대역 — 정한 후보를 돌려주고 받은 인자를 남긴다.

    포트 대역이 테스트 파일마다 복사돼 있었다(추출 3벌·검색 3벌). PR 3이 정확히 그 이유로
    이 패키지를 만들었는데 PR 4의 것들이 안 들어왔고, 대가는 그 diff가 증명했다 — `years=`
    인자를 더하느라 네 대역을 따로 고쳤다.
    """

    hits: tuple[Any, ...] = ()
    error: Exception | None = None
    queries: list[tuple[str, bool]] = field(default_factory=list)
    years: list[Any] = field(default_factory=list)

    def search(self, query: str, *, phrase: bool = False, years: Any = None) -> tuple[Any, ...]:
        self.queries.append((query, phrase))
        self.years.append(years)
        if self.error:
            raise self.error
        return tuple(self.hits)


class NoHits(ScriptedSearch):
    """검색은 돌지만 결과가 없다 — 바닥 2가 묻는 것은 찾았는가가 아니라 찾아봤는가다."""


@dataclass
class NoItems:
    """`EvidenceExtractionPort` 대역 — 정한 **검증 전** 원시 항목을 돌려준다(기본은 없음).

    게이트가 판정할 몫을 대역이 미리 걸러내면 판정 지점이 둘이 된다 — 그래서 원시 dict를
    그대로 돌려주고, 무엇이 통과하는지는 실제 게이트가 정한다.
    """

    items: list[Any] = field(default_factory=list)
    error: Exception | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)
    # 호출당 비용. 기본이 None인 것은 "못 쟀다"이고 0.0과 다르다 — 0으로 두면 예산 계상을
    # 검사하는 테스트가 "쟀는데 공짜"와 구분을 못 한다.
    cost_usd: float | None = None

    def extract(self, *, topic: str, focus: str, papers: tuple[Any, ...]) -> ExtractionDraft:
        self.calls.append({"topic": topic, "focus": focus, "papers": papers})
        if self.error:
            raise self.error
        return ExtractionDraft(items=self.items, cost_estimate_usd=self.cost_usd)
