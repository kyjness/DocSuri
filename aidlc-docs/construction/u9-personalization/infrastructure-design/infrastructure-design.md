# U9 Personalization — Infrastructure Design

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-23  
**Feedback applied**: `plan_feedback.md` removed the backup-table design and requires idempotent scheduled cleanup with U6 alerting.

## Infrastructure Mapping

| U9 concern | Infrastructure choice |
| --- | --- |
| API routes and decision reads | Existing FastAPI backend app-shell in the current ECS/Fargate API deployment. |
| Auth, session, rate path | Existing U6 gateway and U3 owner-scoped session path. |
| Raw behavior events | Existing RDS PostgreSQL table `user_behavior_events`. |
| Interest profiles | Existing RDS PostgreSQL table `user_interest_profiles`. |
| Personalization settings | Existing RDS PostgreSQL table `personalization_settings`. |
| Raw-log deletion | Direct owner-scoped delete from `user_behavior_events`; no U9 backup table. |
| Retention cleanup | EventBridge scheduled ECS task using the existing backend container image and a U9 maintenance command. |
| Observability and alerting | Existing U6 ObservabilityHub/EventStore and CloudWatch alarms. |
| Feature flag | Backend environment variable `PERSONALIZATION_ENABLED`. |

## Compute

U9 API code runs inside the existing backend API task as `backend/modules/personalization/`. No new always-on ECS service is required.

The only new infrastructure surface is a scheduled maintenance task:

| Item | Decision |
| --- | --- |
| Scheduler | EventBridge schedule, daily. |
| Target | ECS RunTask using the existing backend task definition/image. |
| Command | U9 retention cleanup command, finalized during Code Generation. |
| Runtime behavior | Delete active raw events older than 90 days. |
| Idempotency | Re-running after success deletes zero additional rows. |
| Failure handling | Emit U6 telemetry and trigger alerting. |

## Storage

U9 uses existing RDS PostgreSQL. Required migrations add only active U9 tables:

| Table | Purpose | Retention |
| --- | --- | --- |
| `user_behavior_events` | Owner-scoped meaningful behavior events used for profile aggregation. | 90 days, scheduled purge. |
| `user_interest_profiles` | Bounded aggregate profile and summary/translation defaults. | Cleared by profile reset; updated by lazy aggregation. |
| `personalization_settings` | Enabled flag and delete/reset markers. | Kept while account exists. |

There is no `user_behavior_event_backup` table in v1. A backup table may be reconsidered only with a cited legal/compliance retention requirement.

## Messaging

No SQS queue is introduced for behavior logging in v1. Event writes are best-effort RDS writes from successful caller paths. If recording fails, the caller's main feature remains successful and U9 emits U6 operational telemetry.

## Networking

U9 reuses the existing request path:

| Layer | Reused component |
| --- | --- |
| Public edge | Existing CloudFront/ALB path. |
| Backend routing | Existing backend app-shell route mounting. |
| Auth/rate/security | Existing U6 middleware and U3 session. |
| Database connectivity | Existing backend-to-RDS security group and connection configuration. |

No new public endpoint, load balancer, VPC, subnet, or security group is required.

## Observability

U9 emits operational counters/status only:

| Signal | Destination | Payload rule |
| --- | --- | --- |
| Event record failure | U6 ObservabilityHub/EventStore | No raw behavior metadata. |
| Aggregation failure | U6 ObservabilityHub/EventStore | No raw behavior metadata. |
| Degraded decision | U6 ObservabilityHub/EventStore | Reason code only. |
| Delete/reset count | U6 ObservabilityHub/EventStore | Count/status only. |
| Retention purge success/failure | U6 ObservabilityHub/EventStore and CloudWatch alarm path | Row count/status only. |

Retention purge failure is alert-worthy because silent failure can violate the 90-day privacy retention policy.

## Security and Privacy

| Requirement | Infrastructure decision |
| --- | --- |
| Owner isolation | All API and DB access uses existing authenticated user identity. |
| Data minimization | U9 stores only allowlisted event metadata. |
| Delete semantics | User raw-log deletion performs direct active-table delete with no backup copy. |
| Telemetry boundary | U6 receives operational status, not raw behavior payloads. |
| Access boundary | No new analytics database or BI pipeline can read behavior rows in v1. |

## Cost and Capacity

U9 adds negligible steady-state infrastructure cost because it reuses the existing backend and RDS. The scheduled ECS cleanup task runs briefly once per day and is the only incremental compute surface.

## Extension Compliance

| Extension | Status | Rationale |
| --- | --- | --- |
| Security Baseline | Compliant | Owner-scoped access, metadata allowlist, no backup table for deleted behavior logs, no raw payload telemetry. |
| Resiliency Baseline | Compliant | U9 is fail-open for caller features; retention cleanup is idempotent and alerts on failure. |
| Property-Based Testing | N/A for infrastructure design | QT-7 test properties are defined in NFR docs and will be implemented during Code Generation. |

