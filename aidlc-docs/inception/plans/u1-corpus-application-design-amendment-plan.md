# U1 Corpus Application Design Amendment Plan

**Stage**: INCEPTION -> Application Design
**Date**: 2026-06-26
**Scope**: Minimal U1-only amendment after Workflow Planning skip review.

## Decision

- Application Design is executed as a targeted amendment because the old U1 design was arXiv-only and the new FR-6 scope is multisource Corpus + eager DocModel + DocModel Block indexing.
- Units Generation remains skipped because ownership is still U1 Ingestion and no new unit or deployment boundary is introduced.
- No open design questions remain: source priority, dedup keys, eager DocModel, raw PDF non-storage, source watermarks, retry/DLQ, and cost cap were already answered in `requirement-verification-questions-u1-corpus.md` Q1-Q12.

## Checklist

- [x] Update U1 component responsibilities in `components.md`.
- [x] Update U1 method signatures in `component-methods.md`.
- [x] Update U1 service orchestration in `services.md`.
- [x] Update U1 dependency/data-flow notes in `component-dependency.md`.
- [x] Update consolidated summary in `application-design.md`.
- [x] Keep Units Generation skipped and document the reason.
- [x] Validate markdown diff with `git diff --check`.

## Compliance

- **Security Baseline**: Compliant. Raw PDF remains transient only; public exposure stays through DocModel/index records.
- **Resiliency Baseline**: Compliant. Source watermarks, retry/DLQ, alias cutover, and rebuild/backfill stay explicit.
- **Property-Based Testing Partial**: Compliant. QT-9 invariants move to U1 Functional Design and test planning.
