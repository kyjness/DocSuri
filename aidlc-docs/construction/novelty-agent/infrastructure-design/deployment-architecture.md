# Novelty Agent — Deployment Architecture

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-30

## Deployment Units

| Deployment unit | Novelty content |
|---|---|
| Existing API service | job create/status/result/cancel/SSE/export approval routes. |
| Novelty worker | SQS consumer that runs agent stages. |
| Existing RDS PostgreSQL | novelty jobs, progress events, artifact refs, export state, Notion connection metadata. |
| Existing private S3 bucket pattern | stage artifact JSON under `novelty/` prefix. |
| SQS + DLQ | novelty job dispatch and failed job isolation. |
| Existing CloudWatch/U6 | metrics, logs, incident/degraded signals, alarms. |

No separate AWS account, separate public load balancer, novelty-specific search index, or novelty-specific observability stack is introduced.

## Request and Job Flow

| Flow | Path |
|---|---|
| Create job | User -> API -> `novelty_jobs`/initial event -> SQS enqueue. |
| Run job | SQS -> novelty worker -> Evidence/U2/Agent-Browser/LLM/Notion stages -> snapshots/events. |
| Progress | User -> API SSE endpoint -> persisted `novelty_progress_events`. |
| Fallback status | User -> API status/result endpoints -> RDS refs + S3 artifacts. |
| Cancel | User -> API -> cancel flag -> worker checks at stage boundaries. |
| Notion export | User preview/approval -> worker export -> `novelty_exports`. |

## Network Topology

| Component | Network position |
|---|---|
| API service | Existing public ALB/CloudFront path. |
| Novelty worker | Existing ECS/Fargate cluster/VPC pattern. |
| RDS | Existing private database access path/security group. |
| S3 | Private bucket access through IAM. |
| External egress | Worker outbound only, allowlisted and guarded. |

The frontend never calls U2, Agent-Browser, external dataset sites, or Notion directly for novelty work.

## Scaling

| Signal | Use |
|---|---|
| SQS visible messages | Scale worker count up/down. |
| Age of oldest message | Alarm and optional scale signal. |
| CPU/memory | Protect worker task health. |
| DLQ messages | Alarm. |
| CostGuard budget state | Stop/degrade expensive stages; not an autoscaling metric. |

## Configuration

| Variable / secret | Purpose |
|---|---|
| `NOVELTY_AGENT_ENABLED=true` | Deployment-time automatic unit activation. |
| `DOCSURI_NOVELTY_JOB_QUEUE_URL` | Worker queue. |
| `DOCSURI_NOVELTY_ARTIFACT_BUCKET` | Private artifact bucket. |
| `DOCSURI_NOVELTY_ARTIFACT_PREFIX` | `novelty/` prefix. |
| `DOCSURI_NOVELTY_SSE_HEARTBEAT_SECONDS` | SSE keepalive. |
| `DOCSURI_NOVELTY_MAX_WORKER_CONCURRENCY` | Per-worker execution limit. |
| `DOCSURI_NOVELTY_EXTERNAL_ALLOWLIST` | GitHub/dataset/Notion egress allowlist. |
| `NOTION_OAUTH_CLIENT_SECRET` | Secrets Manager secret. |
| `KMS_KEY_ID` | Token envelope encryption. |

## IAM Boundary

| Role | Required permissions |
|---|---|
| API task role | RDS access, SQS send, S3 read refs if needed, U6 telemetry, KMS decrypt for approved token operations only if API builds previews. |
| Worker task role | SQS consume/delete, S3 read/write under `novelty/`, RDS access, KMS encrypt/decrypt for Notion tokens, U6 telemetry, external egress. |
| Event/Alarm roles | CloudWatch alarm publication and existing U6 routes. |

IAM policies must use scoped resources; wildcard actions are not acceptable unless the AWS API lacks resource scoping and the exception is documented.

## Migration Boundary

Code Generation must add custom SQL migrations for novelty tables using the existing migration runner. It must not add Alembic.

Expected migration path:

```text
backend/modules/novelty/migrations/001_create_novelty_tables.sql
```

## Rollout

1. Add migrations and application code.
2. Add CDK resources for queue/DLQ, worker, S3 prefix permissions, alarms, and env vars.
3. Deploy with `NOVELTY_AGENT_ENABLED=true`.
4. Run smoke tests: create job, read status, SSE connects, cancel, degraded source, Notion preview disabled/unconnected path.
5. Watch queue age, DLQ, stage failure, and budget exceeded alarms.

No manual per-unit activation step exists after deployment.
