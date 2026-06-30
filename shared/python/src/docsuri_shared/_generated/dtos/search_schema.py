# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, RootModel
from typing import Any
from enum import StrEnum


class DegradationMode(RootModel[str]):
    root: str = Field(
        ...,
        description='Degradation/fallback mode hint (e.g. lexical-only fallback when the cost circuit is OPEN). Provisional type name — SSOT is the field usage in ResultMeta.degradationMode and DegradedResultDTO.mode. Concrete enum values are refined in U2/U6 FD. Trace: NFR-C1, US-R2, QT-3.',
        examples=['lexical-only', 'partial'],
    )


class ResultCardVM(BaseModel):
    """
    Single-paper phone card view-model. Consumed by U5 ResultCard.render(card). The 6 fields title/authors/year/arxivId/abstractSnippet/arxivUrl are the external-exposure PROJECTION of vector-spec.md §2 IndexRecord card fields (FR-4), 1:1, and are NOT added/removed without an IndexRecord change (FROZEN-adjacent). `relevance` does NOT belong to IndexRecord — it is a display-only value derived from ranking (raw scores NOT exposed, SEC-9). Internal IndexRecord fields (vector, lexicalTerms, chunkId, section, categories) are NOT exposed on the card (SEC-9). Phase 2 (Q2): the card additively exposes source-neutral `sourceName`/`sourceUrl` (derived from IndexRecord.sourceProvenance; the arXiv path keeps arxivId/arxivUrl). Internal `blockRefs`/`sourceProvenance` themselves stay unexposed (Q3). Trace: dtos.md §1.1, FR-4, FR-5.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    title: str = Field(
        ...,
        description='Paper title. Source: IndexRecord.title (vector-spec.md §2). Trace: FR-4.',
    )
    authors: list[str] = Field(
        ...,
        description='Authors. Source: IndexRecord.authors (vector-spec.md §2). Trace: FR-4.',
    )
    year: int = Field(
        ...,
        description='Publication year. Source: IndexRecord.year (vector-spec.md §2). Trace: FR-4.',
    )
    arxivId: str = Field(
        ...,
        description='Display arXiv ID (may include version). Source: IndexRecord.arxivId (vector-spec.md §2). Trace: FR-4.',
    )
    abstractSnippet: str = Field(
        ...,
        description='Card abstract snippet, derived from the full IndexRecord.abstract (the full abstract is NOT exposed — snippet only). Source: IndexRecord.abstractSnippet (vector-spec.md §2). Trace: FR-4, FR-5.',
    )
    relevance: Any = Field(
        ...,
        description='Display-only relevance (ranking order / display grade, derived). Internal raw scores and debug signals are NOT exposed (SEC-9). NOT an IndexRecord field. Display type is refined in U2 FD. Trace: FR-3, FR-4, SEC-9.',
    )
    arxivUrl: str = Field(
        ...,
        description='Resolvable real link (FR-5 grounding — no fabrication; arXiv path). Source: IndexRecord.arxivUrl (vector-spec.md §2). Trace: FR-4, FR-5.',
    )
    sourceName: str | None = Field(
        None,
        description='Phase 2 (Q2). Source label for the multi-source corpus (arXiv / Semantic Scholar / OpenAlex). Derived from IndexRecord.sourceProvenance.sourceName; defaults to "arXiv" for legacy/arXiv-only records. Optional (additive, backward-compatible) but always populated by the assembler. Trace: FR-4, FR-5.',
    )
    sourceUrl: str | None = Field(
        None,
        description='Phase 2 (Q2). Source-neutral resolvable real link (FR-5 grounding — no fabrication): arXiv = arxivUrl, non-arXiv = sourceProvenance.sourceUrl / DOI. Optional (additive) but always populated by the assembler. Trace: FR-4, FR-5.',
    )


class ResultMeta(BaseModel):
    """
    Result-count and degradation banner hints. Internal scores/timings NOT exposed (SEC-9). Trace: dtos.md §1, FR-11, QT-3.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    resultCount: int = Field(
        ..., description='Number of results returned (int). Trace: FR-11.'
    )
    degraded: bool = Field(
        ...,
        description='Degraded-result banner hint (true when results came from a degraded/fallback path). Trace: FR-11, QT-3.',
    )
    degradationMode: DegradationMode | None = Field(
        None,
        description='Optional. Present when degraded=true to indicate the fallback mode (e.g. lexical-only). Trace: NFR-C1, US-R2, QT-3.',
    )


class Scope(StrEnum):
    """
    Retrieval breadth. "lite" (default): BM25 over title+abstract only, no k-NN — the low-latency human search box (P50<3s). "full": hybrid (title+abstract+full-body chunks + k-NN) for deep recall — the literature/evidence agent and the opt-in "본문까지 검색" toggle. Absent ⇒ lite. Trace: FR-2.
    """

    lite = 'lite'
    full = 'full'


