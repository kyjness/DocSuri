from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

from backend.modules.evidence.assembler import EvidenceComparisonAssembler
from backend.modules.evidence.models import (
    AgentRunContext,
    EvidenceSession,
    EvidenceTurn,
    LiteralMatch,
    LiteralSearchResult,
    TurnAbstainResult,
    TurnSuccessResult,
)
from backend.modules.evidence.orchestrator import EvidenceAgentOrchestrator
from backend.modules.evidence.tools import EvidencePaperSearchTool, PaperSearchUnavailable


def _ctx(
    topic: str, prior_paper_ids: tuple[str, ...] = ()
) -> tuple[AgentRunContext, EvidenceRequest]:
    request = EvidenceRequest(topic=topic, scope='auto', paperIds=[])
    session = EvidenceSession(owner_id='owner-1')
    turn = EvidenceTurn(session_id=session.session_id, request=request)
    ctx = AgentRunContext(
        session=session,
        current_turn=turn,
        owner_id='owner-1',
        request_id='req-1',
        budget_signal={'state': 'ok'},
        prior_paper_ids=prior_paper_ids,
    )
    return ctx, request


class _NoToolAllowed:
    """비교 경로(DocModel/LLM)로는 절대 못 들어간다 — 속성 접근 자체가 실패."""

    def __getattr__(self, name: str):
        raise AssertionError(f'literal path must not touch comparison tools ({name})')


class _StubLiteralSearch:
    def __init__(self, result: LiteralSearchResult) -> None:
        self._result = result
        self.calls: list[tuple[str, tuple[str, ...] | None]] = []

    def literal_search(self, phrase: str, paper_ids=None):
        self.calls.append((phrase, tuple(paper_ids) if paper_ids else None))
        return self._result


def _orchestrator(search_tool) -> EvidenceAgentOrchestrator:
    return EvidenceAgentOrchestrator(
        search_tool=search_tool,
        doc_model_tool=_NoToolAllowed(),
        extractor=_NoToolAllowed(),
        assembler=EvidenceComparisonAssembler(),
    )


def test_literal_quote_topic_bypasses_llm_and_returns_matches() -> None:
    topic = '"self-attention reduces computation" 라는 문장이 있는 논문 찾아줘'
    result = LiteralSearchResult(
        phrase='self-attention reduces computation',
        matches=(
            LiteralMatch(
                paper_id='2001.00001', anchor='s3.p2',
                quote='... self-attention reduces computation ...',
            ),
            LiteralMatch(
                paper_id='2001.00002', anchor='s2.p1',
                quote='... self-attention reduces computation ...',
            ),
        ),
    )
    search = _StubLiteralSearch(result)
    ctx, request = _ctx(topic)

    outcome = _orchestrator(search).run(ctx, request)

    assert isinstance(outcome, TurnSuccessResult)
    assert outcome.resolved_paper_ids == ('2001.00001', '2001.00002')
    assert outcome.outcome.claims[0].supporting[0].paperId == '2001.00001'
    assert outcome.outcome.claims[0].supporting[0].anchor == 's3.p2'
    assert outcome.outcome.answer is not None
    assert '2001.00001' in outcome.outcome.answer


def test_literal_quote_topic_abstains_when_no_matches() -> None:
    topic = '"완전히 없는 문장입니다" 라는 문장이 있는 논문 찾아줘'
    search = _StubLiteralSearch(LiteralSearchResult(phrase='완전히 없는 문장입니다', matches=()))
    ctx, request = _ctx(topic)

    outcome = _orchestrator(search).run(ctx, request)

    assert isinstance(outcome, TurnAbstainResult)
    assert outcome.outcome.abstainReason == 'out_of_corpus'


def test_literal_quote_topic_abstains_when_index_unavailable() -> None:
    class _Failing:
        def literal_search(self, phrase, paper_ids=None):
            raise PaperSearchUnavailable('down')

    topic = '"anything" 라는 문장이 있는 논문 찾아줘'
    ctx, request = _ctx(topic)

    outcome = _orchestrator(_Failing()).run(ctx, request)

    assert isinstance(outcome, TurnAbstainResult)
    assert outcome.outcome.abstainReason == 'out_of_corpus'


def test_followup_narrowing_restricts_literal_search_to_prior_papers() -> None:
    topic = '그 중에서 "self-attention" 문장이 있는 논문만 다시 보여줘'
    result = LiteralSearchResult(
        phrase='self-attention',
        matches=(
            LiteralMatch(paper_id='2001.00001', anchor='s3.p2', quote='... self-attention ...'),
        ),
    )
    search = _StubLiteralSearch(result)
    ctx, request = _ctx(topic, prior_paper_ids=('2001.00001', '2001.00002'))

    _orchestrator(search).run(ctx, request)

    assert search.calls == [('self-attention', ('2001.00001', '2001.00002'))]


def test_assemble_literal_answer_lists_papers() -> None:
    result = LiteralSearchResult(
        phrase='self-attention reduces computation',
        matches=(
            LiteralMatch(paper_id='2001.00001', anchor='s3.p2', quote='q1'),
            LiteralMatch(paper_id='2001.00002', anchor=None, quote='q2'),
        ),
    )
    outcome = EvidenceComparisonAssembler().assemble_literal(result)

    assert outcome.coverage.paperCount == 2
    assert outcome.answer is not None
    assert '2편' in outcome.answer


class _CapturingLexicalIndex:
    """phrase_search에 넘어온 paper_ids를 기록하고, 초록에만 문구가 있는 레코드를 돌려준다."""

    def __init__(self, records: list) -> None:
        self._records = records
        self.received_paper_ids: list = []

    def phrase_search(self, phrase, top_k, paper_ids=None):
        self.received_paper_ids.append(paper_ids)
        return [(r, 1.0) for r in self._records]


def _abstract_only_record(arxiv_id: str, paper_id: str, phrase: str):
    from types import SimpleNamespace

    # lexicalTerms 빈 초록 청크(index_record 계약) — 문구는 abstract 필드에만 있다.
    return SimpleNamespace(
        arxivId=arxiv_id,
        paperId=paper_id,
        abstract=f'We show that {phrase} in the linear regime.',
        lexicalTerms='',
        blockRefs=[{'blockId': 's1.p1'}],
    )


def test_literal_search_strips_version_before_paperid_filter_and_reads_abstract() -> None:
    phrase = 'self-attention reduces computation'
    idx = _CapturingLexicalIndex([_abstract_only_record('2001.00001v2', '2001.00001', phrase)])
    tool = EvidencePaperSearchTool(
        embedding=object(), vector_store=object(), lexical_index=idx, paper_lookup=object()
    )

    result = tool.literal_search(phrase, paper_ids=['2001.00001v2', 'hep-th/9901001v3'])

    # 좁히기 필터에는 bare id가 넘어가야 색인 paperId(version-less)와 매칭된다.
    assert idx.received_paper_ids == [['2001.00001', 'hep-th/9901001']]
    # 초록 필드에만 있는 문구도 quote로 잡힌다(lexicalTerms 빈 청크여도).
    assert len(result.matches) == 1
    assert phrase in result.matches[0].quote
    assert result.matches[0].anchor == 's1.p1'
    # 반환 id는 evidence 관례대로 버전 붙은 arxivId 유지(표시·다음 턴 연결용).
    assert result.matches[0].paper_id == '2001.00001v2'
