"""Bedrock/OpenAI isolation (RES-9 / nfr-design §1.1) — now the SHARED breaker.

The full state-machine contract (single HALF-OPEN probe, stale-success ignore,
probe-slot expiry) lives in ``docsuri_shared.resilience`` and is verified by
``shared/python/tests/test_resilience.py``. This file keeps the Unit-level
guard: the gateways must consume that shared breaker and fail fast with
``LlmUnavailable`` while it is OPEN — no dependency call behind an open circuit.
"""

from __future__ import annotations

import pytest

from summarization.adapters.bedrock_llm import BedrockLlmGateway
from summarization.ports.ports import LlmUnavailable


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class _CountingClient:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_model_with_response_stream(self, **kwargs):
        self.calls += 1
        raise RuntimeError("bedrock down")


def test_gateway_fails_fast_without_client_call_while_open() -> None:
    from docsuri_shared.resilience import CircuitBreaker

    client = _CountingClient()
    gateway = BedrockLlmGateway(
        summary_model_id="m-sum", translate_model_id="m-tr", client=client, max_retries=0
    )
    clock = _Clock()
    gateway._cb = CircuitBreaker(  # noqa: SLF001 — 결정론 클록 주입
        "test", failure_threshold=1, recovery_seconds=60.0, clock=clock
    )
    with pytest.raises(LlmUnavailable):
        gateway._invoke_json("m-sum", "sys", "user", {"name": "t", "input_schema": {}})
    calls_before_open = client.calls
    assert calls_before_open >= 1
    # threshold 1 → OPEN: 이후 호출은 클라이언트에 닿지 않고 즉시 실패한다.
    with pytest.raises(LlmUnavailable):
        gateway._invoke_json("m-sum", "sys", "user", {"name": "t", "input_schema": {}})
    assert client.calls == calls_before_open
    # recovery 창 경과 → HALF-OPEN 프로브가 다시 의존성에 닿는다.
    clock.now = 61.0
    with pytest.raises(LlmUnavailable):
        gateway._invoke_json("m-sum", "sys", "user", {"name": "t", "input_schema": {}})
    assert client.calls > calls_before_open
