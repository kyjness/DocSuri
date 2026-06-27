# U1 Corpus NFR Design Plan

**Stage**: CONSTRUCTION -> NFR Design
**Unit**: U1 Ingestion
**Date**: 2026-06-26
**Scope**: NFR design amendment for phase-1 U1 Corpus pipeline.

## Inputs

- `aidlc-docs/construction/u1-ingestion/nfr-requirements/nfr-requirements.md` — U1 Corpus NFR priority section.
- `aidlc-docs/construction/u1-ingestion/nfr-requirements/tech-stack-decisions.md` — TD-C1~TD-C8.
- `aidlc-docs/construction/u1-ingestion/functional-design/` — U1 Corpus priority sections.
- Existing runtime choices: OpenSearch, Bedrock Cohere Embed v4, S3, SQS/DLQ, EventBridge, AWS Budget $1600.

## Decision Review

No new `[Answer]:` questions are required. The NFR design can inherit the already approved NFR Requirements decisions:

- Keep the existing Python worker and add source adapters inside it.
- Add internal GROBID as the PDF structure extraction component.
- Use deterministic HTML/TEI parsers for DocModel.
- Use SQS queues and DLQs for stage retry/reprocess.
- Use EventBridge Scheduler for source-specific collection.
- Use private S3 and the existing control-plane DB for artifacts/provenance/watermarks.
- Use OpenSearch generation + alias cutover for DocModel Block index rollout.
- Use Bedrock Cohere Embed v4/specVersion v2 with cost gating.

## Execution Checklist

- [x] Read NFR Design rule details.
- [x] Review U1 Corpus NFR Requirements and existing NFR Design artifacts.
- [x] Confirm no new NFR Design questions are needed.
- [x] Update `logical-components.md` with Corpus components and topology.
- [x] Update `nfr-design-patterns.md` with Corpus resilience, consistency, cost, security, and cutover patterns.
- [x] Update `aidlc-state.md` for NFR Design completion gate.
- [x] Append NFR Design completion prompt to `audit.md`.
- [x] Run diff validation.

## Content Validation

- Mermaid diagrams: none added in this plan or amendment.
- ASCII diagrams: none added in this plan or amendment.
- Markdown tables: simple pipe tables only.

## Extension Compliance

- **Security Baseline**: Applicable. Internal GROBID only, transient raw PDFs, private S3, parser hardening, least-privilege IAM.
- **Resiliency Baseline**: Applicable. Stage retry/DLQ, source watermarks, generation cutover/rollback, quota-aware circuit breakers.
- **Property-Based Testing Partial**: Applicable. QT-9 invariants map to PBT checks for dedup, watermarks, version consistency, DocModel validation, block refs, raw PDF non-storage, and DLQ reprocess.
