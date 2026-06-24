# U9 Personalization — Logical Components

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-23

| Component | Responsibility |
| --- | --- |
| `PersonalizationApi` | Authenticated API handlers for event recording, settings, delete/reset, and personalization decisions. |
| `BehaviorEventRecorder` | Validates event envelope and metadata allowlist, applies dedupe, writes active events best-effort. |
| `PersonalizationSettingsService` | Reads/writes on/off state and delete/reset markers. |
| `ProfileAggregator` | Read-through lazy aggregation from active events into bounded `UserInterestProfile`. |
| `PersonalizationReadPort` | Supplies bounded search boosts and summary/translation defaults to U2/U7. |
| `ActiveBehaviorEventRepository` | Reads/writes active `user_behavior_events`; only active rows feed profile aggregation. |
| `InterestProfileRepository` | Stores aggregate profile and defaults. |
| `RetentionCleanupCommand` | Idempotent scheduled command that purges expired active behavior events and emits success/failure telemetry. |
| `PersonalizationTelemetryPublisher` | Emits operational counters/status to U6 without raw behavior metadata. |

## API Surface

| Route | Purpose |
| --- | --- |
| `POST /api/personalization/events` | Record a frontend-only meaningful event, such as `source_anchor_clicked`. |
| `GET /api/personalization/decision/search` | Return bounded search boost decision for U2. |
| `GET /api/personalization/decision/summary-defaults` | Return summary/translation default suggestions for U7. |
| `PATCH /api/personalization/settings` | Enable or disable personalization. |
| `POST /api/personalization/delete-events` | Delete owner-scoped active raw behavior events directly. |
| `POST /api/personalization/reset-profile` | Clear aggregate profile/defaults. |

## Repository Boundary

`ProfileAggregator` and `PersonalizationReadPort` read only active `user_behavior_events` and aggregate profile rows. User raw-log deletion calls `ActiveBehaviorEventRepository.delete_for_user(userId)` directly; U9 does not create or read a backup table in v1.

## Integration Points

| Caller | Interaction |
| --- | --- |
| U2 Discovery | Reads search decision; emits `search_executed` / `paper_opened` after success. |
| U4 Library | Emits `library_added` / `library_removed` after successful owner-scoped action. |
| U7 Summarization | Reads summary/translation defaults; emits summary/translation/glossary events. |
| U5 Frontend | Calls settings/delete/reset and frontend-only source-anchor event endpoint. |
| U6 Reliability/Ops | Provides gateway/auth path and receives operational telemetry. |

U9 does not own ranking, summary generation, translation generation, library save/delete, frontend rendering, or operational incident routing.
