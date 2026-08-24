"""도구 6종 — 포트 대역 위에서 상태 갱신·거부 안내·게이트 연결을 본다.

v1의 같은 이름 파일(고정 파이프라인의 검색·DocModel 도구 테스트)을 대체한다.
"""

from __future__ import annotations

from typing import Any

from backend.modules.evidence.adapters.tools import (
    CorpusSearchTool,
    ExternalSearchTool,
    ExtractEvidenceTool,
    FetchPaperTool,
    ReadPaperTool,
)
from backend.modules.evidence.domain.models import (
    LoopState,
    PaperHandle,
    PaperOrigin,
    PromotionOutcome,
)
from backend.modules.evidence.ports.llm import LlmUnavailable
from backend.modules.evidence.ports.sources import (
    PaperCandidate,
    PromotionResult,
    SearchUnavailable,
)
from backend.modules.evidence.ports.tools import ToolContext
from backend.tests.evidence_fakes import (
    TABLE_ROW,
    doc_model,
)

CTX = ToolContext(owner_id="o1", session_id="s1", turn_id="t1")





class FakeSearch:
    def __init__(self, hits=(), error: Exception | None = None) -> None:
        self.hits = hits
        self.error = error
        self.calls: list[tuple[str, bool]] = []
        self.years: list[Any] = []

    def search(self, query: str, *, phrase: bool = False, years=None):
        self.calls.append((query, phrase))
        self.years.append(years)
        if self.error:
            raise self.error
        return self.hits


class FakeExternal(FakeSearch):
    def search(self, query: str):  # type: ignore[override]
        return super().search(query)


class FakeDocModels:
    def __init__(self, doc_model=None) -> None:
        self.doc_model = doc_model

    def get_doc_model(self, paper_id: str):
        return self.doc_model


class FakePromotion:
    def __init__(self, result: PromotionResult) -> None:
        self.result = result
        self.calls: list[str] = []

    def promote(self, paper_id: str) -> PromotionResult:
        self.calls.append(paper_id)
        return self.result


class FakeExtraction:
    def __init__(self, items: list[dict[str, Any]] | None = None, error=None) -> None:
        self.items = items or []
        self.error = error
        self.calls: list[dict] = []

    def extract(self, *, topic: str, focus: str, papers):
        self.calls.append({"topic": topic, "focus": focus, "papers": papers})
        if self.error:
            raise self.error
        return self.items


def _candidate(pid="2107.06xxx") -> PaperCandidate:
    return PaperCandidate(
        paper_id=pid,
        record_ref=f"rec-{pid}",
        title="AlphaFold2",
        abstract="We present AlphaFold2.",
    )


# --- 검색 -------------------------------------------------------------------


def test_corpus_search_registers_candidates_without_marking_them_examined():
    """검색은 '발견'이지 '확인'이 아니다 — 확인 범위 수치가 부풀지 않는다."""
    state = LoopState(topic="q")
    tool = CorpusSearchTool(FakeSearch(hits=(_candidate(),)), state)

    result = tool.invoke({"query": "protein"}, CTX)

    assert result.ok
    assert state.candidates == 1
    assert state.examined == 0


def test_corpus_search_passes_phrase_mode_through():
    """정확 문구 검색이 별도 도구가 아니라 인자로 흡수됐다(v1 intent.py 대체)."""
    state = LoopState(topic="q")
    port = FakeSearch(hits=())
    CorpusSearchTool(port, state).invoke({"query": "attention is all", "mode": "phrase"}, CTX)

    assert port.calls == [("attention is all", True)]


def test_search_failure_tells_the_agent_what_to_do_next():
    state = LoopState(topic="q")
    tool = CorpusSearchTool(FakeSearch(error=SearchUnavailable("down")), state)

    result = tool.invoke({"query": "q"}, CTX)

    assert not result.ok
    assert "반복하지 말고" in (result.error or "")


def test_external_search_marks_origin_so_promotion_takes_the_right_path():
    state = LoopState(topic="q")
    ExternalSearchTool(FakeExternal(hits=(_candidate("arxiv:2401.1v2"),)), state).invoke(
        {"query": "q"}, CTX
    )

    assert state.discovered["arxiv:2401.1v2"].origin is PaperOrigin.EXTERNAL


# --- 본문 확보 ---------------------------------------------------------------


