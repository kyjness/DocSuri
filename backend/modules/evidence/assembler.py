from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceCoverage,
    EvidenceItem,
    EvidenceResult,
    SourceRef,
)

from .models import LiteralSearchResult, PaperSearchResult

_MAX_NAMED_PAPERS = 3


class EvidenceComparisonAssembler:
    """EvidenceItem[] → EvidenceResult 비교표 조립 (BR-EV-5)."""

    def assemble(
        self,
        items: list[EvidenceItem],
        search_result: PaperSearchResult,
        paper_count: int,
    ) -> EvidenceResult:
        coverage = EvidenceCoverage(
            paperCount=paper_count,
            # explicit scope은 queryUsed 생략(INV-EV-5: 내부 검색 정보 비노출)
            queryUsed=search_result.query_used if search_result.scope != 'explicit' else None,
        )
        return EvidenceResult(
            state='ok',
            claims=items,
            coverage=coverage,
            answer=_narrative_from_items(items),
        )

    def assemble_literal(self, result: LiteralSearchResult) -> EvidenceResult:
        """정확 문구 검색 결과 → EvidenceResult. LLM을 거치지 않으므로 claims는
        원문 발췌(quote) 그 자체이며 별도 그라운딩 검증이 필요 없다."""
        items = _items_from_literal_matches(result)
        paper_ids = _distinct_paper_ids(result.matches)
        coverage = EvidenceCoverage(paperCount=len(paper_ids), queryUsed=result.phrase)
        return EvidenceResult(
            state='ok',
            claims=items,
            coverage=coverage,
            answer=_narrative_from_literal(result, paper_ids),
        )


def _items_from_literal_matches(result: LiteralSearchResult) -> list[EvidenceItem]:
    if not result.matches:
        return []
    supporting = [
        SourceRef(paperId=m.paper_id, recordRef=m.paper_id, anchor=m.anchor, quote=m.quote)
        for m in result.matches
    ]
    return [
        EvidenceItem(
            statement=f"'{result.phrase}' 문장이 원문에 그대로 있습니다.",
            supporting=supporting,
            conflicting=[],
        )
    ]


def _distinct_paper_ids(matches) -> list[str]:
    seen: dict[str, None] = {}
    for match in matches:
        paper_id = getattr(match, 'paper_id', None) or getattr(match, 'paperId', None)
        if paper_id:
            seen.setdefault(paper_id, None)
    return list(seen)


def _narrative_from_literal(result: LiteralSearchResult, paper_ids: list[str]) -> str:
    if not paper_ids:
        return f"'{result.phrase}' 문장이 포함된 논문을 찾지 못했습니다."
    listing = ', '.join(paper_ids[:_MAX_NAMED_PAPERS])
    remainder = len(paper_ids) - _MAX_NAMED_PAPERS
    more = f' 외 {remainder}편' if remainder > 0 else ''
    return (
        f"'{result.phrase}' 문장이 포함된 논문을 총 {len(paper_ids)}편 찾았습니다: "
        f'{listing}{more}. 각 카드에서 어느 문단에 있는지 바로 확인할 수 있습니다.'
    )


def _narrative_from_items(items: list[EvidenceItem]) -> str | None:
    """claims만으로 조립하는 대화체 요약 — 새 사실을 도입하지 않고 이미 grounded된
    statement/paperId만 자연스러운 문장으로 잇는다(C-2: '새 사실 금지'이지 '요약 금지'는
    아니다)."""
    if not items:
        return None
    sentences: list[str] = []
    for item in items:
        supporting_papers = _distinct_paper_ids(item.supporting)
        sentence = item.statement.rstrip('.。 ')
        if supporting_papers:
            listing = ', '.join(supporting_papers[:_MAX_NAMED_PAPERS])
            remainder = len(supporting_papers) - _MAX_NAMED_PAPERS
            more = f' 외 {remainder}편' if remainder > 0 else ''
            sentence += f' ({listing}{more}에서 확인됨)'
        conflicting_papers = _distinct_paper_ids(item.conflicting)
        if conflicting_papers:
            listing = ', '.join(conflicting_papers[:_MAX_NAMED_PAPERS])
            sentence += f'. 다만 {listing}는 다른 결과를 보고합니다'
        sentences.append(sentence + '.')
    return ' '.join(sentences)
