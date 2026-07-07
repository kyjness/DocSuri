"""The summary call must request a generous max_tokens, and the translate path must surface an
output-cap truncation so the translator can re-split.

The old 2000-token default truncated a full paper's structured Korean output mid-object → parse
failure → retry → ``LlmUnavailable`` → abstain ("근거 없음"). Guard against a regression to that
cap. Output is now a forced tool call (``emit_summary`` / ``emit_translations``): the model's
arguments stream as ``input_json_delta`` fragments, and a ``max_tokens`` stop cuts them mid-object.
"""

from __future__ import annotations

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
from tests.stubs import FakeBedrockStream, bedrock_tool_use_events


def test_summary_requests_generous_max_tokens_and_forces_tool() -> None:
    # Complete response but unparseable tool arguments → LlmUnavailable; we only assert the body.
    cap = FakeBedrockStream(
        bedrock_tool_use_events("emit_summary", ["not json"], stop_reason="tool_use")
    )
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=cap, max_retries=0
    )
    refined = RefinedSource(body="some source text with figures 1.2 and 3.4")
    req = SummaryRequest(paper_id="p", version=1, task=Task.SUMMARY, target_lang=TargetLang.KO)
    try:
        gw.summarize(refined, req, Glossary())
    except LlmUnavailable:
        pass  # the stubbed arguments aren't valid JSON — we only assert the request body
    assert cap.bodies, "summarize should have invoked the model"
    body = cap.bodies[0]
    assert body["max_tokens"] >= 4096  # not the old 2000 default that truncated
    assert body["tool_choice"] == {"type": "tool", "name": "emit_summary"}
    assert body["tools"][0]["name"] == "emit_summary"


def test_translate_segments_surfaces_output_truncation() -> None:
    # A translation batch that hit the output cap must report ``truncated`` so the translator can
    # re-split + retry. Here the arguments happen to be complete JSON, but the max_tokens stop
    # marks the batch as truncated.
    client = FakeBedrockStream(
        bedrock_tool_use_events(
            "emit_translations", ['{"translations": {"0": "번역"}}'], stop_reason="max_tokens"
        )
    )
    gw = BedrockLlmGateway(summary_model_id="m", translate_model_id="t", client=client)
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    result = gw.translate_segments([TranslationSegment(id="0", text="hello")], req, Glossary())
    assert result.truncated is True
    assert result.translations == {"0": "번역"}


def test_translate_segments_truncated_unparseable_json_reports_truncation() -> None:
    # A batch truncated MID-OBJECT (unparseable arguments) must NOT hard-fail — it must still report
    # ``truncated`` so the translator re-splits into smaller batches, instead of abstaining the
    # whole full-text translation (the observed long-paper failure).
    client = FakeBedrockStream(
        bedrock_tool_use_events(
            "emit_translations", ['{"translations": {"0": "ab'], stop_reason="max_tokens"
        )
    )
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=client, max_retries=0
    )
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    result = gw.translate_segments(
        [TranslationSegment(id="0", text="hello"), TranslationSegment(id="1", text="world")],
        req, Glossary(),
    )
    assert result.truncated is True
    assert result.translations == {}


def test_translate_segments_bad_json_without_truncation_still_fails() -> None:
    # A parse failure on a COMPLETE (non-truncated) response is genuine bad output — it must still
    # fail-closed (retry then LlmUnavailable), not be masked as a truncation.
    client = FakeBedrockStream(
        bedrock_tool_use_events("emit_translations", ["not json at all"], stop_reason="tool_use")
    )
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=client, max_retries=0
    )
    req = SummaryRequest(paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO)
    try:
        gw.translate_segments([TranslationSegment(id="0", text="hello")], req, Glossary())
        raise AssertionError("expected LlmUnavailable for genuine bad output")
    except LlmUnavailable:
        pass