def test_fetch_paper_reads_docmodel_for_corpus_papers():
    state = LoopState(topic="q")
    state.discovered["p1"] = PaperHandle("p1", "r1", PaperOrigin.CORPUS, abstract_text="abs")
    tool = FetchPaperTool(doc_models=FakeDocModels(doc_model()), promotion=None, state=state)

    result = tool.invoke({"paper_id": "p1"}, CTX)

    assert result.ok
    assert state.papers["p1"].scope == "fulltext"
    assert result.content["blockKinds"]["table"] == 1


def test_fetch_paper_promotes_external_papers():
    state = LoopState(topic="q")
    state.discovered["x1"] = PaperHandle("x1", "external:x1", PaperOrigin.EXTERNAL)
    promotion = FakePromotion(
        PromotionResult(outcome=PromotionOutcome.PROMOTED, doc_model=doc_model())
    )
    tool = FetchPaperTool(doc_models=FakeDocModels(), promotion=promotion, state=state)

    result = tool.invoke({"paper_id": "x1"}, CTX)

    assert result.ok
    assert promotion.calls == ["x1"]
    assert state.papers["x1"].scope == "fulltext"


def test_promotion_failure_is_a_normal_result_not_an_error():
    """실패가 예외면 루프가 깨진다 — 초록 범위로 계속하는 것이 설계다(BLM §4)."""
    state = LoopState(topic="q")
    state.discovered["x1"] = PaperHandle(
        "x1", "external:x1", PaperOrigin.EXTERNAL, abstract_text="a"
    )
    tool = FetchPaperTool(
        doc_models=FakeDocModels(),
        promotion=FakePromotion(PromotionResult(outcome=PromotionOutcome.LICENSE_BLOCKED)),
        state=state,
    )

    result = tool.invoke({"paper_id": "x1"}, CTX)

    assert result.ok
    assert state.papers["x1"].scope == "abstract"
    assert "초록 범위" in result.content["note"]


def test_fetch_unknown_paper_points_at_the_search_results():
    state = LoopState(topic="q")
    tool = FetchPaperTool(doc_models=FakeDocModels(), promotion=None, state=state)

    result = tool.invoke({"paper_id": "nope"}, CTX)

    assert not result.ok
    assert "corpus_search" in (result.error or "")


# --- 본문 읽기 ---------------------------------------------------------------


def test_read_paper_exposes_block_ids():
    """v1은 블록 id를 감춰 모델이 유효한 anchor를 쓸 방법이 없었다."""
    state = LoopState(topic="q")
    state.papers["p1"] = PaperHandle("p1", "r1", PaperOrigin.CORPUS, doc_model=doc_model())

    result = ReadPaperTool(state).invoke({"paper_id": "p1"}, CTX)

    ids = [block["id"] for block in result.content["blocks"]]
    assert "s4.tbl1" in ids
    assert {block["type"] for block in result.content["blocks"]} == {
        "paragraph", "table", "figure", "formula",
    }


def test_read_paper_without_full_text_says_how_to_get_it():
    state = LoopState(topic="q")
    state.papers["p1"] = PaperHandle("p1", "r1", PaperOrigin.CORPUS, abstract_text="abs")

    result = ReadPaperTool(state).invoke({"paper_id": "p1"}, CTX)

    assert not result.ok
    assert "fetch_paper" in (result.error or "")


def test_read_paper_keyword_filters_blocks():
    state = LoopState(topic="q")
    state.papers["p1"] = PaperHandle("p1", "r1", PaperOrigin.CORPUS, doc_model=doc_model())

    result = ReadPaperTool(state).invoke({"paper_id": "p1", "keyword": "CASP"}, CTX)

    assert [b["id"] for b in result.content["blocks"]] == ["s4.tbl1"]


# --- 근거 추출 ---------------------------------------------------------------


def _raw_item(anchor="s4.tbl1", quote=TABLE_ROW) -> dict:
    return {
        "statement": "AlphaFold2 reaches 92.4 GDT",
        "supporting": [
            {"paperId": "p1", "anchor": anchor, "quote": quote, "sourceScope": "fulltext"}
        ],
        "conflicting": [],
    }


def _state_with_full_text() -> LoopState:
    state = LoopState(topic="q")
    state.papers["p1"] = PaperHandle("p1", "r1", PaperOrigin.CORPUS, doc_model=doc_model())
    return state


def test_extract_evidence_accumulates_only_gate_survivors():
    state = _state_with_full_text()
    port = FakeExtraction(items=[_raw_item(), _raw_item(quote="fabricated text not in the paper")])

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert result.content["accepted"] == 1
    assert result.content["rejected"] == 2  # 인용 1건 + 그 항목의 supporting 0
    assert len(state.accumulator.items) == 1


