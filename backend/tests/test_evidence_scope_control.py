"""US-EV3(#267) — scope 제어 기준(criteria) 테스트 (QA 2026-07 IMPL-partial-tests 해소).

- AC1 explicit: paperIds 명시 시 그 집합만으로 근거를 형성하고 자동 검색(임베딩·k-NN·BM25)은
  절대 호출되지 않는다(BR-EV-2). 자동 검색 포트는 호출 즉시 AssertionError를 던지는 spy로
  배선해 "호출되지 않음" 자체를 강제한다.
- AC2 mixed: 명시 집합과 자동 검색 결과를 병합해 근거 형성 대상으로 삼는다.

실제 EvidencePaperSearchTool을 fake/spy 포트로 배선해 orchestrator 레벨(수용 기준)과
tool 레벨(계약) 양쪽에서 고정한다 — 모듈 관례(test_evidence.py의 _Spy*/_NoToolAllowed)와 동일.
"""

from __future__ import annotations

from types import SimpleNamespace

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceItem,
    EvidenceRequest,
    EvidenceScope,
    SourceRef,
)

from backend.modules.evidence.assembler import EvidenceComparisonAssembler
from backend.modules.evidence.models import (
    AgentRunContext,
    EvidenceSession,
    EvidenceTurn,
    TurnSuccessResult,
)
from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator
from backend.modules.evidence.tools import EvidencePaperSearchTool


def _record(paper_id: str):
    """IndexRecord 스탠드인 — retriever(RRF)는 paperId, orchestrator는 arxivId를 읽는다."""
    return SimpleNamespace(
        paperId=paper_id, arxivId=paper_id, title=f'title {paper_id}', abstract=''
    )


def _doc_model(paper_id: str):
    return SimpleNamespace(
        fullText=f'full text of {paper_id}',
        sections=[],
        meta=SimpleNamespace(title=paper_id),
    )


class _ForbiddenAutoSearch:
    """explicit scope에서 자동 검색 계열 포트가 호출되면 그 자체로 테스트 실패."""

    def __init__(self, port: str) -> None:
        self._port = port

    def _forbid(self, method: str):
        raise AssertionError(
            f'auto-search must not run in explicit scope: {self._port}.{method} was called'
        )

    def embed_query(self, *args, **kwargs):
        self._forbid('embed_query')

    def knn_search(self, *args, **kwargs):
        self._forbid('knn_search')

    def bm25_search(self, *args, **kwargs):
        self._forbid('bm25_search')

    def phrase_search(self, *args, **kwargs):
        self._forbid('phrase_search')


class _SpyPaperLookup:
    def __init__(self, records: dict[str, object]) -> None:
        self._records = records
        self.requested: list[str] = []

    def fetch_paper(self, paper_id: str):
        self.requested.append(paper_id)
        return self._records.get(paper_id)


class _StubDocModelTool:
    def get_doc_model(self, paper_id: str, version=None):
        return _doc_model(paper_id)


class _GroundedExtractor:
    """추출 포트 fake — 받은 문서 집합을 기록하고 논문당 grounded 항목 1개를 돌려준다."""

    def __init__(self) -> None:
        self.doc_models: list | None = None

    def extract(self, topic: str, doc_models: list) -> list[EvidenceItem]:
        self.doc_models = doc_models
        return [
            EvidenceItem(
                statement=f'statement from {paper_id}',
                supporting=[
                    SourceRef(
                        paperId=paper_id,
                        recordRef=paper_id,
                        quote=f'full text of {paper_id}',
                    )
                ],
                conflicting=[],
            )
            for paper_id, *_ in doc_models
        ]


def _ctx(request: EvidenceRequest) -> AgentRunContext:
    session = EvidenceSession(owner_id='owner-1')
    return AgentRunContext(
        session=session,
        current_turn=EvidenceTurn(session_id=session.session_id, request=request),
        owner_id='owner-1',
        request_id='req-1',
        budget_signal={'state': 'ok'},
    )


def _explicit_search_tool(lookup: _SpyPaperLookup) -> EvidencePaperSearchTool:
    return EvidencePaperSearchTool(
        embedding=_ForbiddenAutoSearch('embedding'),
        vector_store=_ForbiddenAutoSearch('vector_store'),
        lexical_index=_ForbiddenAutoSearch('lexical_index'),
        paper_lookup=lookup,
    )


def _orchestrator(
    search_tool: EvidencePaperSearchTool, extractor: _GroundedExtractor
) -> EvidenceAgentOrchestrator:
    return EvidenceAgentOrchestrator(
        search_tool=search_tool,
        doc_model_tool=_StubDocModelTool(),
        extractor=extractor,
        assembler=EvidenceComparisonAssembler(),
    )


# ---------------------------------------------------------------------------
# AC1 — explicit scope: 지정 집합만 사용, 자동 검색 미호출
# ---------------------------------------------------------------------------

