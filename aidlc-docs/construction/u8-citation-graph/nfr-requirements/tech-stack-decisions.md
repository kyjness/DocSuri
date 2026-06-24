# U8 Citation Graph — Tech Stack Decisions

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-21

## Decisions

| ID | Decision | Rationale |
| --- | --- | --- |
| TD-U8-1 | Start with Semantic Scholar Graph API as the only citation provider. | One provider is enough for v1; add OpenAlex only when coverage data proves the need. |
| TD-U8-2 | Read provider credentials from the existing ECS/Secrets Manager/env path. | No new secret mechanism. |
| TD-U8-3 | Target 7-day citation snapshots through a snapshot-store seam; current code ships process-local in-memory cache, production wiring should swap Redis TTL cache. | Keeps v1 small while preserving the Redis production path. |
| TD-U8-4 | Keep U8 in the existing FastAPI backend app-shell behind U6 gateway. | No separate service until load requires it. |
| TD-U8-5 | Keep U8 DTOs backend-local until FE paper-detail integration needs shared schemas. | Avoid premature shared-contract churn. |
| TD-U8-6 | Emit U8 events through U6 ObservabilityHub/EventStore. | Reuses existing operational path. |
| TD-U8-7 | Use U8 minimal metadata adapter for U4 Library save. | Avoid extra search/card lookups during citation save. |
| TD-U8-8 | Test with fixture providers by default and opt-in real provider contract tests. | CI remains deterministic and free of external API dependency. |
| TD-U8-9 | Use existing Python/Hypothesis property-test stack for QT-6. | Reuses current PBT tooling. |

## Provider Boundary

Semantic Scholar is used only for bibliographic citation metadata. U8 sends paper identifiers and metadata, not paper full text.

## Cache Boundary

Current v1 keys are process-local and include root paper id plus expansion node. Redis snapshot keys should later include provider, root paper id, direction, and expansion node when production wiring replaces the in-memory seam.

## Integration Boundary

U8 backend APIs are added to the existing backend app. Frontend paper-detail buttons are out of scope for this unit because that branch owns the page.

## Deferred

- OpenAlex fallback.
- Durable RDS/S3 citation snapshots.
- Graph database.
- Shared DTO publication before FE integration.
