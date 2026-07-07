from __future__ import annotations

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceCoverage,
    EvidenceItem,
    EvidenceResult,
)

from .models import PaperSearchResult


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
        )
