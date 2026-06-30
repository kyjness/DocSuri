# Novelty Agent — Infrastructure Design

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-30  
**Inputs**: Functional Design, NFR Requirements, NFR Design, `infradesign-answer.md`

## Infrastructure Mapping

| Novelty concern | Infrastructure choice |
|---|---|
| API routes | Existing backend FastAPI app-shell in the current ECS/Fargate API deployment. |
| Worker execution | ECS/Fargate worker using the existing API image pattern, consuming a novelty SQS queue. |
| Queue | Dedicated SQS queue `docsuri-novelty-job-queue` with DLQ. |
| Metadata/state | Existing RDS PostgreSQL with owner-scoped tables. |
| Large artifacts | Existing private S3 artifact/papers bucket pattern under a dedicated `novelty/` prefix. |
| Progress streaming | Existing API service adds SSE endpoint; polling/status remains fallback. |
| Secrets | Notion app credentials in Secrets Manager; user tokens encrypted in RDS with KMS/envelope encryption. |
| Egress | Worker-side allowlist/config plus request-level SSRF guard for external calls. |
| Observability | Existing CloudWatch/U6 ObservabilityHub/EventStore. |

## Compute

| Component | Decision |
|---|---|
| API | Existing backend service; no novelty-only API service. |
| Worker | New novelty worker service/task using existing ECS/Fargate worker pattern. |
| Desired count | Scale-to-zero at rest where practical. |
| Autoscaling | Queue depth, age of oldest message, CPU, and memory. |
| CostGuard | Budget circuit breaker and degraded gate; not an autoscaling metric. |

Worker deployment follows the ingestion/summarization pattern. The worker is allowed to call U2 full, Agent-Browser, LLM, shared parser/evidence ports, and Notion only from the server side.

## Messaging

| Queue | Decision |
|---|---|
| Main queue | Dedicated novelty SQS queue. |
| DLQ | Dedicated novelty DLQ. |
| Retention | 14 days, matching existing worker queue pattern unless Code Generation chooses a stricter value. |
| Visibility timeout | Based on the longest bounded stage duration. |
| Retry | SQS handles message-level retry; worker handles source-level bounded retry/degraded. |

The novelty worker must not share ingestion or summarization queues. Queue isolation prevents a slow novelty workload from starving existing workers.

## RDS Schema

Infrastructure Design reserves these owner-scoped tables:

| Table | Purpose |
|---|---|
| `novelty_jobs` | job metadata, owner, state, cancel flag, timestamps. |
| `novelty_progress_events` | persisted progress events for SSE and polling. |
| `novelty_artifacts` | stage artifact metadata and S3 refs. |
| `novelty_exports` | Notion preview/approval/export state and metadata. |
| `notion_connections` | user-level Notion connection metadata and encrypted token reference/value. |

Migration path uses the existing custom SQL runner: numbered `.sql` files under `backend/modules/novelty/migrations/` plus the existing `_migrations` table. Alembic is not introduced.

## S3 Artifact Storage

Use the existing private bucket pattern and a dedicated prefix:

```text
novelty/{ownerHash}/{jobId}/{stage}/{artifactId}.json
```

`ownerHash` helps lifecycle separation but is not the authorization boundary. Owner isolation is enforced in API/service/repository code before returning artifact refs or signed reads.

## SSE and API Edge

SSE is implemented on the existing API service path over the existing ALB/CloudFront route.

| Concern | Decision |
|---|---|
| Endpoint | `GET /api/novelty/jobs/{job_id}/events` |
| Read model | persisted `novelty_progress_events` |
| Keepalive | Code/infra must define heartbeat/idle timeout behavior. |
| Replay | No Last-Event-ID event-log replay in v1. |
| Fallback | `GET /api/novelty/jobs/{job_id}` and result polling. |

SSE is a new component in this repo. Polling remains the low-risk fallback.

## Secrets and Token Storage

| Secret | Storage |
|---|---|
| Notion OAuth client secret | Secrets Manager. |
| User Notion access token | Encrypted RDS column using KMS/envelope encryption. |
| Token metadata | RDS metadata columns, owner-scoped. |

User-specific Notion tokens are not stored as one Secrets Manager secret per user because that does not scale operationally. Tokens are never stored in job payloads or artifact JSON.

## Network and Egress Controls

Novelty introduces the first untrusted external egress surface for agent browsing.

| Egress target | Control |
|---|---|
| GitHub | allowlisted host/config, timeout, response cap. |
| dataset sources | allowlisted host/config, timeout, response cap. |
| Notion | allowlisted Notion API/MCP endpoint, encrypted token use. |
| arbitrary user URL | not allowed in v1. |

Request-level SSRF guard is required for any fetched URL. Raw manuscript text and full Evidence payloads are never sent as external query text.

## Observability and Alarms

| Signal | Destination |
|---|---|
| queue age/depth | CloudWatch alarm. |
| DLQ count | CloudWatch alarm. |
| stage failure/degraded count | U6 ObservabilityHub/EventStore. |
| Notion export failure | U6 + CloudWatch alarm path. |
| budget exceeded | U6 CostGuard/Observability. |
| half-baked completion | U6 incident signal when job completes without required snapshots. |

Telemetry payloads must not include raw manuscript, raw Evidence, Notion token, or full external search query contents.

## Unit Activation

Deployment must activate the unit automatically. Any deployment environment flag for novelty must default to enabled with an explicit value such as `NOVELTY_AGENT_ENABLED=true`; there is no separate manual unit activation step after deployment.

## Extension Compliance

| Extension | Status | Rationale |
|---|---|---|
| Security Baseline | Compliant | RDS/S3 encryption, owner-scoped access, token encryption, SSRF/egress controls, no raw payload telemetry. |
| Resiliency Baseline | Compliant | Dedicated queue/DLQ, worker backpressure, source degraded behavior, CloudWatch/U6 alarms. |
| Property-Based Testing | N/A for infrastructure design | QT-10 properties are defined; implementation belongs to Code Generation. |
