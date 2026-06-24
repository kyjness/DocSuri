# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, RootModel
from typing import Literal
from . import docmodel_schema


class SummarizeTask(StrEnum):
    """
    The specific summarization task: core summary generation or language translation. Trace: FR-12, FR-13.
    """

    summary = 'summary'
    translate = 'translate'


class SummarizeScope(StrEnum):
    """
    The scope of source text used: abstract-only or full paper text. Trace: FR-13.
    """

    abstract = 'abstract'
    full = 'full'


class Persona(StrEnum):
    """
    The target persona for summary generation: expert-level or beginner-level. Trace: FR-14.
    """

    expert = 'expert'
    beginner = 'beginner'


class TargetLang(StrEnum):
    """
    Target language for translation. Trace: FR-13.
    """

    ko = 'ko'


class SummaryRequest(BaseModel):
    """
    Request payload to trigger summarization or translation (FR-12/13/14).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperId: str = Field(
        ..., description='The unique identifier of the paper (arXiv ID). Trace: FR-12.'
    )
    version: int = Field(..., description='The version of the paper. Trace: FR-12.')
    task: SummarizeTask
    targetLang: TargetLang | None = Field(
        None, description='Target language for translation. Trace: FR-13.'
    )
    persona: Persona | None = None
    scope: SummarizeScope | None = None
    abstract: str | None = Field(
        None,
        description='Optional raw abstract string carried for full-text fallback or abstract-only translation. Trace: FR-13.',
    )


class AnchorTarget(StrEnum):
    """
    Target type for a grounding anchor reference. Trace: FR-12.
    """

    section = 'section'
    table = 'table'
    figure = 'figure'


class Anchor(BaseModel):
    """
    A structured citation anchor mapping a claim back to source paper evidence (FR-12/US-S3).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    field: str = Field(
        ..., description='The summary field name this anchor belongs to. Trace: FR-12.'
    )
    target: AnchorTarget
    span: str = Field(
        ..., description='The exact source quote or text span. Trace: FR-12.'
    )
    label: str = Field(
        ...,
        description="Derived section, table, or figure label (e.g. 'Section 3.1'). Trace: FR-12.",
    )


class Reproducibility(BaseModel):
    """
    Quick assessment of code and data availability. Trace: FR-12.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    code: str = Field(
        ...,
        description='Exposed code repository link or availability statement. Trace: FR-12.',
    )
    data: str = Field(
        ..., description='Exposed dataset link or availability statement. Trace: FR-12.'
    )


class SummaryDraft(BaseModel):
    """
    Structured research paper summary containing key dimensions and citation anchors.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    tldr: str = Field(
        ..., description='A single-sentence TL;DR of the paper. Trace: FR-12.'
    )
    contributions: list[str] = Field(
        ..., description='Key contributions identified. Trace: FR-12.'
    )
    method: str = Field(
        ..., description='The methodology/approach description. Trace: FR-12.'
    )
    results: str = Field(..., description='Key findings/results. Trace: FR-12.')
    limitations: str = Field(
        ..., description='Limitations noted by the authors or pipeline. Trace: FR-12.'
    )
    reproducibility: Reproducibility
    anchors: list[Anchor] = Field(
        ..., description='Grounding anchors for claims. Trace: FR-12.'
    )
    truncated: bool | None = Field(
        None,
        description='Flag indicating if the summary draft was truncated. Trace: FR-12.',
    )


class SummaryMeta(BaseModel):
    """
    Summary metadata including fallback information.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    source: str | None = Field(
        None, description="Source text indicator (e.g. 'full_text'). Trace: FR-12."
    )
    fallback: str | None = Field(
        None,
        description="Fallback reason if processing was degraded (e.g., 'abstract'). Trace: FR-13.",
    )


class PendingDTO(BaseModel):
    """
    A long-input summary (LengthRouter MAP_REDUCE band) is being produced asynchronously as a background job (BR-S6/BR-S8): a cache miss enqueued a summary job. The client re-requests the same action after retryAfterMs and gets the result on a cache hit once the worker finishes. Trace: BR-S6, BR-S8, #135.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['pending']
    retryAfterMs: int | None = Field(
        None,
        description='Suggested client poll backoff in milliseconds before re-requesting.',
    )


class AbstainDTO(BaseModel):
    """
    Returned when summary is abstained due to failure to pass grounding validation rules. Trace: FR-12.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['abstain']
    reason: str = Field(
        ..., description='Non-technical reason for abstaining. Trace: SEC-9.'
    )


class CostDegradedDTO(BaseModel):
    """
    Returned when the budget circuit is OPEN and operations are degraded. Trace: NFR-C1.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['cost_degraded']
    message: str = Field(..., description='User-facing message. Trace: SEC-9.')


