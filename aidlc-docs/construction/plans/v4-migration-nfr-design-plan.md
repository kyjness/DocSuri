# NFR Design Plan - v4-migration

## Design Execution Plan

- [x] Analyze NFR Requirements (NFR-M2, NFR-S2) for the migration.
- [x] Determine Resilience Patterns (handling dual-write failures, backfill interruptions).
- [x] Determine Scalability Patterns (backfill throughput vs OpenSearch/Bedrock limits).
- [x] Define Logical Components (Backfill script, Dual-write adapter, Alias router).
- [x] Ask clarification questions to resolve ambiguities in failure handling and data sourcing.

## Clarification Questions

To ensure a robust NFR design for the migration, please answer the following questions:

### Question 1
When dual-writing new documents to both the existing v3 index and the new v4 index, if the write to the **v4 index** fails (e.g., Bedrock rate limit or OpenSearch timeout), how should the ingestion pipeline behave?

A) **Fail-Closed**: Both v3 and v4 writes must succeed. If v4 fails, the entire ingestion task fails and will be retried later.
B) **Fail-Open (Graceful)**: Log the v4 failure, but as long as the v3 write succeeds, mark the ingestion as successful. (Missing v4 data will be caught by the backfill script later).
C) Other (please describe after [Answer]: tag below)

[Answer]: B. Log the v4 failure, but as long as the v3 write succeeds, mark the ingestion as successful. (Missing v4 data will be caught by the backfill script later).

### Question 2
For the historical data backfill script (re-embedding existing data to v4), what should be the primary source of truth for retrieving the text chunks to embed?

A) **OpenSearch v1 Index**: Iterate over the existing `docsuri-corpus-v1` index using the Scroll API to retrieve chunks and metadata, then re-embed and write to v2.
B) **Original Source**: Re-fetch the text from the original upstream source (arXiv API) or relational DB, process it again, and write to v2.
C) Other (please describe after [Answer]: tag below)

[Answer]: B. Re-fetch the text from the original upstream source (arXiv API) or relational DB, process it again, and write to v2.
