"""도구 6종 — 포트 대역 위에서 상태 갱신·거부 안내·게이트 연결을 본다.

v1의 같은 이름 파일(고정 파이프라인의 검색·DocModel 도구 테스트)을 대체한다.
"""

from __future__ import annotations

from backend.modules.evidence.adapters.tools import (
    CorpusSearchTool,
    ExtractEvidenceTool,
    FetchPaperTool,
    LiveLookupTool,
    ReadPaperTool,
    versioned_arxiv,
)
from backend.modules.evidence.domain.models import (
    LoopState,
    PaperHandle,
    PaperOrigin,
    PromotionOutcome,
)
from backend.modules.evidence.ports.llm import LlmUnavailable
from backend.modules.evidence.ports.sources import (
    LiveLookupResult,
    PaperCandidate,
    PromotionResult,
    SearchUnavailable,
)
from backend.modules.evidence.ports.tools import ToolContext
from backend.modules.evidence.testing import NoItems, ScriptedSearch
from backend.tests.evidence_fakes import (
    TABLE_ROW,
    doc_model,
)

CTX = ToolContext(owner_id="o1", session_id="s1", turn_id="t1")





class FakeLive:
    """`LivePaperLookupPort` 대역 — 계약이 `lookup()` 하나라 저하를 **반드시** 말해야 한다.

    종전에는 `search()`만 있는 대역이었고, 도구가 `getattr`로 갈리는 분기를 살려 두는 유일한
    이유가 이 대역이었다. 계약을 넓히자 그 분기와 함께 사라졌다.
    """

    def __init__(self, hits=(), error: Exception | None = None, degraded=()) -> None:
        self.hits = hits
        self.error = error
        self.degraded = tuple(degraded)

    def lookup(self, query: str) -> LiveLookupResult:
        if self.error:
            raise self.error
        return LiveLookupResult(tuple(self.hits), self.degraded)


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
    tool = CorpusSearchTool(ScriptedSearch(hits=(_candidate(),)), state)

    result = tool.invoke({"query": "protein"}, CTX)

    assert result.ok
    assert state.candidates == 1
    assert state.examined == 0


def test_corpus_search_passes_phrase_mode_through():
    """정확 문구 검색이 별도 도구가 아니라 인자로 흡수됐다(v1 intent.py 대체)."""
    state = LoopState(topic="q")
    port = ScriptedSearch(hits=())
    CorpusSearchTool(port, state).invoke({"query": "attention is all", "mode": "phrase"}, CTX)

    assert port.queries == [("attention is all", True)]


def test_search_failure_tells_the_agent_what_to_do_next():
    state = LoopState(topic="q")
    tool = CorpusSearchTool(ScriptedSearch(error=SearchUnavailable("down")), state)

    result = tool.invoke({"query": "q"}, CTX)

    assert not result.ok
    assert "반복하지 말고" in (result.error or "")


