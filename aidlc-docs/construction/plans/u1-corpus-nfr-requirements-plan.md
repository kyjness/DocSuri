# U1 Corpus NFR Requirements Plan

**Stage**: CONSTRUCTION -> NFR Requirements
**Unit**: U1 Ingestion
**Date**: 2026-06-26
**Scope**: NFR amendment for phase-1 U1 Corpus pipeline.

## Inputs

- `aidlc-docs/construction/u1-ingestion/functional-design/` — 2026-06-26 Corpus priority sections.
- `aidlc-docs/inception/requirements/requirements.md` — FR-6, FR-18, NFR-C1, RES-7/8/9, QT-9, C-1.
- `shared/vector-spec/vector-spec.yaml` — active embedding contract: Cohere Embed v4, specVersion v2, 1024 dimensions.
- Existing production infrastructure choices: OpenSearch, Bedrock, S3, SQS/DLQ, EventBridge, AWS Budget $1600.

## Decision Review

No new `[Answer]:` questions are required. U1 Corpus behavior was already decided in INCEPTION, and the remaining NFR choices have existing repo defaults:

- Use current Python ingestion worker.
- Use OpenSearch for vector + lexical index generation.
- Use Bedrock Cohere Embed v4 / specVersion v2 / 1024 dimensions.
- Use S3 for private FullText/DocModel/assets artifacts.
- Use SQS + DLQ for retries/reprocess.
- Use EventBridge Scheduler for periodic collection.
- Add containerized internal GROBID for Semantic Scholar/OpenAlex PDF extraction.
- Enforce a hard phase-1 build budget gate inside the existing $1600 account/app budget.

## Execution Checklist

- [x] Read NFR Requirements rule details.
- [x] Review current U1 Functional Design and existing U1 NFR Requirements artifacts.
- [x] Confirm no new NFR questions are needed.
- [x] Update `nfr-requirements.md` with U1 Corpus scalability, performance, reliability, security, cost, observability, and PBT requirements.
- [x] Update `tech-stack-decisions.md` with Corpus-specific stack decisions.
- [x] Update `aidlc-state.md` for NFR Requirements completion gate.
- [x] Append NFR Requirements completion prompt to `audit.md`.
- [x] Run diff validation.

## Content Validation

- Mermaid diagrams: none added.
- ASCII diagrams: none added.
- Markdown tables: simple pipe tables only.

## Extension Compliance

- **Security Baseline**: Applicable. Raw PDFs remain transient, GROBID is internal-only, S3 public access is blocked, parsed content is validated.
- **Resiliency Baseline**: Applicable. Source quotas, timeouts, retries, DLQ, source watermarks, and alias rollback are included.
- **Property-Based Testing Partial**: Applicable. QT-9 maps to Hypothesis/PBT checks for dedup, version consistency, DocModel validation, block references, raw PDF non-storage, and DLQ reprocess idempotency.
