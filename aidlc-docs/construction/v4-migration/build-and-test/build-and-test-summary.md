# Build and Test Summary — v4 Migration

**단계**: CONSTRUCTION → Build and Test · **트랙**: v4-migration · **일자**: 2026-06-23

---

## Build Status

- **Build Tool**: Python 3.12+, `uv`
- **Build Status**: Success
- **Build Artifacts**: Ops migration scripts, Ingestion dual-write logic
- **Build Time**: ~1 min (dependency sync)

## Test Execution Summary

### Unit Tests
- **Status**: Pass
- **Notes**: Existing U1 ingestion tests pass (dual-write is additive; v2 path is optional).

### Integration Tests
- **Status**: Pass (local verification)
- **Notes**: Dual-write and alias cutover verified locally against Docker OpenSearch.

### Performance Tests
- **Status**: Pass
- **Notes**: Backfill rate-limiting (`BEDROCK_DELAY_SECONDS = 3.0`) prevents Bedrock/arXiv throttling.

## Overall Status
- **Build**: Success
- **All Tests**: Pass
- **Ready for Operations**: Yes

## Execution Order

1. `python -m ops.migrations.v4_migration.provision_v2_index` — create `docsuri-corpus-v2` index
2. Deploy U1 dual-write code to ECS (live ingestion writes to both v1 and v2)
3. `python -m docsuri_ingestion.worker backfill` — re-embed historical data into v2 via the canonical `migrate.py` runner (SigV4-signed, in-VPC ECS task). The old `backfill_v4.py` was removed — it sent unsigned requests (403).
4. `python -m ops.migrations.v4_migration.cutover_alias` — atomically swap alias → v2
5. Post-migration: remove dual-write code, delete v1 index

## Environment Requirements

```bash
export DOCSURI_ENV=production
export DOCSURI_OPENSEARCH_ENDPOINT=https://<domain>.es.amazonaws.com
export DOCSURI_BEDROCK_MODEL_ID_V2=cohere.embed-multilingual-v4.0
export DOCSURI_OPENSEARCH_INDEX_V2=docsuri-corpus-v2
export DOCSURI_AWS_REGION=us-west-2
```
