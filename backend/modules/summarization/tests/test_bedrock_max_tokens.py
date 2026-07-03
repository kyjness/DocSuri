"""The summary call must request a generous max_tokens.

The old 2000-token default truncated a full paper's structured Korean JSON mid-object →
``_parse_json`` failure → retry → ``LlmUnavailable`` → abstain ("근거 없음"). Guard against a
regression to that cap. (Translate already uses 8192.)
"""

from __future__ import annotations

import json

from summarization.adapters.bedrock_llm import BedrockLlmGateway
from summarization.domain.models import (
    Glossary,
    RefinedSource,
    SummaryRequest,
    TargetLang,
    Task,
    TranslationSegment,
)
from summarization.ports.ports import LlmUnavailable


class _CaptureBedrock:
    """Records each request body; returns a non-JSON chunk so parsing fails after capture."""

    def __init__(self) -> None:
        self.bodies: list[dict] = []

    def invoke_model_with_response_stream(self, *, modelId, body, accept, contentType):  # noqa: N803
        self.bodies.append(json.loads(body))
        chunk = json.dumps({"type": "content_block_delta", "delta": {"text": "not json"}})
        return {"body": [{"chunk": {"bytes": chunk.encode("utf-8")}}]}


def test_summary_requests_generous_max_tokens() -> None:
    cap = _CaptureBedrock()
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=cap, max_retries=0
    )
    refined = RefinedSource(body="some source text with figures 1.2 and 3.4")
    req = SummaryRequest(paper_id="p", version=1, task=Task.SUMMARY, target_lang=TargetLang.KO)
    try:
        gw.summarize(refined, req, Glossary())
    except LlmUnavailable:
        pass  # the stubbed output isn't valid JSON — we only assert the request body
    assert cap.bodies, "summarize should have invoked the model"
    assert cap.bodies[0]["max_tokens"] >= 4096  # not the old 2000 default that truncated


class _TruncatedTranslateBedrock:
    """Streams a valid translations JSON, then a max_tokens stop — i.e. an output-cap truncation
    (the JSON here happens to be complete, but the stop_reason marks the batch as truncated)."""

    def invoke_model_with_response_stream(self, *, modelId, body, accept, contentType):  # noqa: N803
        events = [
            {"type": "content_block_delta", "delta": {"text": '{"translations": {"0": "번역"}}'}},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
        ]
        return {
            "body": [
                {"chunk": {"bytes": json.dumps(e).encode("utf-8")}} for e in events
            ]
        }


def test_translate_segments_surfaces_output_truncation() -> None:
    # A translation batch that hit the output cap must report ``truncated`` so the translator can
    # re-split + retry (and so a partial batch is traceable rather than a silent empty translation).
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=_TruncatedTranslateBedrock()
    )
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    result = gw.translate_segments(
        [TranslationSegment(id="0", text="hello")], req, Glossary()
    )
    assert result.truncated is True
    assert result.translations == {"0": "번역"}


class _UnparseableTruncatedBedrock:
    """A max_tokens stop that cut the JSON MID-STRING, so the payload can't be parsed at all —
    the common real truncation (not the tidy complete-JSON case above)."""

    def invoke_model_with_response_stream(self, *, modelId, body, accept, contentType):  # noqa: N803
        events = [
            # Unterminated string value — json.loads raises "Unterminated string".
            {"type": "content_block_delta", "delta": {"text": '{"translations": {"0": "ab'}},
            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}},
        ]
        return {"body": [{"chunk": {"bytes": json.dumps(e).encode("utf-8")}} for e in events]}


def test_translate_segments_truncated_unparseable_json_reports_truncation() -> None:
    # A batch truncated MID-STRING (unparseable JSON) must NOT hard-fail — it must still report
    # ``truncated`` so the translator re-splits into smaller batches, instead of abstaining the
    # whole full-text translation (the observed long-paper failure).
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=_UnparseableTruncatedBedrock(),
        max_retries=0,
    )
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    result = gw.translate_segments(
        [TranslationSegment(id="0", text="hello"), TranslationSegment(id="1", text="world")],
        req, Glossary(),
    )
    assert result.truncated is True
    assert result.translations == {}


class _UnparseableCompleteBedrock:
    """Bad JSON on a COMPLETE response (no max_tokens stop) — a genuine malformed output."""

    def invoke_model_with_response_stream(self, *, modelId, body, accept, contentType):  # noqa: N803
        chunk = json.dumps({"type": "content_block_delta", "delta": {"text": "not json at all"}})
        return {"body": [{"chunk": {"bytes": chunk.encode("utf-8")}}]}


def test_translate_segments_bad_json_without_truncation_still_fails() -> None:
    # A parse failure on a COMPLETE (non-truncated) response is genuine bad output — it must still
    # fail-closed (retry then LlmUnavailable), not be masked as a truncation.
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=_UnparseableCompleteBedrock(),
        max_retries=0,
    )
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    try:
        gw.translate_segments([TranslationSegment(id="0", text="hello")], req, Glossary())
        raise AssertionError("expected LlmUnavailable for genuine bad output")
    except LlmUnavailable:
        pass
