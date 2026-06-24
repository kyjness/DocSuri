# U8 Citation Graph — Infrastructure Components

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-21

| Component | Infrastructure |
| --- | --- |
| Backend routes | Existing FastAPI backend app-shell. |
| Auth/rate path | Existing U6 gateway/session/rate-limit path. |
| Snapshot cache | Current code: process-local in-memory TTL seam. Production target: existing Redis, key prefix `citation_graph:v1:`. |
| Provider secret | `SEMANTIC_SCHOLAR_API_KEY` through existing server secret/env injection. |
| Feature flag | `CITATION_GRAPH_ENABLED=true`. |
| Telemetry | Existing U6 ObservabilityHub/EventStore. |
| Library save | Existing U4 owner-scoped library API/path. |

No new ECS service, database, S3 bucket, queue, graph DB, or frontend deployment is required for v1.
