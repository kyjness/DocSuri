"""BedrockLlmGateway — real LLM adapter (TD-S3/S4), streaming Sonnet/Haiku.

task → model tier (BR-S5): summary=Sonnet, translate=Haiku. Output is elicited as a **forced
tool call** (structured output): ``tool_choice`` pins the model to ``emit_summary`` /
``emit_translations``, so the streamed ``input_json_delta`` fragments accumulate into a
schema-shaped JSON object the model can't wrap in prose or corrupt with unescaped quotes / raw
LaTeX backslashes (the old free-text-JSON failure mode that abstained whole summaries). The full
input is buffered before parsing so the U7 grounding gate can validate the complete structured
output before exposure (Q5/BR-S8). Explicit timeout + ONE retry; persistent failure raises
``LlmUnavailable`` so the orchestrator abstains (Q1/RES-9). No Production Mock — the shipped impl.
"""

from __future__ import annotations

import json
import logging
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
from ..prompts import (
    SUMMARY_TOOL,
    TRANSLATE_TOOL,
    build_summary_prompt,
    build_translate_segments_prompt,
)

log = logging.getLogger("docsuri.summarization.bedrock")


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

            # read_timeout is per-read (the gap between streamed events), so it must cover the
            # model's time-to-first-token, not the total generation. A full-paper translation sends
            # a large prompt under forced tool-use and emits an input-sized (up to 8192-token)
            # chunk, whose TTFT routinely exceeds 30s → ReadTimeout → retry → abstain (the observed
            # full-translation "generation_unavailable"). Summaries are short and were unaffected.
            # These calls run in the background worker (no gateway deadline), so a generous ceiling
            # is safe; it bounds a genuine hang without cutting a slow-to-start large generation.
            config = Config(
                connect_timeout=5.0,
                read_timeout=120.0,
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
        # A translation's output volume tracks its input, so it needs a generous token cap; the
        # StructuredTranslator chunks upstream (output-bounded) so each call stays within this 8192
        # ceiling — the same cap the summary path uses to avoid mid-JSON truncation.
        payload = self._invoke_json(
            self._translate_model, system, user, TRANSLATE_TOOL,
            max_tokens=8192, graceful_truncation=True,
        )
        raw = payload.get("translations", {})
        translations = {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}
        return TranslationSegmentsResult(
            translations=translations,
            kept_terms=tuple(str(t) for t in payload.get("keptTerms", [])),
            # Surface an output-cap truncation so the translator can re-split + retry, and so a
            # partial batch is diagnosable rather than silently degrading to an empty translation.
            truncated=bool(payload.get("_truncated", False)),
        )

    # --- bedrock plumbing ----------------------------------------------------
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
        if not self._cb.allow_request():
            raise LlmUnavailable("Bedrock LLM circuit breaker is OPEN")

        # Force the structured-output tool: the model must call ``tool`` and return its arguments
        # as ``tool_use.input``, so the response is a schema-shaped object rather than free-text
        # JSON we have to slice out of prose and repair (unescaped quotes / raw LaTeX backslashes).
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": tool["name"]},
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                time.sleep(2 ** attempt * 0.5)
            try:
                text, truncated = self._stream_tool_input(model_id, body)
                try:
                    payload = json.loads(text)
                    if not isinstance(payload, dict):
                        raise ValueError("tool input is not a JSON object")
                except (ValueError, json.JSONDecodeError):
                    # A response stopped at max_tokens is cut MID-JSON, so the accumulated tool
                    # arguments are incomplete and don't parse — a raw re-raise loses the truncation
                    # signal and the whole batch hard-fails (the observed full-translation abstain
                    # on long papers). For a re-splittable caller (translate), surface truncation so
                    # the chunk is split into smaller batches — each emits less output and fits the
                    # cap — instead of abstaining. A parse failure on a COMPLETE response is genuine
                    # bad output and still raises (retry then abstain).
                    if not (graceful_truncation and truncated):
                        raise
                    self._cb.record_success()  # the call succeeded; only the batch was oversized
                    return {"_truncated": True}
                payload["_truncated"] = truncated
                self._cb.record_success()
                return payload
            except Exception as exc:  # noqa: BLE001 — any Bedrock/transport/parse error → retry/abstain
                last_exc = exc
        self._cb.record_failure()
        # Surface the swallowed root cause: without this the orchestrator only logs a generic
        # ``generation_unavailable`` abstain, so a paper-specific transport/parse failure (e.g. a
        # math-heavy translate batch) is invisible on the request path and undiagnosable in prod.
        log.warning(
            "Bedrock generation failed after %d attempt(s): %s: %s",
            self._max_retries + 1,
            type(last_exc).__name__ if last_exc else "None",
            last_exc,
        )
        raise LlmUnavailable("Bedrock generation failed") from last_exc

    def _stream_tool_input(self, model_id: str, body: dict) -> tuple[str, bool]:
        """Buffer the forced tool call's ``input`` JSON from the stream (buffer-validate, Q5).

        Under ``tool_choice`` the model emits a single ``tool_use`` block whose arguments arrive
        as ``input_json_delta`` fragments (``partial_json``) — concatenated they form the complete
        arguments object. Non-tool-use deltas (there are none under a forced tool, but a stray text
        block is possible) are ignored. ``stop_reason == "max_tokens"`` marks an output-cap
        truncation, so the accumulated ``partial_json`` is a cut-off (unparseable) prefix.
        """
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
                delta = data.get("delta", {})
                if delta.get("type") == "input_json_delta":
                    chunks.append(delta.get("partial_json", ""))
            elif data.get("type") == "message_delta":
                stop_reason = data.get("delta", {}).get("stop_reason")
                if stop_reason == "max_tokens":
                    truncated = True
        return "".join(chunks), truncated


def _as_str(value: Any) -> str:
    """Coerce a payload field to a string (``None`` → "")."""
    return "" if value is None else str(value)


def _as_list(value: Any) -> list:
    """A payload field that must be a list; anything else (str/dict/None) → ``[]`` so iterating it
    never char-splits a string or walks dict keys."""
    return value if isinstance(value, list) else []


def _to_summary_draft(payload: dict) -> SummaryDraft:
    # The tool schema pins each field's shape, but a model can still deviate (a field returned as a
    # bare string instead of a list/object). Every access is shape-guarded so an off-schema field
    # degrades to empty/best-effort rather than raising — a single ``str`` where a dict was expected
    # used to crash the whole job (``'str' object has no attribute 'get'``) → infinite redelivery.
    anchors = tuple(
        Anchor(
            field_name=_as_str(a.get("field", "")),
            target=_anchor_target(a.get("target", "section")),
            span=_as_str(a.get("span", "")),
            label=_as_str(a.get("label", "")),
            # Keep the raw target string (the grounding gate resolves it against real doc-model
            # structure); ``target`` above is only the coarse 3-value display type.
            target_hint=_as_str(a.get("target", "")),
        )
        for a in _as_list(payload.get("anchors"))
        if isinstance(a, dict)  # skip a stray non-object anchor entry instead of crashing
    )
    repro_raw = payload.get("reproducibility")
    if isinstance(repro_raw, dict):
        repro = repro_raw
    elif isinstance(repro_raw, str) and repro_raw.strip():
        # Model returned a flat string instead of {code, data}: keep the text under 'code' rather
        # than dropping it.
        repro = {"code": repro_raw}
    else:
        repro = {}
    # A contributions field returned as a bare string must become a one-element list, never the
    # per-character split ``tuple("abc")`` produces.
    contribs_raw = payload.get("contributions")
    if isinstance(contribs_raw, str) and contribs_raw.strip():
        contributions: tuple[str, ...] = (contribs_raw,)
    else:
        contributions = tuple(_as_str(c) for c in _as_list(contribs_raw))
    return SummaryDraft(
        tldr=_as_str(payload.get("tldr", "")),
        contributions=contributions,
        method=_as_str(payload.get("method", "")),
        results=_as_str(payload.get("results", "")),
        limitations=_as_str(payload.get("limitations", "")),
        reproducibility={
            "code": _as_str(repro.get("code", "")),
            "data": _as_str(repro.get("data", "")),
        },
        anchors=anchors,
        truncated=bool(payload.get("_truncated", False)),
    )


def _anchor_target(value: str) -> AnchorTarget:
    try:
        return AnchorTarget(str(value).lower())
    except ValueError:
        return AnchorTarget.SECTION
