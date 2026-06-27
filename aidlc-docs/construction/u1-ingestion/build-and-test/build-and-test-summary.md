# Build and Test Summary — U1 Corpus

**Stage**: CONSTRUCTION / Build and Test
**Unit**: U1 Ingestion / Corpus
**Date**: 2026-06-26
**Branch**: `feature/u1-corpus-code-generation`

## Build Status

- **Shared DTO drift check**: Pass.
- **Ingestion package**: Pass.
- **Summarization consumer**: Pass.
- **Frontend consumer**: Pass.
- **Whitespace check**: Pass.

## Test Execution Summary

### Unit Tests

- `shared/python`: `uv run python tools/generate.py --check` -> passed.
- `shared/python`: `uv run pytest` -> 66 passed.
- `ingestion`: `uv run pytest` -> 129 passed, 1 skipped.
- `ingestion`: `uv run ruff check .` -> passed.
- `ops`: `uv run pytest` -> 42 passed.
- `backend/modules/discovery`: `uv run pytest` -> 53 passed, 3 skipped.
- `backend/modules/summarization`: `uv run pytest` -> 116 passed, 3 skipped.
- `frontend`: targeted `pnpm exec vitest ...` -> 5 files, 19 tests passed.
- `frontend`: `pnpm exec tsc --noEmit` -> passed.
- repo root: `git diff --check` -> passed.

### Integration Smoke

- NEW/CHANGED fake ingestion path covers FullText -> DocModel -> chunk -> embed -> index.
- External source-record smoke covers OpenAlex PDF -> GROBID -> DocModel -> structured `blockRefs[]` -> source watermark.
- arXiv HTML-miss smoke covers PDF/full-text fallback DocModel instead of DLQ.
- Retry/DLQ path preserves source and stage metadata.
- GROBID 429 remains retriable; malformed-PDF 400 remains permanent.
- U7 DocModel endpoint and input refiner consume required `fullText`.
- Frontend classify/useDocModel/viewer targeted tests consume required `fullText` without duplicate rendering.

### Performance

- Dedicated load harness: not added.
- Performance validation path: bounded backfill with worker telemetry, OpenSearch generation validation, and cost/throttle monitoring.

### Security And Resiliency

- Raw PDF bytes remain transient for GROBID extraction.
- GROBID is wired as an internal sidecar, not a public endpoint.
- Provider-backed Semantic Scholar/OpenAlex sources are queued through source-specific jobs; unconfigured providers are skipped with telemetry rather than failing the scheduler.
- Production corpus build preflight requires worker rollout completion/redeploy freeze confirmation before harvest can be queued.
- OpenSearch alias cutover is separated from candidate writes and blocked by validation failure.
- DLQ/retry payloads preserve enough metadata for source-aware reprocess.

## Overall Status

- **Build**: Pass.
- **Tests**: Pass.
- **Ready for Operations placeholder**: Yes, pending review approval.

## Generated Instruction Files

- `build-instructions.md`
- `unit-test-instructions.md`
- `integration-test-instructions.md`
- `performance-test-instructions.md`
- `build-and-test-summary.md`
