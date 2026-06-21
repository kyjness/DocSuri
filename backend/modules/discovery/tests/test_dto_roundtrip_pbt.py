"""PBT-09 — SearchResponse DTO roundtrip for all 4 terminal states + SEC-9 card shape."""

from __future__ import annotations

from docsuri_shared.dtos import (
    AbstainDTO,
    DegradedResultDTO,
    SearchResponse,
    SearchResultPageDTO,
    ValidationErrorDTO,
)
from hypothesis import given
from hypothesis import strategies as st

from discovery.domain.assembler import ResultAssembler
from discovery.domain.models import Candidate, DegradeMode, GroundedResults, NoMatchResult
from discovery.mocks.fixtures import RECORDS

_assembler = ResultAssembler()
_CARD_FIELDS = {"title", "authors", "year", "arxivId", "abstractSnippet", "relevance", "arxivUrl"}


def _roundtrip(response: SearchResponse) -> None:
    assert SearchResponse.model_validate_json(response.model_dump_json()) == response


def test_abstain_roundtrip() -> None:
    # Abstain is a grounding *refusal* only — use the real rejection code (grounding_adapter).
    _roundtrip(SearchResponse(AbstainDTO(reason="no_grounded_results")))


def test_empty_page_roundtrip() -> None:
    # No-match terminates as an explicit empty page (cards=[], resultCount=0), NOT an abstain
    # (BR-9 / U5 B3-a). The success-page strategy below starts at n=1, so cover cards=[] here.
    response = _assembler.assemble(NoMatchResult(), DegradeMode.NORMAL)
    assert isinstance(response.root, SearchResultPageDTO)
    assert response.root.meta.resultCount == 0
    _roundtrip(response)


def test_validation_error_roundtrip() -> None:
    _roundtrip(SearchResponse(ValidationErrorDTO(field="query", message="bad")))


@given(st.integers(min_value=1, max_value=len(RECORDS)))
def test_success_page_roundtrip_and_card_shape(n: int) -> None:
    items = tuple(Candidate(record=RECORDS[i], retrieval_score=1.0 / (i + 1)) for i in range(n))
    response = _assembler.assemble(GroundedResults(items=items), DegradeMode.NORMAL)
    assert isinstance(response.root, SearchResultPageDTO)
    _roundtrip(response)
    # SEC-9 (INV-2): a card exposes exactly the 7 projected fields — no internal fields.
    for card in response.root.cards:
        assert set(card.model_dump().keys()) == _CARD_FIELDS


@given(st.sampled_from([DegradeMode.RERANK_OFF, DegradeMode.LEXICAL_ONLY]))
def test_degraded_roundtrip(mode: DegradeMode) -> None:
    items = (Candidate(record=RECORDS[0], retrieval_score=1.0),)
    response = _assembler.assemble(GroundedResults(items=items), mode)
    assert isinstance(response.root, DegradedResultDTO)
    assert response.root.meta.degraded is True
    _roundtrip(response)