class SearchRequest(BaseModel):
    """
    Synchronous search entry input. Source: QueryIntakeController.search(request: SearchRequest, ctx) (component-methods U2). Trace: dtos.md §1, FR-1, SEC-5, US-H1.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    query: str = Field(
        ...,
        description='Search query. Validated per FR-1/SEC-5 (non-empty, <=500 chars, sanitized). Trace: FR-1, SEC-5.',
        max_length=500,
        min_length=1,
    )
    scope: Scope | None = Field(
        None,
        description='Retrieval breadth. "lite" (default): BM25 over title+abstract only, no k-NN — the low-latency human search box (P50<3s). "full": hybrid (title+abstract+full-body chunks + k-NN) for deep recall — the literature/evidence agent and the opt-in "본문까지 검색" toggle. Absent ⇒ lite. Trace: FR-2.',
    )
    options: Any | None = Field(
        None,
        description='PROVISIONAL — optional search options. Type name is provisional; SSOT (dtos.md §1) records only the field `options?` (shape refined when the type is finalized in U2 FD). Trace: dtos.md §1.',
    )


class SearchResultPageDTO(BaseModel):
    """
    Successful search response: order-preserving top-N card page (FR-3). The card array is in RANKING ORDER (PBT-03). Trace: dtos.md §1, FR-3, FR-4.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    cards: list[ResultCardVM] = Field(
        ..., description='Result cards in ranking order. Trace: FR-3, FR-4, PBT-03.'
    )
    meta: ResultMeta = Field(
        ..., description='Result metadata (count, degradation hints). Trace: FR-11.'
    )


class AbstainDTO(BaseModel):
    """
    Grounding abstain / out-of-corpus response — non-technical message, NO fabricated results (maps to U6 verdict=abstain). Internal violation detail NOT exposed. Provisional type name — SSOT (dtos.md §1) is AbstainResult{reason}. Trace: dtos.md §1, FR-5, US-D5, US-D6.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    reason: Any = Field(
        ...,
        description='Abstain reason code (non-technical; internal violation detail NOT exposed). Trace: FR-5, US-D5, US-D6, SEC-9.',
    )


class DegradedResultDTO(BaseModel):
    """
    Partial / lexical-only fallback results returned WITH explicit degradation (NFR-C1 / US-R2). Card shape is identical to the success page. meta.degraded MUST be true. Trace: dtos.md §1, NFR-C1, US-R2, US-R3, QT-3.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    cards: list[ResultCardVM] = Field(
        ...,
        description='Degraded result cards (same shape as success). Trace: NFR-C1, US-R2.',
    )
    meta: ResultMeta = Field(
        ..., description='Result metadata with degraded=true. Trace: FR-11, QT-3.'
    )
    mode: DegradationMode = Field(
        ...,
        description='The degradation mode in effect for this response. Trace: NFR-C1, US-R2.',
    )


class ValidationErrorDTO(BaseModel):
    """
    FR-1/SEC-5 validation failure inline error (non-technical, internal info blocked, fail-closed). Trace: dtos.md §1, FR-1, SEC-5, FR-11.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    field: str | None = Field(
        None,
        description='Optional. Offending field name (e.g. query). Trace: FR-1, SEC-5.',
    )
    message: str = Field(
        ...,
        description='Non-technical validation message (stack/internal identifiers blocked, fail-closed). Trace: FR-1, SEC-5, FR-11.',
    )


class SearchResponse(
    RootModel[SearchResultPageDTO | AbstainDTO | DegradedResultDTO | ValidationErrorDTO]
):
    root: SearchResultPageDTO | AbstainDTO | DegradedResultDTO | ValidationErrorDTO = (
        Field(
            ...,
            description='U2 Discovery/Search DTO contract (dtos.md §1). The ROOT schema describes SearchResponse — the terminal-state union (oneOf) returned by QueryIntakeController.search(request: SearchRequest, ctx) -> SearchResponse and branched by U5 ApiClient.search to surface status (FR-11). All named DTOs (SearchRequest, SearchResultPageDTO, ResultCardVM, ResultMeta, AbstainDTO, DegradedResultDTO, ValidationErrorDTO) are defined in $defs for per-track type generation. 🟡 PROVISIONAL, but card fields are FROZEN-adjacent. Producer: U2; Consumer: U5. Grounding premise (FR-5): every exposed card maps to a real IndexRecord (real arXiv ID/link); U6.GroundingEnforcementHook validates at the response edge — zero fabrication. Internal fields (raw scores, timings, vector/lexicalTerms/chunkId/section) are NOT exposed (SEC-9). Trace: FR-1, FR-3, FR-4, FR-5, FR-11, SEC-5, SEC-9, US-D1..D7.',
            title='SearchResponse',
        )
    )
