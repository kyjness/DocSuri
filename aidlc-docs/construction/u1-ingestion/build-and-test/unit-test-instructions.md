# Unit Test Execution — U1 Corpus

## Commands

### Shared Contract

```bash
cd shared/python
uv run python tools/generate.py --check
```

### Ingestion

```bash
cd ingestion
uv run pytest
uv run ruff check .
```

### Summarization Consumer

```bash
cd backend/modules/summarization
uv run pytest
```

### Frontend Consumer

```bash
cd frontend
pnpm exec vitest run test/classifyDocModel.test.ts test/useDocModel.test.ts test/classifySummarize.test.ts test/glossaryBadge.test.tsx test/docModelViewer.test.tsx
pnpm exec tsc --noEmit
```

## Expected Results

- Shared schema drift check: pass.
- Ingestion: `121 passed, 1 skipped`; ruff pass.
- Summarization: `116 passed, 3 skipped`.
- Frontend targeted vitest: `5 files, 19 tests passed`; typecheck pass.
- Repo whitespace: `git diff --check` pass.

## Coverage Notes

- DocModel `fullText` schema and parser projection.
- Eager DocModel build before index exposure.
- DocModel block-aware chunking and `block_refs`.
- Canonical key and source watermark property tests.
- Source adapter/GROBID network-free fake tests.
- Retry/DLQ source and stage metadata preservation.
- U7 and frontend DocModel consumer compatibility.
