# Logical Components - Cohere v4 Migration

## 1. Backfill Script (Migration Worker)
- **Role**: Re-fetches historical data from the original upstream source (arXiv API) and writes embeddings to the `docsuri-corpus-v2` OpenSearch index using the `embed-multilingual-v4.0` model.
- **Pattern Integration**: Runs asynchronously or as a manual batch job with rate limiting.

## 2. Dual-Write Adapter
- **Role**: Extends the ingestion traffic in U1 and dispatches the write to both `docsuri-corpus-v1` (using v3 model) and `docsuri-corpus-v2` (using v4 model) indices.
- **Pattern Integration**: Fail-open design; logs v2 failures but does not fail the primary ingestion pipeline if v1 succeeds.

## 3. Alias Router
- **Role**: OpenSearch alias (e.g., `docsuri-corpus`) that initially points to `docsuri-corpus-v1`. Upon migration completion, the alias is atomically swapped to point to `docsuri-corpus-v2`.
- **Pattern Integration**: Enables zero-downtime Instant Cutover for the U2 Discovery search API.
