# U9 Personalization — Tech Stack Decisions

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-23

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| TD-U9-1 | Store raw events, interest profiles, and personalization settings in existing RDS Postgres with U9-owned tables. | Reuses current production database; no new service. |
| TD-U9-2 | Add U9 as `backend/modules/personalization/` in the existing backend FastAPI app-shell behind U6 gateway. | Keeps v1 small and consistent with U7/U8 API modules. |
| TD-U9-3 | Record events best-effort from successful caller paths. | Satisfies NFR-P4; U9 does not block search, summary, translation, or library actions. |
| TD-U9-4 | Use lazy/on-demand profile aggregation for v1, with optional later batch correction. | Avoids a speculative worker/ML pipeline. |
| TD-U9-5 | Enforce 90-day active raw-event retention with timestamp purge/filter logic. | Simple and auditable. |
| TD-U9-6 | Use metadata allowlists and reject free-form payloads. | Reduces privacy and injection risk. |
| TD-U9-7 | For user-requested raw-log deletion, delete owner-scoped active rows directly and do not create a U9 backup table. | Simpler privacy model; "delete" means delete unless a future cited compliance requirement needs retention. |
| TD-U9-8 | Search personalization reads only a bounded profile decision; timeout/failure falls back to default search. | Protects search latency and relevance. |
| TD-U9-9 | Emit U9 operational signals through existing U6 ObservabilityHub/EventStore. | No separate telemetry pipeline. |
| TD-U9-10 | Keep U9 DTOs backend-local first; promote to shared schema only when U2/U7/U5 integration requires it. | Avoids premature shared-contract churn. |
| TD-U9-11 | Use unit/PBT tests by default and lightweight DB integration tests for repositories. | Keeps CI deterministic without external services. |
| TD-U9-12 | Use existing Python/Hypothesis stack for QT-7. | Reuses current project test tooling. |

## Persistence Boundary

U9 owns three active logical stores:

- `user_behavior_events`: 90-day raw event input for personalization.
- `user_interest_profile`: bounded aggregate profile and defaults.
- `personalization_settings`: on/off and delete/reset markers.

U9 does not own a backup table for deleted behavior logs in v1. Retention is enforced by direct active-table delete for user requests and a scheduled, idempotent 90-day purge command.

## API Boundary

U9 APIs live in the existing backend app and pass through U6 gateway and U3 session ownership checks. U9 does not introduce a separate ECS service.

## Degradation Boundary

U2, U4, U7, and U5 may call U9 after successful actions or before optional personalization. U9 timeout/failure returns `degraded`, `disabled`, or `no_profile` style decisions and leaves the primary feature path intact.

## Test Boundary

Default CI must not require external services. Property tests cover DTO roundtrip, dedupe, owner isolation, deterministic aggregation, delete/reset behavior, and fail-open default behavior. Repository tests may use the existing opt-in/lightweight database integration style.

## Deferred

- Dedicated personalization service.
- Realtime ML recommendation pipeline.
- Separate recommendation list.
- Full clickstream SDK.
- U9-specific observability pipeline.
- Eager shared DTO publication before U2/U7/U5 integration needs it.
