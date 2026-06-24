# U9 Personalization — NFR Requirements

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-06-23  
**Inputs**: FR-18, FR-19, FR-20, NFR-P4, QT-7, U9 Functional Design

## Scope

U9 records meaningful user behavior events, aggregates owner-scoped interest profiles, and supplies bounded personalization decisions for search and summary/translation defaults. It does not create a recommendation feed, full clickstream collection, real-time ML pipeline, or separate deployment service.

## Performance

| ID | Requirement |
| --- | --- |
| NFR-U9-P1 | Event recording must be best-effort and must not turn a successful caller action into a failure. |
| NFR-U9-P2 | Search personalization must use only a bounded profile read; timeout/failure must immediately fall back to non-personalized search. |
| NFR-U9-P3 | Summary/translation defaults must be suggestions only and must not block generation when U9 is unavailable. |
| NFR-U9-P4 | Profile aggregation must be lazy/on-demand for v1; batch correction may be added only when measured stale-profile cost justifies it. |

## Scalability

| ID | Requirement |
| --- | --- |
| NFR-U9-SC1 | v1 capacity target is users in the hundreds to low thousands with meaningful domain events only. |
| NFR-U9-SC2 | Raw behavior events are retained for 90 days by default and must be purgeable by timestamp. |
| NFR-U9-SC3 | Aggregation must operate on bounded event windows and bounded output weights. |

## Availability and Resiliency

| ID | Requirement |
| --- | --- |
| NFR-U9-R1 | U9 event store, profile store, or aggregation failure must degrade to default non-personalized behavior. |
| NFR-U9-R2 | U9 degraded states must be observable through U6 but must not surface as modal user interruptions. |
| NFR-U9-R3 | Delete/reset API failures may fail that control request, but must not affect unrelated search/summary/library actions. |

## Security and Privacy

| ID | Requirement |
| --- | --- |
| NFR-U9-SEC1 | All U9 data access must be owner-scoped through the existing U3/U6 authenticated path. |
| NFR-U9-SEC2 | Metadata must use an allowlist. Raw paper text, anchor-adjacent source text, credentials, internal tokens, and free-form click payloads must not be stored. |
| NFR-U9-SEC3 | Personalization data must remain separate from U6 operational telemetry; U6 receives only operational degradation metrics. |
| NFR-U9-SEC4 | User controls must support personalization off, raw event deletion, and profile reset as separate actions. |
| NFR-U9-SEC5 | Raw event deletion must remove active-table rows from personalization use immediately after request success. |
| NFR-U9-SEC6 | U9 must not create a backup table for user-requested raw behavior log deletion unless a future legal/compliance requirement explicitly requires it. |

## Retention, Delete, and Reset

| ID | Requirement |
| --- | --- |
| NFR-U9-D1 | Raw events in the active table are subject to a 90-day retention policy. |
| NFR-U9-D2 | User raw-log deletion deletes owner-scoped active rows directly from `user_behavior_events`; deleted behavior rows are not copied to a U9 backup table. |
| NFR-U9-D3 | Retention purge must run on a clock, not only lazily on user activity, so inactive users' expired events are also removed. |
| NFR-U9-D4 | Profile reset deletes or clears aggregate profile/default rows so the next personalization decision returns `no_profile` or default behavior. |
| NFR-U9-D5 | Delete/reset success must affect the next personalization decision. |
| NFR-U9-D6 | The retention cleanup command must be idempotent and safe to retry. |

## Observability

| ID | Requirement |
| --- | --- |
| NFR-U9-O1 | U9 must emit through existing U6 ObservabilityHub/EventStore. |
| NFR-U9-O2 | Required metrics: event record failure rate, aggregation failure rate, degraded decision count, delete/reset count, retention purge success/failure, and purged row count. |
| NFR-U9-O3 | Observability events must not include raw behavior payloads beyond operational counts/status. |
| NFR-U9-O4 | Retention purge failure must trigger U6 alerting because silent purge failure becomes a privacy retention violation. |

## Test Requirements

| ID | Requirement |
| --- | --- |
| QT-7.1 | BehaviorEvent DTO roundtrip must preserve event type, subject, metadata, and dedupe key. |
| QT-7.2 | Duplicate events with the same dedupe key must not affect a profile twice. |
| QT-7.3 | Events from user A must never affect user B profile or decisions. |
| QT-7.4 | Aggregation must be deterministic for the same event set. |
| QT-7.5 | Raw-log deletion must remove active-table events from future personalization decisions. |
| QT-7.6 | Profile reset must remove aggregate/default signals from future personalization decisions. |
| QT-7.7 | U9 read/record failure must return or allow non-personalized behavior. |
| QT-7.8 | Default CI must run without external services; DB repository tests may be lightweight integration tests. |

## Traceability

| Source | Covered By |
| --- | --- |
| FR-18 | NFR-U9-P1, NFR-U9-SEC1..SEC3, QT-7.1..7.3 |
| FR-19 | NFR-U9-SC1..SC3, NFR-U9-D1..D5, QT-7.4..7.6 |
| FR-20 | NFR-U9-P2..P4, NFR-U9-R1..R3, QT-7.7 |
| NFR-P4 | NFR-U9-P1..P4, NFR-U9-R1..R3 |
| QT-7 | QT-7.1..7.8 |
