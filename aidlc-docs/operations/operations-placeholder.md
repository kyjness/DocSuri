# operations-placeholder.md — Operations Phase Current State

**Phase**: OPERATIONS  
**Status**: Placeholder acknowledged; no executable operations workflow in current AI-DLC version  
**Date**: 2026-06-26

---

## 1. Current Workflow Boundary

The current AI-DLC rule set defines Operations as a placeholder. Deployment planning,
monitoring setup, incident response, maintenance, and production readiness workflows are
future scope.

Build and test activities are handled in the Construction phase. For the U1 Corpus cycle,
the Construction Build and Test instruction set has been generated, reviewed, and approved
for transition.

## 2. Current U1 Corpus Status

- U1 Corpus Functional Design / NFR Requirements / NFR Design / Infrastructure Design: complete and approved.
- U1 Corpus Code Generation: complete, review findings fixed, and pushed.
- 2026-06-27 follow-up review fix: lazy/eager DocModel fallback policy is unified, and canonical dedup now records arXiv plus applies source priority before external PDF/GROBID work.
- U1 Corpus Build and Test: complete and approved for Operations placeholder transition.
- Latest validation:
  - `shared/python`: schema drift check passed, `pytest` 66 passed
  - `ingestion`: `pytest` 129 passed / 1 skipped, `ruff` passed
  - `ops`: `pytest` 42 passed
  - `backend/modules/discovery`: `pytest` 53 passed / 3 skipped
  - `backend/modules/summarization`: `pytest` 116 passed / 3 skipped
  - `frontend`: targeted vitest 19 passed, `tsc --noEmit` passed
  - repository: `git diff --check` passed

## 3. Not Yet Production-Ready

U1 Corpus is not marked production deployable from this placeholder stage because these
items remain outside the current Operations workflow:

- Production Semantic Scholar/OpenAlex HTTP provider implementation plus credentials/quota decisions
- GROBID sidecar production capacity tuning
- Corpus backfill batch sizing and budget stop threshold
- OpenSearch generation cutover execution
- Existing corpus backfill/reindex to rebuild legacy chunks through DocModel-based chunking
- Multimodal asset rollout for vision-model inputs: flag enablement, non-arXiv/PDF figure strategy, and validation that asset refs resolve to stored private assets
- Production monitoring dashboards and alert routing for the Corpus run

These should be handled by an executable deployment/operations workflow before production
Corpus backfill.

## 4. Extension Compliance Summary

| Extension | Status | Rationale |
|---|---|---|
| Security Baseline | N/A for placeholder execution | No production deployment or IAM/network changes are executed in this phase. Security test instructions were generated in Build and Test. |
| Resiliency Baseline | N/A for placeholder execution | No runtime topology, failover, backup, or alarm resources are created in this phase. Resiliency test instructions were generated in Build and Test. |
| Property-Based Testing | Compliant for generated U1 Corpus code | Corpus PBT and regression suites passed as part of local validation. |

## 5. Recommended Next Executable Work

The current AI-DLC workflow ends here. The next practical engineering work should be one
of the following, depending on planning priority:

1. Open or update the U1 Corpus PR from `feature/u1-corpus-code-generation` to `develop`.
2. After merge, run a bounded Corpus backfill plan using the generated Build and Test instructions.
3. Extend the Operations workflow when executable deployment and monitoring rules are available.
