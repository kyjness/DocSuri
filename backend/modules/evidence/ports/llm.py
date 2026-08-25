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
    "COUNTER_REQUIRED_KINDS",
    "QUESTION_KINDS",
    "QUESTION_KIND_UNKNOWN",
    "AnswerDraft",
    "AnswerEvidenceView",
    "AnswerRequest",
    "AnswerSentence",
    "EvidenceAnswerPort",
    "EvidenceExtractionPort",
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
    # content의 렌더형(직렬화+절단) — 관찰은 같은 결과를 매 회차 다시 싣는 구조라,
    # 여기서 1회 만들어 두지 않으면 수십 KB dict가 회차마다 재직렬화된다.
    content_preview: str = ""
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
    # 토큰 예산에서 밀려난 앞쪽 턴들의 요약 한 단락(§3.4). 최근 턴은 `prior_topics`에
    # 그대로 실리고 이쪽은 그 앞을 접은 것이다.
    prior_summary: str = ""
    notes: tuple[str, ...] = ()
    # 아직 확인하지 않은 후보 — **모델에게 보여야 부를 수 있다**. 검색 도구가 없는
    # explicit scope에서는 이 목록이 유일한 id 출처라, 빠지면 모델이 id를 지어낸다.
    pending_papers: tuple[PaperView, ...] = ()


@dataclass(frozen=True, slots=True)
class ToolCallProposal:
    tool_name: str
    args: dict[str, Any]
    decision_note: str | None = None


# 질문 유형(설계 v3 §3.3) — 별도 분류기를 두지 않고 모델이 선언한다.
QUESTION_KINDS = ("claim", "comparison", "fact", "out_of_scope")
QUESTION_KIND_UNKNOWN = "unknown"

# 반대 측 탐색이 필요한 유형(§3.3 바닥 2). `fact`는 면제이고, 선언 기회가 없던 턴
# (`unknown`)도 면제한다 — 선언 못 한 것을 이유로 종료를 막으면 예산 소진·취소로 끝난
# 턴이 영영 못 끝난다.
#
# **한 곳에만 둔다.** 루프의 바닥 검사와 1층 채점이 이 집합을 나눠 쓰는데, 두 벌로 뒀더니
# 불변식을 주석이 지키고 있었다 — 넓으면 루프가 통과시킨 턴을 채점이 위반으로 찍고,
# 좁으면 지표가 조용히 눈감는다. 골든셋 하네스까지 세 벌이었다.
COUNTER_REQUIRED_KINDS: frozenset[str] = frozenset({"claim", "comparison"})


@dataclass(frozen=True, slots=True)
class TerminationProposal:
    """'충분하다' 제안 — 누적 근거가 없으면 수용되지 않는다(INV-EV-2)."""

    note: str | None = None
    # 종료 시점에 선언되는 질문 유형. 예산 소진·취소로 끝난 턴에는 선언 기회가 없어
    # None이 온다 — 판단 프롬프트는 그때 `unknown`으로 읽는다.
    question_kind: str | None = None


@dataclass(frozen=True, slots=True)
class LlmDecision:
    proposal: ToolCallProposal | TerminationProposal
    cost_estimate_usd: float | None = None


class EvidenceLlmPort(Protocol):
    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision: ...


class EvidenceExtractionPort(Protocol):
    """근거 추출 LLM — `extract_evidence` 도구 뒤에 있다.

    `decide`와 분리한 이유는 역할이 다르기 때문이다: decide는 "다음에 무엇을 할까",
    extract는 "이 논문들에서 무엇을 인용할까". 프롬프트도 검증 경계도 다르고,
    추출 결과는 **반드시 게이트를 지나야** 저장된다(INV-EV-6).

    반환은 검증 전 원시 항목이다(`{statement, supporting[], conflicting[]}`) —
    게이트가 판정할 몫을 어댑터가 미리 걸러내면 판정 지점이 둘이 된다.
    """

    def extract(
        self, *, topic: str, focus: str, papers: tuple[Any, ...]
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class AnswerEvidenceView:
    """판단 층에 넘기는 근거 한 건(설계 v3 §4.2).

    `number`는 `assemble`이 화면에 낼 표시 순서의 1-기반 번호다 — 근거표 행 번호와
    같은 출처이므로 여기서 따로 매기지 않는다.
    """

    number: int
    statement: str
    paper_id: str
    quote: str
    locator: str = ""
    # 이 근거와 상충하는 다른 근거 번호 — §2.2 "갈릴 때 조건을 나눠 말한다"의 재료다.
    conflicts_with: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    """`answer` 노드 입력. **게이트를 통과한 근거만** 실린다(§4.2)."""

    topic: str
    question_kind: str
    evidence: tuple[AnswerEvidenceView, ...]
    # 재생성일 때만 채워진다 — 무엇이 거부됐는지 알려야 다음 시도가 달라진다(§4.3).
    reject_reason: str | None = None


@dataclass(frozen=True, slots=True)
class AnswerSentence:
    """모델이 낸 **검증 전** 문장.

    `kind`(cited/synthesis)는 여기 없다 — 모델이 선언하는 값이 아니라 `refs`에서
    도메인이 유도한다. 모델에게 "이건 확인된 문장이다"라고 스스로 말하게 두면 그 선언을
    또 검사해야 하고, 판정 지점이 둘이 된다(게이트가 추출 결과를 다루는 방식과 같다).
    """

    text: str
    refs: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AnswerDraft:
    sentences: tuple[AnswerSentence, ...]
    cost_estimate_usd: float | None = None


class EvidenceAnswerPort(Protocol):
    """판단 LLM — `decide`·`extract`와 분리한다.

    셋의 임무가 다르다: decide는 "다음에 무엇을 할까", extract는 "이 논문에서 무엇을
    인용할까", answer는 "모인 근거로 무엇이라 판단할까". 프롬프트도 검증 경계도 다르고,
    answer 결과는 반드시 §4.3 검사를 지나야 화면에 간다.
    """

    def write(self, request: AnswerRequest) -> AnswerDraft: ...
