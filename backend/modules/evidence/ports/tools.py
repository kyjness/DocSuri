"""도구 포트(BLM §2) — 루프가 부르는 부품. 스스로 판단하지 않는다.

도구 실행 결과는 **신뢰 경계 밖 데이터**다(BR-EV-17) — LLM 컨텍스트에 넣을 내용과
트레이스용 sanitized 요약을 분리해 반환한다. 등록은 allowlist deny-by-default라
어휘 밖 도구는 이름과 무관하게 구조적으로 합류할 수 없다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "KNOWN_LOOP_TOOLS",
    "TOOL_CORPUS_SEARCH",
    "TOOL_EXTRACT_EVIDENCE",
    "TOOL_EXTERNAL_SEARCH",
    "TOOL_FETCH_PAPER",
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
TOOL_EXTERNAL_SEARCH = "external_search"
TOOL_FETCH_PAPER = "fetch_paper"
TOOL_READ_PAPER = "read_paper"
TOOL_VIEW_FIGURE = "view_figure"
TOOL_EXTRACT_EVIDENCE = "extract_evidence"

# v1 도구 어휘(FD 게이트 Q1=A). 신규 도구는 이 어휘를 명시 확장해야만 합류한다.
KNOWN_LOOP_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_CORPUS_SEARCH,
        TOOL_EXTERNAL_SEARCH,
        TOOL_FETCH_PAPER,
        TOOL_READ_PAPER,
        TOOL_VIEW_FIGURE,
        TOOL_EXTRACT_EVIDENCE,
    }
)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """LLM에 노출되는 도구 서명(JSON Schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """owner-scoped 실행 문맥(SEC-8)."""

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

    def __init__(self, allowed_names: Iterable[str] | None = None) -> None:
        self._allowed = (
            frozenset(allowed_names) if allowed_names is not None else KNOWN_LOOP_TOOLS
        )
        unknown = sorted(self._allowed - KNOWN_LOOP_TOOLS)
        if unknown:
            raise ValueError(f"tools outside the v1 vocabulary may not be allowlisted: {unknown}")
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

    def names(self) -> frozenset[str]:
        return frozenset(self._tools)
