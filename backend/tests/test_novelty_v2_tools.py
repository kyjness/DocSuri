"""corpus_search·form_evidence 도구 어댑터 계약 + Notion 레지스트리 부재(BR-RA12)."""

from __future__ import annotations

from backend.modules.novelty.adapters.corpus import CorpusSearchTool
from backend.modules.novelty.adapters.evidence import FormEvidenceTool
from backend.modules.novelty.adapters.external.datasets import DatasetSearchTool
from backend.modules.novelty.adapters.external.github import GithubSearchTool
from backend.modules.novelty.domain.gate import evaluate_artifact
from backend.modules.novelty.domain.models import ArtifactKind
from backend.modules.novelty.ports.tools import ToolContext, ToolRegistry

_CTX = ToolContext(owner_id="o1", job_id="j1")


def _page_response(cards: list[dict], degraded: bool = False):
    from docsuri_shared._generated.dtos.search_schema import (
        ResultCardVM,
        ResultMeta,
        SearchResponse,
        SearchResultPageDTO,
    )

    page = SearchResultPageDTO(
        cards=[ResultCardVM(**card) for card in cards],
        meta=ResultMeta(resultCount=len(cards), degraded=degraded),
    )
    return SearchResponse(root=page)


def _card(arxiv_id: str = "2401.00001") -> dict:
    return {
        "title": "Sparse retrieval under DP",
        "authors": ["A. Researcher"],
        "year": 2024,
        "arxivId": arxiv_id,
        "abstractSnippet": "…",
        "relevance": "high",
        "arxivUrl": f"https://arxiv.org/abs/{arxiv_id}",
    }


def test_corpus_tool_exposes_record_refs_for_gate() -> None:
    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: _page_response([_card()]),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    assert result.ok is True
    assert result.record_refs == ("2401.00001",)
    assert result.content["items"][0]["sourceName"] == "arXiv"


def test_corpus_tool_abstain_and_validation_paths() -> None:
    from docsuri_shared._generated.dtos.search_schema import AbstainDTO, SearchResponse

    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: SearchResponse(root=AbstainDTO(reason="out_of_corpus")),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    assert result.ok is True and result.content["items"] == []
    assert tool.invoke({"query": "  "}, _CTX).ok is False


class _FakeEvidencePort:
    def __init__(self, result) -> None:
        self._result = result

    async def form_evidence(self, request, ctx):
        return self._result


def _evidence_result():
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
        SourceRef,
    )

    return EvidenceResult(
        state="ok",
        claims=[
            EvidenceItem(
                statement="DP retrieval degrades nDCG modestly",
                supporting=[
                    SourceRef(paperId="2401.00001", recordRef="rec:2401.00001", quote="…")
                ],
                conflicting=[],
            )
        ],
        coverage=EvidenceCoverage(paperCount=1, queryUsed="dp retrieval"),
    )


def test_form_evidence_snapshot_passes_gate_and_exposes_refs() -> None:
    tool = FormEvidenceTool(_FakeEvidencePort(_evidence_result()))
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is True
    assert result.record_refs == ("rec:2401.00001",)
    snapshot = result.content["evidence"]
    # 루프 자동 보존 경로와 동일 — 스냅샷은 게이트를 통과해야 한다.
    assert evaluate_artifact(
        ArtifactKind.EVIDENCE, snapshot, frozenset(result.record_refs)
    ) is None


def test_form_evidence_abstain_is_a_result_not_error() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult

    tool = FormEvidenceTool(
        _FakeEvidencePort(EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus"))
    )
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is True
    assert result.content["evidence"]["state"] == "abstain"
    assert evaluate_artifact(
        ArtifactKind.EVIDENCE, result.content["evidence"], frozenset()
    ) is None


def test_form_evidence_engine_failure_returned_as_error() -> None:
    class _DownPort:
        async def form_evidence(self, request, ctx):
            raise RuntimeError("engine down")

    tool = FormEvidenceTool(_DownPort())
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is False
    assert "unavailable" in (result.error or "")


def test_no_buildable_registry_contains_notion() -> None:
    # BR-RA12 — 도구 레지스트리 어디에도 Notion이 없다(구성 가능한 전체 도구 대상).
    registry = ToolRegistry()

    class _Stub:
        def __init__(self, spec):
            self.spec = spec

        def invoke(self, args, ctx):
            raise NotImplementedError

    for tool_cls in (GithubSearchTool, DatasetSearchTool, CorpusSearchTool, FormEvidenceTool):
        registry.register(_Stub(tool_cls.spec))
    assert all("notion" not in name.lower() for name in registry.names())


def test_corpus_cards_carry_the_record_ref_key_the_gate_requires() -> None:
    """카드가 게이트가 요구하는 이름(recordRef)으로 값을 실어야 한다.

    arxivId가 곧 실재성 핸들이지만 카드에 `arxivId`로만 보이면, 모델은 그것을
    source_refs[].recordRef에 넣어야 한다는 걸 알 방법이 없다 — 로컬 실스택
    검증에서 실제로 산출물마다 unknown_source_ref로 거부돼 필수 세트가 완성되지
    않았다. 데이터가 스스로 계약을 담아야 프롬프트 설명에만 기대지 않는다.
    """
    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: _page_response([_card("2401.09999")]),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    card = result.content["items"][0]
    assert card["recordRef"] == "2401.09999"
    # 게이트가 대조하는 집합과 카드에 보이는 값이 같아야 한다.
    assert card["recordRef"] in result.record_refs
