# Novelty Agent — NFR Requirements

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-29  
**Inputs**: FR-30..35, NFR-P5/R3, QT-10, Functional Design, `nfr-answer.md`

## Scope

Novelty Agent runs long-running research-assist jobs from natural language input or uploaded manuscripts. It reuses `EvidenceFormationPort`, U2 `full` search, U6 CostGuard/ObservabilityHub, existing RDS/S3 storage patterns, and server-side Agent-Browser/Notion execution. It does not create a separate search index, separate grounding authority, novelty score, paper-writing output, or code skeleton.

## Performance

| ID | Requirement |
|---|---|
| NFR-NV-P1 | Job creation, status lookup, cancel, and export approval APIs must return quickly and must not synchronously run the whole agent loop. |
| NFR-NV-P2 | Agent execution must run in a worker boundary. Long U2 full, Agent-Browser, LLM, and Notion calls are off the request path. |
| NFR-NV-P3 | U2 full search must use a bounded query set, max paper count, timeout, and per-job budget. |
| NFR-NV-P4 | v1 progress UX requires streaming/SSE. Polling fallback may exist for reconnect or compatibility, but the primary product behavior is live progress. |
| NFR-NV-P5 | LLM output validation failures must degrade or fail the affected stage without discarding prior successful snapshots. |

## Scalability

| ID | Requirement |
|---|---|
| NFR-NV-SC1 | v1 reuses existing backend/API and worker deployment patterns; a novelty-only microservice is not introduced unless NFR Design proves it necessary. |
| NFR-NV-SC2 | External source fan-out is bounded by per-job source, query, page, and timeout limits. |
| NFR-NV-SC3 | Large stage artifacts may be stored in S3/object storage; RDS stores owner-scoped metadata, state, events, and references. |
| NFR-NV-SC4 | Worker concurrency must be capped so U2 full, Agent-Browser, and LLM calls do not starve existing workloads. |

## Availability and Resiliency

| ID | Requirement |
|---|---|
| NFR-NV-R1 | GitHub, dataset, U2 full, risk analyzer, LLM, and Notion failures are source/stage-specific degraded states when partial results remain usable. |
| NFR-NV-R2 | EvidenceFormationPort abstain or failure is handled at job creation/retrieval stage as abstain, retry, or failed, because Evidence is the first-order input. |
| NFR-NV-R3 | Stage snapshots must make reconnect and partial-result display possible after worker or client interruption. |
| NFR-NV-R4 | Notion export failure must not delete or corrupt internal novelty results. |
| NFR-NV-R5 | Cancelled jobs must stop further external calls when practical and preserve already completed snapshots for owner review/delete. |

## Security and Privacy

| ID | Requirement |
|---|---|
| NFR-NV-SEC1 | All job, input, artifact, event, and export access is owner-scoped through existing U3/U6 authenticated paths. |
| NFR-NV-SEC2 | Agent-Browser searches use only topic, keywords, anonymized summaries, paper titles, or technology names. Raw manuscript text and full Evidence payloads are not sent to external websites. |
| NFR-NV-SEC3 | Uploaded manuscripts and parsed artifacts are internal owner-scoped data and are deleted with the novelty session unless retention is explicitly changed later. |
| NFR-NV-SEC4 | Notion export requires user-specific OAuth or explicit connection; tokens must be encrypted at rest and revocable. |
| NFR-NV-SEC5 | Notion export sends only user-approved preview content. It is never automatic. |
| NFR-NV-SEC6 | User-facing failures hide parser, tool, MCP, token, stack trace, and infrastructure details. |
| NFR-NV-SEC7 | Manuscript parsing belongs in the shared ingestion/doc-model or evidence formation parsing boundary, not inside novelty Agent business logic. |

## Cost and Budget

| ID | Requirement |
|---|---|
| NFR-NV-C1 | U6 CostGuard/rate limit is the single budget authority. Novelty Agent does not create a separate cost system. |
| NFR-NV-C2 | Per-job budgets cover U2 full search, LLM calls, Agent-Browser steps, Notion MCP export, and parser work. |
| NFR-NV-C3 | Budget exhaustion returns partial results with `degraded` or `failed` state and a user-safe explanation. |

## Observability

| ID | Requirement |
|---|---|
| NFR-NV-O1 | Novelty Agent emits through existing U6 ObservabilityHub/EventStore. |
| NFR-NV-O2 | Required metrics: job count, stage latency, source degraded count, U2 full usage, Agent-Browser usage, LLM validation failure, Notion failure, budget exceeded, cancel count. |
| NFR-NV-O3 | Observability payloads must not include raw manuscripts, raw Evidence, Notion tokens, or external search full query contents beyond sanitized summaries. |
| NFR-NV-O4 | Half-baked result incidents are surfaced when required stage snapshots are missing but the job claims completion. |

## LLM and Grounding Validation

| ID | Requirement |
|---|---|
| NFR-NV-V1 | Similar work rows, novelty candidates, and experiment plans must pass schema validation. |
| NFR-NV-V2 | Required source refs must be present for supported claims; unsupported cells must abstain instead of hallucinating. |
| NFR-NV-V3 | This is novelty-local output validation, not a second U6 `GroundingEnforcementHook` invocation site. |
| NFR-NV-V4 | Anchor existence may reuse the shared DocModel/anchor utility direction from `ports.md` and `docmodel.md`; enforcement policy remains local to novelty outputs. |

## Manuscript Parsing

| ID | Requirement |
|---|---|
| NFR-NV-MP1 | v1 backend manuscript analysis supports Markdown and TXT object refs only. PDF and DOCX parser support is deferred until a shared extraction/upload handle path exists. |
| NFR-NV-MP2 | Novelty Agent consumes parsed Evidence/SourceRef only; parser failures must produce user-safe parse failure states without leaking document internals. |

## Test Requirements

| ID | Requirement |
|---|---|
| QT-10.1 | SourceRef DTO roundtrip preserves source identity and DocModel anchor. |
| QT-10.2 | Source normalization is idempotent for paper, GitHub, and dataset artifacts. |
| QT-10.3 | Dedupe is idempotent and preserves one representative per canonical key. |
| QT-10.4 | Job state transition rejects invalid edges and terminal-state reentry. |
| QT-10.5 | ExperimentPlan always contains required fields and source refs. |
| QT-10.6 | Owner isolation prevents cross-user job/input/artifact/export leakage. |
| QT-10.7 | Notion export cannot reach `exported` without preview and approval. |
| QT-10.8 | UI state mapping covers every progress state, including `degraded` and `failed`. |
| QT-10.9 | PBT uses existing Python/Hypothesis for backend pure functions and DTOs; TypeScript fast-check is only considered if Code scope adds non-trivial frontend state logic. |

## Traceability

| Source | Covered By |
|---|---|
| FR-30 | NFR-NV-P1/P2, NFR-NV-SEC1/SEC7, NFR-NV-MP1..MP2 |
| FR-31 | NFR-NV-P3, NFR-NV-SC2, NFR-NV-R1/R2 |
| FR-32 | NFR-NV-V1..V4 |
| FR-33 | QT-10.5, NFR-NV-V1/V2 |
| FR-34 | NFR-NV-SEC3, NFR-NV-R1 |
| FR-35 | NFR-NV-P4, NFR-NV-R3/R4/R5, NFR-NV-SEC4/SEC5 |
| NFR-P5/R3 | NFR-NV-P1..P5, NFR-NV-R1..R5 |
| QT-10 | QT-10.1..10.9 |
