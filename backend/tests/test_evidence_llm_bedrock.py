"""Bedrock LLM 어댑터 — `test_evidence_llm`(OpenAI)과 **같은 계약**을 건다.

프로바이더가 둘이 되는 순간 위험한 것은 문법 차이가 아니라 계약이 갈리는 것이다.
같은 관찰을 넣었을 때 같은 제안이 나오고, 같은 실패가 같은 예외로 좁혀지고,
이미지가 같은 순서로 실려야 한다(BR-EV-17). 그래서 단언을 형제 파일과 맞춰 둔다.

Anthropic use-case 양식이 이 계정에 아직 제출되지 않아 **실호출 검증은 불가능하다**
(2026-08-15 실측: 모든 Anthropic 모델이 ResourceNotFoundException). novelty의 Bedrock
어댑터가 선 자리와 같다 — 통합 실행이 아니라 포트 계약 유지가 목적이고, 로컬 페이크
위에서 계약을 고정한다.
"""

from __future__ import annotations

import json

import pytest

from backend.modules.evidence.adapters.llm_bedrock import BedrockDecider, BedrockExtractor
from backend.modules.evidence.domain.models import PaperHandle, PaperOrigin
from backend.modules.evidence.ports.llm import (
    LlmUnavailable,
    LoopObservation,
    PaperView,
    TerminationProposal,
    ToolCallProposal,
    ToolResultView,
)
from backend.modules.evidence.ports.tools import ImageAttachment, ToolSpec
from backend.tests.evidence_fakes import doc_model


class FakeBedrock:
    """boto3 bedrock-runtime 대역 — 요청을 기록하고 준비된 응답을 돌려준다."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response or {}
        self._error = error
        self.calls: list[dict] = []

    def invoke_model(self, *, modelId, body, accept, contentType):  # noqa: N803 — boto3 어휘
        self.calls.append(json.loads(body.decode("utf-8")))
        if self._error is not None:
            raise self._error
        return {"body": json.dumps(self._response).encode("utf-8")}


def _tool_response(name: str, args: dict, *, usage=(100, 50)):
    return {
        "content": [{"type": "tool_use", "name": name, "input": args}],
        "usage": {"input_tokens": usage[0], "output_tokens": usage[1]},
    }


def _text_response(text: str):
    return {"content": [{"type": "text", "text": text}], "usage": {}}


def _observation(**overrides) -> LoopObservation:
    base = {
        "topic": "protein folding",
        "papers": (PaperView("2401.1", "r1", "T", "corpus", "full"),),
        "recent_results": (),
        "evidence_count": 0,
        "cited_paper_count": 0,
        "has_conflicts": False,
        "iterations_left": 5,
        "tool_calls_left": 10,
        "cost_left_usd": 1.0,
    }
    return LoopObservation(**{**base, **overrides})


def _decider(response=None, error=None) -> tuple[BedrockDecider, FakeBedrock]:
    client = FakeBedrock(response, error)
    return BedrockDecider(model="anthropic.x", client=client), client


def test_decide_returns_a_tool_call():
    decider, _ = _decider(_tool_response("corpus_search", {"query": "protein"}))

    decision = decider.decide(_observation(), (ToolSpec("corpus_search", "d", {}),))

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {"query": "protein"}
    assert decision.cost_estimate_usd and decision.cost_estimate_usd > 0


def test_finish_tool_becomes_a_termination_proposal():
    decider, _ = _decider(_tool_response("finish", {"note": "충분"}))

    decision = decider.decide(_observation(), ())

    assert isinstance(decision.proposal, TerminationProposal)
    assert decision.proposal.note == "충분"


def test_no_tool_call_is_read_as_termination():
    decider, _ = _decider(_text_response("음..."))

    assert isinstance(decider.decide(_observation(), ()).proposal, TerminationProposal)


def test_malformed_arguments_do_not_crash_the_turn():
    decider, _ = _decider(_tool_response("corpus_search", "not-a-dict"))

    decision = decider.decide(_observation(), ())

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {}


def test_provider_failure_is_narrowed_to_the_port_contract():
    decider, _ = _decider(error=RuntimeError("429 rate limited"))

    with pytest.raises(LlmUnavailable):
        decider.decide(_observation(), ())


def test_missing_usage_does_not_invent_a_cost():
    """토큰 수가 없으면 계상하지 않는다 — 추정치를 넣으면 예산이 실제와 무관해진다."""
    decider, _ = _decider({"content": [{"type": "tool_use", "name": "finish", "input": {}}]})

    assert decider.decide(_observation(), ()).cost_estimate_usd is None


def test_system_prompt_goes_to_the_system_field_not_messages():
    """Anthropic은 system을 별도 필드로 받는다. messages에 남기면 지시가 데이터로 섞인다."""
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(_observation(), ())

    body = client.calls[0]
    assert body["system"]
    assert all(m["role"] != "system" for m in body["messages"])


def test_tool_choice_forces_a_call():
    """무-호출 턴을 막는다 — OpenAI 쪽 tool_choice='required'와 같은 의도."""
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(_observation(), (ToolSpec("corpus_search", "d", {}),))

    body = client.calls[0]
    assert body["tool_choice"] == {"type": "any"}
    assert {t["name"] for t in body["tools"]} == {"corpus_search", "finish"}


def test_images_are_attached_after_the_tool_result_section():
    """그림 안의 문구가 지시로 읽히지 않도록 데이터 구획 뒤에 붙인다(BR-EV-17)."""
    image = ImageAttachment(media_type="image/webp", data_b64="AAA", asset_id="fig1")
    view = ToolResultView(seq=1, tool_name="view_figure", ok=True, images=(image,))
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(_observation(recent_results=(view,)), ())

    last = client.calls[0]["messages"][-1]
    assert last["role"] == "user"
    assert [block["type"] for block in last["content"]] == ["text", "image"]


# --- extract -----------------------------------------------------------------


def _handle(dm=None) -> PaperHandle:
    return PaperHandle(
        paper_id="2401.1",
        record_ref="r1",
        title="T",
        origin=PaperOrigin.CORPUS,
        doc_model=dm,
        abstract_text="",
    )


def test_extractor_returns_raw_items_for_the_gate_to_judge():
    payload = '{"items": [{"statement": "s", "supporting": [], "conflicting": []}]}'
    extractor = BedrockExtractor(model="anthropic.x", client=FakeBedrock(_text_response(payload)))

    assert len(extractor.extract(topic="q", focus="", papers=(_handle(doc_model()),))) == 1


@pytest.mark.parametrize("payload", ["", "not json", '{"items": "nope"}', "{}"])
def test_unparseable_extraction_yields_no_items_instead_of_raising(payload):
    extractor = BedrockExtractor(model="anthropic.x", client=FakeBedrock(_text_response(payload)))

    assert extractor.extract(topic="q", focus="", papers=()) == []


def test_extraction_tolerates_a_code_fenced_object():
    """Anthropic에는 OpenAI의 json_object 강제 모드가 없어 펜스가 섞일 수 있다."""
    fenced = '```json\n{"items": [{"statement": "s"}]}\n```'
    extractor = BedrockExtractor(model="anthropic.x", client=FakeBedrock(_text_response(fenced)))

    assert len(extractor.extract(topic="q", focus="", papers=())) == 1
