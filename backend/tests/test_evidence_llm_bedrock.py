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
import threading

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
    # **병렬도 함께 끈다.** `any`는 "최소 1개"만 강제하고 개수를 안 막는다 — 모델이 여러 개를
    # 함께 내면 루프는 첫 개만 쓰고 나머지를 버리는데, 버리는 것이 아니라 **생성한 것이
    # 비용**이다(출력 토큰은 이미 냈다). 실측: 같은 프롬프트에서 켜기 전 3·3·3개, 켠 뒤 1·1·1개.
    assert body["tool_choice"] == {"type": "any", "disable_parallel_tool_use": True}
    assert {t["name"] for t in body["tools"]} == {"corpus_search", "finish"}


def test_extra_parallel_calls_are_noted_not_silently_dropped():
    """방어선은 둘이다. 요청에서 병렬을 끄지만(`disable_parallel_tool_use`), 그것이 없는
    프로바이더·모델에서도 **버려진 사실은 기록에 남아야** 한다 — 기록이 없으면 모델이 시킨
    일이 그냥 사라진다. 이 검사는 그 두 번째 방어선을 본다."""
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

    draft = extractor.extract(topic="q", focus="", papers=(paper_handle(doc_model()),))
    assert len(draft.items) == 1


@pytest.mark.parametrize("payload", ["", "not json", '{"items": "nope"}', "{}"])
def test_unparseable_extraction_yields_no_items_instead_of_raising(payload):
    extractor = _extractor(_text_response(payload))

    assert extractor.extract(topic="q", focus="", papers=()).items == []


def test_extraction_reads_every_text_block():
    """서문 블록 뒤에 JSON 블록이 오면 첫 블록만 읽는 파서는 조용히 []를 낸다."""
    response = {
        "content": [
            {"type": "text", "text": "다음은 추출 결과입니다."},
            {"type": "text", "text": '{"items": [{"statement": "s"}]}'},
        ],
        "usage": {},
    }

    assert len(_extractor(response).extract(topic="q", focus="", papers=()).items) == 1


def test_extraction_tolerates_a_code_fenced_object():
    """JSON 강제 모드가 없어 모델이 코드펜스를 두를 수 있다."""
    fenced = '```json\n{"items": [{"statement": "s"}]}\n```'
    extractor = _extractor(_text_response(fenced))

    assert len(extractor.extract(topic="q", focus="", papers=()).items) == 1


# --- 추출 병렬화 --------------------------------------------------------------


class _PerPaperBedrock:
    """논문 id를 프롬프트에서 읽어 그 논문의 항목만 돌려주는 대역.

    호출을 **동시에** 받으므로 기록에 락을 건다 — 안 걸면 이 테스트가 드물게 흔들리고,
    그 흔들림은 검사 대상(순서)과 구분되지 않는다.
    """

    def __init__(self, order: list[str]) -> None:
        self._order = order
        self.prompts: list[str] = []
        self._lock = threading.Lock()

    def invoke_model(self, *, modelId, body, accept, contentType):  # noqa: N803 — boto3 어휘
        prompt = json.loads(body.decode("utf-8"))["messages"][0]["content"][0]["text"]
        with self._lock:
            self.prompts.append(prompt)
        pid = next(p for p in self._order if f"[PAPER {p}]" in prompt)
        payload = {"items": [{"statement": pid, "supporting": [], "conflicting": []}]}
        return {
            "body": json.dumps(
                {"content": [{"type": "text", "text": json.dumps(payload)}],
                 "usage": {"input_tokens": 100, "output_tokens": 50}}
            ).encode("utf-8")
        }


