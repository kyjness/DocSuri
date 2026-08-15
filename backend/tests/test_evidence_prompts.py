"""프롬프트 정합 — 프롬프트에 실린 문자열이 게이트가 대조할 투영과 같아야 한다.

v1 캡션 결함(프롬프트가 게이트와 다른 문자열을 실어 인용이 통과하지 못한 것)의 재발
방지가 목적이다. 어댑터가 아니라 `adapters/prompts.py`를 직접 부른다 — 프롬프트는
프로바이더와 무관하고, 전송 계층을 끼우면 이 단언이 어댑터 구현에 묶인다.
어댑터 계약(도구 호출·종료·실패 좁히기·이미지 순서)은 test_evidence_llm_bedrock.py가 본다.
"""

from __future__ import annotations

from backend.modules.evidence.adapters.prompts import (
    build_decide_messages,
    build_extraction_messages,
)
from backend.modules.evidence.domain.projection import block_projection, paper_projection
from backend.modules.evidence.ports.llm import PaperView, ToolResultView
from backend.tests.evidence_fakes import (
    FIGURE_CAPTION,
    doc_model,
    observation,
    paper_handle,
)


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
