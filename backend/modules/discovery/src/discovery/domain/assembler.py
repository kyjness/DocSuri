"""ResultAssembler — FR-4/FR-11 (BR-6/9/15; INV-2; PBT-09).

Maps grounded results / no-match / abstain to the external ``SearchResponse`` union. SEC-9: a
card exposes ONLY the projected fields (``relevance`` is the display rank position, NOT the
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
from .source_ref import record_has_link, safe_url, source_ref


def _card(candidate: Candidate, rank: int) -> ResultCardVM:
    """Project a real IndexRecord to the exposed card fields (SEC-9). ``relevance`` = 1-based
    rank (display-only; raw retrieval_score is NOT exposed). Phase 2 (Q2): adds source-neutral
    ``sourceName``/``sourceUrl`` so non-arXiv results carry a real link (FR-5). EVERY exposed
    link runs through ``safe_url`` — the structural guard keys on the projected ``sourceUrl``,
    so a non-http(s) ``arxivUrl`` would otherwise ride unchecked on a non-arXiv card (FR-5)."""
    r = candidate.record
    source_name, source_url = source_ref(r)
    return ResultCardVM(
        title=r.title,
        authors=list(r.authors),
        year=r.year,
        arxivId=r.arxivId,
        abstractSnippet=r.abstractSnippet,
        relevance=rank,
        arxivUrl=safe_url(r.arxivUrl),
        sourceName=source_name,
        sourceUrl=safe_url(source_url),
    )


class ResultAssembler:
    def assemble(
        self,
        result: GroundedResults | AbstainResult | NoMatchResult,
        degrade_mode: DegradeMode,
        *,
        personalized: bool = False,
    ) -> SearchResponse:
        # ``personalized`` (US-P4 #155): the LIVE boost stage actually reordered/boosted this
        # page. Exposed as the optional meta.personalized flag on non-empty pages only; kept
        # None (absent) when False so old consumers see an unchanged shape (fail-soft default).
        # A grounding *refusal* (verdict block/abstain) is the only true abstain.
        if isinstance(result, AbstainResult):
            return SearchResponse(AbstainDTO(reason=result.reason))

        # NoMatchResult has no ``items`` → explicit empty page (resultCount=0, BR-9).
        if isinstance(result, NoMatchResult):
            return self._empty_page()

        # GroundingStructuralGuard (defense-in-depth, FR-5; business-logic-model §3.7): keep only
        # candidates whose source-neutral projection yields a resolvable real link, then re-rank
        # the survivors 1..N. A single malformed record is DROPPED rather than shipped ungrounded
        # — it must not sink the whole page. If every candidate is dropped (or there were none),
        # terminate as an explicit empty page (resultCount=0), NOT an abstain (BR-9 / U5 B3-a:
        # 기권 ≠ 빈 결과; 근거화 통과 후 전량 필터 → 빈 페이지).
        grounded = [c for c in result.items if record_has_link(c.record)]
        if not grounded:
            return self._empty_page()

        cards = [_card(c, rank=i + 1) for i, c in enumerate(grounded)]
        flag = True if personalized else None  # absent (not false) keeps old responses valid
        if degrade_mode is DegradeMode.NORMAL:
            meta = ResultMeta(
                resultCount=len(cards), degraded=False, degradationMode=None, personalized=flag
            )
            return SearchResponse(SearchResultPageDTO(cards=cards, meta=meta))

        mode = DegradationMode(degrade_mode.value)
        meta = ResultMeta(
            resultCount=len(cards), degraded=True, degradationMode=mode, personalized=flag
        )
        return SearchResponse(DegradedResultDTO(cards=cards, meta=meta, mode=mode))

    @staticmethod
    def _empty_page() -> SearchResponse:
        """Explicit empty page (resultCount=0) — no-match or all candidates filtered (BR-9)."""
        meta = ResultMeta(resultCount=0, degraded=False, degradationMode=None)
        return SearchResponse(SearchResultPageDTO(cards=[], meta=meta))
