"""ResultAssembler — FR-4/FR-11 (BR-6/9/15; INV-2; PBT-09).

Maps grounded results / no-match / abstain to the external ``SearchResponse`` union. SEC-9: a
card exposes ONLY the 7 projected fields (``relevance`` is the display rank position, NOT the
raw RRF score). A no-match (or a grounding pass that filtered out every candidate) is an
explicit empty page (resultCount=0), distinct from a grounding *refusal* which is an AbstainDTO
(BR-9 / U5 B3-a: 기권 ≠ 빈 결과). When a degrade mode is active for a non-empty successful
response, returns DegradedResultDTO with the mode (BR-11).
"""

from __future__ import annotations

from docsuri_shared.dtos import (
    AbstainDTO,
    DegradationMode,
    DegradedResultDTO,
    ResultCardVM,
    ResultMeta,
    SearchResponse,
    SearchResultPageDTO,
)

from .models import AbstainResult, Candidate, DegradeMode, GroundedResults, NoMatchResult


def _card(candidate: Candidate, rank: int) -> ResultCardVM:
    """Project a real IndexRecord to the 7 card fields (SEC-9). ``relevance`` = 1-based rank
    (display-only; raw retrieval_score is NOT exposed)."""
    r = candidate.record
    return ResultCardVM(
        title=r.title,
        authors=list(r.authors),
        year=r.year,
        arxivId=r.arxivId,
        abstractSnippet=r.abstractSnippet,
        relevance=rank,
        arxivUrl=r.arxivUrl,
    )


class ResultAssembler:
    def assemble(
        self,
        result: GroundedResults | AbstainResult | NoMatchResult,
        degrade_mode: DegradeMode,
    ) -> SearchResponse:
        # A grounding *refusal* (verdict block/abstain) is the only true abstain.
        if isinstance(result, AbstainResult):
            return SearchResponse(AbstainDTO(reason=result.reason))

        # No-match, or a grounding pass that filtered out every candidate: an explicit empty
        # page (resultCount=0), NOT an abstain (BR-9 / U5 B3-a: 기권 ≠ 빈 결과). The empty page
        # carries no degrade banner — there are no cards to qualify.
        # Order matters: NoMatchResult is checked first so ``.items`` is only read on the
        # remaining GroundedResults branch (NoMatchResult has no ``items``).
        if isinstance(result, NoMatchResult) or not result.items:
            meta = ResultMeta(resultCount=0, degraded=False, degradationMode=None)
            return SearchResponse(SearchResultPageDTO(cards=[], meta=meta))

        cards = [_card(c, rank=i + 1) for i, c in enumerate(result.items)]
        if degrade_mode is DegradeMode.NORMAL:
            meta = ResultMeta(resultCount=len(cards), degraded=False, degradationMode=None)
            return SearchResponse(SearchResultPageDTO(cards=cards, meta=meta))

        mode = DegradationMode(degrade_mode.value)
        meta = ResultMeta(resultCount=len(cards), degraded=True, degradationMode=mode)
        return SearchResponse(DegradedResultDTO(cards=cards, meta=meta, mode=mode))
