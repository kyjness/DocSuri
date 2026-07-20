"""배포 기준선 어댑터(SQS·RDS·Bedrock) — 계약 보존(TD-NV2-1~5).

AWS 배포는 회수 상태다: 이 모듈은 통합 실행이 아니라 **포트 계약 유지**가 목적이며
로컬 페이크와 같은 계약 테스트를 공유한다(nfr-design-patterns §7). 배포 복원 시
local_wiring 대신 이 조립을 선택하면 된다 — 루프 코어·프롬프트는 불변.

- RDS 저장: SqlNoveltyStore 재사용(동일 스키마 — migrations/004).
- SQS 큐: visibility timeout이 리스 역할(수신 후 비가시 = 잠금, 갱신 =
  change_message_visibility). 프로세스 내 이중 실행은 in-flight 맵으로 방지.
- Bedrock tool-calling: Anthropic messages + tool_choice any — OpenAI 어댑터와
  동일한 결정 계약(합성 propose_termination 포함).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..ports.llm import LlmDecision, LoopObservation
from ..ports.queue import QueuedJob
from ..ports.tools import ToolSpec
from .external.base import SourceBreaker, SourceUnavailable
from .llm_prompt import (
    SYSTEM_PROMPT,
    TERMINATION_TOOL,
    LlmUnavailable,
    conservative_termination,
    decision_from_tool_call,
    estimate_cost,
    render_observation,
    termination_parameters,
)

__all__ = ["BedrockToolCallingLlm", "SqsJobQueue"]

log = logging.getLogger("docsuri.novelty.real_wiring")


class SqsJobQueue:
    """JobQueuePort + ExecutionLockPort(visibility 리스). client는 boto3 sqs."""

    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url
        # job_id → receipt handle. 수신 즉시 등록되어 프로세스 내 이중 실행을 막고,
        # 프로세스 간 격리는 SQS visibility timeout이 담당한다.
        self._in_flight: dict[str, str] = {}

    def enqueue(self, job_id: str, owner_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"job_id": job_id, "owner_id": owner_id}),
        )

    def consume(self, timeout_seconds: float) -> QueuedJob | None:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=1,
            WaitTimeSeconds=min(int(timeout_seconds), 20),
        )
        messages = response.get("Messages") or []
        if not messages:
            return None
        message = messages[0]
        receipt = message["ReceiptHandle"]
        try:
            data = json.loads(message.get("Body") or "{}")
            job = QueuedJob(
                job_id=str(data["job_id"]), owner_id=str(data["owner_id"]), receipt=receipt
            )
        except (ValueError, KeyError):
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
            return None
        self._in_flight[job.job_id] = receipt
        return job

    def ack(self, job: QueuedJob) -> None:
        if job.receipt is not None:
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=job.receipt)
        self._in_flight.pop(job.job_id, None)

    # ── 실행 잠금: visibility 리스 ──
    def acquire(self, job_id: str, ttl_seconds: float) -> bool:
        receipt = self._in_flight.get(job_id)
        if receipt is None:
            # 이 프로세스가 수신하지 않은 잡: 충돌할 리스가 없다 — stale 스윕이 방치된
            # 잡을 잠글 수 있어야 한다(NFR-NV2-3). 프로세스 간 이중 스윕은 종단 상태
            # 래치(update_job)가 멱등으로 흡수한다.
            return True
        return self.renew(job_id, ttl_seconds)

    def renew(self, job_id: str, ttl_seconds: float) -> bool:
        receipt = self._in_flight.get(job_id)
        if receipt is None:
            return False
        self._client.change_message_visibility(
            QueueUrl=self._queue_url,
            ReceiptHandle=receipt,
            VisibilityTimeout=max(int(ttl_seconds), 1),
        )
        return True

    def release(self, job_id: str) -> None:
        self._in_flight.pop(job_id, None)


class BedrockToolCallingLlm:
    """ToolCallingLlmPort — Bedrock Anthropic tool-calling(레거시 패턴 이식)."""

    def __init__(
        self,
        *,
        model_id: str,
        client: Any,
        max_tokens: int = 4096,
        input_usd_per_mtok: float = 3.0,
        output_usd_per_mtok: float = 15.0,
        breaker: SourceBreaker | None = None,
    ) -> None:
        self._model_id = model_id
        self._client = client
        self._max_tokens = max_tokens
        self._input_rate = input_usd_per_mtok
        self._output_rate = output_usd_per_mtok
        self._breaker = breaker or SourceBreaker()

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._max_tokens,
            "system": SYSTEM_PROMPT,
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": render_observation(observation)}],
                }
            ],
            "tools": [*(_to_tool(spec) for spec in tools), _termination_tool()],
            "tool_choice": {"type": "any"},
        }
        response = self._invoke(body)
        return self._parse(response)

    def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        def call() -> dict[str, Any]:
            response = self._client.invoke_model(
                modelId=self._model_id,
                body=json.dumps(body).encode("utf-8"),
                accept="application/json",
                contentType="application/json",
            )
            raw = response["body"]
            payload = raw.read() if hasattr(raw, "read") else raw
            return json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)

        try:
            # 재시도 1회 + 서킷 브레이커(외부 연동 규칙) — OpenAI 어댑터와 동일 실패 계약.
            return self._breaker.call(call)
        except SourceUnavailable as exc:
            raise LlmUnavailable(str(exc)) from exc

    def _parse(self, response: dict[str, Any]) -> LlmDecision:
        usage = response.get("usage") or {}
        cost = estimate_cost(
            usage.get("input_tokens") if usage else None,
            usage.get("output_tokens") if usage else None,
            input_usd_per_mtok=self._input_rate,
            output_usd_per_mtok=self._output_rate,
        )
        tool_use = next(
            (
                block
                for block in response.get("content") or []
                if block.get("type") == "tool_use"
            ),
            None,
        )
        if tool_use is None:
            text = " ".join(
                str(block.get("text") or "")
                for block in response.get("content") or []
                if block.get("type") == "text"
            )
            return conservative_termination(text, cost)
        args = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else {}
        return decision_from_tool_call(str(tool_use.get("name") or ""), args, cost)


def _to_tool(spec: ToolSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "description": spec.description,
        "input_schema": spec.parameters,
    }


def _termination_tool() -> dict[str, Any]:
    return {
        "name": TERMINATION_TOOL,
        "description": "필수 산출물이 모두 저장되어 조사를 끝내자고 제안한다.",
        "input_schema": termination_parameters(),
    }
