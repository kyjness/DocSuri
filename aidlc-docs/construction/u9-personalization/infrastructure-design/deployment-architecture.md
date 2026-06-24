# U9 Personalization — Deployment Architecture

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-23

## Deployment Units

| Deployment unit | U9 content |
| --- | --- |
| Existing API service | U9 routes, recorder, profile read port, settings/delete/reset handlers. |
| Existing RDS PostgreSQL | U9 migrations and tables. |
| Scheduled ECS task | Daily retention cleanup command. |
| Existing U6 observability | U9 counters, degradation events, retention purge alerts. |

No separate U9 API service, worker service, queue, Redis cache, S3 bucket, OpenSearch index, or analytics lake is added.

## Request Paths

| Path | Flow |
| --- | --- |
| Event recording | U2/U4/U7 successful action or U5 frontend anchor event -> backend U9 route/service -> RDS best-effort write -> U6 telemetry on failure. |
| Search decision | U2 -> `PersonalizationReadPort` -> settings/profile read or lazy aggregation -> bounded boost decision. |
| Summary/translation defaults | U7 -> `PersonalizationReadPort` -> settings/profile read or lazy aggregation -> bounded defaults. |
| User raw-log deletion | U5 -> U9 delete endpoint -> owner-scoped direct delete from `user_behavior_events` -> next decision sees no deleted signals. |
| Profile reset | U5 -> U9 reset endpoint -> clear `user_interest_profiles` row/defaults -> next decision returns `no_profile`. |

## Scheduled Cleanup

| Field | Decision |
| --- | --- |
| Schedule | Daily EventBridge schedule. |
| Execution | ECS RunTask with existing backend image. |
| Scope | Delete `user_behavior_events` rows older than 90 days. |
| Idempotency | Delete predicate is timestamp based; repeated runs are safe. |
| Failure signal | U6 telemetry plus CloudWatch alarm path. |
| Success signal | U6 metric with purged row count. |

Lazy cleanup alone is not allowed because inactive users may never trigger a read/write after their events expire.

## Configuration

| Environment variable | Purpose | Default |
| --- | --- | --- |
| `PERSONALIZATION_ENABLED` | Server-side feature flag for U9 route/decision behavior. | `false` until deployment is ready. |
| `PERSONALIZATION_RAW_EVENT_RETENTION_DAYS` | Active raw behavior event retention period. | `90`. |
| `PERSONALIZATION_DECISION_TIMEOUT_MS` | U2/U7 read timeout before fail-open default. | Finalized in Code Generation. |

## Migration Boundary

U9 Code Generation must add RDS migrations for:

- `user_behavior_events`
- `user_interest_profiles`
- `personalization_settings`

It must not add `user_behavior_event_backup` in v1.

## IAM Boundary

The API task role keeps existing RDS and U6 telemetry permissions. The scheduled ECS task needs only the same backend runtime permissions plus permission for EventBridge to run the task. No S3, SQS, OpenSearch, or Bedrock permissions are introduced by U9.

## Rollout

1. Deploy migrations.
2. Deploy backend with `PERSONALIZATION_ENABLED=false`.
3. Enable scheduled retention cleanup.
4. Enable U9 API/decision path after smoke checks.
5. Watch U6 metrics for record failure, degraded decisions, and retention purge failures.

