# Contract Test Instructions

## Purpose

Validate that U1 writes and consumes shared contracts without drift.

## Contract Sources

- `shared/vector-spec/vector-spec.yaml`
- `shared/vector-spec/index-record.schema.json`
- `shared/events/ingestion.schema.json`
- `shared/python/src/docsuri_shared/`

## Test Scenarios

### Scenario 1: IndexRecord Contract

- Description: U1 assembled records must validate against generated `docsuri_shared.IndexRecord`.
- Existing coverage:
  - `IndexRecordAssembler` creates `IndexRecord` objects directly.
  - PBT verifies chunk-to-record cardinality and embedding alignment.

Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_properties.py
```

Expected result: all generated records satisfy the shared pydantic model.

### Scenario 2: Embedding Space Contract

- Description: U1 writer must use `EMBEDDING_SPEC.input_type_writer == "search_document"`
  and vectors must be 1024 dimensions.
- Existing coverage:
  - `assert_writer_embedding_role`
  - `EmbeddingBatch` dimension validation
  - `BedrockCohereEmbeddingPort` dimension validation

Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_domain_units.py ingestion/tests/test_properties.py
```

### Scenario 3: Ingestion Failure Signal Contract

- Description: U1 failure signal must use `docsuri_shared.events.IngestionFailureSignal`.
- Existing coverage:
  - `IngestFailureHandler.emit_failure_signal`
  - orchestration failure tests

Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_orchestration.py
```

## Additional Shared Contract Validation

Run shared package tests when shared schemas change:

```powershell
$env:PYTHONPATH="shared/python/src"
python -m pytest shared/python/tests
```
# U9 Personalization Contract Test Instructions — 2026-06-23

U9 v1 contracts are backend-local. Shared DTO promotion is deferred until U2/U7/U5 integration requires it.

Current contract checks:

```powershell
python -m pytest backend/tests/test_personalization.py -q
```

Covered contracts:

- behavior event request shape
- metadata allowlist
- decision response shape
- settings/delete/reset response shape

Future contract tests should be added when U2/U7/U5 call U9 directly.

---

# U11 Novelty Agent Contract Test Instructions — 2026-06-30

U11 v1 contracts are backend-local plus provisional adapter seams for U2 full search, Agent-Browser, similarity check, and Notion export.

Current contract checks:

```powershell
python -m pytest backend/tests/test_novelty.py -q
```

Covered contracts:

- job request/result/progress DTO shape
- manuscript content-type boundary: Markdown and TXT accepted; PDF/DOCX rejected until parser/upload handle support exists
- supported artifact outputs require `sourceRefs`
- experiment-plan artifacts require research question, novelty angle, hypotheses, baselines, procedure, datasets, metrics, resources, risks, evidence status, and source refs
- Notion export cannot complete before preview approval
- SSE progress events encode persisted job progress

Future contract tests should be added when real U2 full-search, Agent-Browser, and Notion adapters replace the no-op seams.

---

# Agent Chat Frontend Contract Test Instructions — 2026-07-01

Agent Chat Frontend v1 uses a frontend API seam that mirrors the planned backend session APIs.
The real backend adapter is not implemented in this frontend slice.

Current contract checks:

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- tsc --noEmit
corepack pnpm@9.15.9 --dir frontend exec -- vitest run test/agentChatReducer.test.ts test/agentChatScreen.test.tsx --reporter=dot
```

Covered contracts:

- `AgentMode` accepts `evidence` and `novelty`.
- `ApiClient` exposes `listAgentSessions`, `loadAgentSession`, `deleteAgentSession`, and `sendAgentMessage`.
- `MockTransport` implements the frontend seam through `/api/research/jobs` and `/api/novelty/jobs`.
- frontend send payload carries `mode`, `content`, and attachment metadata.
- timeline and assistant responses remain typed through `AgentSendMessageResult`.

Future contract tests should be added when backend research/novelty session APIs replace the mock transport.

---