def test_extract_evidence_returns_reason_distribution_not_details():
    """INV-EV-5 — 어떤 인용이 왜 떨어졌는지는 내부에 둔다. 분포와 수리 지시만 준다."""
    state = _state_with_full_text()
    port = FakeExtraction(items=[_raw_item(anchor="s9.nope")])

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert result.content["rejectedReasons"] == {"anchor_not_found": 1, "no_supporting": 1}
    assert "read_paper" in result.content["hint"]
    assert TABLE_ROW not in str(result.content)


def test_extract_evidence_marks_papers_as_examined():
    state = _state_with_full_text()
    state.discovered["p2"] = PaperHandle("p2", "r2", PaperOrigin.CORPUS, abstract_text="a")

    ExtractEvidenceTool(FakeExtraction(), state).invoke({"paper_ids": ["p1", "p2"]}, CTX)

    assert state.examined == 2


def test_extract_evidence_reports_unknown_papers_without_failing():
    state = _state_with_full_text()

    result = ExtractEvidenceTool(FakeExtraction(), state).invoke(
        {"paper_ids": ["p1", "ghost"]}, CTX
    )

    assert result.ok
    assert result.content["unknownPapers"] == ["ghost"]


def test_extraction_llm_failure_is_reported_as_a_tool_failure():
    state = _state_with_full_text()
    port = FakeExtraction(error=LlmUnavailable("down"))

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert not result.ok
    assert "근거 추출 모델" in (result.error or "")


# --- 연도 제약(§2.5) — 인자이지 프롬프트 당부가 아니다 -------------------------------


def _corpus(hits=()):
    port = FakeSearch(hits=hits)
    return port, CorpusSearchTool(port, LoopState(topic="t"))


def test_year_arguments_reach_the_port_as_a_bound() -> None:
    port, tool = _corpus(hits=(PaperCandidate("2401.1", "2401.1", "t"),))

    tool.invoke({"query": "x", "year_from": 2023, "year_to": 2025}, CTX)

    assert (port.years[0].start, port.years[0].end) == (2023, 2025)


def test_a_year_given_as_a_string_is_accepted() -> None:
    """모델은 "2023"을 문자열로 주는 일이 흔하다 — 거부하면 연도 제약이 조용히 사라진다."""
    port, tool = _corpus(hits=(PaperCandidate("2401.1", "2401.1", "t"),))

    tool.invoke({"query": "x", "year_from": "2023"}, CTX)

    assert port.years[0].start == 2023
    assert port.years[0].end is None


def test_no_year_argument_passes_no_bound_at_all() -> None:
    port, tool = _corpus(hits=(PaperCandidate("2401.1", "2401.1", "t"),))

    tool.invoke({"query": "x"}, CTX)

    assert port.years == [None]


def test_an_unreadable_year_is_dropped_rather_than_failing_the_search() -> None:
    port, tool = _corpus(hits=(PaperCandidate("2401.1", "2401.1", "t"),))

    result = tool.invoke({"query": "x", "year_from": "최근"}, CTX)

    assert result.ok
    assert port.years == [None]


def test_an_inverted_range_is_passed_through_unfixed() -> None:
    """조용히 바로잡으면 모델은 자기가 뒤집었다는 것을 영영 모른다 — 0건이 그것을 알려준다."""
    port, tool = _corpus()

    tool.invoke({"query": "x", "year_from": 2025, "year_to": 2020}, CTX)

    assert (port.years[0].start, port.years[0].end) == (2025, 2020)


def test_zero_hits_under_a_year_bound_says_the_bound_is_why() -> None:
    """"그런 논문이 없다"와 "연도로 걸러졌다"가 같은 0건으로 보이면 모델은 연도만 붙인 채
    같은 질의를 반복한다."""
    _port, tool = _corpus()

    result = tool.invoke({"query": "x", "year_from": 2023}, CTX)

    assert result.ok
    assert "2023년 이후" in result.content["note"]


def test_zero_hits_without_a_year_bound_keeps_the_plain_note() -> None:
    _port, tool = _corpus()

    result = tool.invoke({"query": "x"}, CTX)

    assert "연도" not in result.content["note"]


def test_the_tool_advertises_the_year_arguments() -> None:
    """스펙에 없으면 모델이 부를 수 없다 — 배선만 하고 노출을 빠뜨리면 조용히 미사용이다."""
    props = CorpusSearchTool.spec.parameters["properties"]

    assert "year_from" in props
    assert "year_to" in props
