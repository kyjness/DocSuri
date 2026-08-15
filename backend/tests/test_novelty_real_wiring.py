"""배포 어댑터(SQS·Bedrock) 계약 테스트 — 페이크 boto 클라이언트로 포트 계약만 본다
(nfr-design-patterns §7). local_wiring의 조립 결정도 함께 건다."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from backend.modules.novelty.adapters.real_wiring import (
    BedrockToolCallingLlm,
    SqsJobQueue,
)
from backend.modules.novelty.ports.llm import (
    LoopObservation,
    TerminationProposal,
    ToolCallProposal,
)
from backend.modules.novelty.ports.tools import ToolSpec
from backend.modules.novelty.settings import NoveltySettings

_TOOLS = (ToolSpec(name="corpus_search", description="d", parameters={"type": "object"}),)


def _observation() -> LoopObservation:
    return LoopObservation(
        topic="privacy preserving RAG",
        input_type="natural_language",
        recent_results=(),
        saved_artifact_kinds=frozenset(),
        missing_required_kinds=frozenset({"evidence", "similar_works", "gap_analysis"}),
        iterations_left=24,
        tool_calls_left=40,
        cost_left_usd=0.5,
    )


# ── SQS 큐 계약 ──


class _FakeSqsClient:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.visibility_calls: list[tuple[str, int]] = []
        self._receipt_seq = 0

    def send_message(self, QueueUrl, MessageBody):
        self.messages.append({"Body": MessageBody})

    def receive_message(self, QueueUrl, MaxNumberOfMessages, WaitTimeSeconds):
        if not self.messages:
            return {}
        message = self.messages.pop(0)
        self._receipt_seq += 1
        message = {**message, "ReceiptHandle": f"r-{self._receipt_seq}"}
        self._last = message
        return {"Messages": [message]}

    def delete_message(self, QueueUrl, ReceiptHandle):
        self.deleted = getattr(self, "deleted", [])
        self.deleted.append(ReceiptHandle)

    def change_message_visibility(self, QueueUrl, ReceiptHandle, VisibilityTimeout):
        self.visibility_calls.append((ReceiptHandle, VisibilityTimeout))


def test_sqs_queue_roundtrip_and_visibility_lease() -> None:
    client = _FakeSqsClient()
    queue = SqsJobQueue(client, "https://sqs.test/queue")
    queue.enqueue("job-1", "owner-1")
    job = queue.consume(timeout_seconds=1)
    assert job is not None and job.job_id == "job-1" and job.receipt == "r-1"
    # 수신한 잡의 잠금 갱신은 visibility 연장으로 표현된다.
    assert queue.acquire("job-1", ttl_seconds=120) is True
    assert queue.renew("job-1", ttl_seconds=120) is True
    assert client.visibility_calls and client.visibility_calls[0][1] == 120
    # 미수신 잡: 충돌 리스 없음 → stale 스윕이 잠글 수 있다(NFR-NV2-3, 코드 리뷰 반영).
    assert queue.acquire("job-9", ttl_seconds=120) is True
    queue.ack(job)
    assert client.deleted == ["r-1"]
    assert queue.renew("job-1", ttl_seconds=120) is False  # ack 후 리스 소멸


def test_sqs_corrupt_payload_discarded() -> None:
    client = _FakeSqsClient()
    client.messages.append({"Body": "not-json"})
    queue = SqsJobQueue(client, "https://sqs.test/queue")
    assert queue.consume(timeout_seconds=1) is None
    assert client.deleted  # 독약 메시지는 제거


# ── Bedrock LLM 계약 ──


class _FakeBedrockClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.bodies: list[dict] = []

    def invoke_model(self, modelId, body, accept, contentType):
        self.bodies.append(json.loads(body.decode("utf-8")))
        return {"body": json.dumps(self._payload).encode("utf-8")}


def _bedrock(payload: dict) -> tuple[BedrockToolCallingLlm, _FakeBedrockClient]:
    client = _FakeBedrockClient(payload)
    return (
        BedrockToolCallingLlm(model_id="anthropic.test", client=client),
        client,
    )


def test_bedrock_tool_call_decision_and_cost() -> None:
    llm, client = _bedrock(
        {
            "content": [
                {"type": "tool_use", "name": "corpus_search", "input": {"query": "dp rag"}}
            ],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
        }
    )
    decision = llm.decide(_observation(), _TOOLS)
    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {"query": "dp rag"}
    assert decision.cost_estimate_usd == pytest.approx(3.0 + 15.0)
    body = client.bodies[0]
    assert body["tool_choice"] == {"type": "any"}
    names = {tool["name"] for tool in body["tools"]}
    assert names == {"corpus_search", "propose_termination"}


def test_bedrock_termination_and_text_fallback() -> None:
    termination_block = {
        "type": "tool_use",
        "name": "propose_termination",
        "input": {"note": "done"},
    }
    llm, _ = _bedrock({"content": [termination_block]})
    assert isinstance(llm.decide(_observation(), _TOOLS).proposal, TerminationProposal)

    llm_text, _ = _bedrock({"content": [{"type": "text", "text": "충분합니다"}]})
    proposal = llm_text.decide(_observation(), _TOOLS).proposal
    assert isinstance(proposal, TerminationProposal)
    assert proposal.note == "충분합니다"


# ── local_wiring 조립 ──


def _settings(**overrides) -> NoveltySettings:
    base = NoveltySettings(
        llm_input_usd_per_mtok=3.0,
        llm_output_usd_per_mtok=15.0,
        bedrock_model_id="anthropic.test",
        region_name=None,
        queue_url=None,
        sqs_queue_url=None,
        github_token=None,
        external_timeout_seconds=5.0,
        assets_enabled=False,
        figure_max_image_bytes=4 * 1024 * 1024,
        lock_ttl_seconds=120.0,
        stale_after_seconds=900.0,
        max_iterations=24,
        max_tool_calls_total=40,
        max_search_calls=12,
        max_form_evidence_calls=4,
        max_view_figure_calls=8,
        max_save_artifact_calls=12,
        job_cost_limit_usd=0.5,
        max_turn_steps=4,
    )
    return replace(base, **overrides)


def test_llm_assembly_lives_in_composition_root() -> None:
    from backend.modules.novelty.adapters.local_wiring import build_llm, build_store
    from backend.modules.novelty.adapters.memory import InMemoryNoveltyStore
    from backend.modules.novelty.adapters.real_wiring import BedrockToolCallingLlm

    # The adapter builds its boto3 client eagerly, which needs a region. Supplied here so the
    # test asserts the ASSEMBLY rather than the ambient AWS configuration — CI has no region on
    # this lane and would otherwise fail with NoRegionError while the wiring is correct.
    llm = build_llm(_settings(region_name="us-east-1"))
    assert isinstance(llm, BedrockToolCallingLlm)
    # 단가는 settings에서 온다 — 어댑터 기본값에 기대면 모델을 바꿨을 때 단가만 옛 모델에
    # 남아 예산 대장이 조용히 어긋난다(FR-45 집계 입력).
    assert llm._input_rate == 3.0
    assert llm._output_rate == 15.0
    assert isinstance(build_store(None), InMemoryNoveltyStore)  # 폴백 — 항상 마운트 가능


def test_renamed_rate_env_still_reads_the_legacy_name_and_warns(monkeypatch, caplog) -> None:
    """`DOCSURI_NOVELTY_OPENAI_*` → `DOCSURI_NOVELTY_*` 개명. 옛 이름만 설정된 환경이
    조용히 기본값으로 떨어지면, 지금 기본값이 마침 Sonnet 단가와 같아 아무 증상 없이
    지나가고 모델을 바꾼 뒤 예산 대장이 틀어진 채로만 드러난다."""
    import logging as _logging

    from backend.modules.novelty.settings import NoveltySettings

    monkeypatch.delenv("DOCSURI_NOVELTY_INPUT_USD_PER_MTOK", raising=False)
    monkeypatch.setenv("DOCSURI_NOVELTY_OPENAI_INPUT_USD_PER_MTOK", "0.15")

    with caplog.at_level(_logging.WARNING, logger="docsuri.novelty.settings"):
        settings = NoveltySettings.from_env()

    assert settings.llm_input_usd_per_mtok == 0.15  # 무시되지 않는다
    assert any("DOCSURI_NOVELTY_INPUT_USD_PER_MTOK" in r.message for r in caplog.records)


def test_new_rate_env_wins_over_the_legacy_one(monkeypatch) -> None:
    from backend.modules.novelty.settings import NoveltySettings

    monkeypatch.setenv("DOCSURI_NOVELTY_OPENAI_INPUT_USD_PER_MTOK", "0.15")
    monkeypatch.setenv("DOCSURI_NOVELTY_INPUT_USD_PER_MTOK", "3.0")

    assert NoveltySettings.from_env().llm_input_usd_per_mtok == 3.0


def test_tool_registry_shrinks_naturally_without_deps() -> None:
    from backend.modules.novelty.adapters.local_wiring import build_tool_registry

    class _NoopHttp:
        def get(self, *args, **kwargs):
            raise RuntimeError("no network in tests")

    registry = build_tool_registry(_settings(), http_client=_NoopHttp())
    # corpus·evidence·자산 의존성 없음 → 외부 탐색 도구만. Notion·view_figure 부재.
    assert registry.names() == frozenset({"github_search", "dataset_search"})


def test_view_figure_registers_only_when_the_asset_store_is_wired() -> None:
    """logical-components §4 — 자산 스토어 설정이 있을 때만 등록된다."""
    from backend.modules.novelty.adapters.local_wiring import build_tool_registry

    class _NoopHttp:
        def get(self, *args, **kwargs):
            raise RuntimeError("no network in tests")

    registry = build_tool_registry(
        _settings(), asset_port=object(), http_client=_NoopHttp()
    )
    assert "view_figure" in registry.names()


def test_asset_port_gates_on_the_toggle_and_postgres_only() -> None:
    """u1/u7과 같은 토글을 공유한다 — 자산을 쓰지 않는 배포에서 도구만 살아나면
    에이전트가 매번 빈 목록을 받고 캡만 태운다.

    버킷 env는 조건에 넣지 않는다: 객체 주소는 `paper_asset.object_ref`가 들고 있고,
    `DOCSURI_S3_BUCKET`은 인제스천 스택에만 설정돼 있어(compute 스택에는 없다) 조건에
    넣으면 배포 환경에서 view_figure가 아무 신호 없이 사라진다.
    """
    from backend.modules.novelty.adapters.local_wiring import build_asset_port

    session_factory = object
    assert build_asset_port(_settings(), session_factory) is None  # 토글 off
    assert build_asset_port(_settings(assets_enabled=True), None) is None  # postgres 없음
    assert build_asset_port(_settings(assets_enabled=True), session_factory) is not None


def test_bedrock_outage_goes_through_breaker_to_llm_unavailable() -> None:
    """외부 연동 규칙(NFR-NV2-11) — 재시도 1회 후 실패, 차단 개방 중 즉시 거부."""
    from backend.modules.novelty.adapters.external.base import SourceBreaker
    from backend.modules.novelty.adapters.llm_prompt import LlmUnavailable

    calls = {"n": 0}

    class _DownClient:
        def invoke_model(self, **kwargs):
            calls["n"] += 1
            raise RuntimeError("bedrock outage")

    clock = {"now": 0.0}
    llm = BedrockToolCallingLlm(
        model_id="anthropic.test",
        client=_DownClient(),
        breaker=SourceBreaker(failure_threshold=1, cooldown_seconds=60, clock=lambda: clock["now"]),
    )
    with pytest.raises(LlmUnavailable):
        llm.decide(_observation(), _TOOLS)
    first_attempts = calls["n"]  # 재시도 1회 포함
    with pytest.raises(LlmUnavailable):
        llm.decide(_observation(), _TOOLS)  # 차단 개방 — 호출 없이 즉시 실패
    assert calls["n"] == first_attempts


