# Novelty Agent — Tech Stack Decisions

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-29

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| TD-NV-1 | Keep API responsibilities in the existing backend app: create job, get status/result, cancel, approve export. | Avoids gateway timeout and keeps agent work off the request path. |
| TD-NV-2 | Run the agent loop in an existing ECS/Fargate-style worker boundary. | Reuses ingestion/summarization worker patterns; no novelty microservice by default. |
| TD-NV-3 | Store job/event/export metadata in existing RDS and large artifacts in existing S3/object storage pattern. | Matches FR-35 and existing production storage. |
| TD-NV-4 | Provide v1 live progress through streaming/SSE, with polling fallback for reconnect/compatibility. | `nfr-answer.md` Q4 selected B; product needs visible exploration progress. |
| TD-NV-5 | Reuse U2 `full` search through its existing port/API with bounded query, timeout, and budget. | No novelty search index or ranking fork. |
| TD-NV-6 | Run Agent-Browser only server-side in the worker with allowlisted GitHub/dataset sources, query budgets, and timeouts. | Keeps raw user material out of external sites and prevents client-side tool exposure. |
| TD-NV-7 | Keep manuscript parsing in shared ingestion/doc-model or evidence formation parsing, not in novelty business logic. | Preserves shared contract boundary and avoids parser duplication. |
| TD-NV-8 | Defer PDF/DOCX parser support from backend v1. | Current Novelty worker has no PDF/DOCX extraction path; Markdown/TXT object refs cover the lower-cost v1 manuscript scope. |
| TD-NV-9 | Store uploaded manuscript references and parsed artifacts owner-scoped; delete them with novelty session deletion. | Matches privacy and delete requirements. |
| TD-NV-10 | Use user-specific Notion OAuth/explicit connection with encrypted token storage and revocation. | Avoids shared server token and supports owner-scoped export. |
| TD-NV-11 | Reuse U6 CostGuard/rate limit and ObservabilityHub/EventStore. | Cost/observability single authority already exists in shared ports. |
| TD-NV-12 | Validate LLM outputs with schema + required source refs + abstain rules inside novelty Agent. | This is output validation, not a second U6 GroundingEnforcementHook. |
| TD-NV-13 | Use existing Python/Hypothesis for QT-10 backend PBT. | Already present across Python modules. |
| TD-NV-14 | Consider TypeScript fast-check only if Code Generation adds non-trivial frontend state transition logic. | Avoids a speculative dependency. |

## Runtime Boundary

The backend API owns request validation, auth boundary, job creation, status/result reads, cancel, and export approval. The worker owns U2 full calls, Agent-Browser searches, LLM steps, risk analysis, experiment planning, and Notion export execution.

## Storage Boundary

RDS stores owner-scoped job metadata, progress events, export status, and artifact references. S3/object storage stores large stage snapshots and parsed artifact payloads when they exceed practical relational storage size.

## Streaming Boundary

SSE is the preferred v1 progress channel. Polling is still allowed as a fallback for reconnect and clients that cannot keep a stream open. Both surfaces read the same persisted ProgressEvent/stage snapshot model.

## Parsing Boundary

Markdown and TXT manuscript refs are read directly by the Novelty worker. PDF and DOCX parsing must stay in shared parsing or evidence formation before Novelty consumes parsed `EvidenceResult`, `SourceRef`, and attachment/doc-model handles.

## Validation Boundary

Novelty output validation checks schemas, required source refs, unsupported-cell abstain behavior, and DocModel anchor existence. U6 remains the single system-level grounding gateway authority; novelty-local validation does not add another global enforcement hook invocation.

## Deferred

- Novelty-only microservice.
- Separate search index or ranking model.
- Separate cost guard or observability pipeline.
- Client-side Agent-Browser execution.
- News search.
- DOCX upload support and `python-docx` or equivalent parser dependency.
- Mandatory fast-check dependency before frontend logic requires it.
