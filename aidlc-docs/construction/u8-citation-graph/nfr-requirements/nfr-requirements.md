# U8 Citation Graph — NFR Requirements

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-21  
**Inputs**: FR-15, FR-16, NFR-P3, NFR-C1, QT-6, U8 Functional Design

## Scope

U8 provides a login-required backward-reference citation tree for paper detail pages. It does not implement frontend screens in this unit and does not use LLM inference for citations.

## Performance

| ID | Requirement |
| --- | --- |
| NFR-U8-P1 | Cached citation-tree reads should target P50 < 500ms at the backend boundary. |
| NFR-U8-P2 | First provider fetch is outside search SLA NFR-P1 and may return loading, partial, rate-limited, or unavailable states. |
| NFR-U8-P3 | Responses must enforce `depthReturned <= 2` and `visibleNodeCount <= 50`. |
| NFR-U8-P4 | 2-hop expansion must be lazy-loaded per expanded node, not preloaded for the whole graph. |

## Resiliency

| ID | Requirement |
| --- | --- |
| NFR-U8-R1 | Provider calls must use a short timeout and at most one retry. |
| NFR-U8-R2 | Provider timeout/error must degrade cache-first; without cache, return `Unavailable`. |
| NFR-U8-R3 | Provider 429/quota states must return `RateLimited` and may serve cache-only results. |
| NFR-U8-R4 | Snapshot write failure must not fail an otherwise successful tree read; it must be observable. |
| NFR-U8-R5 | Unresolved references must be isolated from save and expand actions. |

## Security

| ID | Requirement |
| --- | --- |
| NFR-U8-S1 | All U8 APIs require the existing authenticated user session. |
| NFR-U8-S2 | Provider API keys must be read from the existing secret/env injection path and never exposed to clients. |
| NFR-U8-S3 | Library save must use the owner-scoped U4 path and must not allow unresolved nodes. |
| NFR-U8-S4 | Error responses must expose safe user states only, not provider credentials or raw stack traces. |

## Cost and Quota

| ID | Requirement |
| --- | --- |
| NFR-U8-C1 | U8 must consume U6 gateway rate limits plus a citation-provider quota counter. |
| NFR-U8-C2 | When quota thresholds are exceeded, U8 must switch to cache-only or `RateLimited`. |
| NFR-U8-C3 | U8 must emit provider status and cache-hit metrics for cost monitoring. |

## Observability

| ID | Requirement |
| --- | --- |
| NFR-U8-O1 | Each tree lookup must emit to U6 ObservabilityHub/EventStore. |
| NFR-U8-O2 | Required event fields: `paperId`, `cacheHit`, `providerStatus`, `nodeCount`, `unresolvedCount`, `depthRequested`, `depthReturned`, `truncated`, `latencyMs`. |
| NFR-U8-O3 | Manual refresh and provider quota/rate-limit states must be distinguishable in telemetry. |

## Test Requirements

| ID | Requirement |
| --- | --- |
| QT-6.1 | Property tests must prove `depthReturned <= 2`. |
| QT-6.2 | Property tests must prove visible nodes never exceed 50. |
| QT-6.3 | Duplicate folding must be idempotent. |
| QT-6.4 | Cycles must stop without unbounded traversal. |
| QT-6.5 | Unresolved entries must never be saveable or expandable. |
| QT-6.6 | DTO roundtrip must preserve citation response shape. |
| QT-6.7 | Default CI tests must use fixture providers and must not call external APIs. |
| QT-6.8 | Real provider contract tests must be opt-in. |

## Traceability

| Source | Covered By |
| --- | --- |
| FR-15 | NFR-U8-P1..P4, NFR-U8-R1..R5, QT-6.1..6.6 |
| FR-16 | NFR-U8-S1..S4, NFR-U8-R5 |
| NFR-P3 | NFR-U8-P1..P2 |
| NFR-C1 | NFR-U8-C1..C3 |
| QT-6 | QT-6.1..6.8 |