def test_live_lookup_marks_origin_so_promotion_takes_the_right_path():
    state = LoopState(topic="q")
    LiveLookupTool(FakeLive(hits=(_candidate("arxiv:2401.1v2"),)), state).invoke(
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
    state.discovered["arxiv:2401.10001v1"] = PaperHandle(
        "arxiv:2401.10001v1", "external:arxiv:2401.10001v1", PaperOrigin.EXTERNAL
    )
    promotion = FakePromotion(
        PromotionResult(outcome=PromotionOutcome.PROMOTED, doc_model=doc_model())
    )
    tool = FetchPaperTool(doc_models=FakeDocModels(), promotion=promotion, state=state)

    result = tool.invoke({"paper_id": "arxiv:2401.10001v1"}, CTX)

    assert result.ok
    assert promotion.calls == ["arxiv:2401.10001v1"]
    assert state.papers["arxiv:2401.10001v1"].scope == "fulltext"


def test_promotion_failure_is_a_normal_result_not_an_error():
    """실패가 예외면 루프가 깨진다 — 초록 범위로 계속하는 것이 설계다(BLM §4)."""
    state = LoopState(topic="q")
    state.discovered["arxiv:2401.10001v1"] = PaperHandle(
        "arxiv:2401.10001v1", "external:arxiv:2401.10001v1", PaperOrigin.EXTERNAL, abstract_text="a"
    )
    tool = FetchPaperTool(
        doc_models=FakeDocModels(),
        promotion=FakePromotion(PromotionResult(outcome=PromotionOutcome.LICENSE_BLOCKED)),
        state=state,
    )

    result = tool.invoke({"paper_id": "arxiv:2401.10001v1"}, CTX)

    assert result.ok
    assert state.papers["arxiv:2401.10001v1"].scope == "abstract"
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
    port = NoItems(items=[_raw_item(), _raw_item(quote="fabricated text not in the paper")])

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert result.content["accepted"] == 1
    assert result.content["rejected"] == 2  # 인용 1건 + 그 항목의 supporting 0
    assert len(state.accumulator.items) == 1


def test_extract_evidence_returns_reason_distribution_not_details():
    """INV-EV-5 — 어떤 인용이 왜 떨어졌는지는 내부에 둔다. 분포와 수리 지시만 준다."""
    state = _state_with_full_text()
    port = NoItems(items=[_raw_item(anchor="s9.nope")])

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert result.content["rejectedReasons"] == {"anchor_not_found": 1, "no_supporting": 1}
    assert "read_paper" in result.content["hint"]
    assert TABLE_ROW not in str(result.content)


def test_extract_evidence_marks_papers_as_examined():
    state = _state_with_full_text()
    state.discovered["p2"] = PaperHandle("p2", "r2", PaperOrigin.CORPUS, abstract_text="a")

    ExtractEvidenceTool(NoItems(), state).invoke({"paper_ids": ["p1", "p2"]}, CTX)

    assert state.examined == 2


def test_extract_evidence_reports_unknown_papers_without_failing():
    state = _state_with_full_text()

    result = ExtractEvidenceTool(NoItems(), state).invoke(
        {"paper_ids": ["p1", "ghost"]}, CTX
    )

    assert result.ok
    assert result.content["unknownPapers"] == ["ghost"]


def test_extraction_llm_failure_is_reported_as_a_tool_failure():
    state = _state_with_full_text()
    port = NoItems(error=LlmUnavailable("down"))

    result = ExtractEvidenceTool(port, state).invoke({"paper_ids": ["p1"]}, CTX)

    assert not result.ok
    assert "근거 추출 모델" in (result.error or "")


# --- 연도 제약(§2.5) — 인자이지 프롬프트 당부가 아니다 -------------------------------


def _corpus(hits=()):
    port = ScriptedSearch(hits=hits)
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


# --- 승격은 arXiv 논문만 가능하다 -----------------------------------------------


def test_a_non_arxiv_paper_never_reaches_the_promotion_queue():
    """`live_lookup`이 실어 오는 `doi:` 논문은 U1이 빌드할 수 없다. 막지 않으면 못 만드는
    잡이 큐에 들어가고 20초 폴링을 태운 뒤 timed_out으로 끝난다 — 결과는 "초록 범위로
    계속"으로 같지만 매 호출마다 큐 메시지와 20초가 나간다."""
    state = LoopState(topic="t")
    state.discovered["doi:10.1/x"] = PaperHandle(
        "doi:10.1/x", "external:doi:10.1/x", PaperOrigin.EXTERNAL, abstract_text="a"
    )
    promotion = FakePromotion(PromotionResult(outcome=PromotionOutcome.PROMOTED))
    tool = FetchPaperTool(doc_models=FakeDocModels(), promotion=promotion, state=state)

    result = tool.invoke({"paper_id": "doi:10.1/x"}, CTX)

    assert result.ok
    assert result.content["status"] == "abstract_only"
    assert promotion.calls == [], "빌드할 수 없는 논문이 승격 큐로 갔다"


def test_an_arxiv_paper_still_promotes():
    state = LoopState(topic="t")
    state.discovered["arxiv:2401.10001v1"] = PaperHandle(
        "arxiv:2401.10001v1", "external:arxiv:2401.10001v1", PaperOrigin.EXTERNAL
    )
    promotion = FakePromotion(PromotionResult(outcome=PromotionOutcome.TIMED_OUT))
    tool = FetchPaperTool(doc_models=FakeDocModels(), promotion=promotion, state=state)

    tool.invoke({"paper_id": "arxiv:2401.10001v1"}, CTX)

    assert promotion.calls == ["arxiv:2401.10001v1"]


# --- 실시간 조회가 통째로 죽은 턴 -------------------------------------------------


def test_a_total_lookup_failure_is_reported_to_the_screen():
    """**완전 실패야말로 화면이 밝혀야 하는 경우다.**

    부분 저하만 표시하고 전면 실패는 침묵하면 정확히 거꾸로다 — 조회가 통째로 죽은 턴이
    "그런 논문이 없다"로 보이고, 사용자는 "다시 물어보기" 대신 "주제 넓히기"를 한다
    (프론트 주석이 그 둘을 정반대 행동이라고 적어 뒀다). 계약 설명도 "셋 다 죽은 턴도
    true"라고 약속한다.
    """
    state = LoopState(topic="t")
    tool = LiveLookupTool(FakeLive(error=SearchUnavailable("all three down")), state)

    result = tool.invoke({"query": "x"}, CTX)

    assert result.ok is False
    assert state.live_lookup_degraded is True, "조회가 통째로 죽었는데 화면이 침묵한다"


def test_a_partial_degradation_is_reported_too():
    state = LoopState(topic="t")
    tool = LiveLookupTool(
        FakeLive(hits=(_candidate("arxiv:2401.1v2"),), degraded=("arxiv",)), state
    )

    result = tool.invoke({"query": "x"}, CTX)

    assert state.live_lookup_degraded is True
    assert result.content["degradedSources"] == ["arxiv"]


def test_a_healthy_lookup_leaves_the_flag_alone():
    state = LoopState(topic="t")
    tool = LiveLookupTool(FakeLive(hits=(_candidate("arxiv:2401.1v2"),)), state)

    tool.invoke({"query": "x"}, CTX)

    assert state.live_lookup_degraded is False


def test_the_year_note_no_longer_clobbers_the_plain_guidance():
    """노트를 쓰는 자리가 둘이면 하나가 다른 하나를 지운다 — 연도 제약이 걸린 검색에서
    "phrase 모드였다면 mode를 빼라"가 통째로 사라지고 있었다."""
    _port, tool = _corpus()

    plain = tool.invoke({"query": "x"}, CTX)
    with_year = tool.invoke({"query": "x", "year_from": 2023}, CTX)

    assert "phrase" in plain.content["note"], "기본 안내가 사라졌다"
    assert "연도 제약" in with_year.content["note"]
    assert "phrase" not in with_year.content["note"], "연도 사유가 안 실렸다"


def test_the_two_arxiv_judgements_see_the_same_string():
    """`promotable`은 다듬고 재는데 분해는 원본을 봤다 — 공백이 낀 id가 통과한 뒤
    `  2304.10557  v1`으로 조립돼 색인 잡의 `arxivRef`에 그대로 실렸다."""
    assert versioned_arxiv("  2304.10557  ") == "2304.10557v1"
    assert versioned_arxiv("arxiv:hep-th/9901001v2") == "hep-th/9901001v2"
    assert versioned_arxiv("doi:10.1145/abc") is None
