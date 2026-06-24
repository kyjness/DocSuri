# DocSuri U1 Ingestion

U1 is the asynchronous ingestion worker for the shared DocSuri corpus index. It consumes
arXiv seed, schedule, and new-paper events; validates OA eligibility; stores full text;
embeds chunks with the shared writer role; and writes `docsuri_shared.vector_spec.IndexRecord`
documents to OpenSearch.

## Local Development

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests
ruff check ingestion
```

With `uv`:

```powershell
cd ingestion
uv sync --all-groups
uv run pytest
uv run ruff check .
```

## Entrypoints

```powershell
python -m docsuri_ingestion.cli ingest-one --arxiv-ref 2401.00001v1 --local
python -m docsuri_ingestion.cli trigger-full-rebuild --local
python -m docsuri_ingestion.worker
```

The `--local` mode uses fake adapters for development and tests. Production mode is
fail-closed: missing required environment variables stop the process before any external
call is attempted.

## Runtime Environment

Required in production:

- `DOCSURI_ENV`
- `DOCSURI_AWS_REGION`
- `DOCSURI_S3_BUCKET`
- `DOCSURI_BEDROCK_MODEL_ID`
- `DOCSURI_OPENSEARCH_ENDPOINT`
- `DOCSURI_OPENSEARCH_INDEX`
- `DOCSURI_CONTROL_PLANE_DSN`
- `DOCSURI_SQS_QUEUE_URL`
- `DOCSURI_SQS_DLQ_URL`

Optional policy controls:

- `DOCSURI_INDEX_STATS_TTL_SECONDS` defaults to `60`
- `DOCSURI_ARXIV_RATE_PER_SECOND` defaults to `0.33`
- `DOCSURI_REQUEST_TIMEOUT_SECONDS` defaults to `30`

## Supply Chain Checks

Run dependency and image checks in CI before publishing:

```powershell
uv export --all-groups --format requirements-txt > requirements.lock.txt
pip-audit -r requirements.lock.txt
syft packages dir:. -o spdx-json > sbom.spdx.json
trivy fs --scanners vuln,secret,misconfig .
```

Do not publish images with `latest`; use immutable git SHA or release tags.
