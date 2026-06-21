"""ResultAssembler terminal-state mapping (BR-9 / U5 B3-a: 기권 ≠ 빈 결과).

A no-match — or a grounding pass that filters every candidate out — is an explicit empty page
(resultCount=0, not silent), in BOTH normal and degraded modes. Only a grounding *refusal*
(AbstainResult) becomes an AbstainDTO.
"""

from __future__ import annotations

from docsuri_shared.dtos import AbstainDTO, SearchResultPageDTO

from discovery.domain.assembler import ResultAssembler
from discovery.domain.models import AbstainResult, DegradeMode, GroundedResults, NoMatchResult

_assembler = ResultAssembler()


def test_no_match_is_empty_page_not_abstain() -> None:
    response = _assembler.assemble(NoMatchResult(), DegradeMode.NORMAL)
    assert isinstance(response.root, SearchResultPageDTO)
    assert response.root.cards == []
    assert response.root.meta.resultCount == 0


def test_empty_grounded_normal_is_empty_page() -> None:
    response = _assembler.assemble(GroundedResults(items=()), DegradeMode.NORMAL)
    assert isinstance(response.root, SearchResultPageDTO)
    assert response.root.meta.resultCount == 0


def test_empty_grounded_degraded_is_empty_page_no_banner() -> None:
    # An empty result carries no degrade banner — there are no cards to qualify.
    response = _assembler.assemble(GroundedResults(items=()), DegradeMode.LEXICAL_ONLY)
    assert isinstance(response.root, SearchResultPageDTO)
    assert response.root.meta.degraded is False


def test_no_match_degraded_is_empty_page_no_banner() -> None:
    # Same invariant for a no-match under an active degrade mode: empty page, no banner.
    response = _assembler.assemble(NoMatchResult(), DegradeMode.LEXICAL_ONLY)
    assert isinstance(response.root, SearchResultPageDTO)
    assert response.root.meta.resultCount == 0
    assert response.root.meta.degraded is False


def test_grounding_refusal_is_abstain() -> None:
    response = _assembler.assemble(AbstainResult(reason="no_grounded_results"), DegradeMode.NORMAL)
    assert isinstance(response.root, AbstainDTO)
    assert response.root.reason == "no_grounded_results"
