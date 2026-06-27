# Integration Test Instructions — U1 Corpus

## Local Smoke Scenarios

### FullText to DocModel to Index

```bash
cd ingestion
uv run pytest tests/test_docmodel_build_job.py tests/test_orchestration.py
```

Expected:
- NEW paper builds DocModel before index write.
- CHANGED paper replaces stale chunks.
- OpenSearch candidate generation validation blocks empty candidates.
- Alias cutover remains separate from write path.

### U7 DocModel Read Compatibility

```bash
cd backend/modules/summarization
uv run pytest tests/test_docmodel_input.py tests/test_docmodel_endpoint.py
```

Expected:
- `S3DocModelReader` keeps bare paper id key normalization.
- `InputRefiner.refine_doc_model` projects sections/tables/formulas/captions from DocModel.
- Root `fullText` stays aligned with section projection.

### Frontend Rich View Compatibility

```bash
cd frontend
pnpm exec vitest run test/classifyDocModel.test.ts test/useDocModel.test.ts test/docModelViewer.test.tsx
```

Expected:
- `classifyDocModelResponse` accepts required `fullText`.
- lazy build polling is unchanged.
- `DocModelViewer` still renders section tree, table data, and figure join through assets.

## Env-Gated Production Smoke

Run after deploying migration and worker task:

1. Wait for ECS rollout completion: every ingestion task must run the new task definition.
2. Freeze ingestion worker redeploys for the harvest window.
3. Set `DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED=true` and `DOCSURI_MULTIMODAL_ASSETS_ENABLED=true`; keep `DOCSURI_BEDROCK_MODEL_ID_V2` unset.
4. Provision the new OpenSearch on-disk candidate index.
5. Enable only arXiv source first: `DOCSURI_CORPUS_SOURCES=ARXIV`.
6. Ingest one known OA paper.
7. Confirm S3 full text and `doc-model/{paperId}/v{version}.json` exist.
8. Confirm OpenSearch candidate index document count is greater than zero.
9. Run generation validation.
10. Switch alias only after validation passes.
11. Query U7 `GET /api/papers/{id}/doc-model?version={version}`.

## Cleanup

- Do not delete active alias targets during smoke.
- Roll back by keeping or restoring the previous OpenSearch alias target.
- DLQ reprocess should reuse original pipeline metadata and idempotent upsert paths.
