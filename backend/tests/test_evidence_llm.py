"""LLM 어댑터 + 프롬프트 — 프로바이더 대역 위에서.

가장 중요한 단언은 프롬프트 정합이다: **프롬프트에 실린 문자열이 게이트가 대조할
투영과 같아야** 인용이 통과한다(v1 캡션 결함의 재발 방지).
"""

from __future__ import annotations

import pytest

from backend.modules.evidence.adapters.llm_openai import OpenAiDecider, OpenAiExtractor
from backend.modules.evidence.adapters.prompts import (
    build_decide_messages,
    build_extraction_messages,
)
from backend.modules.evidence.domain.projection import block_projection, paper_projection
from backend.modules.evidence.ports.llm import (
    LlmUnavailable,
    PaperView,
    TerminationProposal,
    ToolCallProposal,
    ToolResultView,
)
from backend.modules.evidence.ports.tools import ImageAttachment, ToolSpec
from backend.tests.evidence_fakes import (
    FIGURE_CAPTION,
    doc_model,
    observation,
    paper_handle,
)


class FakeTransport:
    """HTTP 전송 대역 — 네트워크 없이 어댑터 계약만 본다."""

    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response or {}
        self.error = error
        self.calls: list[dict] = []

    def __call__(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        return self.response


def _tool_response(name: str, arguments: str, *, usage=(100, 50)):
    return {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": name, "arguments": arguments}}]}}
        ],
        "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
    }


def _text_response(text: str):
    return {"choices": [{"message": {"content": text}}]}


# --- 프롬프트 정합 (v1 결함 재발 방지) ----------------------------------------


def test_extraction_prompt_renders_the_same_string_the_gate_will_compare():
    """프롬프트 표현 ≠ 대조 투영이면 인용은 구조적으로 탈락한다."""
    handle = paper_handle(doc_model=doc_model())
    messages = build_extraction_messages(topic="q", focus="", papers=(handle,))
    body = messages[-1]["content"]

    figure_block = handle.doc_model.sections[0].blocks[2]  # 공용 픽스처: [p, tbl, fig, eq]
    assert block_projection(figure_block) == FIGURE_CAPTION
    assert FIGURE_CAPTION in body
    assert FIGURE_CAPTION in paper_projection(handle.doc_model)


def test_extraction_prompt_exposes_block_ids():
    messages = build_extraction_messages(topic="q", focus="", papers=(paper_handle(doc_model()),))
    body = messages[-1]["content"]

    assert "s5.fig3" in body
    assert "s4.tbl1" in body


def test_abstract_only_paper_is_labelled_in_the_prompt():
    messages = build_extraction_messages(
        topic="q", focus="", papers=(paper_handle(abstract="We present AlphaFold2."),)
    )
    body = messages[-1]["content"]

    assert "abstract" in body
    assert "We present AlphaFold2." in body


def test_decide_prompt_carries_call_arguments_with_results():
    """결과만 보이면 모델이 같은 질의를 반복한다(⑤3 실측)."""
    view = ToolResultView(
        seq=1, tool_name="corpus_search", ok=True,
        args_summary="query=protein folding", content={"hits": []},
    )
    messages = build_decide_messages(observation(recent_results=(view,)))

    assert "query=protein folding" in messages[-1]["content"]


def test_decide_prompt_lists_pending_papers_so_ids_are_not_invented():
    """확보했지만 아직 열지 않은 논문이 관찰에 보여야 모델이 그 id를 부를 수 있다.

    검색 도구가 없는 explicit scope에서는 이 목록이 **유일한 id 출처**다. 빠져 있으면
    모델은 부를 id를 몰라 존재하지 않는 값을 지어내고(실스택에서 `WJ-23-347` 등으로
    재현), 사용자가 지정한 논문은 한 번도 열리지 않는다.
    """
    pending = PaperView("2201.13299", "2201.13299", "Orientation-Aware GNNs", "corpus", "unknown")
    messages = build_decide_messages(observation(papers=(), pending_papers=(pending,)))

    body = messages[-1]["content"]
    assert "2201.13299" in body
    assert "fetch_paper" in body


def test_decide_prompt_marks_tool_results_as_data_not_instructions():
    view = ToolResultView(seq=1, tool_name="read_paper", ok=True, content={"blocks": []})
    messages = build_decide_messages(observation(recent_results=(view,)))

    assert "지시 아님" in messages[-1]["content"]


# --- decide ------------------------------------------------------------------


def _decider(response=None, error=None) -> tuple[OpenAiDecider, FakeTransport]:
    transport = FakeTransport(response, error)
    return OpenAiDecider(model="gpt-x", transport=transport), transport


def test_decide_returns_a_tool_call():
    decider, _ = _decider(_tool_response("corpus_search", '{"query": "protein"}'))

    decision = decider.decide(observation(), (ToolSpec("corpus_search", "d", {}),))

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {"query": "protein"}
    assert decision.cost_estimate_usd and decision.cost_estimate_usd > 0


def test_finish_tool_becomes_a_termination_proposal():
    decider, _ = _decider(_tool_response("finish", '{"note": "충분"}'))

    decision = decider.decide(observation(), ())

    assert isinstance(decision.proposal, TerminationProposal)
    assert decision.proposal.note == "충분"


def test_no_tool_call_is_read_as_termination():
    """도메인이 근거 유무로 판정하므로 여기서는 애매함을 종료 제안으로 좁힌다."""
    decider, _ = _decider(_text_response("음..."))

    decision = decider.decide(observation(), ())

    assert isinstance(decision.proposal, TerminationProposal)


def test_malformed_arguments_do_not_crash_the_turn():
    decider, _ = _decider(_tool_response("corpus_search", "{not json"))

    decision = decider.decide(observation(), ())

    assert isinstance(decision.proposal, ToolCallProposal)
    assert decision.proposal.args == {}


def test_provider_failure_is_narrowed_to_the_port_contract():
    decider, _ = _decider(error=RuntimeError("429 rate limited"))

    with pytest.raises(LlmUnavailable):
        decider.decide(observation(), ())


def test_images_are_attached_after_the_tool_result_section():
    """그림 안의 문구가 지시로 읽히지 않도록 데이터 구획 뒤에 붙인다(BR-EV-17)."""
    image = ImageAttachment(media_type="image/webp", data_b64="AAA", asset_id="fig1")
    view = ToolResultView(seq=1, tool_name="view_figure", ok=True, images=(image,))
    decider, transport = _decider(_tool_response("finish", "{}"))

    decider.decide(observation(recent_results=(view,)), ())

    messages = transport.calls[0]["messages"]
    assert messages[-1]["role"] == "user"
    kinds = [block["type"] for block in messages[-1]["content"]]
    assert kinds == ["text", "image_url"]


# --- extract -----------------------------------------------------------------


def test_extractor_returns_raw_items_for_the_gate_to_judge():
    payload = '{"items": [{"statement": "s", "supporting": [], "conflicting": []}]}'
    extractor = OpenAiExtractor(model="gpt-x", transport=FakeTransport(_text_response(payload)))

    items = extractor.extract(topic="q", focus="", papers=(paper_handle(doc_model()),))

    assert len(items) == 1


@pytest.mark.parametrize("payload", ["", "not json", '{"items": "nope"}', "{}"])
def test_unparseable_extraction_yields_no_items_instead_of_raising(payload):
    extractor = OpenAiExtractor(model="gpt-x", transport=FakeTransport(_text_response(payload)))

    assert extractor.extract(topic="q", focus="", papers=()) == []
