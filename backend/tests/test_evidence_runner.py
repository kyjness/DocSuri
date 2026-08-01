"""턴 실행 — 비용 게이트, 도구 조건부 등록, 루프→조립 연결."""

from __future__ import annotations

from types import SimpleNamespace

from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

from backend.modules.evidence.domain.models import AgentRunContext
from backend.modules.evidence.models import TurnAbstainResult, TurnSuccessResult
from backend.modules.evidence.ports.llm import (
    LlmDecision,
    TerminationProposal,
    ToolCallProposal,
)
from backend.modules.evidence.ports.sources import PaperCandidate
from backend.modules.evidence.runner import (
    ABSTAIN_COST_DEGRADED,
    EvidenceTurnRunner,
    RunnerDeps,
)

CTX = AgentRunContext(owner_id="o1", session_id="s1", turn_id="t1")
TABLE_ROW = "AlphaFold2 | 92.4 | 87.0"


def _doc_model() -> SimpleNamespace:
    table = SimpleNamespace(
        id="s4.tbl1", type="table", anchorLabel="Table 1", caption="Results",
        rows=[
            SimpleNamespace(
                cells=[SimpleNamespace(text=c) for c in ("AlphaFold2", "92.4", "87.0")]
            )
        ],
    )
    return SimpleNamespace(
        sections=[SimpleNamespace(id="s1", title="Intro", blocks=[table], sections=[])]
    )


class ScriptedLlm:
    def __init__(self, script) -> None:
        self.script = list(script)
        self.seen_tools: list[frozenset[str]] = []

    def decide(self, observation, tools):
        self.seen_tools.append(frozenset(spec.name for spec in tools))
        if not self.script:
            return LlmDecision(proposal=TerminationProposal())
        return LlmDecision(proposal=self.script.pop(0))


class Extractor:
    def __init__(self, items=None) -> None:
        self.items = items or []

    def extract(self, *, topic, focus, papers):
        return self.items


class Search:
    def __init__(self, hits=()) -> None:
        self.hits = hits

    def search(self, query, *, phrase=False):
        return self.hits


class DocModels:
    def get_doc_model(self, paper_id):
        return _doc_model()


def _request(topic="단백질 구조 예측", **kw) -> EvidenceRequest:
    return EvidenceRequest(topic=topic, **kw)


def _raw_item() -> dict:
    return {
        "statement": "AlphaFold2 reaches 92.4 GDT",
        "supporting": [
            {"paperId": "p1", "anchor": "s4.tbl1", "quote": TABLE_ROW, "sourceScope": "fulltext"}
        ],
        "conflicting": [],
    }


def test_cost_degraded_abstains_before_the_loop_starts():
    """호출을 시작한 뒤 중단하면 이미 지출한 뒤다(BR-EV-7)."""
    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(RunnerDeps(llm=llm, extractor=Extractor()))

    result = runner.run(CTX, _request(), budget_signal={"state": "degraded"})

    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == ABSTAIN_COST_DEGRADED
    assert llm.seen_tools == []  # 루프가 아예 돌지 않았다


def test_only_configured_tools_are_registered():
    """설정이 없는 도구는 목록에서 자연히 빠진다(logical-components §4)."""
    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor(), corpus_search=Search())
    )

    runner.run(CTX, _request())

    assert llm.seen_tools[0] == {"corpus_search", "extract_evidence"}


def test_full_wiring_exposes_all_six_tools():
    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm,
            extractor=Extractor(),
            corpus_search=Search(),
            external_search=Search(),
            doc_models=DocModels(),
            assets=object(),
        )
    )

    runner.run(CTX, _request())

    assert llm.seen_tools[0] == {
        "corpus_search", "external_search", "fetch_paper",
        "read_paper", "view_figure", "extract_evidence",
    }


def test_search_then_fetch_then_extract_produces_a_grounded_result():
    """루프 한 바퀴가 근거표까지 이어진다."""
    hits = (PaperCandidate(paper_id="p1", record_ref="r1", title="AlphaFold2", abstract="a"),)
    llm = ScriptedLlm([
        ToolCallProposal("corpus_search", {"query": "protein"}),
        ToolCallProposal("fetch_paper", {"paper_id": "p1"}),
        ToolCallProposal("extract_evidence", {"paper_ids": ["p1"]}),
    ])
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm,
            extractor=Extractor([_raw_item()]),
            corpus_search=Search(hits),
            doc_models=DocModels(),
        )
    )

    result = runner.run(CTX, _request())

    assert isinstance(result, TurnSuccessResult)
    assert len(result.outcome.claims) == 1
    ref = result.outcome.claims[0].supporting[0]
    assert ref.anchorType.value == "table"
    assert ref.sourceScope.value == "fulltext"
    assert result.resolved_paper_ids == ("p1",)


def test_result_carries_the_examined_range():
    hits = tuple(
        PaperCandidate(paper_id=f"p{i}", record_ref=f"r{i}", title="t", abstract="a")
        for i in range(4)
    )
    llm = ScriptedLlm([
        ToolCallProposal("corpus_search", {"query": "q"}),
        ToolCallProposal("fetch_paper", {"paper_id": "p1"}),
        ToolCallProposal("extract_evidence", {"paper_ids": ["p1"]}),
    ])
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm,
            extractor=Extractor([_raw_item_for("p1")]),
            corpus_search=Search(hits),
            doc_models=DocModels(),
        )
    )

    result = runner.run(CTX, _request())

    assert result.outcome.coverage.examined == 1
    assert result.outcome.coverage.candidates == 4


def _raw_item_for(paper_id: str) -> dict:
    item = _raw_item()
    item["supporting"][0]["paperId"] = paper_id
    return item


def test_no_evidence_abstains_rather_than_returning_an_empty_table():
    """INV-EV-2 — 빈 성공 금지."""
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=ScriptedLlm([]), extractor=Extractor(), corpus_search=Search())
    )

    result = runner.run(CTX, _request())

    assert isinstance(result, TurnAbstainResult)
    assert result.outcome.abstainReason == "out_of_corpus"


def test_attachments_are_examined_without_a_search():
    attachment = SimpleNamespace(
        paper_id="userdoc:abc", record_ref="upload:o1:s1:a1", name="my.md",
        doc_model=_doc_model(), text="",
    )
    llm = ScriptedLlm([ToolCallProposal("extract_evidence", {"paper_ids": ["userdoc:abc"]})])
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor([_raw_item_for("userdoc:abc")]))
    )

    result = runner.run(CTX, _request(), attachments=(attachment,))

    assert isinstance(result, TurnSuccessResult)
    assert result.outcome.claims[0].supporting[0].paperId == "userdoc:abc"


def test_trace_sink_receives_every_executed_call():
    seen = []
    llm = ScriptedLlm([ToolCallProposal("corpus_search", {"query": "q"})])
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor(), corpus_search=Search())
    )

    runner.run(CTX, _request(), on_trace=seen.append)

    assert [r.tool for r in seen] == ["corpus_search"]
