from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import EvidenceItem, SourceRef

from backend.modules.evidence.assembler import EvidenceComparisonAssembler
from backend.modules.evidence.models import PaperSearchResult


def test_assemble_builds_narrative_from_grounded_statements() -> None:
    items = [
        EvidenceItem(
            statement='self-attention is O(1) sequential operations',
            supporting=[
                SourceRef(paperId='2001.00001', recordRef='2001.00001', quote='q1'),
            ],
            conflicting=[
                SourceRef(paperId='2001.00002', recordRef='2001.00002', quote='q2'),
            ],
        ),
    ]
    search_result = PaperSearchResult(records=(), query_used='self-attention', scope='auto')

    outcome = EvidenceComparisonAssembler().assemble(items, search_result, paper_count=2)

    assert outcome.answer is not None
    assert '2001.00001' in outcome.answer
    assert '2001.00002' in outcome.answer
    # C-2: narrative는 claims의 statement/paperId만 재조합 — 새 사실이 없다.
    assert 'self-attention is O(1) sequential operations' in outcome.answer


def test_assemble_returns_none_answer_for_empty_claims() -> None:
    search_result = PaperSearchResult(records=(), query_used='q', scope='auto')

    outcome = EvidenceComparisonAssembler().assemble([], search_result, paper_count=0)

    assert outcome.answer is None
