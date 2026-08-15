"""LLM 어댑터 — 결정(tool calling)과 근거 추출(JSON).

둘을 나눈 이유는 역할이 다르기 때문이다: `decide`는 "다음에 무엇을 할까",
`extract`는 "이 논문들에서 무엇을 인용할까". 프롬프트도 실패 처리도 다르다.

프로바이더는 어댑터 안에만 있다(TD-EV2-2). 도메인은 `EvidenceLlmPort` /
`EvidenceExtractionPort`만 알고, 교체는 여기 형제 파일을 하나 더 두는 일이다.

SDK 대신 **HTTP를 직접 친다** — novelty가 이미 그렇게 하고 있고(`urllib.request`),
백엔드 의존성 closure를 늘리지 않는다. 전송은 주입 가능하므로 테스트는 네트워크
없이 돈다.

이미지는 도구 결과 구획 **뒤에** 실린다(BR-EV-17) — 그림 안의 문구가 지시로
읽히지 않도록 시스템 프롬프트가 경계를 명시하고, 배치도 그 뒤다.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections.abc import Callable
from typing import Any

from backend.modules.novelty.adapters.external.base import SourceBreaker, SourceUnavailable

from ..ports.llm import LlmDecision, LlmUnavailable, LoopObservation
from ..ports.tools import ToolSpec
from ._llm_shared import (
    FINISH_DESCRIPTION,
    FINISH_PARAMETERS,
    FINISH_TOOL,
    IMAGE_BOUNDARY_BANNER,
    decision_from_tool_call,
    parse_json_items,
    usage_cost,
)
from .prompts import build_decide_messages, build_extraction_messages

__all__ = ["OpenAiDecider", "OpenAiExtractor"]

log = logging.getLogger("docsuri.evidence.llm")

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_TIMEOUT_S = 120.0

Transport = Callable[[dict[str, Any]], dict[str, Any]]


def _finish_spec() -> dict[str, Any]:
    """OpenAI 문법으로 감싼 종료 도구(사양은 `_llm_shared`)."""
    return {
        "type": "function",
        "function": {
            "name": FINISH_TOOL,
            "description": FINISH_DESCRIPTION,
            "parameters": FINISH_PARAMETERS,
        },
    }


def _tool_schema(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


class _OpenAiBase:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        transport: Transport | None = None,
        input_usd_per_mtok: float = 0.15,
        output_usd_per_mtok: float = 0.60,
        breaker: SourceBreaker | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._transport = transport or self._http_post
        self._input_rate = input_usd_per_mtok
        self._output_rate = output_usd_per_mtok
        # 외부 연동 규칙(일시 실패 재시도 1회 + 반복 실패 자동 차단) — novelty와
        # 같은 정책. 브레이커만 감싸면 첫 일시 오류가 곧장 턴 실패가 된다.
        self._breaker = breaker or SourceBreaker()

    def _complete(self, **kwargs: Any) -> dict[str, Any]:
        try:
            return self._breaker.call(lambda: self._transport({"model": self._model, **kwargs}))
        except SourceUnavailable as exc:
            raise LlmUnavailable(str(exc)[:300]) from exc

    def _usage_cost(self, response: dict[str, Any]) -> float | None:
        return usage_cost(
            (response or {}).get("usage"),
            input_key="prompt_tokens",
            output_key="completion_tokens",
            input_usd_per_mtok=self._input_rate,
            output_usd_per_mtok=self._output_rate,
        )

    def _http_post(self, request: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(  # noqa: S310 — 고정 상수 엔드포인트
            _ENDPOINT,
            data=json.dumps(request).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))


class OpenAiDecider(_OpenAiBase):
    """루프의 `decide` — 다음 도구·인자 또는 종료."""

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        messages = build_decide_messages(observation)
        messages = _attach_images(messages, observation)
        response = self._complete(
            messages=messages,
            tools=[_tool_schema(spec) for spec in tools] + [_finish_spec()],
            tool_choice="required",
        )
        return decision_from_tool_call(_first_tool_call(response), self._usage_cost(response))


class OpenAiExtractor(_OpenAiBase):
    """`extract_evidence` 뒤의 추출 — 검증 전 원시 항목을 돌려준다."""

    def __init__(self, *, model: str, **kwargs: Any) -> None:
        super().__init__(model=model, **kwargs)

    def extract(
        self, *, topic: str, focus: str, papers: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        response = self._complete(
            messages=build_extraction_messages(topic=topic, focus=focus, papers=papers),
            response_format={"type": "json_object"},
        )
        return parse_json_items(_first_text(response))


def _attach_images(messages: list[dict], observation: LoopObservation) -> list[dict]:
    """이미지는 마지막 사용자 메시지 **뒤**에 별도 블록으로 붙인다.

    `content` 텍스트에 base64를 실으면 문자 한도로 잘려 디코드 불능이 된다 —
    타입 채널을 따로 쓰는 이유다.
    """
    images = [img for view in observation.recent_results for img in view.images]
    if not images:
        return messages
    blocks: list[dict[str, Any]] = [{"type": "text", "text": IMAGE_BOUNDARY_BANNER}]
    for image in images:
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{image.media_type};base64,{image.data_b64}"},
            }
        )
    return [*messages, {"role": "user", "content": blocks}]


def _first_tool_call(response: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    choices = (response or {}).get("choices") or []
    if not choices:
        return None
    calls = (choices[0].get("message") or {}).get("tool_calls") or []
    if not calls:
        return None
    function = calls[0].get("function") or {}
    try:
        args = json.loads(function.get("arguments") or "{}")
    except (TypeError, ValueError):
        args = {}
    return str(function.get("name") or ""), args if isinstance(args, dict) else {}


def _first_text(response: dict[str, Any]) -> str:
    choices = (response or {}).get("choices") or []
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content") or "")