def test_explicit_scope_forms_evidence_only_from_supplied_set_without_auto_search() -> None:
    lookup = _SpyPaperLookup(
        {'2401.00001': _record('2401.00001'), '2401.00002': _record('2401.00002')}
    )
    extractor = _GroundedExtractor()
    orchestrator = _orchestrator(_explicit_search_tool(lookup), extractor)
    request = EvidenceRequest(
        topic='transformer attention efficiency',
        scope='explicit',
        paperIds=['2401.00001', '2401.00002'],
    )

    result = orchestrator.run(_ctx(request), request)

    # 자동 검색 포트는 _ForbiddenAutoSearch라 호출됐다면 이미 실패했다 — 여기 도달 자체가
    # "auto-search 미호출" 검증. 명시 집합은 corpus lookup으로만 해석된다.
    assert lookup.requested == ['2401.00001', '2401.00002']
    assert extractor.doc_models is not None
    assert [source[0] for source in extractor.doc_models] == ['2401.00001', '2401.00002']
    assert isinstance(result, TurnSuccessResult)
    cited = {
        ref.paperId
        for item in result.outcome.claims
        for ref in (*item.supporting, *item.conflicting)
    }
    assert cited == {'2401.00001', '2401.00002'}  # 근거는 지정 집합 밖을 인용하지 않는다
    # INV-EV-5: explicit scope은 내부 검색 쿼리를 노출하지 않는다
    assert result.outcome.coverage.queryUsed is None
    assert result.outcome.coverage.paperCount == 2


def test_explicit_scope_search_tool_returns_lookup_records_and_no_query() -> None:
    lookup = _SpyPaperLookup({'2401.00001': _record('2401.00001')})
    tool = _explicit_search_tool(lookup)

    result = tool.search(
        topic='transformer attention', scope=EvidenceScope.explicit, paper_ids=['2401.00001']
    )

    assert [r.paperId for r in result.records] == ['2401.00001']
    assert result.query_used is None
    assert result.scope == EvidenceScope.explicit


# ---------------------------------------------------------------------------
# AC2 — mixed scope: 명시 집합 + 자동 검색 결과 병합
# ---------------------------------------------------------------------------

class _FakeEmbedding:
    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class _FakeVectorStore:
    def __init__(self, records: list) -> None:
        self._records = records

    def knn_search(self, vector, top_k, abstract_only=False):
        return [(record, 0.9) for record in self._records]


class _FakeLexicalIndex:
    def __init__(self, records: list) -> None:
        self._records = records

    def bm25_search(self, terms, top_k, fields=('title', 'abstract', 'lexicalTerms')):
        return [(record, 7.0) for record in self._records]

    def phrase_search(self, phrase, top_k, paper_ids=None):
        return []


def _mixed_search_tool(auto_records: list, lookup: _SpyPaperLookup) -> EvidencePaperSearchTool:
    return EvidencePaperSearchTool(
        embedding=_FakeEmbedding(),
        vector_store=_FakeVectorStore(auto_records),
        lexical_index=_FakeLexicalIndex(auto_records),
        paper_lookup=lookup,
    )


def test_mixed_scope_merges_explicit_set_with_auto_search_results() -> None:
    auto_record = _record('2401.11111')
    lookup = _SpyPaperLookup({'2401.22222': _record('2401.22222')})
    extractor = _GroundedExtractor()
    orchestrator = _orchestrator(_mixed_search_tool([auto_record], lookup), extractor)
    request = EvidenceRequest(
        topic='retrieval augmented generation', scope='mixed', paperIds=['2401.22222']
    )

    result = orchestrator.run(_ctx(request), request)

    assert extractor.doc_models is not None
    merged_ids = {source[0] for source in extractor.doc_models}
    assert merged_ids == {'2401.11111', '2401.22222'}  # 자동 검색 + 명시 집합 병합
    assert lookup.requested == ['2401.22222']
    assert isinstance(result, TurnSuccessResult)
    assert result.outcome.coverage.paperCount == 2
    # mixed scope은 자동 검색이 실제로 수행됐음을 coverage로 드러낸다(explicit과 대비)
    assert result.outcome.coverage.queryUsed == 'retrieval augmented generation'


def test_mixed_scope_deduplicates_explicit_paper_already_found_by_auto_search() -> None:
    auto_record = _record('2401.11111')
    lookup = _SpyPaperLookup({})
    tool = _mixed_search_tool([auto_record], lookup)

    result = tool.search(
        topic='retrieval augmented generation',
        scope=EvidenceScope.mixed,
        paper_ids=['2401.11111'],  # 자동 검색 결과에 이미 존재
    )

    assert [r.paperId for r in result.records] == ['2401.11111']  # 병합해도 논문은 1건
    assert lookup.requested == []  # 이미 병합돼 있으므로 corpus lookup을 다시 하지 않는다
    assert result.scope == EvidenceScope.mixed
