# Code Generation Plan - v4-migration

## Overview
This plan details the implementation steps for the Cohere Embed v4.0 migration, including dual-write logic in the U1 Ingestion worker, default index updates in the U2 Discovery API, and the operational migration scripts (provision, backfill, cutover).

## Unit Context
- **Target Unit**: `v4-migration` (Cross-cutting: U1 Ingestion, U2 Discovery, Ops)
- **Implemented Requirements**: FR-17 (Dual-write), NFR-M2 (Blue/Green Migration), NFR-S2 (v4 Model Cutover)
- **Key Patterns**: Fail-Open Dual-Write, Idempotent Backfill, Instant Cutover

## Execution Steps

- [x] **Step 1**: **U1 Ingestion Configuration**
  - **File**: `ingestion/src/docsuri_ingestion/settings.py`
  - **Action**: Add `opensearch_index_v2` (default: `docsuri-corpus-v2`) and `bedrock_model_id_v2` to `Settings`.

- [x] **Step 2**: **U1 Ingestion Dual-Write Implementation**
  - **File**: `ingestion/src/docsuri_ingestion/main.py` (or relevant worker module)
  - **Action**: Update the document ingestion logic to generate embeddings using BOTH the v3 and v4 models. Write the v3 embedding to the v1 index and the v4 embedding to the v2 index. Implement a Fail-Open pattern for the v4 write.

- [x] **Step 3**: **U2 Discovery Configuration**
  - **File**: `backend/modules/discovery/src/discovery/adapters/settings.py`
  - **Action**: Update `_DEFAULT_INDEX` to `docsuri-corpus` (the alias) so it can seamlessly cutover to `v2`.

- [x] **Step 4**: **U2 Discovery Seed Script**
  - **File**: `backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py`
  - **Action**: Update to create `docsuri-corpus-v1`, `docsuri-corpus-v2`, and the `docsuri-corpus` alias pointing to `v1` for local development. Set `v2` dimensions to 1024.

- [x] **Step 5**: **Ops Migration - Provision Script**
  - **File**: `ops/migrations/v4_migration/provision_v2_index.py` (New File)
  - **Action**: Create script to provision `docsuri-corpus-v2` with k-NN mapping (dimension=1024).

- [x] **Step 6**: **Ops Migration - Backfill Script**
  - **File**: `ops/migrations/v4_migration/backfill_v4.py` (New File)
  - **Action**: Create a standalone script to fetch historical data from the arXiv API, embed it using Bedrock (`embed-multilingual-v4.0`), and write to `docsuri-corpus-v2`.

- [x] **Step 7**: **Ops Migration - Cutover Script**
  - **File**: `ops/migrations/v4_migration/cutover_alias.py` (New File)
  - **Action**: Create a script to atomically swap the `docsuri-corpus` alias from `v1` to `v2`.

- [x] **Step 8**: **Documentation Updates**
  - **File**: `aidlc-docs/construction/v4-migration/code/README.md`
  - **Action**: Document the migration execution order and dual-write semantics.
