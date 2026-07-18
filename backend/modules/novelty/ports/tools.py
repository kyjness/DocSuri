"""도구 포트 — corpus_search·form_evidence·external_search·view_figure.

도구 실행 결과는 신뢰 경계 밖 데이터로 취급한다(prompt injection 방어) —
LLM 컨텍스트에 넣을 내용과 트레이스용 sanitized 요약을 분리해 반환한다.
Notion은 도구가 아니다(BR-RA12) — 레지스트리가 등록 자체를 거부한다.
`view_figure`는 포트만 정의하고 ⑤ 4단계 전까지 등록하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "TOOL_CORPUS_SEARCH",
    "TOOL_DATASET_SEARCH",
    "TOOL_FORM_EVIDENCE",
    "TOOL_GITHUB_SEARCH",
    "TOOL_SAVE_ARTIFACT",
    "TOOL_VIEW_FIGURE",
    "ToolContext",
    "ToolPort",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
]

# v1 도구 어휘(BLM §3). view_figure는 ⑤ 4단계 전까지 미등록.
TOOL_CORPUS_SEARCH = "corpus_search"
TOOL_FORM_EVIDENCE = "form_evidence"
TOOL_GITHUB_SEARCH = "github_search"
TOOL_DATASET_SEARCH = "dataset_search"
TOOL_VIEW_FIGURE = "view_figure"
TOOL_SAVE_ARTIFACT = "save_artifact"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """LLM에 노출되는 도구 서명(JSON Schema parameters)."""

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolContext:
    """owner-scoped 실행 문맥(SECURITY-08)."""

    owner_id: str
    job_id: str


@dataclass(frozen=True, slots=True)
class ToolResult:
    """단일 도구 실행 결과.

    content        — 다음 observe에서 LLM에 보이는 내용(신뢰 경계 밖 데이터).
    result_summary — 트레이스·활동 피드용 sanitized 요약(SEC-9/15).
    record_refs    — 결과가 확보한 실재 출처 핸들(recordRef) — 게이트 실재성 검사 입력.
    """

    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    record_refs: tuple[str, ...] = ()
    cost_usd: float | None = None
    error: str | None = None


class ToolPort(Protocol):
    spec: ToolSpec

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    """가용 설정이 있는 도구만 등록된다 — 없으면 에이전트 도구 목록이 자연 축소
    (logical-components §4). Notion 계열 이름은 등록 자체를 거부한다(BR-RA12)."""

    _FORBIDDEN_PREFIXES = ("notion",)

    def __init__(self) -> None:
        self._tools: dict[str, ToolPort] = {}

    def register(self, tool: ToolPort) -> None:
        name = tool.spec.name
        if name.lower().startswith(self._FORBIDDEN_PREFIXES):
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
