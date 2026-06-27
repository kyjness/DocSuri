# U1 Corpus Infrastructure Design Plan

**Stage**: CONSTRUCTION -> Infrastructure Design
**Unit**: U1 Ingestion
**Date**: 2026-06-26
**Scope**: Infrastructure amendment for phase-1 U1 Corpus pipeline.

## Inputs

- `aidlc-docs/construction/u1-ingestion/functional-design/`
- `aidlc-docs/construction/u1-ingestion/nfr-requirements/`
- `aidlc-docs/construction/u1-ingestion/nfr-design/`
- Existing CDK references: `ops/cdk/stacks/ingestion_stack.py`, `search_stack.py`, `compute_stack.py`

## Decision Review

No new `[Answer]:` questions are required. The existing AWS deployment already fixes the main infrastructure choices:

- ECS Fargate ingestion worker.
- Existing `docsuri-ingestion-queue` and `docsuri-ingestion-dlq`.
- Existing `docsuri-papers-fulltext-{account}` S3 bucket.
- Existing OpenSearch domain `docsuri-papers`.
- Existing RDS/Postgres control plane.
- Existing EventBridge schedule pattern.
- Existing Bedrock Cohere Embed v4 profile.
- Existing AWS Budget `$1600/month`.

## Execution Checklist

- [x] Read Infrastructure Design rule details.
- [x] Review U1 Corpus design/NFR artifacts and existing infra docs.
- [x] Review current CDK infrastructure mappings.
- [x] Update `infrastructure-design.md` with Corpus resource mapping.
- [x] Update `deployment-architecture.md` with Corpus deployment topology.
- [x] Apply PR review correction within Infrastructure Design scope: DocModel `fullText`, multimodal blocks, AssetRef storage boundary, and removal of premature code/schema/test changes.
- [x] Update `aidlc-state.md` for Infrastructure Design completion gate.
- [x] Append Infrastructure Design completion prompt to `audit.md`.
- [x] Run diff validation.

## Content Validation

- Mermaid diagrams: none added in this plan or amendment.
- ASCII diagrams: none added in this plan or amendment.
- Markdown tables: simple pipe tables only.

## Extension Compliance

- **Security Baseline**: Applicable. No public GROBID endpoint, raw PDFs transient only, private S3, least-privilege IAM, no wildcard permissions.
- **Resiliency Baseline**: Applicable. Existing queue/DLQ, source schedules, watermark alarms, cutover rollback, and budget stop are mapped.
- **Property-Based Testing Partial**: Applicable. Infrastructure supports QT-9 testability via isolated generation, DLQ replay, and artifact manifests.
