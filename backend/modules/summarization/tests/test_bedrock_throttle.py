"""Bedrock throttling waits instead of failing the generation.

A full translation fans out several chunks per job and several jobs at once, so throttling is
routine. Before, it shared the one generic retry: two throttles raised ``LlmUnavailable``, which
failed the whole translation and had the orchestrator redo every chunk — finished, already billed
ones included. A throttle now waits on its own jittered schedule; other failures keep the generic
retry-then-raise path.
"""

from __future__ import annotations

import json

import pytest

from summarization.adapters import bedrock_llm
from summarization.adapters.bedrock_llm import _THROTTLE_BACKOFF_S, BedrockLlmGateway
from summarization.ports.ports import LlmUnavailable
from tests.stubs import bedrock_chunk_event, bedrock_tool_use_events

_TOOL = {"name": "emit", "input_schema": {}}


class _ClientError(Exception):
    """botocore ``ClientError`` shape (the gateway reads ``response`` without importing it)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Client:
    """Fails the first ``n`` calls with ``failure()``, then streams a valid tool call."""

    def __init__(self, n: int, failure) -> None:
        self.n = n
        self.failure = failure
        self.calls = 0

    def invoke_model_with_response_stream(self, **kwargs):
        self.calls += 1
        if self.calls <= self.n:
            return self.failure()
        events = bedrock_tool_use_events("emit", [json.dumps({"ok": True})])
        return {"body": [bedrock_chunk_event(e) for e in events]}


def _throttle_error():
    raise _ClientError("ThrottlingException")


def _throttle_in_stream():
    return {"body": [{"throttlingException": {"message": "Too many requests"}}]}


@pytest.fixture
def waits(monkeypatch) -> list[float]:
    slept: list[float] = []
    monkeypatch.setattr(bedrock_llm, "_sleep", slept.append)
    return slept


def _gw(client: _Client) -> BedrockLlmGateway:
    # max_retries=0: no generic retry, so any recovery below is the throttle schedule's alone.
    return BedrockLlmGateway(
        summary_model_id="m", translate_model_id="t", client=client, max_retries=0
    )


@pytest.mark.parametrize("failure", [_throttle_error, _throttle_in_stream])
def test_throttles_wait_out_the_schedule_then_succeed(failure, waits) -> None:
    client = _Client(len(_THROTTLE_BACKOFF_S), failure)
    assert _gw(client)._invoke_json("m", "s", "u", _TOOL)["ok"] is True
    assert client.calls == len(_THROTTLE_BACKOFF_S) + 1
    # One jittered wait per throttle, each within [d/2, d] of its slot.
    assert len(waits) == len(_THROTTLE_BACKOFF_S)
    for slept, d in zip(waits, _THROTTLE_BACKOFF_S, strict=True):
        assert d / 2 <= slept <= d


def test_throttling_past_the_schedule_still_raises(waits) -> None:
    client = _Client(len(_THROTTLE_BACKOFF_S) + 1, _throttle_error)
    with pytest.raises(LlmUnavailable):
        _gw(client)._invoke_json("m", "s", "u", _TOOL)
    assert client.calls == len(_THROTTLE_BACKOFF_S) + 1


def test_other_failures_do_not_wait_on_the_throttle_schedule(waits) -> None:
    # Waiting does not cure an access or validation error; it must fail as before.
    client = _Client(1, lambda: (_ for _ in ()).throw(_ClientError("AccessDeniedException")))
    with pytest.raises(LlmUnavailable):
        _gw(client)._invoke_json("m", "s", "u", _TOOL)
    assert client.calls == 1
    assert waits == []
