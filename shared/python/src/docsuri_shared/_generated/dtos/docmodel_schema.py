# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel
from typing import Literal
from enum import StrEnum


class DocModelRequest(BaseModel):
    """
    Request to fetch (and lazily build+cache on miss) the doc-model for a paper version. Trace: BR-30 (lazy on-demand + (paperId, version) cache), D6.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperId: str = Field(..., description='arXiv ID. Trace: FR-12.')
    version: int = Field(
        ...,
        description='Paper version; doc-model cache key is (paperId, version). Trace: D6, BR-30.',
    )


class BuildingDTO(BaseModel):
    """
    The doc-model is being built asynchronously (lazy on-demand, D6/BR-30): a cache miss enqueued a build job and the client should poll getDocModel again after retryAfterMs. Distinct from source_unavailable (a build that ran and failed every source tier) — building is transient/in-flight. Trace: BR-30, BR-S8 (async job), D6.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['building']
    retryAfterMs: int | None = Field(
        None,
        description='Suggested client poll backoff in milliseconds before re-requesting.',
    )


class LicenseUnavailableDTO(BaseModel):
    """
    OA license does not permit in-app rich rendering of this paper; client links out to arXiv instead. Trace: BR-SF-11, SEC-9.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['license_unavailable']
    reason: str | None = Field(
        None, description='Non-technical reason for the license gate (display copy).'
    )
    arxivUrl: str | None = Field(
        None, description='Safe arXiv link-out target (http/https). Trace: BR-U5-7.'
    )


class SourceUnavailableDTO(BaseModel):
    """
    doc-model could not be produced from any source tier (HTML/ar5iv/e-print/PDF all failed). Trace: Q6 fallback ladder.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['source_unavailable']
    reason: str | None = Field(None, description='Non-technical reason (display copy).')


class SourceTier(StrEnum):
    """
    Which rung of the fallback ladder produced this doc-model: native arXiv HTML -> ar5iv -> e-print LaTeX -> (last resort) PDF parse. Trace: Q6, BR-29, TD-11.
    """

    native_html = 'native_html'
    ar5iv = 'ar5iv'
    eprint_latex = 'eprint_latex'
    pdf = 'pdf'


class ParagraphBlock(BaseModel):
    """
    Body text. Inline mathematics is embedded as LaTeX delimited by \\( ... \\) within `text` (KaTeX renders it; the summary prompt and agents read the LaTeX verbatim). Trace: D1.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(
        ...,
        description='Deterministic block id / anchor handle, e.g. "s3.p2". Trace: Q2-decision.',
    )
    type: Literal['paragraph']
    text: str = Field(
        ...,
        description='Paragraph text; may contain inline LaTeX in \\( ... \\) delimiters. Rendered escaped except for trusted KaTeX (SEC-5).',
    )


class TableCell(BaseModel):
    """
    A table cell. `text` may contain inline LaTeX in \\( ... \\) delimiters.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    text: str = Field(..., description='Cell content as text (inline LaTeX allowed).')
    isHeader: bool | None = Field(None, description='True for header (th) cells.')
    colspan: int | None = Field(None, description='Column span (default 1).', ge=1)
    rowspan: int | None = Field(None, description='Row span (default 1).', ge=1)


