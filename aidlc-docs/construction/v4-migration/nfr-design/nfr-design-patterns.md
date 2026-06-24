# NFR Design Patterns - Cohere v4 Migration

## 1. Resilience Patterns
- **Fail-Open Dual-Write**: During the migration period, document ingestion will dual-write to both `docsuri-corpus-v1` and `docsuri-corpus-v2`. If the write to `v2` (using the v4 model) fails, the system will log the failure and gracefully continue, marking the overall task as successful as long as the write to `v1` succeeds. The backfill process will catch any missing data later.
- **Idempotent Backfill**: The backfill script re-fetches text from the original upstream source (arXiv API) and writes to `v2`. Since multiple passes might be necessary (e.g., to catch failed dual-writes), the backfill script's writes are idempotent.

## 2. Scalability Patterns
- **Backfill Rate Limiting**: The backfill script will respect the arXiv API rate limits and AWS Bedrock Cohere rate limits to avoid throttling, connection exhaustion, and unexpected cost spikes.
- **Instant Cutover**: By pre-warming the `docsuri-corpus-v2` index and ensuring all data is present, the search alias cutover is an atomic, instant metadata operation, allowing for zero downtime.

## 3. Performance Patterns
- **Cost & Dimensionality Efficiency**: Using `embed-multilingual-v4.0` with 1024 dimensions allows parity with v3 while improving search relevance and avoiding bloat in the OpenSearch vector database memory overhead.

## 4. Security Patterns
- **IAM Scoping**: The migration scripts and ingestion roles will require explicit IAM permissions for the new Bedrock `embed-multilingual-v4.0` model ARN, adhering to the principle of least privilege.
