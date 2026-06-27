# U1 Corpus Functional Design Plan

**Stage**: CONSTRUCTION -> Functional Design
**Unit**: U1 Ingestion
**Date**: 2026-06-26
**Scope**: U1 Corpus phase-1 pipeline amendment. Existing U1 remains the owning unit; no new unit is introduced.

## Inputs

- `aidlc-docs/inception/requirements/requirements.md` — FR-6, FR-18, NFR-C1, QT-9, C-1 U1 Corpus amendments.
- `aidlc-docs/inception/user-stories/stories.md` — US-I1, US-I2, US-I3 U1 Corpus amendments.
- `aidlc-docs/inception/application-design/components.md` and `services.md` — U1 component/service amendments.
- `aidlc-docs/inception/application-design/unit-of-work*.md` — U1 ownership review.
- `aidlc-docs/inception/plans/u1-corpus-workflow-plan.md` — Construction execution decision.

## Decision Review

All functional-design questions that would change business behavior were already answered in INCEPTION by `requirement-verification-questions-u1-corpus.md` Q1-Q12 = A. No new `[Answer]:` questions are needed for this Functional Design pass.

Key inherited decisions:

- Sources: arXiv HTML first, arXiv PDF fallback, Semantic Scholar PDF via GROBID, OpenAlex PDF via GROBID.
- Dedup: DOI -> arXiv id -> normalized title + first author + year, with source priority and full-text quality as winner rules.
- Phase-1 scope: recent AI/ML 1-2 years, OA/indexing-allowed, explicit eager cost cap.
- DocModel: eager for phase-1 Corpus, complete Section/Block model, table rows/cols, formulas LaTeX/MathML, figure AssetRef, provenance/source tier, no vision inference.
- Indexing: DocModel Block chunking, Cohere Embed v4/specVersion v2, new OpenSearch index generation with alias cutover.
- Operations: source-specific watermarks, scheduler, retries, DLQ, reprocess path, ObservabilityHub `emitMetric`/`emitLog`.

## Execution Checklist

- [x] Read Functional Design rule details and content validation rules.
- [x] Review U1 Corpus requirements, stories, application design, unit ownership, and current U1 Functional Design artifacts.
- [x] Determine that no additional Functional Design questions are required.
- [x] Update `domain-entities.md` with U1 Corpus source, dedup, DocModel, chunk, index, watermark, job, and DLQ domain entities.
- [x] Update `business-logic-model.md` with the multisource -> FullText/GROBID -> eager DocModel -> Block chunk -> embedding -> index/S3 pipeline.
- [x] Update `business-rules.md` with Corpus BR rules and QT-9/PBT invariants.
- [x] Update `aidlc-state.md` for U1 Corpus Functional Design completion gate.
- [x] Append Functional Design completion prompt to `audit.md`.
- [x] Run markdown/diff validation checks.

## Content Validation

- Mermaid diagrams: none added in this stage.
- ASCII diagrams: none added in this plan.
- Markdown tables: simple pipe tables only; no nested code fences inside table cells.
- Special characters: arrows are limited to prose/list items and existing AIDLC style.

## Extension Compliance

- **Security Baseline**: Applicable. Raw PDFs remain transient only; public S3 exposure is forbidden; untrusted parsed content must be validated before storage/use.
- **Resiliency Baseline**: Applicable. Source-specific watermarks, retries, DLQ, reprocess paths, and cutover/rollback gates are represented.
- **Property-Based Testing Partial**: Applicable. QT-9 maps to PBT-02/03/07/08/09 blocking invariants for dedup, watermarks, DocModel schema, block references, and retry/DLQ idempotency.
