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
