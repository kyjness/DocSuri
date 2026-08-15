"""Bedrock 와이어 포맷 헬퍼 — 유닛 사본(U7·U11·U12)에서 보존해야 할 시맨틱."""

from __future__ import annotations

import io
import json

from docsuri_shared.bedrock import (
    ANTHROPIC_VERSION,
    first_tool_call,
    image_block,
    invoke_model,
    text_blocks,
    tool_schema,
)


class _Client:
    """invoke_model 스텁 — 응답 본문 모양을 주입해 봉투 처리만 본다."""

    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.seen: dict = {}

    def invoke_model(self, **kwargs):
        self.seen = kwargs
        return {"body": self._payload}


def test_invoke_model_encodes_body_and_decodes_stream_or_bytes() -> None:
    body = {"anthropic_version": ANTHROPIC_VERSION, "max_tokens": 8}
    # 실제 boto3는 StreamingBody(read()), 대다수 페이크는 그냥 bytes를 준다. 한쪽만
    # 처리하면 테스트는 통과하고 운영에서 깨진다 — 둘 다 받는다.
    for payload in (io.BytesIO(b'{"ok": 1}'), b'{"ok": 1}', '{"ok": 1}'):
        client = _Client(payload)
        assert invoke_model(client, "m-1", body) == {"ok": 1}
        assert client.seen["modelId"] == "m-1"
        assert json.loads(client.seen["body"].decode("utf-8")) == body
        assert client.seen["contentType"] == "application/json"


def test_tool_schema_uses_input_schema_key() -> None:
    # ``input_schema``는 Anthropic 문법이고 벤더마다 키와 중첩이 다르다 — 이 모양이 포트가
    # 아니라 프로바이더 어댑터에 속하는 이유다.
    spec = tool_schema("finish", "끝낸다", {"type": "object"})
    assert spec == {
        "name": "finish",
        "description": "끝낸다",
        "input_schema": {"type": "object"},
    }


def test_image_block_shape() -> None:
    assert image_block("image/png", "AAAA") == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    }


def test_first_tool_call_reads_name_and_arguments() -> None:
    response = {
        "content": [
            {"type": "text", "text": "생각 중"},
            {"type": "tool_use", "name": "search", "input": {"q": "x"}},
            {"type": "tool_use", "name": "second", "input": {}},
        ]
    }
    assert first_tool_call(response) == ("search", {"q": "x"})


def test_first_tool_call_absent_or_malformed_arguments() -> None:
    assert first_tool_call({"content": [{"type": "text", "text": "산문"}]}) is None
    assert first_tool_call({}) is None
    # 인자가 객체가 아니면 {} — 호출자가 도구 스키마로 검증하므로, 문자열을 그대로
    # 흘리면 여기서 멀리 떨어진 곳에서 TypeError가 된다.
    odd = {"content": [{"type": "tool_use", "name": "t", "input": "not-an-object"}]}
    assert first_tool_call(odd) == ("t", {})


def test_text_blocks_preserves_order_and_skips_non_text() -> None:
    response = {
        "content": [
            {"type": "text", "text": "하나"},
            {"type": "tool_use", "name": "t", "input": {}},
            {"type": "text", "text": "둘"},
        ]
    }
    assert text_blocks(response) == ["하나", "둘"]
    assert text_blocks({}) == []
