"""도구 포트 — corpus_search·form_evidence·external_search·view_figure.

도구 실행 결과는 신뢰 경계 밖 데이터로 취급한다(prompt injection 방어) —
LLM 컨텍스트에 넣을 내용과 트레이스용 sanitized 요약을 분리해 반환한다.
Notion은 도구가 아니다(BR-RA12) — 레지스트리가 등록 자체를 거부한다.
`view_figure`는 자산 스토어 설정이 있을 때만 등록된다(logical-components §4).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = [
    "KNOWN_LOOP_TOOLS",
    "TOOL_CORPUS_SEARCH",
    "TOOL_DATASET_SEARCH",
    "TOOL_FORM_EVIDENCE",
    "TOOL_GITHUB_SEARCH",
    "TOOL_SAVE_ARTIFACT",
    "TOOL_VIEW_FIGURE",
    "ImageAttachment",
    "ToolContext",
    "ToolPort",
    "ToolRegistry",
    "ToolResult",
    "ToolSpec",
]

# v1 도구 어휘(BLM §3).
TOOL_CORPUS_SEARCH = "corpus_search"
TOOL_FORM_EVIDENCE = "form_evidence"
TOOL_GITHUB_SEARCH = "github_search"
TOOL_DATASET_SEARCH = "dataset_search"
TOOL_VIEW_FIGURE = "view_figure"
TOOL_SAVE_ARTIFACT = "save_artifact"

# 레지스트리 기본 allowlist — 루프에 등록될 수 있는 도구 어휘의 전체(BLM §3).
# 신규 도구는 이 어휘를 명시 확장하는 방식으로만 합류한다.
KNOWN_LOOP_TOOLS: frozenset[str] = frozenset(
    {
        TOOL_CORPUS_SEARCH,
        TOOL_FORM_EVIDENCE,
        TOOL_GITHUB_SEARCH,
        TOOL_DATASET_SEARCH,
        TOOL_VIEW_FIGURE,
        TOOL_SAVE_ARTIFACT,
    }
)

# BR-RA12 — Notion은 도구가 아니다. allowlist에 올리는 것 자체를 거부한다.
_FORBIDDEN_MARKER = "notion"


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
class ImageAttachment:
    """도구가 확보한 이미지 1건 — 텍스트가 아닌 별도 채널로 LLM에 전달된다.

    `content`(JSON 덤프 후 문자 한도로 절단)로는 base64를 보낼 수 없다 — 잘린
    base64는 디코드 불능이라 조용히 사라진다. 그래서 타입 채널을 따로 둔다.
    이미지도 도구 결과와 동일한 **신뢰 경계 밖 데이터**다(그림 안의 문구는 지시가
    아니다) — 어댑터는 반드시 도구 결과 구획 뒤에 배치한다.
    """

    media_type: str
    data_b64: str
    asset_id: str
    caption: str = ""


@dataclass(frozen=True, slots=True)
class ToolResult:
    """단일 도구 실행 결과.

    content        — 다음 observe에서 LLM에 보이는 내용(신뢰 경계 밖 데이터).
    result_summary — 트레이스·활동 피드용 sanitized 요약(SEC-9/15).
    record_refs    — 결과가 확보한 실재 출처 핸들(recordRef) — 게이트 실재성 검사 입력.
    images         — 멀티모달 첨부(BR-RA11). content와 달리 어댑터가 프로바이더별
                     이미지 블록으로 렌더한다.
    gate_rejection_code — 저장 게이트 거부 사유 코드(BR-RA2). 트레이스 outcome 분류의
                     타입 채널 — 오류 문자열 프로토콜에 의존하지 않는다.
    """

    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    result_summary: str = ""
    record_refs: tuple[str, ...] = ()
    cost_usd: float | None = None
    error: str | None = None
    gate_rejection_code: str | None = None
    images: tuple[ImageAttachment, ...] = ()


class ToolPort(Protocol):
    spec: ToolSpec

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


class ToolRegistry:
    """가용 설정이 있는 도구만 등록된다 — 없으면 에이전트 도구 목록이 자연 축소
    (logical-components §4).

    등록은 allowlist 기반 deny-by-default — 어휘(`KNOWN_LOOP_TOOLS`) 밖 도구는
    이름 패턴과 무관하게 구조적으로 등록 불가. Notion 계열 이름은 allowlist에
    올리는 것 자체를 생성자가 거부하므로(BR-RA12) 어떤 확장 경로로도 합류할 수 없다."""

    def __init__(self, allowed_names: Iterable[str] | None = None) -> None:
        allowed = frozenset(allowed_names) if allowed_names is not None else KNOWN_LOOP_TOOLS
        forbidden = sorted(name for name in allowed if _FORBIDDEN_MARKER in name.lower())
        if forbidden:
            raise ValueError(f"notion tools may never be allowlisted: {forbidden}")
        self._allowed = allowed
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
