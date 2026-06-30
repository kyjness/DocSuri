"""BedrockLlmGateway — real LLM adapter (TD-S3/S4), streaming Sonnet/Haiku.

task → model tier (BR-S5): summary=Sonnet, translate=Haiku. Uses Bedrock
``invoke_model_with_response_stream`` and buffers the token stream into a complete JSON
draft so the U7 grounding gate can validate the whole structured output before exposure
(Q5/BR-S8). Explicit timeout + ONE retry; persistent failure raises ``LlmUnavailable`` so
the orchestrator abstains (Q1/RES-9). No Production Mock — this is the single shipped impl.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Sequence
from typing import Any

from ..domain.models import (
    Anchor,
    AnchorTarget,
    Glossary,
    RefinedSource,
    SummaryDraft,
    SummaryRequest,
    TranslationSegment,
    TranslationSegmentsResult,
)
from ..ports.ports import LlmUnavailable
from ..prompts import build_summary_prompt, build_translate_segments_prompt


class LocalCircuitBreaker:
    """Stateful in-memory circuit breaker."""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 30.0) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state = "CLOSED"  # CLOSED, OPEN, HALF-OPEN
        self._failure_count = 0
        self._last_state_change = time.time()
        self._lock = threading.Lock()

    def allow_request(self) -> bool:
        with self._lock:
            self._check_recovery()
            return self._state != "OPEN"

    def record_success(self) -> None:
        with self._lock:
            if self._state == "HALF-OPEN":
                self._state = "CLOSED"
                self._failure_count = 0
                self._last_state_change = time.time()
            elif self._state == "CLOSED":
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            now = time.time()
            if self._state == "HALF-OPEN" or self._failure_count >= self._failure_threshold:
                self._state = "OPEN"
                self._last_state_change = now

    def _check_recovery(self) -> None:
        if self._state == "OPEN":
            now = time.time()
            if now - self._last_state_change > self._recovery_timeout:
                self._state = "HALF-OPEN"
                self._last_state_change = now


class BedrockLlmGateway:
    def __init__(
        self,
        *,
        summary_model_id: str,
        translate_model_id: str,
        region_name: str | None = None,
        client: Any | None = None,
        max_retries: int = 1,
    ) -> None:
        if client is None:
            import boto3  # lazy: only the `real` extra needs boto3
            from botocore.config import Config

            config = Config(
                connect_timeout=5.0,
                read_timeout=30.0,
                retries={"max_attempts": 1},
            )
            client = boto3.client("bedrock-runtime", region_name=region_name, config=config)
        self._client = client
        self._summary_model = summary_model_id
        self._translate_model = translate_model_id
        self._max_retries = max_retries
        self._cb = LocalCircuitBreaker()

    # --- public ports --------------------------------------------------------
    def summarize(
        self, refined: RefinedSource, request: SummaryRequest, glossary: Glossary
    ) -> SummaryDraft:
        system, user = build_summary_prompt(refined, request, glossary)
        # The structured summary is small, but Korean output + per-claim anchor spans push a
        # full paper's JSON past the old 2000-token default — it truncated mid-JSON → parse
        # failure → abstain. max_tokens is a cap (the model stops when done), so a generous
        # ceiling costs nothing for short outputs while preventing truncation on long ones.
        payload = self._invoke_json(self._summary_model, system, user, max_tokens=8192)
        return _to_summary_draft(payload)

    def translate_segments(
        self,
        segments: Sequence[TranslationSegment],
        request: SummaryRequest,
        glossary: Glossary,
    ) -> TranslationSegmentsResult:
        system, user = build_translate_segments_prompt(segments, request, glossary)
        # A translation's output volume tracks its input, so it needs a generous token cap; the
        # StructuredTranslator chunks upstream (output-bounded) so each call stays within this 8192
        # ceiling — the same cap the summary path uses to avoid mid-JSON truncation.
        payload = self._invoke_json(self._translate_model, system, user, max_tokens=8192)
        raw = payload.get("translations", {})
        translations = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        return TranslationSegmentsResult(
            translations=translations,
            kept_terms=tuple(str(t) for t in payload.get("keptTerms", [])),
        )

    # --- bedrock plumbing ----------------------------------------------------
    def _invoke_json(
        self, model_id: str, system: str, user: str, *, max_tokens: int = 2000
    ) -> dict:
        if not self._cb.allow_request():
            raise LlmUnavailable("Bedrock LLM circuit breaker is OPEN")

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                time.sleep(2 ** attempt * 0.5)
            try:
                text, truncated = self._stream_text(model_id, body)
                payload = _parse_json(text)
                payload["_truncated"] = truncated
                self._cb.record_success()
                return payload
            except Exception as exc:  # noqa: BLE001 — any Bedrock/transport/parse error → retry/abstain
                last_exc = exc
        self._cb.record_failure()
        raise LlmUnavailable("Bedrock generation failed") from last_exc

    def _stream_text(self, model_id: str, body: dict) -> tuple[str, bool]:
        """Buffer the response stream into the full text (buffer-validate-stream, Q5)."""
        response = self._client.invoke_model_with_response_stream(
            modelId=model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        chunks: list[str] = []
        truncated = False
        for event in response.get("body", []):
            raw = event.get("chunk", {}).get("bytes")
            if not raw:
                continue
            data = json.loads(raw.decode("utf-8"))
            if data.get("type") == "content_block_delta":
                chunks.append(data.get("delta", {}).get("text", ""))
            elif data.get("type") == "message_delta":
                stop_reason = data.get("delta", {}).get("stop_reason")
                if stop_reason == "max_tokens":
                    truncated = True
        text = "".join(chunks)
        return text, truncated


def _parse_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def _to_summary_draft(payload: dict) -> SummaryDraft:
    anchors = tuple(
        Anchor(
            field_name=str(a.get("field", "")),
            target=_anchor_target(a.get("target", "section")),
            span=str(a.get("span", "")),
            label=str(a.get("label", "")),
        )
        for a in payload.get("anchors", [])
    )
    repro = payload.get("reproducibility", {}) or {}
    return SummaryDraft(
        tldr=str(payload.get("tldr", "")),
        contributions=tuple(payload.get("contributions", [])),
        method=str(payload.get("method", "")),
        results=str(payload.get("results", "")),
        limitations=str(payload.get("limitations", "")),
        reproducibility={"code": str(repro.get("code", "")), "data": str(repro.get("data", ""))},
        anchors=anchors,
        truncated=bool(payload.get("_truncated", False)),
    )


def _anchor_target(value: str) -> AnchorTarget:
    try:
        return AnchorTarget(str(value).lower())
    except ValueError:
        return AnchorTarget.SECTION
