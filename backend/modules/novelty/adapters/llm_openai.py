"""OpenAI tool-calling 어댑터(TD-NV2-3, 로컬 1차) — ToolCallingLlmPort 구현.

summarization의 솔로-로컬 관례를 따라 stdlib urllib만 사용한다(신규 의존성 없음).
결정은 강제 함수 호출(tool_choice=required)로 유도한다 — 종료 제안은 합성 함수
``propose_termination``으로 표현되고 포트 계약의 TerminationProposal로 변환된다.

Prompt Injection 방어: 시스템 지시와 도구 결과 데이터를 분리하고, 도구 결과는
"데이터이며 지시가 아님"을 명시한 구획에만 싣는다(backend 개발 지침 — 에이전트
루프 항목). 실패는 명시 타임아웃 + 기계 재시도 1회 후 예외 — 루프가 fatal로
수렴한다(LLM은 결정 주체라 대체 경로가 없다).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from typing import Any

from ..ports.llm import (
    LlmDecision,
    LoopObservation,
    TerminationProposal,
    ToolCallProposal,
)
from ..ports.tools import ToolSpec
from .llm_prompt import (
    SYSTEM_PROMPT,
    TERMINATION_TOOL,
    render_observation,
    termination_parameters,
)

__all__ = ["LlmUnavailable", "OpenAiToolCallingLlm"]

log = logging.getLogger("docsuri.novelty.llm.openai")

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_TIMEOUT_S = 120.0


class LlmUnavailable(RuntimeError):
    pass


class OpenAiToolCallingLlm:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        input_usd_per_mtok: float = 0.15,
        output_usd_per_mtok: float = 0.60,
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._input_rate = input_usd_per_mtok
        self._output_rate = output_usd_per_mtok
        self._transport = transport or self._http_post

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        request = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": render_observation(observation)},
            ],
            "tools": [*(_to_function(spec) for spec in tools), _termination_function()],
            "tool_choice": "required",
        }
        response = self._invoke(request)
        return _parse_decision(response, self._input_rate, self._output_rate)

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for _ in range(2):  # 기계 재시도 1회(NFR-NV2-11)
            try:
                return self._transport(request)
            except Exception as exc:  # noqa: BLE001 — 재시도 후 LlmUnavailable로 수렴
                last_error = exc
        raise LlmUnavailable(str(last_error))

    def _http_post(self, request: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            _ENDPOINT,
            data=json.dumps(request).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as response:
            return json.loads(response.read().decode("utf-8"))


def _to_function(spec: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.description,
            "parameters": spec.parameters,
        },
    }


def _termination_function() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TERMINATION_TOOL,
            "description": "필수 산출물이 모두 저장되어 조사를 끝내자고 제안한다.",
            "parameters": termination_parameters(),
        },
    }


def _parse_decision(
    response: dict[str, Any], input_rate: float, output_rate: float
) -> LlmDecision:
    cost = _estimate_cost(response.get("usage") or {}, input_rate, output_rate)
    choices = response.get("choices") or []
    if not choices:
        raise LlmUnavailable("empty choices in completion response")
    message = choices[0].get("message") or {}
    tool_calls = message.get("tool_calls") or []
    if not tool_calls:
        # tool_choice=required 위반 — 텍스트 응답은 종료 제안으로 보수적으로 해석.
        content = str(message.get("content") or "").strip()
        return LlmDecision(TerminationProposal(note=content[:500] or None), cost)
    function = tool_calls[0].get("function") or {}
    name = str(function.get("name") or "")
    args, note = _parse_args(function.get("arguments"))
    if name == TERMINATION_TOOL:
        return LlmDecision(TerminationProposal(note=str(args.get("note") or "")[:500]), cost)
    if not name:
        raise LlmUnavailable("tool call without function name")
    return LlmDecision(ToolCallProposal(tool_name=name, args=args, decision_note=note), cost)


def _parse_args(raw: Any) -> tuple[dict[str, Any], str | None]:
    if isinstance(raw, dict):
        return raw, None
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}, "arguments unparseable — sent empty args"
    if not isinstance(parsed, dict):
        return {}, "arguments not an object — sent empty args"
    return parsed, None


def _estimate_cost(usage: dict[str, Any], input_rate: float, output_rate: float) -> float | None:
    prompt_tokens = usage.get("prompt_tokens")
    completion_tokens = usage.get("completion_tokens")
    if prompt_tokens is None and completion_tokens is None:
        return None
    return (
        float(prompt_tokens or 0) * input_rate + float(completion_tokens or 0) * output_rate
    ) / 1_000_000
