"""Bedrock Anthropic 어댑터 — `llm_openai`의 형제(TD-EV2-2).

프로바이더 교체는 "여기 형제 파일을 하나 더 두는 일"이라고 `llm_openai` 독스트링이
적어뒀고, 이 파일이 그 형제다. 포트(`EvidenceLlmPort`/`EvidenceExtractionPort`)·
프롬프트(`prompts.build_*`)·비용 계상(`estimate_cost`)·실패 계약(재시도 1회 +
`SourceBreaker` → `LlmUnavailable`)을 전부 공유한다. 다른 것은 요청 문법 하나뿐이다.

Bedrock **와이어 포맷**(invoke_model 봉투·도구 스키마 모양·이미지 블록·응답 블록 읽기)은
`docsuri_shared.bedrock`이 소유한다 — U7·U12도 같은 프로토콜을 말하므로 사본을 두면 프로토콜이
움직일 때 한 곳만 고쳐진다. 여기 남는 것은 U11의 **정책**이다: 브레이커·재시도·`LlmUnavailable`.

OpenAI와의 문법 차이는 셋이고, 전부 여기서 흡수한다:

- **system이 필드다.** `build_decide_messages`는 `[{system}, {user}]`를 돌려주므로
  system 역할을 뽑아 `body["system"]`에 넣고 나머지만 `messages`로 보낸다.
- **도구 스키마가 다르다.** `{name, description, input_schema}`이고, 강제 호출은
  `tool_choice={"type": "any"}`(OpenAI의 `tool_choice="required"` 대응)다.
- **JSON 강제 모드가 없다.** OpenAI의 `response_format={"type":"json_object"}`에
  해당하는 것이 없어 추출은 프롬프트 + 본문에서 객체를 잘라내는 파싱에 의존한다
  (파싱·결정 매핑·비용 계상은 `_llm_shared`가 소유 — 갈리면 한쪽만 고쳐진다).

이미지는 **같은 user 턴 안에서** 텍스트 블록 뒤에 실린다(BR-EV-17) — OpenAI 어댑터의
`_attach_images`와 같은 순서 규칙이고, novelty의 Bedrock 어댑터와 같은 턴 모양이다.
별도 user 메시지로 덧붙이면 user 턴이 연속돼 Anthropic의 역할 교대 규칙에 걸린다.

클라이언트는 composition root가 만들어 주입한다(타임아웃·재시도 정책이 거기 있다). 이
모듈은 boto3를 import하지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any

from docsuri_shared.bedrock import (
    ANTHROPIC_VERSION,
    first_tool_call,
    image_block,
    invoke_model,
    text_blocks,
    tool_schema,
)

from backend.modules.novelty.adapters.external.base import SourceBreaker, SourceUnavailable

from ..ports.llm import LlmDecision, LlmUnavailable, LoopObservation
from ..ports.tools import ToolSpec
from ._llm_shared import (
    FINISH_DESCRIPTION,
    FINISH_PARAMETERS,
    FINISH_TOOL,
    IMAGE_BOUNDARY_BANNER,
    decision_from_tool_call,
    parse_json_items,
    usage_cost,
)
from .prompts import build_decide_messages, build_extraction_messages

__all__ = ["BedrockDecider", "BedrockExtractor"]

log = logging.getLogger("docsuri.evidence.llm")

_MAX_TOKENS = 4096


def _split_system(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    """Anthropic은 system을 messages가 아니라 별도 필드로 받는다."""
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    rest: list[dict[str, Any]] = [
        {"role": m["role"], "content": [{"type": "text", "text": m["content"]}]}
        for m in messages
        if m.get("role") != "system"
    ]
    return system, rest


class _BedrockBase:
    def __init__(
        self,
        *,
        model: str,
        client: Any,
        input_usd_per_mtok: float,
        output_usd_per_mtok: float,
        breaker: SourceBreaker | None = None,
    ) -> None:
        # 단가에 기본값을 두지 않는다 — settings 테이블이 유일한 출처다. 여기 3.0/15.0을
        # 박아두면 모델을 바꾼 뒤 한쪽만 고쳐져 예산 대장이 조용히 어긋난다.
        self._model = model
        self._client = client
        self._input_rate = input_usd_per_mtok
        self._output_rate = output_usd_per_mtok
        self._breaker = breaker or SourceBreaker()

    def _body(self, system: str, messages: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return {
            "anthropic_version": ANTHROPIC_VERSION,
            "max_tokens": _MAX_TOKENS,
            "system": system,
            "messages": messages,
            **extra,
        }

    def _invoke(self, body: dict[str, Any]) -> dict[str, Any]:
        """전송은 공유 봉투가, 실패 계약(재시도 1회 + 브레이커 → `LlmUnavailable`)은 여기가."""
        try:
            return self._breaker.call(lambda: invoke_model(self._client, self._model, body))
        except SourceUnavailable as exc:
            raise LlmUnavailable(str(exc)[:300]) from exc

    def _usage_cost(self, response: dict[str, Any]) -> float | None:
        return usage_cost(
            (response or {}).get("usage"),
            input_key="input_tokens",
            output_key="output_tokens",
            input_usd_per_mtok=self._input_rate,
            output_usd_per_mtok=self._output_rate,
        )


class BedrockDecider(_BedrockBase):
    """루프의 `decide` — 다음 도구·인자 또는 종료."""

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        system, messages = _split_system(build_decide_messages(observation))
        messages = _attach_images(messages, observation)
        response = self._invoke(
            self._body(
                system,
                messages,
                tools=[
                    *(tool_schema(s.name, s.description, s.parameters) for s in tools),
                    tool_schema(FINISH_TOOL, FINISH_DESCRIPTION, FINISH_PARAMETERS),
                ],
                tool_choice={"type": "any"},
            )
        )
        return decision_from_tool_call(first_tool_call(response), self._usage_cost(response))


class BedrockExtractor(_BedrockBase):
    """`extract_evidence` 뒤의 추출 — 검증 전 원시 항목을 돌려준다."""

    def extract(
        self, *, topic: str, focus: str, papers: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        system, messages = _split_system(
            build_extraction_messages(topic=topic, focus=focus, papers=papers)
        )
        response = self._invoke(self._body(system, messages))
        # Join every text block: a preface block before the JSON block would otherwise make the
        # first block parse to [] with no error — the same prompt through OpenAI's json_object
        # mode arrives as one string, and the two paths must not diverge on shape.
        return parse_json_items("\n".join(text_blocks(response)))


def _attach_images(
    messages: list[dict[str, Any]], observation: LoopObservation
) -> list[dict[str, Any]]:
    """이미지는 마지막 user 턴의 텍스트 블록 뒤에 붙인다(BR-EV-17) — 그림 안의 문구가
    지시로 읽히지 않도록 경계 선언이 먼저 오고 데이터가 뒤에 온다. 새 user 메시지를 만들지
    않는다: user 턴이 연속되면 Anthropic 역할 교대 규칙에 걸리고, 하필 그림을 볼 차례에만
    400이 난다."""
    images = [img for view in observation.recent_results for img in view.images]
    if not images:
        return messages
    last = messages[-1]
    assert last["role"] == "user", "decide prompt must end with the user turn"
    blocks: list[dict[str, Any]] = [
        *last["content"],
        {"type": "text", "text": IMAGE_BOUNDARY_BANNER},
        *(image_block(image.media_type, image.data_b64) for image in images),
    ]
    return [*messages[:-1], {"role": "user", "content": blocks}]