class SourceUnavailableDTO(BaseModel):
    """
    Returned when source content is unavailable for processing. Trace: FR-12.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['source_unavailable']
    reason: str = Field(
        ..., description='Reason for source unavailability. Trace: SEC-9.'
    )


class Type(StrEnum):
    """
    Asset kind. Trace: FR-17.
    """

    figure = 'figure'
    table = 'table'


class SourceMode(StrEnum):
    """
    How the asset was extracted (hybrid). Trace: FR-17.
    """

    structured = 'structured'
    page_crop = 'page-crop'


class AssetRef(BaseModel):
    """
    FR-17 figure/table view-model (display-only). Produced by U1 ingestion (paper_asset), presigned by U7. SEC-9: a short-lived signed `url` only — the S3 object_ref and internal manifest columns are NEVER exposed.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    assetId: str = Field(..., description='Deterministic asset id. Trace: FR-17.')
    type: Type = Field(..., description='Asset kind. Trace: FR-17.')
    ordinal: int = Field(
        ..., description='Display order within its type. Trace: FR-17.'
    )
    caption: str = Field(
        ..., description='Figure/table caption (escaped on render). Trace: FR-17.'
    )
    sourceMode: SourceMode = Field(
        ..., description='How the asset was extracted (hybrid). Trace: FR-17.'
    )
    url: str = Field(
        ..., description='Short-lived signed GET URL (SEC-9). Trace: FR-17, SEC-9.'
    )
    pageRef: int | None = Field(
        None, description='Source page (page-crop). Trace: FR-17.'
    )
    bbox: list[float] | None = Field(
        None, description='Source bbox (page-crop). Trace: FR-17.'
    )


class AssetsOkDTO(BaseModel):
    """
    Successful asset manifest. Trace: FR-17.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['ok']
    assets: list[AssetRef] = Field(
        ..., description='Figure/table assets in display order. Trace: FR-17.'
    )


class AssetsLicenseUnavailableDTO(BaseModel):
    """
    OA license not permitted (or assets not configured) → no assets shown. Trace: FR-17, BR-SF-11.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['license_unavailable']


class AssetsUnauthorizedDTO(BaseModel):
    """
    Authentication required (401). Trace: FR-17, SEC-8.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['unauthorized']


class PaperAssetsResponse(
    RootModel[AssetsOkDTO | AssetsLicenseUnavailableDTO | AssetsUnauthorizedDTO]
):
    root: AssetsOkDTO | AssetsLicenseUnavailableDTO | AssetsUnauthorizedDTO = Field(
        ...,
        description='GET /api/papers/{id}/assets terminal union (FR-17). OA-license-gated like full-text (BR-SF-11).',
        title='PaperAssetsResponse',
    )


class TranslationDraft(BaseModel):
    """
    Structured Korean translation as a 'translated doc-model' mirroring the source structure (FR-13): section titles, paragraphs, list items, and table/figure captions are translated to Korean, while structural/verbatim fields — block & section ids, formula LaTeX, table numeric cells, figure assetRefs — are copied from the source doc-model unchanged (numbers/equations are never translated; D8). Block & section ids mirror the source doc-model so the client renders it with the SAME rich viewer as the original body. Trace: FR-13, BR-S3.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    docModel: docmodel_schema.DocModel = Field(
        ...,
        description='The translated doc-model: Korean text over the source structure (ids mirror the source). Rendered by the same rich viewer as the original body. Trace: FR-13.',
    )
    keptTerms: list[str] = Field(
        ...,
        description='Untranslated terminology or glossary terms kept as-is. Trace: FR-13.',
    )


class SummaryResultDTO(BaseModel):
    """
    Successful summary or translation response. Only SEC-9 white-listed fields are exposed.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['ok'] = Field(
        ..., description='Successful status indicator. Trace: FR-11.'
    )
    task: SummarizeTask
    meta: SummaryMeta
    cached: bool = Field(
        ...,
        description='Indicates if the response was served from cache. Trace: FR-11.',
    )
    summary: SummaryDraft | None = None
    translation: TranslationDraft | None = None


class SummaryResponse(
    RootModel[
        SummaryResultDTO
        | PendingDTO
        | AbstainDTO
        | CostDegradedDTO
        | SourceUnavailableDTO
    ]
):
    root: (
        SummaryResultDTO
        | PendingDTO
        | AbstainDTO
        | CostDegradedDTO
        | SourceUnavailableDTO
    ) = Field(
        ...,
        description='U7 Summarization DTO contract. The ROOT schema describes SummaryResponse — the union (oneOf) returned by on-demand actions (FR-12/13/14) and branched by U5 ApiClient to surface status. All named DTOs (SummaryRequest, SummaryResultDTO, SummaryDraft, Anchor, TranslationDraft, PendingDTO, AbstainDTO, CostDegradedDTO, SourceUnavailableDTO) are defined in $defs for type generation.',
        title='SummaryResponse',
    )