class ListItem(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    text: str = Field(
        ...,
        description='List item text; inline LaTeX allowed in \\( ... \\) delimiters.',
    )


class CodeBlock(BaseModel):
    """
    A verbatim/code/algorithm block (rendered monospace, not interpreted).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(..., description='Deterministic block id, e.g. "s3.code1".')
    type: Literal['code']
    text: str = Field(..., description='Verbatim text.')
    language: str | None = Field(None, description='Optional language hint.')


class Type(StrEnum):
    """
    Asset kind. "formula" is a page-crop equation image used only as the FormulaBlock fallback when no LaTeX is recoverable (PDF/GROBID path). Trace: FR-17, TD-12.
    """

    figure = 'figure'
    table = 'table'
    formula = 'formula'


class SourceMode(StrEnum):
    """
    How the image was obtained: structured graphic extraction or page-crop fallback. Trace: TD-11/TD-12.
    """

    structured = 'structured'
    page_crop = 'page-crop'


class AssetRef(BaseModel):
    """
    A REFERENCE to a stored image asset — assetId, not pixels and not an object_ref. The read API (getDocModel / GET /api/papers/{id}/assets) issues a short-lived signed URL at read time; the doc-model artifact never stores the URL or object_ref (SEC-9). Mirrors the existing AssetRef in summarization.schema.json minus the runtime-only `url`. Trace: FR-17, SEC-9, D8/D5.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    assetId: str = Field(
        ...,
        description='Deterministic asset id keying assets/{paperId}/{version}/{assetId}.webp and the paper_asset row. Trace: FR-17.',
    )
    type: Type = Field(
        ...,
        description='Asset kind. "formula" is a page-crop equation image used only as the FormulaBlock fallback when no LaTeX is recoverable (PDF/GROBID path). Trace: FR-17, TD-12.',
    )
    ordinal: int = Field(
        ..., description='Display order within its type (figure/table). Trace: FR-17.'
    )
    caption: str | None = Field(
        None,
        description='Caption (mirrors the parent block caption; convenience for asset-only views).',
    )
    sourceMode: SourceMode | None = Field(
        None,
        description='How the image was obtained: structured graphic extraction or page-crop fallback. Trace: TD-11/TD-12.',
    )


class Provenance(BaseModel):
    """
    How this doc-model was produced — for cache invalidation, debugging, and coverage telemetry. No PII (SEC-3).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    sourceTier: SourceTier
    parserVersion: str = Field(
        ...,
        description='Deterministic parser build identifier; bumping it invalidates cached doc-models. Trace: BR-30, TD-16.',
    )
    schemaVersion: str = Field(
        ...,
        description='doc-model schema version for additive evolution (consumers ignore unknown fields). Trace: shared/README Versioning.',
    )
    generatedAt: AwareDatetime = Field(..., description='UTC timestamp of generation.')


class TableRow(BaseModel):
    """
    A table row.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    cells: list[TableCell]


class FormulaBlock(BaseModel):
    """
    A display (block-level) equation. LaTeX is preferred (KaTeX renders it; agents read it verbatim and it is indexed for search). When the source carries no recoverable LaTeX (the PDF/GROBID path: a formula is rendered pixels, not LaTeX source) the equation degrades to a page-crop image via `assetRef` — display-only, not searchable. Exactly one of `latex` / `assetRef` is the render source; `latex` wins when both are present. Inline math lives in ParagraphBlock.text instead. Trace: D1, TD-16.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(
        ...,
        description='Deterministic block id / anchor handle, e.g. "s3.eq2". Trace: Q2-decision.',
    )
    type: Literal['formula']
    latex: str | None = Field(
        None,
        description='LaTeX (converted from source MathML when needed; HTML-borne <math> coverage ~94% per Q1 spike). Rendered by KaTeX/MathJax. Absent on the PDF/GROBID path when no LaTeX is recoverable — `assetRef` carries the image instead. Trace: D1, TD-16.',
    )
    assetRef: AssetRef | None = Field(
        None,
        description='Page-crop image fallback for a formula with no recoverable LaTeX (PDF/GROBID path). assetRef.type is "formula". Display-only — not indexed for search. Trace: FR-17, TD-12.',
    )
    display: bool | None = Field(
        None,
        description='Always true for a FormulaBlock (display/block equation); present for renderer clarity.',
    )
    anchorLabel: str | None = Field(
        None, description='Equation number as in the paper, e.g. "(3)".'
    )
    mathmlSource: str | None = Field(
        None, description='Optional original MathML, retained for fidelity/debugging.'
    )


class FigureBlock(BaseModel):
    """
    A figure: a webp image referenced by assetId (pixels reused from the FR-17 assets pipeline; reuses U5 AssetGallery + asset-anchor matcher for render). Trace: FR-17, D5.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(
        ...,
        description='Deterministic block id / anchor handle, e.g. "s3.fig1". Trace: Q2-decision.',
    )
    type: Literal['figure']
    assetRef: AssetRef
    caption: str | None = Field(
        None, description='Figure caption text (preserved). Trace: BR-S3.'
    )
    anchorLabel: str | None = Field(
        None,
        description='Human label, e.g. "Figure 2" — used by the asset-anchor matcher. Trace: FR-12.',
    )


class ListBlock(BaseModel):
    """
    An ordered or unordered list. Nested lists are an additive future extension.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(..., description='Deterministic block id, e.g. "s3.list1".')
    type: Literal['list']
    ordered: bool = Field(..., description='True for an ordered (numbered) list.')
    items: list[ListItem]


class DocModelMeta(BaseModel):
    """
    doc-model identity, title/abstract, and provenance.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    paperId: str = Field(..., description='arXiv ID. Trace: FR-12.')
    version: int = Field(
        ...,
        description='Paper version; doc-model is keyed (paperId, version). Trace: D6.',
    )
    title: str = Field(
        ..., description='Paper title (rendered as document title in the rich view).'
    )
    abstract: str | None = Field(
        None,
        description='Optional abstract plain text (translate task uses the abstract directly; rich view shows it). Trace: BR-S2.',
    )
    macros: dict[str, str] | None = Field(
        None,
        description='Optional KaTeX macro map ("\\\\name" -> expansion) extracted from the e-print LaTeX preamble (\\newcommand / \\providecommand / \\DeclareMathOperator / \\def). The renderer passes it to KaTeX so author-defined commands in formula LaTeX resolve instead of rendering as red unsupported-command errors. Additive/optional — absent when no e-print preamble was available; consumers ignore it if unset. Trace: BR-30, TD-16.',
    )
    provenance: Provenance


class TableBlock(BaseModel):
    """
    A table as STRUCTURED DATA (rows/cols), NOT a cropped image — so table numbers are visible to the summary LLM, grounding numeric-match, and agents (D8). A crop image may be carried in `assetRef` ONLY as a last-resort fallback (e.g. pdf source tier). Trace: D8, TD-12.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(
        ...,
        description='Deterministic block id / anchor handle, e.g. "s3.tbl2". Trace: Q2-decision.',
    )
    type: Literal['table']
    caption: str | None = Field(
        None,
        description='Table caption text (preserved — a results-number source). Trace: BR-S3 (preserve captions).',
    )
    anchorLabel: str | None = Field(
        None,
        description='Human label as it appears in the paper, e.g. "Table 3" — used by the asset-anchor matcher and AnchorChip display. Trace: FR-12.',
    )
    rows: list[TableRow] = Field(
        ..., description='All rows in order; header rows are marked via cell.isHeader.'
    )
    assetRef: AssetRef | None = Field(
        None,
        description='Optional table crop image (page-crop fallback only). The PRIMARY representation is `rows` data; this is a degraded fallback for non-HTML sources. Trace: TD-11 (last-resort), D8.',
    )


class Block(
    RootModel[
        ParagraphBlock | TableBlock | FormulaBlock | FigureBlock | ListBlock | CodeBlock
    ]
):
    root: (
        ParagraphBlock | TableBlock | FormulaBlock | FigureBlock | ListBlock | CodeBlock
    ) = Field(
        ...,
        description='A content block, discriminated by `type`. Headings are NOT blocks — they are carried by Section.title.',
        title='Block',
    )


class Section(BaseModel):
    """
    A heading-delimited section. `id` is the deterministic anchor handle (see Anchor binding in the spec). Subsections recurse via `sections`. Trace: Q1-decision (nested tree), Q2-decision (block id anchors).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    id: str = Field(
        ...,
        description='Deterministic section id / anchor handle, e.g. "s3", "s3.2". Stable across rebuilds of the same source (P7). Anchor.target may reference this id. Trace: Q2-decision, BR-S7.',
    )
    title: str = Field(
        ...,
        description='Heading text; may be empty when source headings are absent (span-only section). Trace: BR-S3 (section derivation).',
    )
    blocks: list[Block] = Field(
        ...,
        description='Ordered content blocks directly in this section (before any subsection).',
    )
    sections: list[Section] | None = Field(
        None, description='Nested subsections (recursive).'
    )


class DocModel(BaseModel):
    """
    The structured paper artifact: fullText plus a nested section tree of typed content blocks. fullText is the complete reading-order text projection of the paper. Tables are DATA (rows/cols), formulas are LaTeX (page-crop image fallback when no LaTeX is recoverable — PDF/GROBID path), figures/table-images are webp references by assetId (pixels are NOT embedded — base64 bloat avoided; reuse assets/{paperId}/{version}/{assetId}.webp). Deterministic: same source HTML -> same DocModel (LLM extraction forbidden). Trace: D1, D8, P7.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    meta: DocModelMeta
    fullText: str = Field(
        ...,
        description='Complete reading-order text projection of the paper. Includes section titles, paragraphs, table captions/cells, formula LaTeX, figure captions, list items, and code text. Excludes image bytes, base64 payloads, presigned URLs, and internal object refs. Trace: FR-6, FR-18, QT-9.',
    )
    sections: list[Section] = Field(
        ...,
        description='Top-level sections in reading order; each may nest subsections (recursive). The rich-view DocTOC and the summary map-reduce split (P3) both consume this tree. Trace: Q1-decision (nested section tree).',
    )


class DocModelResultDTO(BaseModel):
    """
    Successful response carrying the structured doc-model. Trace: D4 (self rich-view render), BR-S2 (summary input).
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    status: Literal['ok']
    cached: bool | None = Field(
        None,
        description='True if served from the (paperId, version) cache; false if built on this request (lazy). Trace: D6, BR-30.',
    )
    docModel: DocModel


class DocModelResponse(
    RootModel[
        DocModelResultDTO | BuildingDTO | LicenseUnavailableDTO | SourceUnavailableDTO
    ]
):
    root: (
        DocModelResultDTO | BuildingDTO | LicenseUnavailableDTO | SourceUnavailableDTO
    ) = Field(
        ...,
        description='doc-model contract (DocModel pivot — SSOT spec: aidlc-docs/construction/shared/docmodel.md; gate: construction/plans/docmodel-foundation-pivot-plan.md, D1/D2/D4/D6/D8). The ROOT schema is DocModelResponse — the union (oneOf) returned by getDocModel and branched by U5 ApiClient to surface status (ok | building | license_unavailable | source_unavailable). The bare DocModel artifact (the JSON stored at doc-model/{paperId}/v{version}.json and consumed as the U7 summary input) is defined at #/$defs/DocModel. STATUS: FROZEN for U1 Corpus build v1. Footnotes/references/page numbers are intentionally out of scope; Citation Graph owns structured references and DocModel block ids replace page anchors. Trace: FR-12, FR-17, BR-30, BR-S2.',
        title='DocModelResponse',
    )


Section.model_rebuild()
