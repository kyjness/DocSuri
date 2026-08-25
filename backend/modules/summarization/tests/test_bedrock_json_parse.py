"""Structured output (tool-use) parsing — the gateway forces ``emit_summary`` /
``emit_translations`` and buffers the tool call's ``input_json_delta`` fragments into the
arguments object. This replaces the old free-text-JSON path (and its ``_escape_stray_backslashes``
recovery): raw LaTeX (\\mathcal, \\rho) and inner quotes (경우("sandwiched")) that used to break
``json.loads`` are now carried as valid JSON escapes on the wire, so they round-trip cleanly.
"""

from __future__ import annotations

import json

import pytest

from summarization.adapters.bedrock_llm import BedrockLlmGateway, _as_str
from summarization.domain.models import (
    AnchorTarget,
    Glossary,
    RefinedSource,
    SummaryRequest,
    TargetLang,
    Task,
    TranslationSegment,
)
from summarization.ports.ports import LlmUnavailable
from tests.stubs import FakeBedrockStream, bedrock_chunk_event, bedrock_tool_use_events


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


@pytest.mark.parametrize(
    "tail_event",
    [
        # Stream-level error event (ResponseStream union member other than ``chunk``).
        {"modelStreamErrorException": {"message": "stream broke mid-generation"}},
        # In-band error frame inside a chunk.
        bedrock_chunk_event(
            {"type": "error", "error": {"type": "overloaded_error", "message": "overloaded"}}
        ),
    ],
)
def test_stream_error_event_aborts_instead_of_partial_buffer(tail_event: dict) -> None:
    # A mid-stream error used to fall through the chunk-only loop, silently returning the partial
    # buffer as if complete. It must abort the call → retry → LlmUnavailable → abstain (RES-9).
    partial = {"type": "input_json_delta", "partial_json": '{"tldr": "요'}
    events = [
        bedrock_chunk_event({"type": "content_block_delta", "delta": partial}),
        tail_event,
    ]
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t",
        client=FakeBedrockStream(events, raw=True), max_retries=0,
    )
    with pytest.raises(LlmUnavailable):
        gw.summarize(RefinedSource(body="paper text"), _SUMMARY_REQ, Glossary())


def test_stream_empty_chunk_event_is_benign() -> None:
    # A present-but-EMPTY chunk event is not an error member — it must be skipped (the pre-guard
    # behavior), not classified as a fatal stream error.
    payload = {"tldr": "요약", "contributions": [], "method": "", "results": "",
               "limitations": "", "reproducibility": {"code": "", "data": ""}, "anchors": []}
    events = [{"chunk": {}}]
    events += [bedrock_chunk_event(e) for e in _tool_use_events(payload, name="emit_summary")]
    gw = BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t",
        client=FakeBedrockStream(events, raw=True), max_retries=0,
    )
    draft = gw.summarize(RefinedSource(body="paper text"), _SUMMARY_REQ, Glossary())
    assert draft.tldr == "요약"


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


def test_leaked_tool_markup_is_stripped_from_field_values() -> None:
    """모델이 값 **안에** 도구 호출 마크업을 써 넣는 일이 있다.

    실측(2026-08-25 배포본): `reproducibility.code`가
    `"\\n<parameter name=\\"code\\">코드 공개 여부가 논문 본문에…"`로 왔다. 그대로 두면 화면에
    태그가 글자로 보이고, 앵커 대조·용어집 치환도 그 쓰레기를 함께 본다.
    """
    assert _as_str('\n<parameter name="code">코드 공개 없음') == "코드 공개 없음"
    assert _as_str("<invoke name='x'>본문</invoke>") == "본문"


def test_ordinary_angle_brackets_survive() -> None:
    """본문의 부등호는 건드리지 않는다 — 수식·코드 인용에 정상적으로 나온다.

    여는 태그 이름을 좁게 잡은 이유가 이것이다. `<[^>]*>`로 넓게 지우면 `$x < y$` 같은 원문이
    잘려 나가고, 그 훼손은 앵커 대조가 실패하는 모양으로만 표가 난다.
    """
    assert _as_str("손실은 $x < y$ 이고 a > b 이다") == "손실은 $x < y$ 이고 a > b 이다"
    assert _as_str("List<int> 타입") == "List<int> 타입"
