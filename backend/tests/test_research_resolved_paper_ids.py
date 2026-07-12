from __future__ import annotations

import asyncio

from docsuri_shared._generated.dtos.evidence_schema import EvidenceCoverage, EvidenceResult

from backend.modules.evidence.models import TurnSuccessResult
from backend.modules.research.models import ResearchChatRequest
from backend.modules.research.repository import InMemoryResearchRepository
from backend.modules.research.service import ResearchService


class _StubOrchestrator:
    """호출될 때마다 다른 결과를 순서대로 반환하고, 이번 턴에 전달된 ctx를 기록한다."""

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.contexts: list = []

    def run(self, ctx, request):
        self.contexts.append(ctx)
        return self._results.pop(0)


def _success(resolved: tuple[str, ...]) -> TurnSuccessResult:
    return TurnSuccessResult(
        outcome=EvidenceResult(
            state='ok', claims=[], coverage=EvidenceCoverage(paperCount=len(resolved))
        ),
        resolved_paper_ids=resolved,
    )


def test_resolved_paper_ids_persist_on_assistant_message() -> None:
    repo = InMemoryResearchRepository()
    orchestrator = _StubOrchestrator([_success(('2001.00001', '2001.00002'))])
    service = ResearchService(repo)

    response = asyncio.run(
        service.create_job(
            'owner-1',
            ResearchChatRequest(content='self-attention 문장이 있는 논문 찾아줘'),
            orchestrator,
        )
    )

    messages = service.list_messages('owner-1', response.jobId).messages
    assistant = [m for m in messages if m.role == 'assistant'][0]
    assert assistant.resolvedPaperIds == ['2001.00001', '2001.00002']


def test_followup_turn_receives_prior_resolved_paper_ids_in_context() -> None:
    repo = InMemoryResearchRepository()
    orchestrator = _StubOrchestrator(
        [_success(('2001.00001', '2001.00002')), _success(())]
    )
    service = ResearchService(repo)

    created = asyncio.run(
        service.create_job(
            'owner-1',
            ResearchChatRequest(content='self-attention 문장이 있는 논문 찾아줘'),
            orchestrator,
        )
    )
    asyncio.run(
        service.add_message(
            'owner-1',
            created.jobId,
            ResearchChatRequest(content='그 중에서 2020년 이후 논문만 다시 보여줘'),
            orchestrator,
        )
    )

    assert orchestrator.contexts[0].prior_paper_ids == ()
    assert orchestrator.contexts[1].prior_paper_ids == ('2001.00001', '2001.00002')
