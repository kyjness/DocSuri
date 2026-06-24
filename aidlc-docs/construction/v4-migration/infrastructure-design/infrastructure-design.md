# Infrastructure Design - Cohere v4 Migration

## 1. Storage Infrastructure (OpenSearch)
- **New Index (`docsuri-corpus-v2`)**: A new OpenSearch index will be created with k-NN vector mappings configured for 1024-dimensional vectors. This index will coexist with `docsuri-corpus-v1` on the existing OpenSearch domain provisioned by the `Docsuri-Search` CDK stack.
- **Index Alias (`docsuri-corpus`)**: A routing alias used by the U2 Discovery API. Initially, it points to `v1`.

## 2. Compute Infrastructure (Migration Script)
- **Execution Environment**: The historical data backfill script will run locally on a developer/operator machine. It connects securely to AWS resources using local AWS credentials/SSO.

## 3. Alias Cutover Infrastructure
- **Automated Cutover**: Upon successfully confirming that all data from the upstream source (arXiv API) has been embedded and written to `docsuri-corpus-v2`, the local backfill script will invoke the OpenSearch `_aliases` API to atomically remove `v1` and add `v2` to the `docsuri-corpus` alias.

## 4. Shared Infrastructure Impacts
- The migration process reuses the existing OpenSearch domain, Bedrock execution roles, and the ingestion pipelines. It introduces no new managed AWS services, only data structures within existing services.
