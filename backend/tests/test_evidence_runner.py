"""턴 실행 — 비용 게이트, 도구 조건부 등록, 루프→조립 연결."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

from backend.modules.evidence.models import TurnAbstainResult, TurnSuccessResult
from backend.modules.evidence.ports.llm import (
    ToolCallProposal,
)
from backend.modules.evidence.ports.sources import PaperCandidate
from backend.modules.evidence.runner import (
    ABSTAIN_COST_DEGRADED,
    EvidenceTurnRunner,
    RunnerDeps,
)
from backend.modules.evidence.testing import ScriptedLlm, run_context
from backend.tests.evidence_fakes import (
    TABLE_ROW,
    doc_model,
)

CTX = run_context()




class Extractor:
    def __init__(self, items=None) -> None:
        self.items = items or []

    def extract(self, *, topic, focus, papers):
        return self.items


class Search:
    def __init__(self, hits=()) -> None:
        self.hits = hits
        self.years: list[Any] = []

    def search(self, query, *, phrase=False, years=None):
        self.years.append(years)
        return self.hits


class DocModels:
    def __init__(self) -> None:
        self.reads: list[str] = []

    def get_doc_model(self, paper_id):
        self.reads.append(paper_id)
        return doc_model()


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
    """호출을 시작한 뒤 중단하면 이미 지출한 뒤다(BR-EV-7). 판정 권위는 U6 cost_guard 하나다."""
    from types import SimpleNamespace

    class _CriticalGuard:
        def get_budget_state(self):
            return SimpleNamespace(tier="critical", degrade_mode="normal", circuit_state="closed")

    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor(), cost_guard=_CriticalGuard())
    )

    result = runner.run(CTX, _request())

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
            live_lookup=Search(),
            doc_models=DocModels(),
            assets=object(),
        )
    )

    runner.run(CTX, _request())

    assert llm.seen_tools[0] == {
        "corpus_search", "live_lookup", "fetch_paper",
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
        doc_model=doc_model(), text="",
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


def test_explicit_scope_never_exposes_search_tools():
    """BR-EV-2/PBT-EV-4 — 명시 집합만 사용, 자동 검색 금지는 구조로 강제된다.

    v1의 격리는 오케스트레이터 분기였고 삭제와 함께 사라졌었다(리뷰 지적).
    """
    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm,
            extractor=Extractor(),
            corpus_search=Search(),
            live_lookup=Search(),
            doc_models=DocModels(),
        )
    )

    runner.run(CTX, _request(scope="explicit", paperIds=["2401.00001"]))

    assert "corpus_search" not in llm.seen_tools[0]
    assert "live_lookup" not in llm.seen_tools[0]
    # 명시 논문의 본문 확보·추출 경로는 열려 있다.
    assert {"fetch_paper", "read_paper", "extract_evidence"} <= llm.seen_tools[0]


def test_auto_scope_keeps_search_tools():
    llm = ScriptedLlm([])
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor(), corpus_search=Search())
    )

    runner.run(CTX, _request())

    assert "corpus_search" in llm.seen_tools[0]


def test_auto_scope_ignores_explicit_paper_ids():
    """계약대로 auto에서는 paperIds를 무시한다(schema 설명 + BR-EV-2).

    씨앗으로 올리면 사용자가 고르지도 않은 논문이 확인 대상 수치에 섞인다.
    """
    llm = ScriptedLlm([ToolCallProposal("fetch_paper", {"paper_id": "2401.00001"})])
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm, extractor=Extractor(), corpus_search=Search(), doc_models=DocModels()
        )
    )

    runner.run(CTX, _request(paperIds=["2401.00001"]))

    # 씨앗이 없으므로 fetch_paper는 "모르는 논문"으로 실패한다 — 검색으로 찾아야 한다.
    assert "corpus_search" in llm.seen_tools[0]


def test_explicit_scope_rejects_private_namespace_paper_ids():
    """업로드 문서(`userdoc:`)는 코퍼스 id로 위장해 들어올 수 없다.

    첨부는 소유권이 확인되는 경로(_seed_attachments)로만 근거 대상이 된다 —
    호출자가 준 id를 그대로 코퍼스 논문으로 올리면 그 경로를 우회하게 된다.
    """
    llm = ScriptedLlm([ToolCallProposal("fetch_paper", {"paper_id": "userdoc:victim"})])
    docs = DocModels()
    runner = EvidenceTurnRunner(
        RunnerDeps(llm=llm, extractor=Extractor(), doc_models=docs)
    )

    runner.run(CTX, _request(scope="explicit", paperIds=["userdoc:victim"]))

    # 씨앗이 안 올라갔으므로 doc-model 저장소를 건드리지 않는다.
    assert docs.reads == []


# --- 중첩 evidence는 판단을 끄고 돈다(novelty 잡) --------------------------------


def test_a_runner_without_an_answer_port_never_writes_an_answer_trace_row():
    """novelty는 evidence를 도구처럼 부르므로 `build_evidence_runner(with_answer=False)`로
    조립한다 — 중첩 턴에서 판단 산문을 또 쓰면 그 비용이 잡 예산을 먹고, novelty는 그것을
    읽지도 않는다(claims만 쓴다).

    조립 함수는 실 어댑터(S3·OpenSearch·Bedrock)를 만들어 단위 테스트를 못 붙인다. 대신
    그 플래그가 만들어내는 **관측 가능한 결과**를 고정한다: `answer` 포트가 없으면 트레이스에
    `answer` 행이 없고 답은 결정론 이어붙이기로 나간다.
    """
    hits = (PaperCandidate("p1", "p1", "AlphaFold"),)
    llm = ScriptedLlm([
        ToolCallProposal("corpus_search", {"query": "protein"}),
        ToolCallProposal("fetch_paper", {"paper_id": "p1"}),
        ToolCallProposal("extract_evidence", {"paper_ids": ["p1"]}),
    ])
    trace: list = []
    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=llm,
            extractor=Extractor([_raw_item()]),
            answer=None,  # = build_evidence_runner(with_answer=False)
            corpus_search=Search(hits),
            doc_models=DocModels(),
        )
    )

    result = runner.run(CTX, _request(), on_trace=trace.append)

    assert isinstance(result, TurnSuccessResult)
    assert [r.tool for r in trace if r.tool == "answer"] == [], "중첩 턴이 판단을 불렀다"
    # 답은 나간다 — 판단만 없다(§4.3 fail-closed의 정상 경로).
    assert result.outcome.answer is not None
    assert result.outcome.answer.checks.fallback is True
