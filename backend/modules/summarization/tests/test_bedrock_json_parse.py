"""Structured output (tool-use) parsing — the gateway forces ``emit_summary`` /
``emit_translations`` and buffers the tool call's ``input_json_delta`` fragments into the
arguments object. This replaces the old free-text-JSON path (and its ``_escape_stray_backslashes``
recovery): raw LaTeX (\\mathcal, \\rho) and inner quotes (경우("sandwiched")) that used to break
``json.loads`` are now carried as valid JSON escapes on the wire, so they round-trip cleanly.
"""

from __future__ import annotations

import json

from summarization.adapters.bedrock_llm import BedrockLlmGateway
from summarization.domain.models import (
    AnchorTarget,
    Glossary,
    RefinedSource,
    SummaryRequest,
    TargetLang,
    Task,
    TranslationSegment,
)
from tests.stubs import FakeBedrockStream, bedrock_tool_use_events


def _tool_use_events(payload: dict, *, name: str, fragments: int = 3) -> list[dict]:
    """Forced-tool-use stream that serializes ``payload`` as the tool arguments.

    ``json.dumps`` escapes backslashes / inner quotes exactly as the platform would on the wire;
    the arguments are split across several ``input_json_delta`` fragments (via the shared
    ``bedrock_tool_use_events`` envelope) to exercise accumulation."""
    body = json.dumps(payload, ensure_ascii=False)
    step = max(1, len(body) // fragments)
    pieces = [body[i : i + step] for i in range(0, len(body), step)] or [""]
    return bedrock_tool_use_events(name, pieces)


def _gw(events: list[dict]) -> tuple[BedrockLlmGateway, FakeBedrockStream]:
    client = FakeBedrockStream(events)
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=client, max_retries=0
    )
    return gw, client


_SUMMARY_REQ = SummaryRequest(
    paper_id="p", version=1, task=Task.SUMMARY, target_lang=TargetLang.KO
)
_TRANSLATE_REQ = SummaryRequest(
    paper_id="p", version=1, task=Task.TRANSLATE, target_lang=TargetLang.KO
)


def test_summarize_parses_forced_tool_input_with_anchors() -> None:
    payload = {
        "tldr": "요약",
        "contributions": ["기여 1", "기여 2"],
        "method": "방법",
        "results": "결과",
        "limitations": "한계",
        "reproducibility": {"code": "github.com/x/y", "data": ""},
        "anchors": [
            {"field": "results", "target": "table", "label": "Table 3", "span": "95.3%"},
        ],
    }
    gw, client = _gw(_tool_use_events(payload, name="emit_summary"))
    draft = gw.summarize(RefinedSource(body="paper text"), _SUMMARY_REQ, Glossary())

    assert draft.tldr == "요약"
    assert draft.contributions == ("기여 1", "기여 2")
    assert draft.reproducibility == {"code": "github.com/x/y", "data": ""}
    assert draft.truncated is False
    (anchor,) = draft.anchors
    assert anchor.field_name == "results"
    assert anchor.target is AnchorTarget.TABLE
    assert anchor.label == "Table 3"
    assert anchor.target_hint == "table"  # raw target string preserved for the grounding gate
    # The forced tool is pinned in the request body.
    body = client.bodies[0]
    assert body["tool_choice"] == {"type": "tool", "name": "emit_summary"}
    assert body["tools"][0]["name"] == "emit_summary"


def test_summarize_survives_off_schema_field_shapes() -> None:
    # The model deviated from the tool schema: reproducibility came back as a bare STRING (not
    # {code, data}), contributions as a bare string, and an anchors entry as a non-object. The old
    # code did ``reproducibility.get(...)`` on the string and crashed the whole job
    # (``'str' object has no attribute 'get'``) → infinite redelivery / eternal pending. Now each
    # off-schema shape degrades gracefully instead of raising.
    payload = {
        "tldr": "요약",
        "contributions": "단일 기여 문자열",
        "method": "방법",
        "results": "결과",
        "limitations": "한계",
        "reproducibility": "코드는 github.com/x/y 에 공개",
        "anchors": ["not-an-object", {"field": "results", "target": "table", "label": "T3"}],
    }
    gw, _ = _gw(_tool_use_events(payload, name="emit_summary"))
    draft = gw.summarize(RefinedSource(body="paper text"), _SUMMARY_REQ, Glossary())

    # A bare-string reproducibility is kept under 'code' (not dropped, not a crash).
    assert draft.reproducibility == {"code": "코드는 github.com/x/y 에 공개", "data": ""}
    # A bare-string contributions becomes ONE element, never a per-character split.
    assert draft.contributions == ("단일 기여 문자열",)
    # The stray non-object anchor is skipped; the valid one survives.
    (anchor,) = draft.anchors
    assert anchor.label == "T3"


def test_translate_segments_parses_forced_tool_input() -> None:
    payload = {"translations": {"0": "첫 번째", "1": "두 번째"}, "keptTerms": ["Transformer"]}
    gw, _ = _gw(_tool_use_events(payload, name="emit_translations"))
    result = gw.translate_segments(
        [TranslationSegment(id="0", text="first"), TranslationSegment(id="1", text="second")],
        _TRANSLATE_REQ,
        Glossary(),
    )
    assert result.translations == {"0": "첫 번째", "1": "두 번째"}
    assert result.kept_terms == ("Transformer",)
    assert result.truncated is False


def test_raw_latex_and_inner_quotes_round_trip_as_valid_json() -> None:
    # The exact values that broke the old free-text parser: raw LaTeX commands and an inner quote.
    # Under tool-use these are valid JSON escapes on the wire, so no repair heuristic is needed.
    latex = "에너지 \\mathcal{G}=-i\\hat{H}, \\rho_t, \\nabla_r, \\frac{a}{b}"
    quoted = '이 경우("sandwiched")를 다룬다'
    payload = {"translations": {"0": latex, "1": quoted}, "keptTerms": []}
    gw, _ = _gw(_tool_use_events(payload, name="emit_translations", fragments=6))
    result = gw.translate_segments(
        [TranslationSegment(id="0", text="a"), TranslationSegment(id="1", text="b")],
        _TRANSLATE_REQ,
        Glossary(),
    )
    assert result.translations["0"] == latex
    assert "\\mathcal{G}" in result.translations["0"]
    assert result.translations["1"] == quoted
