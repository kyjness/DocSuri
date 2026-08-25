"""도구 포트(BLM §2) — 루프가 부르는 부품. 스스로 판단하지 않는다.

도구 실행 결과는 **신뢰 경계 밖 데이터**다(BR-EV-17) — LLM 컨텍스트에 넣을 내용과
트레이스용 sanitized 요약을 분리해 반환한다. 등록은 allowlist deny-by-default라
어휘 밖 도구는 이름과 무관하게 구조적으로 합류할 수 없다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "KNOWN_LOOP_TOOLS",
    "STANCES",
    "STANCE_COUNTER",
    "STANCE_TOOLS",
    "counter_probes",
    "TOOL_CORPUS_SEARCH",
    "TOOL_EXTRACT_EVIDENCE",
    "TOOL_FETCH_PAPER",
    "TOOL_LIVE_LOOKUP",
    "TOOL_READ_PAPER",
    "TOOL_VIEW_FIGURE",
    "ImageAttachment",
    "ToolContext",
    "ToolPort",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
]

TOOL_CORPUS_SEARCH = "corpus_search"
TOOL_LIVE_LOOKUP = "live_lookup"
TOOL_FETCH_PAPER = "fetch_paper"
TOOL_READ_PAPER = "read_paper"
TOOL_VIEW_FIGURE = "view_figure"
TOOL_EXTRACT_EVIDENCE = "extract_evidence"

# 탐색 방향 선언(설계 v3 §3.2). 모델이 "반대 근거를 찾는 중"이라고 **선언**하게 해서
# 시스템이 셀 수 있게 한다 — 프롬프트 당부("반대 근거도 찾아라")로 두지 않는 이유는
# novelty에서 당부가 지켜지지 않는 것을 실측했기 때문이다.
STANCE_SUPPORT = "support"
STANCE_COUNTER = "counter"
STANCE_NEUTRAL = "neutral"
STANCES: tuple[str, ...] = (STANCE_SUPPORT, STANCE_COUNTER, STANCE_NEUTRAL)

# v1 도구 어휘(FD 게이트 Q1=A). 신규 도구는 이 어휘를 명시 확장해야만 합류한다.
KNOWN_LOOP_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_CORPUS_SEARCH,
        TOOL_LIVE_LOOKUP,
        TOOL_FETCH_PAPER,
        TOOL_READ_PAPER,
        TOOL_VIEW_FIGURE,
        TOOL_EXTRACT_EVIDENCE,
    }
)


# `stance`를 인자로 받는 도구 — 바닥 검사(§3.3)가 세는 대상이다. 다른 도구에 붙은 선언은
# 세지 않는다: `read_paper`에 stance=counter를 달아도 반대 측을 **찾은** 것은 아니다.
STANCE_TOOLS: frozenset[str] = frozenset(
    {TOOL_CORPUS_SEARCH, TOOL_LIVE_LOOKUP, TOOL_EXTRACT_EVIDENCE}
)


# 반대 측 탐색으로 인정되는 결과 — **일을 했는가**가 기준이다.
#
# 0건(EMPTY)은 센다: 바닥이 요구하는 것은 "찾아봤는가"이지 "찾았는가"가 아니다(없다는 것도
# 결과다). 반대로 실패(ERROR)·예산 거부는 **세지 않는다** — 초안은 "인덱스가 죽은 턴이
# 영원히 못 끝난다"는 이유로 ERROR를 셌는데, 그러면 `extract_evidence(paper_ids=[])`처럼
# **포트에 닿기도 전에 인자 검증에서 떨어지는 호출**이 바닥을 열어 준다(실측). 선언만 붙이면
# 지나는 공짜 통로다.
#
# 그래서 "영원히 못 끝난다"는 걱정은 세는 규칙이 아니라 **바닥 쪽 탈출구**로 막는다 —
# stance를 받는 도구를 더 부를 예산이 없으면 바닥이 종료를 받아들인다(`domain.loop`).
_PROBE_COUNTED = frozenset({"ok", "empty"})


def counter_probes(trace: list[Any]) -> int:
    """`stance="counter"`로 실제 돈 검색·추출 횟수 — 바닥 2와 1층 채점이 같은 것을 센다.

    `ToolCallRecord`(도메인)와 `STANCE_TOOLS`(여기) 둘 다에 붙는 순수 술어라 이 자리에 둔다.
    그래프 모듈에 두었더니 1층 채점이 픽스처를 매기려고 langgraph를 끌고 왔다.
    """
    return sum(
        1
        for r in trace
        if r.stance == STANCE_COUNTER
        and r.tool in STANCE_TOOLS
        and str(getattr(r.outcome, "value", r.outcome)) in _PROBE_COUNTED
    )


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """LLM에 노출되는 도구 서명(JSON Schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """owner-scoped 실행 문맥(SEC-8).

    현행 도구 6종은 이 값을 읽지 않는다 — 코퍼스 자산은 소유자별 리소스가 아니고
    (novelty ViewFigureTool과 같은 근거), 세션 격리는 턴마다 새로 만드는 루프
    상태가 담당한다. 소유자별 도구(예: 개인 라이브러리 검색)가 생기면 그때 읽는다.
    포트 계약으로 유지하는 이유다."""

    owner_id: str
    session_id: str
    turn_id: str


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    """도구가 확보한 이미지 1건 — 텍스트가 아닌 별도 채널로 전달된다.

    `content`는 문자 한도로 절단되므로 base64를 실으면 디코드 불능으로 조용히
    사라진다. 이미지도 신뢰 경계 밖 데이터이며 어댑터가 도구 결과 구획 **뒤에**
    배치한다(그림 안의 문구는 지시가 아니다).
    """

    media_type: str
    data_b64: str
    asset_id: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """단일 도구 실행 결과.

    content        — 다음 observe에서 LLM이 보는 내용(신뢰 경계 밖).
    result_summary — 트레이스·활동 피드용 sanitized 요약(SEC-9, INV-EV-5).
    error          — 실패 사유. **판정이자 수리 지시**여야 한다(BR-EV-18) —
                     "무엇이 틀렸는지 + 다음에 무엇을 하면 되는지".
    """

    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    cost_usd: float | None = None
    error: str | None = None
    images: tuple[ImageAttachment, ...] = ()


class ToolPort(Protocol):
    spec: ToolSpec

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    """가용 설정이 있는 도구만 등록된다 — 없으면 도구 목록이 자연 축소된다
    (logical-components §4). 어휘 밖 이름은 등록 자체가 거부된다."""

    def __init__(self) -> None:
        self._allowed = KNOWN_LOOP_TOOLS
        self._tools: dict[str, ToolPort] = {}

    def register(self, tool: ToolPort) -> None:
        name = tool.spec.name
        if name not in self._allowed:
            raise ValueError(f"tool may not join the loop registry: {name}")
        if name in self._tools:
            raise ValueError(f"duplicate tool: {name}")
        self._tools[name] = tool

    def get(self, name: str) -> ToolPort | None:
        return self._tools.get(name)

    def specs(self) -> tuple[ToolSpec, ...]:
        return tuple(tool.spec for tool in self._tools.values())
