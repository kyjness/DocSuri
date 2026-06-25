# Cohere v4 Migration

This module tracks the code generation and updates implemented for the Cohere v4 model migration (`embed-multilingual-v4.0`).

## What was Changed

1. **U1 Ingestion Settings (`ingestion/src/docsuri_ingestion/settings.py`)**: Added `DOCSURI_OPENSEARCH_INDEX_V2` and `DOCSURI_BEDROCK_MODEL_ID_V2`.
2. **U1 Dual-Write Logic (`ingestion/src/docsuri_ingestion/application.py` & `runtime.py`)**: Added Fail-Open dual-write logic in the pipeline to write to `docsuri-corpus-v2`.
3. **U2 Discovery (`backend/modules/discovery/src/discovery/adapters/settings.py`)**: Reconfigured `_DEFAULT_INDEX` to the `docsuri-corpus` alias to prepare for cutover.
4. **Seed Script**: Updated local seeding script to mock both indices and an alias.
5. **Ops Migration Scripts (`ops/migrations/v4_migration/`)**:
   - `provision_v2_index.py`: Creates `docsuri-corpus-v2`.
   - `cutover_alias.py`: Swaps the `docsuri-corpus` alias to `v2`.

> **Canonical runner:** `ingestion/src/docsuri_ingestion/migrate.py`, invoked in-VPC as a one-off ECS task
> via the worker entrypoint (`python -m docsuri_ingestion.worker {provision|backfill|cutover}`). It SigV4-signs,
> uses the OAI harvest path, and supports a `DOCSURI_BACKFILL_START/END` window. The standalone `backfill_v4.py`
> was **removed** — it sent unsigned requests (403) and used the rate-limited Atom re-fetch (429). Use `migrate.py`.
