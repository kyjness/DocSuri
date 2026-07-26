"""OpenAI tool-calling 어댑터(TD-NV2-3, 로컬 1차) — ToolCallingLlmPort 구현.

summarization의 솔로-로컬 관례를 따라 stdlib urllib만 사용한다(신규 의존성 없음).
결정은 강제 함수 호출(tool_choice=required, parallel_tool_calls=false)로 유도한다 —
종료 제안은 합성 함수 ``propose_termination``으로 표현되고 TerminationProposal로
변환된다. 결정 매핑·프롬프트는 llm_prompt(프로바이더 중립 단일 정의)를 쓴다.

Prompt Injection 방어: 시스템 지시와 도구 결과 데이터를 분리하고, 도구 결과는
"데이터이며 지시가 아님"을 명시한 구획에만 싣는다(backend 개발 지침 — 에이전트
루프 항목). 전송 실패는 SourceBreaker(재시도 1회 + 서킷 브레이커 — 외부 연동
규칙)를 거쳐 LlmUnavailable로 수렴하고 루프가 fatal(outage→abstain 계열)로
처리한다.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from typing import Any

from ..ports.llm import LlmDecision, LoopObservation
from ..ports.tools import ToolSpec
from .external.base import SourceBreaker, SourceUnavailable
from .llm_prompt import (
    TERMINATION_TOOL,
    LlmUnavailable,
    conservative_termination,
    decision_from_tool_call,
    estimate_cost,
    render_observation,
    system_prompt_for,
    termination_parameters,
)

__all__ = ["LlmUnavailable", "OpenAiToolCallingLlm"]

log = logging.getLogger("docsuri.novelty.llm.openai")

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_TIMEOUT_S = 120.0


class OpenAiToolCallingLlm:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        input_usd_per_mtok: float = 0.15,
        output_usd_per_mtok: float = 0.60,
        transport: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
        breaker: SourceBreaker | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._input_rate = input_usd_per_mtok
        self._output_rate = output_usd_per_mtok
        self._transport = transport or self._http_post
        self._breaker = breaker or SourceBreaker()

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        request = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt_for(observation)},
                {"role": "user", "content": render_observation(observation)},
            ],
            "tools": [*(_to_function(spec) for spec in tools), _termination_function()],
            "tool_choice": "required",
            # 결정은 턴당 정확히 하나 — 병렬 호출의 무기록 폐기를 원천 차단.
            "parallel_tool_calls": False,
        }
        response = self._invoke(request)
        return self._parse_decision(response)

    def _invoke(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._breaker.call(lambda: self._transport(request))
        except SourceUnavailable as exc:
            raise LlmUnavailable(str(exc)) from exc

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

    def _parse_decision(self, response: dict[str, Any]) -> LlmDecision:
        usage = response.get("usage") or {}
        cost = estimate_cost(
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            input_usd_per_mtok=self._input_rate,
            output_usd_per_mtok=self._output_rate,
        )
        choices = response.get("choices") or []
        if not choices:
            raise LlmUnavailable("empty choices in completion response")
        message = choices[0].get("message") or {}
        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            # tool_choice=required 위반 — 텍스트 응답은 종료 제안으로 보수적으로 해석.
            return conservative_termination(str(message.get("content") or ""), cost)
        if len(tool_calls) > 1:
            # 방어선 — parallel_tool_calls=false에도 복수 호출이 오면 폐기를 기록한다.
            log.warning("openai returned %d tool calls; using the first", len(tool_calls))
        function = tool_calls[0].get("function") or {}
        args, note = _parse_args(function.get("arguments"))
        if len(tool_calls) > 1:
            dropped = ", ".join(
                str((call.get("function") or {}).get("name") or "?") for call in tool_calls[1:]
            )
            note = f"{note + '; ' if note else ''}dropped parallel calls: {dropped}"
        return decision_from_tool_call(
            str(function.get("name") or ""), args, cost, decision_note=note
        )


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
