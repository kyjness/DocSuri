# Build Instructions — U1 Corpus

## Prerequisites

- **Build Tool**: `uv` with Python 3.11+ for Python packages, `pnpm` for frontend checks.
- **Core Packages**: `shared/python`, `ingestion`, `backend/modules/summarization`, `frontend`.
- **External Runtime Services**: AWS S3, RDS/Postgres, SQS/DLQ, OpenSearch, Bedrock, ECS Fargate, internal GROBID sidecar.
- **Build-Time Env**: none required for local compile/test.
- **Runtime Env**: `DOCSURI_S3_BUCKET`, `DOCSURI_CONTROL_PLANE_DSN`, `DOCSURI_SQS_QUEUE_URL`, `DOCSURI_SQS_DLQ_URL`, `DOCSURI_OPENSEARCH_ENDPOINT`, `DOCSURI_OPENSEARCH_INDEX`, `DOCSURI_OPENSEARCH_ALIAS`, `DOCSURI_BEDROCK_MODEL_ID`, `DOCSURI_CORPUS_SOURCES`, `DOCSURI_GROBID_URL`, `DOCSURI_MULTIMODAL_ASSETS_ENABLED`, `DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED`.

## Build Steps

### 1. Verify Shared DTO Generation

```bash
cd shared/python
uv run python tools/generate.py --check
```

Expected: `_generated/` matches `shared/dtos/*.schema.json`.

### 2. Verify Ingestion Package

```bash
cd ingestion
uv run ruff check .
uv run pytest
```

Expected: ruff passes and ingestion tests pass.

### 3. Verify Summarization Consumer

```bash
cd backend/modules/summarization
uv run pytest
```

Expected: summarization tests pass with skipped env-gated tests only.

### 4. Verify Frontend Consumer

```bash
cd frontend
pnpm exec vitest run test/classifyDocModel.test.ts test/useDocModel.test.ts test/classifySummarize.test.ts test/glossaryBadge.test.tsx test/docModelViewer.test.tsx
pnpm exec tsc --noEmit
```

Expected: targeted DocModel consumer tests and typecheck pass.

### 5. Apply Database Migration Before Deploy

```bash
cd ingestion
psql "$DOCSURI_CONTROL_PLANE_DSN" -f migrations/postgres/003_corpus_control_plane.sql
```

This adds corpus control-plane tables for canonical dedup state, version state, generation tracking, and job items.

### 6. Production Corpus Build Sequence

1. Deploy the new ingestion worker image and wait until the ECS service is stable with only the new task definition running.
2. Freeze ingestion worker redeploys for the harvest window.
3. Set `DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED=true`, `DOCSURI_MULTIMODAL_ASSETS_ENABLED=true`, and keep `DOCSURI_BEDROCK_MODEL_ID_V2` unset.
4. Provision the new OpenSearch on-disk candidate index.
5. Run `python -m docsuri_ingestion.cli trigger-full-rebuild`.
6. Harvest/backfill, validate the candidate generation, then switch the alias.

## Build Artifacts

- Ingestion worker package and ECS task image.
- Shared generated Python DTOs.
- Frontend curated DocModel type.
- Postgres migration `003_corpus_control_plane.sql`.
- CDK task definition update with GROBID sidecar env.

## Troubleshooting

- **DocModel validation fails**: rerun shared DTO generation and confirm all DocModel fixtures include `fullText`.
- **GROBID unavailable**: keep `DOCSURI_GROBID_URL` unset for arXiv-only local tests; production worker uses the sidecar URL.
- **Corpus rebuild preflight fails**: verify worker rollout completion, redeploy freeze, multimodal asset enablement, external-source GROBID URL, and that `DOCSURI_BEDROCK_MODEL_ID_V2` is unset.
- **OpenSearch cutover blocked**: inspect candidate generation stats before alias switch; do not force alias cutover on an empty candidate.
