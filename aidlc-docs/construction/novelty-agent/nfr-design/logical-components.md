# Novelty Agent — Logical Components

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-29

## Components

| Component | Responsibility |
|---|---|
| `NoveltyApiController` | Authenticated job create/status/result/cancel/export-approval endpoints. |
| `NoveltyJobService` | Request validation, owner checks, initial job/event creation, queue enqueue. |
| `NoveltyJobRepository` | RDS-backed job metadata, current state, owner scope, cancel flag. |
| `ProgressEventRepository` | RDS-backed persisted progress events for SSE and polling. |
| `ArtifactStore` | Stage snapshot refs in RDS and large JSON payloads in S3/object storage. |
| `NoveltyJobQueue` | SQS job enqueue/dequeue boundary. |
| `NoveltyWorker` | Runs evidence, U2 full, external search, validation, candidates, plan, export. |
| `EvidenceFormationClient` | Adapter to provisional `EvidenceFormationPort`; no upstream internals import. |
| `U2FullSearchClient` | Existing U2 `full` search adapter with query/time/budget bounds. |
| `ExternalSearchAdapter` | Server-side Agent-Browser GitHub/dataset search with allowlist and sanitized queries. |
| `NoveltyOutputValidator` | Schema/source_ref/abstain/anchor checks for similar work, candidates, plans. |
| `ProgressStreamController` | SSE endpoint reading persisted progress state; polling fallback shares read model. |
| `NotionExportAdapter` | User-approved Notion export with encrypted token read and failure state. |
| `NoveltyTelemetryPublisher` | Emits job/stage/source/budget/export metrics to U6. |

## API Surface

| Route | Purpose |
|---|---|
| `POST /api/novelty/jobs` | Create novelty job and enqueue worker task. |
| `GET /api/novelty/jobs/{job_id}` | Read current job state and summary. |
| `GET /api/novelty/jobs/{job_id}/events` | SSE progress stream. |
| `GET /api/novelty/jobs/{job_id}/result` | Read available stage snapshots/final result. |
| `POST /api/novelty/jobs/{job_id}/cancel` | Set cooperative cancel flag. |
| `POST /api/novelty/jobs/{job_id}/notion/preview` | Build export preview from internal result. |
| `POST /api/novelty/jobs/{job_id}/notion/approve` | Approve and enqueue/export Notion save. |

## Worker Stages

| Stage | Components |
|---|---|
| `retrieving_corpus` | `EvidenceFormationClient`, `NoveltyJobRepository`, `ProgressEventRepository` |
| `searching_external` | `U2FullSearchClient`, `ExternalSearchAdapter`, `ArtifactStore` |
| `summarizing_prior_work` | `NoveltyOutputValidator`, `ArtifactStore` |
| `checking_similarity` | shared parser/evidence output, risk analyzer, `ArtifactStore` |
| `forming_ideas` | candidate generation, `NoveltyOutputValidator` |
| `planning_experiment` | experiment plan generation, `NoveltyOutputValidator` |
| `exporting_notion` | `NotionExportAdapter`, export state update |

## Persistence Boundary

| Data | Store |
|---|---|
| job metadata/current state/cancel flag | RDS |
| progress events | RDS |
| artifact refs | RDS |
| large stage artifacts | S3/object storage |
| Notion export state | RDS |
| Notion token | encrypted token store/secrets path, not job payload |

## Integration Boundaries

| Dependency | Boundary |
|---|---|
| EvidenceFormationPort | Provisional shared port; implementation blocked on upstream freeze or fixture adapter. |
| U2 full | Existing search API/port, bounded request. |
| Agent-Browser | Server-side worker only, allowlisted sources. |
| U6 CostGuard | Budget state and rate limiting; not concurrency by itself. |
| U6 ObservabilityHub | Metrics/logs only, no raw manuscripts or tokens. |
| Notion MCP | Greenfield adapter, approval-gated. |
| Frontend | SSE + polling/status/result views, degraded visible. |

## Known Greenfield Components

| Component | Reason |
|---|---|
| `ProgressStreamController` | Repo currently has no SSE/EventSource implementation. |
| `NotionExportAdapter` | Repo currently has no Notion integration. |
| `EvidenceFormationClient` | Port is documented but provisional and not implemented here. |

## Non-Goals

- DOCX parser in v1.
- Last-Event-ID replay store.
- Novelty-specific microservice.
- Novelty-specific cost or observability authority.
- U6 grounding hook clone.
- Client-side Agent-Browser execution.