def test_extraction_splits_papers_into_one_call_each():
    """추출은 턴 시간의 3분의 2 이상을 먹고, 여러 편을 한 프롬프트에 묶은 호출이 가장 느리다
    (배포본 실측: 3편 35.8초 · 4편 33.5초 — 1편은 22초). 나눠 던지면 가장 느린 한 편으로 준다.

    추출은 논문 간 대조를 하지 않으므로(그건 조립·판단의 몫이다) 나눠도 근거를 안 잃는다.
    """
    papers = tuple(paper_handle(doc_model(), paper_id=pid) for pid in ("p1", "p2", "p3"))
    client = _PerPaperBedrock(["p1", "p2", "p3"])
    extractor = BedrockExtractor(model="anthropic.x", client=client, **_RATES)

    draft = extractor.extract(topic="q", focus="", papers=papers)

    assert len(client.prompts) == 3, "논문 수만큼 나가야 한다"
    # **제출 순서로 모은다.** 완료 순서로 모으면 근거 번호가 실행마다 흔들리고, 그 번호는
    # 판단 산문이 가리키는 값이다(BR-EV-5).
    assert [item["statement"] for item in draft.items] == ["p1", "p2", "p3"]
    # 비용은 호출별로 합산된다 — 나누면 시스템 프롬프트가 논문 수만큼 반복된다.
    # 입력 100 · 출력 50 토큰 × 3회 (단가는 _RATES).
    one = 100 / 1e6 * 3.0 + 50 / 1e6 * 15.0
    assert draft.cost_estimate_usd == pytest.approx(3 * one)


def test_extraction_does_not_split_a_single_paper():
    """나눌 것이 없으면 스레드풀을 만들지 않는다."""
    client = FakeBedrock(_text_response('{"items": [{"statement": "s"}]}'))
    extractor = BedrockExtractor(model="anthropic.x", client=client, **_RATES)

    extractor.extract(topic="q", focus="", papers=(paper_handle(doc_model()),))

    assert len(client.calls) == 1


def test_one_paper_failing_does_not_discard_the_others():
    """부분 실패를 전면 실패로 삼으면 논문 한 편의 스로틀이 턴 전체의 근거를 날린다."""

    class _OneFails(_PerPaperBedrock):
        def invoke_model(self, **kw):
            body = json.loads(kw["body"].decode("utf-8"))
            if "[PAPER p2]" in body["messages"][0]["content"][0]["text"]:
                raise RuntimeError("throttled")
            return super().invoke_model(**kw)

    papers = tuple(paper_handle(doc_model(), paper_id=pid) for pid in ("p1", "p2"))
    extractor = BedrockExtractor(
        model="anthropic.x", client=_OneFails(["p1", "p2"]), **_RATES
    )

    draft = extractor.extract(topic="q", focus="", papers=papers)

    assert [item["statement"] for item in draft.items] == ["p1"]


def test_every_paper_failing_is_still_a_failure():
    """전부 죽었으면 조용히 빈 결과를 내지 않는다 — 근거 0건과 구분되지 않는다."""
    papers = tuple(paper_handle(doc_model(), paper_id=pid) for pid in ("p1", "p2"))
    extractor = BedrockExtractor(
        model="anthropic.x", client=FakeBedrock(error=RuntimeError("down")), **_RATES
    )

    with pytest.raises(LlmUnavailable):
        extractor.extract(topic="q", focus="", papers=papers)


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


def test_answer_normalises_the_declared_role_without_judging_the_vocabulary():
    """역할은 **모델이 선언한다**(refs에서 유도할 수 없다).

    어댑터는 **모양만** 다듬는다 — 대소문자·공백을 정규화하고 빈 값을 None으로 만든다.
    어휘 밖(`summary`)을 여기서 버리지 않는 이유는 refs·추출과 같다: 무엇이 유효한지는
    도메인이 정한다. 판정을 양쪽에서 하면 어휘 밖 값의 행동이 두 곳에 나뉜다.
    최종 세그먼트에서 `summary`가 evidence로 읽히는 것은 `test_evidence_answer_checks`가 본다.
    """
    sentences = parse_json_sentences(
        '{"sentences":['
        '{"text":"a","refs":[1],"role":"conclusion"},'
        '{"text":"b","refs":[1],"role":"  DIVERGENCE "},'
        '{"text":"c","refs":[1],"role":"summary"},'
        '{"text":"d","refs":[1]}]}'
    )

    assert [s.role for s in sentences] == ["conclusion", "divergence", "summary", None]
