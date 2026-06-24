# Cohere Embed v4.0 Migration - Requirements Clarification Questions

Please answer the following questions to help clarify the requirements for migrating from Cohere Embed v3 to v4.0.

## Question 1
Cohere Embed v4 vectors will be incompatible with existing v3 vectors in OpenSearch. What is the strategy for migrating the existing `docsuri-corpus-v1` index?

A) Blue/Green indexing: Create a new index (`docsuri-corpus-v2`), re-embed and backfill all existing data in the background, then switch the search alias (zero downtime).

B) In-place or direct re-indexing: Delete and recreate the existing index or overwrite data (will cause search downtime/disruption).

C) Other (please describe after [Answer]: tag below)

[Answer]: A. Create a new index (`docsuri-corpus-v2`), re-embed and backfill all existing data in the background, then switch the search alias (zero downtime).

## Question 2
Cohere v4 introduces new models and variable dimensionality (e.g., you can specify lower dimensions to save storage, though 1024 is standard). Which model and dimension setting should be used?

A) `embed-multilingual-v4.0` with standard dimensions (1024).

B) `embed-multilingual-v4.0` with compressed/lower dimensions (e.g., 512 or 256) to save OpenSearch storage/memory.

C) `embed-english-v4.0` (if we no longer need multilingual support).

D) Other (please describe after [Answer]: tag below)

[Answer]: A. `embed-multilingual-v4.0` with standard dimensions (1024).

## Question 3
How should the U1 Ingestion pipeline behave while the historical data is being migrated?

A) Dual-write: Write new incoming documents to both the v3 index and the new v4 index until migration is fully complete.

B) Pause ingestion: Temporarily halt the ingestion pipeline until the v4 migration completes.

C) Write only to v4: New documents go only to v4, accepting temporary search inconsistencies if clients are still using v3.

D) Other (please describe after [Answer]: tag below)

[Answer]: A. Write new incoming documents to both the v3 index and the new v4 index until migration is fully complete.

## Question 4
How should the U2 Discovery (Search API) transition to v4?

A) Instant Cutover: Once the v4 index is ready, immediately point all search queries to use the v4 embedding model and index (no API contract changes).

B) A/B Testing Mode: Temporarily allow clients to request either v3 or v4 embeddings via an API parameter to compare relevance before removing v3.

C) Other (please describe after [Answer]: tag below)

[Answer]: A. Instant Cutover: Once the v4 index is ready, immediately point all search queries to use the v4 embedding model and index (no API contract changes).
