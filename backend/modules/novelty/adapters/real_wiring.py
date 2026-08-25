"""배포 기준선 어댑터(SQS·RDS·Bedrock) — 계약 보존(TD-NV2-1~5).

AWS 배포는 회수 상태다: 이 모듈은 통합 실행이 아니라 **포트 계약 유지**가 목적이며
로컬 페이크와 같은 계약 테스트를 공유한다(nfr-design-patterns §7). 배포 복원 시
local_wiring 대신 이 조립을 선택하면 된다 — 루프 코어·프롬프트는 불변.

- RDS 저장: SqlNoveltyStore 재사용(동일 스키마 — migrations/004).
- SQS 큐: visibility timeout이 리스 역할(수신 후 비가시 = 잠금, 갱신 =
  change_message_visibility). 프로세스 내 이중 실행은 in-flight 맵으로 방지.
- Bedrock tool-calling: Anthropic messages + tool_choice any(합성 propose_termination
  포함). 와이어 포맷은
  `docsuri_shared.bedrock`이 소유하고(U7·U11과 공유), 여기엔 정책만 남는다:
  브레이커·재시도 1회·`LlmUnavailable`·결정 매핑.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from docsuri_shared.bedrock import (
    ANTHROPIC_VERSION,
    dropped_call_note,
    image_block,
    invoke_model,
    text_blocks,
    tool_calls,
    tool_schema,
)

from ..ports.llm import LlmDecision, LoopObservation
from ..ports.queue import KIND_LOOP, QueuedJob
from ..ports.tools import ToolSpec
from .external.base import SourceBreaker, SourceUnavailable
from .llm_prompt import (
    TERMINATION_TOOL,
    LlmUnavailable,
    conservative_termination,
    decision_from_tool_call,
    estimate_cost,
    render_observation_parts,
    system_prompt_for,
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

    def enqueue(
        self,
        job_id: str,
        owner_id: str,
        *,
        kind: str = KIND_LOOP,
        message_id: str | None = None,
    ) -> None:
        job = QueuedJob(job_id=job_id, owner_id=owner_id, kind=kind, message_id=message_id)
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps(job.to_payload())
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
            job = QueuedJob.from_payload(json.loads(message.get("Body") or "{}"), receipt=receipt)
        except (ValueError, KeyError):
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
            return None
        self._in_flight[job.job_id] = receipt
        return job

    def ack(self, job: QueuedJob) -> None:
        if job.receipt is not None:
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=job.receipt)
        self._in_flight.pop(job.job_id, None)

    def nack(self, job: QueuedJob) -> None:
        """visibility를 0으로 되돌려 즉시 재전달 가능하게 한다. 만료를 기다리는
        기존 동작(ack 생략)보다 대기가 짧고, redis 구현과 계약이 같아진다."""
        if job.receipt is not None:
            self._client.change_message_visibility(
                QueueUrl=self._queue_url, ReceiptHandle=job.receipt, VisibilityTimeout=0
            )
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
        text, images = render_observation_parts(observation)
        # 텍스트(신뢰 경계 선언 포함)가 반드시 이미지보다 앞에 온다.
        content: list[dict[str, Any]] = [{"type": "text", "text": text}]
        content.extend(image_block(image.media_type, image.data_b64) for image in images)
        body = {
            "anthropic_version": ANTHROPIC_VERSION,
            "max_tokens": self._max_tokens,
            "system": system_prompt_for(observation),
            "messages": [{"role": "user", "content": content}],
            "tools": [
                *(tool_schema(s.name, s.description, s.parameters) for s in tools),
                tool_schema(
                    TERMINATION_TOOL,
                    "필수 산출물이 모두 저장되어 조사를 끝내자고 제안한다.",
                    termination_parameters(),
                ),
            ],
            # 병렬 호출을 끈다 — evidence와 같은 이유다(루프가 턴당 한 호출만 실행하므로
            # 나머지는 생성 비용만 내고 버려진다).
            "tool_choice": {"type": "any", "disable_parallel_tool_use": True},
        }
        return self._parse(self._invoke(body))

    def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        try:
            # 재시도 1회 + 서킷 브레이커(외부 연동 규칙, NFR-NV2-11).
            return self._breaker.call(
                lambda: invoke_model(self._client, self._model_id, body)
            )
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
        calls = tool_calls(response)
        if not calls:
            # 도구 없이 산문만 온 턴 — 남은 텍스트 전부를 근거로 보수적 종료.
            return conservative_termination(" ".join(text_blocks(response)), cost)
        # 루프는 턴당 한 호출만 실행한다. tool_choice는 최소 1개를 강제할 뿐 1개로 제한하지
        # 않으므로 나머지는 버려지는데, 조용히 버리면 모델이 요청한 작업이 사라진 사실이
        # 어디에도 안 남는다 — 폐기 목록을 결정 노트에 기록한다.
        name, args = calls[0]
        return decision_from_tool_call(name, args, cost, decision_note=dropped_call_note(calls))
