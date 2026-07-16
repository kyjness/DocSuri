"""OpenAILlmGateway — solo-local ``LlmGatewayPort`` (solo-local-migration.md §2).

Replaces ``BedrockLlmGateway`` when ``DOCSURI_LLM_PROVIDER=openai`` (the AWS deployment is
retired; personal key via ``OPENAI_API_KEY``). Same contract and the same structured-output
strategy: the output is elicited as a **forced tool (function) call**, so the response is a
schema-shaped JSON object the model can't wrap in prose or corrupt with unescaped quotes /
raw LaTeX backslashes. The prompt builders and tool schemas are the shared SSOT
(``prompts/templates.py``); only the transport differs — Chat Completions instead of the
Bedrock invoke stream, with ``finish_reason == "length"`` playing the role of the
``max_tokens`` stop-reason truncation signal (the graceful-truncation re-split path in the
StructuredTranslator works unchanged).

Reuses the Bedrock adapter's circuit breaker and payload shaping (same failure semantics:
explicit timeout + ONE retry; persistent failure raises ``LlmUnavailable`` so the
orchestrator abstains, Q1/RES-9). Stdlib ``urllib`` only (no new dependency).
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections.abc import Sequence
from typing import Any

from ..domain.models import (
    Glossary,
    RefinedSource,
    SummaryDraft,
    SummaryRequest,
    TranslationSegment,
    TranslationSegmentsResult,
)
from ..ports.ports import LlmUnavailable
from ..prompts import (
    SUMMARY_TOOL,
    TRANSLATE_TOOL,
    build_summary_prompt,
    build_translate_segments_prompt,
)
from .bedrock_llm import LocalCircuitBreaker, _to_summary_draft

log = logging.getLogger("docsuri.summarization.openai")

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
# Generation runs on the worker path (no gateway deadline) — same generous ceiling rationale
# as the Bedrock adapter's read_timeout: bound a genuine hang without cutting a large output.
_TIMEOUT_S = 120.0


class OpenAILlmGateway:
    def __init__(
        self,
        *,
        summary_model_id: str,
        translate_model_id: str,
        api_key: str | None = None,
        max_retries: int = 1,
    ) -> None:
        import os

        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        self._summary_model = summary_model_id
        self._translate_model = translate_model_id
        self._max_retries = max_retries
        self._cb = LocalCircuitBreaker()

    # --- public ports (same surface as BedrockLlmGateway) ---------------------
    def summarize(
        self, refined: RefinedSource, request: SummaryRequest, glossary: Glossary
    ) -> SummaryDraft:
        system, user = build_summary_prompt(refined, request, glossary)
        payload = self._invoke_json(
            self._summary_model, system, user, SUMMARY_TOOL, max_tokens=8192
        )
        return _to_summary_draft(payload)

    def translate_segments(
        self,
        segments: Sequence[TranslationSegment],
        request: SummaryRequest,
        glossary: Glossary,
    ) -> TranslationSegmentsResult:
        system, user = build_translate_segments_prompt(segments, request, glossary)
        payload = self._invoke_json(
            self._translate_model, system, user, TRANSLATE_TOOL,
            max_tokens=8192, graceful_truncation=True,
        )
        raw = payload.get("translations", {})
        translations = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        return TranslationSegmentsResult(
            translations=translations,
            kept_terms=tuple(str(t) for t in payload.get("keptTerms", [])),
            truncated=bool(payload.get("_truncated", False)),
        )

    # --- transport -------------------------------------------------------------
    def _invoke_json(
        self,
        model_id: str,
        system: str,
        user: str,
        tool: dict,
        *,
        max_tokens: int = 2000,
        graceful_truncation: bool = False,
    ) -> dict:
        permit = self._cb.acquire()
        if permit is None:
            raise LlmUnavailable("OpenAI LLM circuit breaker is open")

        body = {
            "model": model_id,
            "max_completion_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # The Bedrock tool schema (name/description/input_schema) maps 1:1 onto the
            # Chat Completions function shape — templates.py stays the single SSOT.
            "tools": [{
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"],
                },
            }],
            "tool_choice": {"type": "function", "function": {"name": tool["name"]}},
        }
        last_exc: Exception | None = None
        try:
            for attempt in range(self._max_retries + 1):
                if attempt > 0:
                    time.sleep(2 ** attempt * 0.5)
                try:
                    text, truncated = self._request_tool_arguments(body)
                    try:
                        payload = json.loads(text)
                        if not isinstance(payload, dict):
                            raise ValueError("tool arguments are not a JSON object")
                    except (ValueError, json.JSONDecodeError):
                        # finish_reason=length cuts the arguments mid-JSON — surface truncation to
                        # a re-splittable caller (translate) instead of hard-failing the batch;
                        # a parse failure on a COMPLETE response is genuine bad output → retry.
                        if not (graceful_truncation and truncated):
                            raise
                        permit.success()
                        return {"_truncated": True}
                    payload["_truncated"] = truncated
                    permit.success()
                    return payload
                except Exception as exc:  # noqa: BLE001 — any transport/parse error → retry/abstain
                    last_exc = exc
            log.warning(
                "OpenAI generation failed after %d attempt(s): %s: %s",
                self._max_retries + 1,
                type(last_exc).__name__ if last_exc else "None",
                last_exc,
            )
            raise LlmUnavailable("OpenAI generation failed") from last_exc
        finally:
            # Catch-all release (no-op after success()): records the failure and frees the
            # HALF-OPEN probe even when a BaseException escapes the retry loop.
            permit.failure()

    def _request_tool_arguments(self, body: dict) -> tuple[str, bool]:
        """One Chat Completions call → (forced tool call's ``arguments`` JSON, truncated?)."""
        request = urllib.request.Request(  # noqa: S310 — fixed https endpoint, not user input
            _ENDPOINT,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:  # noqa: S310
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
        choice = (payload.get("choices") or [{}])[0]
        truncated = choice.get("finish_reason") == "length"
        calls = (choice.get("message") or {}).get("tool_calls") or []
        arguments = calls[0]["function"].get("arguments", "") if calls else ""
        return arguments, truncated
