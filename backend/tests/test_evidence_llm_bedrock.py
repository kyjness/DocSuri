"""Bedrock LLM 어댑터 계약 — 도구 호출·종료·실패 좁히기·이미지 순서.

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

from backend.modules.evidence.adapters.llm_bedrock import (
    IMAGE_BOUNDARY_BANNER,
    BedrockAnswerWriter,
    BedrockDecider,
    BedrockExtractor,
    parse_json_sentences,
)
from backend.modules.evidence.ports.llm import (
    AnswerEvidenceView,
    AnswerRequest,
    LlmUnavailable,
    TerminationProposal,
    ToolCallProposal,
    ToolResultView,
)
from backend.modules.evidence.ports.tools import ImageAttachment, ToolSpec
from backend.tests.evidence_fakes import doc_model, observation, paper_handle


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



_RATES = {"input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0}


def _decider(response=None, error=None) -> tuple[BedrockDecider, FakeBedrock]:
    client = FakeBedrock(response, error)
    return BedrockDecider(model="anthropic.x", client=client, **_RATES), client


def _extractor(response) -> BedrockExtractor:
    return BedrockExtractor(model="anthropic.x", client=FakeBedrock(response), **_RATES)


def test_decide_returns_a_tool_call():
    decider, _ = _decider(_tool_response("corpus_search", {"query": "protein"}))

    decision = decider.decide(observation(), (ToolSpec("corpus_search", "d", {}),))

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {"query": "protein"}
    assert decision.cost_estimate_usd and decision.cost_estimate_usd > 0


def test_finish_tool_becomes_a_termination_proposal():
    decider, _ = _decider(_tool_response("finish", {"note": "충분"}))

    decision = decider.decide(observation(), ())

    assert isinstance(decision.proposal, TerminationProposal)
    assert decision.proposal.note == "충분"


def test_no_tool_call_is_read_as_termination():
    decider, _ = _decider(_text_response("음..."))

    assert isinstance(decider.decide(observation(), ()).proposal, TerminationProposal)


def test_malformed_arguments_do_not_crash_the_turn():
    decider, _ = _decider(_tool_response("corpus_search", "not-a-dict"))

    decision = decider.decide(observation(), ())

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {}


def test_provider_failure_is_narrowed_to_the_port_contract():
    decider, _ = _decider(error=RuntimeError("429 rate limited"))

    with pytest.raises(LlmUnavailable):
        decider.decide(observation(), ())


def test_missing_usage_does_not_invent_a_cost():
    """토큰 수가 없으면 계상하지 않는다 — 추정치를 넣으면 예산이 실제와 무관해진다."""
    decider, _ = _decider({"content": [{"type": "tool_use", "name": "finish", "input": {}}]})

    assert decider.decide(observation(), ()).cost_estimate_usd is None


def test_system_prompt_goes_to_the_system_field_not_messages():
    """Anthropic은 system을 별도 필드로 받는다. messages에 남기면 지시가 데이터로 섞인다."""
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(observation(), ())

    body = client.calls[0]
    assert body["system"]
    assert all(m["role"] != "system" for m in body["messages"])


def test_tool_choice_forces_a_call():
    """무-호출 턴을 막는다 — 모델이 '아무 도구도 안 부른' 애매한 턴을 만들 수 없게 한다."""
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(observation(), (ToolSpec("corpus_search", "d", {}),))

    body = client.calls[0]
    assert body["tool_choice"] == {"type": "any"}
    assert {t["name"] for t in body["tools"]} == {"corpus_search", "finish"}


def test_extra_parallel_calls_are_noted_not_silently_dropped():
    """tool_choice는 최소 1개를 강제할 뿐 1개로 제한하지 않는다. 루프는 턴당 하나만
    실행하므로 나머지는 버려지는데, 기록이 없으면 모델이 시킨 일이 그냥 사라진다."""
    decider, _ = _decider(
        {
            "content": [
                {"type": "tool_use", "name": "corpus_search", "input": {"q": "x"}},
                {"type": "tool_use", "name": "read_paper", "input": {}},
            ],
            "usage": {},
        }
    )

    decision = decider.decide(observation(), (ToolSpec("corpus_search", "d", {}),))

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.tool_name == "corpus_search"
    assert "dropped parallel calls: read_paper" in (decision.proposal.decision_note or "")


def test_images_are_attached_after_the_tool_result_section():
    """그림 안의 문구가 지시로 읽히지 않도록 데이터 구획 뒤에 붙인다(BR-EV-17)."""
    image = ImageAttachment(media_type="image/webp", data_b64="AAA", asset_id="fig1")
    view = ToolResultView(seq=1, tool_name="view_figure", ok=True, images=(image,))
    decider, client = _decider(_tool_response("finish", {}))

    decider.decide(observation(recent_results=(view,)), ())

    messages = client.calls[0]["messages"]
    # ONE user turn: observation text, then the boundary banner, then the image. A second
    # consecutive user message would break Anthropic's role alternation exactly when the loop
    # has a figure to look at.
    assert [m["role"] for m in messages] == ["user"]
    assert [block["type"] for block in messages[0]["content"]] == ["text", "text", "image"]
    assert IMAGE_BOUNDARY_BANNER in messages[0]["content"][1]["text"]


# --- extract -----------------------------------------------------------------



def test_extractor_returns_raw_items_for_the_gate_to_judge():
    payload = '{"items": [{"statement": "s", "supporting": [], "conflicting": []}]}'
    extractor = _extractor(_text_response(payload))

    assert len(extractor.extract(topic="q", focus="", papers=(paper_handle(doc_model()),))) == 1


@pytest.mark.parametrize("payload", ["", "not json", '{"items": "nope"}', "{}"])
def test_unparseable_extraction_yields_no_items_instead_of_raising(payload):
    extractor = _extractor(_text_response(payload))

    assert extractor.extract(topic="q", focus="", papers=()) == []


def test_extraction_reads_every_text_block():
    """서문 블록 뒤에 JSON 블록이 오면 첫 블록만 읽는 파서는 조용히 []를 낸다."""
    response = {
        "content": [
            {"type": "text", "text": "다음은 추출 결과입니다."},
            {"type": "text", "text": '{"items": [{"statement": "s"}]}'},
        ],
        "usage": {},
    }

    assert len(_extractor(response).extract(topic="q", focus="", papers=())) == 1


def test_extraction_tolerates_a_code_fenced_object():
    """JSON 강제 모드가 없어 모델이 코드펜스를 두를 수 있다."""
    fenced = '```json\n{"items": [{"statement": "s"}]}\n```'
    extractor = _extractor(_text_response(fenced))

    assert len(extractor.extract(topic="q", focus="", papers=())) == 1


# --- 판단 어댑터(§4.2) ---------------------------------------------------------


def _answer_writer(response) -> BedrockAnswerWriter:
    return BedrockAnswerWriter(model="anthropic.x", client=FakeBedrock(response), **_RATES)


def _answer_request() -> AnswerRequest:
    return AnswerRequest(
        topic="q",
        question_kind="comparison",
        evidence=(
            AnswerEvidenceView(number=1, statement="s", paper_id="p1", quote="quote text"),
        ),
    )


def test_answer_parses_sentences_with_their_refs():
    writer = _answer_writer(
        _text_response('{"sentences": [{"text": "A", "refs": [1]}, {"text": "B", "refs": []}]}')
    )

    draft = writer.write(_answer_request())

    assert [s.text for s in draft.sentences] == ["A", "B"]
    assert draft.sentences[0].refs == (1,)


def test_answer_keeps_a_malformed_ref_list_as_a_synthesis_sentence():
    """걸러내면 §4.3 검사가 볼 것이 줄어 판정이 어댑터로 샌다 — 추출 쪽과 같은 원칙."""
    writer = _answer_writer(
        _text_response('{"sentences": [{"text": "A", "refs": "nope"}, {"text": "B"}]}')
    )

    draft = writer.write(_answer_request())

    assert [s.refs for s in draft.sentences] == [(), ()]


def test_answer_drops_empty_sentences_but_not_the_rest():
    writer = _answer_writer(
        _text_response('{"sentences": [{"text": "   ", "refs": [1]}, {"text": "B", "refs": [1]}]}')
    )

    draft = writer.write(_answer_request())

    assert [s.text for s in draft.sentences] == ["B"]


def test_a_non_json_answer_yields_no_sentences_rather_than_crashing():
    """문장이 0건이면 검사기가 A4로 거부하고 재생성·폴백으로 간다 — 여기서 판정하지 않는다."""
    draft = _answer_writer(_text_response("판단을 못 하겠습니다")).write(_answer_request())

    assert draft.sentences == ()


def test_finish_tool_declares_the_question_kind():
    decider, _ = _decider(_tool_response("finish", {"note": "done", "question_kind": "fact"}))

    decision = decider.decide(observation(), ())

    assert decision.proposal.question_kind == "fact"


def test_an_unknown_question_kind_is_not_carried_through():
    """어휘 밖 값은 지어낸 것이다 — None으로 두고 판단 프롬프트가 unknown으로 읽는다."""
    decider, _ = _decider(_tool_response("finish", {"question_kind": "vibes"}))

    decision = decider.decide(observation(), ())

    assert decision.proposal.question_kind is None


def test_answer_accepts_a_bare_json_array():
    """모델은 래퍼 없이 배열로도 답한다 — 못 읽으면 판단이 통째로 사라진다(2026-08-24 실측).

    그때 문장 0건 → 검사기 A4 거부 → 재생성 → 폴백으로 흘러, 골든셋 6문항 전부
    `fallback_rate=1.0`이 나왔다. 예외도 로그도 없이 "판단 없는 답"만 나갔다.
    """
    writer = _answer_writer(
        _text_response('앞에 붙은 산문\n```json\n[{"text": "A", "refs": [1]}]\n```')
    )

    draft = writer.write(_answer_request())

    assert [(s.text, s.refs) for s in draft.sentences] == [("A", (1,))]


def test_answer_still_prefers_the_documented_wrapper():
    writer = _answer_writer(_text_response('{"sentences": [{"text": "B", "refs": [1]}]}'))

    assert [s.text for s in writer.write(_answer_request()).sentences] == ["B"]


def test_answer_coerces_int_like_refs_and_drops_only_the_unreadable():
    """`"1"`·`1.0`은 1이다. 정수만 통과시키면 문자열 refs 응답의 인용이 **전부** 사라져
    A4 → 재생성 → 폴백으로 판단이 없어진다 — 맨 배열과 같은 모양의 구멍이다."""
    sentences = parse_json_sentences(
        '{"sentences":[{"text":"a","refs":["1",2]},{"text":"b","refs":[1.0]},'
        '{"text":"c","refs":[true,"x",1.5]}]}'
    )

    assert [s.refs for s in sentences] == [(1, 2), (1,), ()]


def test_answer_absorbs_an_inline_marker_into_refs_and_strips_it_from_text():
    """본문의 `[1, 2]`는 refs로 옮기고 text에서는 지운다 — refs가 권위다."""
    (sentence,) = parse_json_sentences(
        '{"sentences":[{"text":"데이터가 적을 때는 LoRA가 낫다 [1, 2]","refs":[2]}]}'
    )

    assert sentence.text == "데이터가 적을 때는 LoRA가 낫다"
    assert sentence.refs == (2, 1)
