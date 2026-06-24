# U9 Personalization — NFR Design Patterns

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-23

## Fail-Open Personalization

U9 is optional for the caller's core result.

| U9 Result | Caller Behavior |
| --- | --- |
| profile/defaults available | Apply bounded boost/default suggestion. |
| disabled | Use non-personalized default path. |
| no profile | Use non-personalized default path. |
| timeout/error | Treat as `degraded`; continue with non-personalized default path and emit telemetry. |

U2/U7 must not wait long enough for U9 to dominate search or generation latency. Concrete timeout values are finalized in Code Generation defaults.

## Bounded Profile Read

`PersonalizationReadPort` returns a compact `PersonalizationDecision`; it does not expose raw events. Decisions contain only bounded boosts, defaults, and a reason code.

## Read-Through Lazy Aggregation

1. Read current settings.
2. If disabled, return `disabled`.
3. Read profile.
4. If profile is missing/stale, run lightweight aggregation from active events.
5. If aggregation succeeds, store profile and return decision.
6. If aggregation fails, return previous profile if safe, otherwise default `degraded`.

No v1 aggregation worker is required.

## Direct Active-Table Delete

Raw-log deletion follows this boundary:

1. Select owner-scoped active rows.
2. Delete rows from active `user_behavior_events`.
3. Emit operational status.

Deleted behavior rows are not copied to a U9 backup table. A backup table may be reconsidered only with an explicit legal/compliance retention requirement.

## Scheduled Retention Cleanup

Active raw events older than 90 days are purged by a clock-driven maintenance command, not by lazy cleanup alone. The command must be idempotent:

- repeated runs after a successful purge delete zero additional rows,
- partial failure can be safely retried,
- row counts and failures are emitted through U6.

Retention purge failure must raise a U6 alert because silent failure violates the privacy retention policy.

## Metadata Allowlist

`BehaviorEventRecorder` is the single validation gate. It enforces:

- event type allowlist,
- subject shape validation,
- metadata keys per event type,
- no raw paper text,
- no source-nearby quoted text,
- no credentials, tokens, or free-form click payload.

Repositories only accept validated envelopes.

## U6 Observability Without Behavior Payloads

U9 emits operational counters/status only:

- event record failure,
- aggregation failure,
- degraded decision,
- personalization disabled decision count,
- delete/reset count,
- retention purge success/failure and purged row count.

Telemetry does not include raw event metadata.

## Test Patterns

| Pattern | Coverage |
| --- | --- |
| Property tests | DTO roundtrip, dedupe, owner isolation, deterministic aggregation, delete/reset effect, fail-open default. |
| Repository integration | Direct active delete and idempotent retention purge with lightweight DB test. |
| Unit tests | Metadata allowlist and decision reason cases. |

Default CI does not require external services.
