"""tool-calling LLM 포트 — 매 턴 다음 도구·인자 또는 종료 제안을 결정한다.

에이전트의 종료 판단은 제안일 뿐 판정 권위가 아니다(BR-RA1) — 수용 여부는
domain.loop이 저장 게이트 기준으로 판정한다. 시스템 지시와 도구 결과(신뢰 경계
밖 데이터)의 분리는 어댑터 책임이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from .tools import ImageAttachment, ToolSpec

__all__ = [
    "LlmDecision",
    "LoopObservation",
    "TerminationProposal",
    "ToolCallProposal",
    "ToolCallingLlmPort",
    "ToolResultView",
    "fit_result_content",
]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _longest_list_path(content: dict[str, Any]) -> tuple[str, ...] | None:
    """가장 긴 목록의 위치(최상위 또는 한 겹 안). 키 이름을 미리 정해두지 않는다 —
    도구·산출물마다 이름이 다르고(`items`·`claims`·`evidence.claims`), 이름 목록에
    없는 것이 오면 바이트 절단으로 되돌아가기 때문이다."""
    best: tuple[str, ...] | None = None
    best_len = 0
    for key, value in content.items():
        if isinstance(value, list) and len(value) > best_len:
            best, best_len = (key,), len(value)
        elif isinstance(value, dict):
            for nested_key, nested in value.items():
                if isinstance(nested, list) and len(nested) > best_len:
                    best, best_len = (key, nested_key), len(nested)
    return best


def _with_list_at(
    content: dict[str, Any], path: tuple[str, ...], kept: list[Any]
) -> dict[str, Any]:
    if len(path) == 1:
        return {**content, path[0]: kept}
    outer, inner = path
    return {**content, outer: {**content[outer], inner: kept}}


def fit_result_content(content: dict[str, Any], max_chars: int) -> dict[str, Any]:
    """도구 결과 content를 한도 안에 맞춘다 — 목록은 항목 단위로 덜어낸다.

    직렬화한 문자열을 바이트로 자르면 마지막 항목이 값 중간에서 끊긴다. 카드의
    recordRef가 그렇게 잘리면 모델은 잘린 줄 모르고 그대로 복사하고, 게이트는
    unknown_source_ref로 거부한다 — 실재하는 출처인데도 인용할 수 없게 된다.
    항목을 통째로 빼면 **보이는 항목은 전부 온전하다**. 몇 개를 뺐는지 함께 알려
    모델이 목록이 전부가 아님을 알 수 있게 한다.
    """
    try:
        text = _dump(content)
    except (TypeError, ValueError):
        return {"note": "content not serialisable"}
    if len(text) <= max_chars:
        return content

    path = _longest_list_path(content)
    if path is not None:
        source = content[path[0]] if len(path) == 1 else content[path[0]][path[1]]
        for keep in range(len(source) - 1, 0, -1):
            trimmed = _with_list_at(content, path, source[:keep])
            trimmed["omitted"] = {"field": ".".join(path), "count": len(source) - keep}
            if len(_dump(trimmed)) <= max_chars:
                return trimmed

    # 덜어낼 목록이 없거나 한 항목조차 한도를 넘는다 — 잘렸다는 사실이라도 남긴다.
    # 자른 문자열을 다시 감싸 직렬화하면 따옴표 이스케이프로 길이가 늘어나므로,
    # 감싼 결과가 한도 안에 들어올 때까지 줄인다(한도는 한도여야 한다).
    slice_len = max_chars
    while slice_len > 0 and len(_dump({"truncated": text[:slice_len]})) > max_chars:
        slice_len -= max(1, (len(_dump({"truncated": text[:slice_len]})) - max_chars))
    return {"truncated": text[:max(slice_len, 0)]}


@dataclass(frozen=True, slots=True)
class ToolResultView:
    """직전 도구 호출의 관찰 뷰 — content·images 모두 신뢰 경계 밖 데이터.

    `images`는 **가장 최근 결과 1건에만** 남는다(도메인이 절단). 관찰은 매 턴 최근
    결과 여러 건을 다시 싣는 구조라, 그냥 두면 이미지 1건이 윈도우에서 밀려날 때까지
    매 턴 재전송돼 토큰을 반복 계상한다.
    """

    seq: int
    tool_name: str
    ok: bool
    content: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    images: tuple[ImageAttachment, ...] = ()


@dataclass(frozen=True, slots=True)
class LoopObservation:
    """observe 단계 입력(BLM §2): 도구 결과·산출물 현황·남은 예산 요약.

    `notes`는 시스템이 작성한 신뢰 채널이고, `steering`은 사용자가 작성한 준신뢰
    채널이다 — 두 구획은 렌더링에서 섞이지 않는다(어댑터 책임).
    """

    topic: str
    input_type: str
    recent_results: tuple[ToolResultView, ...]
    saved_artifact_kinds: frozenset[str]
    missing_required_kinds: frozenset[str]
    iterations_left: int
    tool_calls_left: int
    cost_left_usd: float
    notes: tuple[str, ...] = ()
    # 잡 내 대화 스티어링(FR-44, BLM §6) — 조사 방향·우선순위만 바꿀 수 있고
    # 예산·저장 게이트·allowlist·Notion 승인은 바꿀 수 없다(BR-RA9).
    steering: tuple[str, ...] = ()
    # 실행 맥락: "loop"(자율 조사) 또는 "turn"(종단 잡의 온디맨드 대화 한 턴).
    # 어댑터가 이 값으로 시스템 프롬프트를 고른다 — 조사용 지시("필수 산출물이
    # 전부 저장되어야 완료")를 종단 잡의 대화 턴에 그대로 쓰면 안 되기 때문이다.
    mode: str = "loop"
    # 온디맨드 턴에서 사용자가 요청한 내용(turn 모드에서만 채워진다).
    request: str | None = None


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
