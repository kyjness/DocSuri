# Novelty Agent — NFR Design Patterns

**Unit**: Novelty Agent  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-29  
**Inputs**: NFR Requirements, `nfr-design-review.md`

## Async Job Pattern

Novelty analysis runs as an async job:

1. Backend API validates owner and creates `NoveltyJob`.
2. API stores initial `queued` event and enqueues work.
3. ECS/Fargate worker consumes the job.
4. Worker writes stage snapshots and progress events.
5. Frontend reads progress through SSE and can fall back to status/result polling.

The API does not run U2 full, Agent-Browser, LLM, risk analysis, or Notion export inside the request.

## Queue and Worker Pattern

Use the existing SQS + ECS/Fargate worker pattern. SQS visibility timeout and DLQ handle message-level retry. The job handler handles source-level retry and degraded decisions.

| Concern | Pattern |
|---|---|
| Message retry | SQS visibility timeout and DLQ. |
| Source retry | Short bounded retry inside the worker stage. |
| Backpressure | Worker count, per-worker concurrency, queue depth, and U6 budget state. |
| Shutdown | Finish current bounded stage or leave message for retry. |

## Source-Level Retry and Degraded Pattern

U2 full, Agent-Browser, LLM, risk analysis, and Notion have separate timeout/retry policies. Retry exhaustion does not automatically fail the whole job.

| Source / Stage | Failure Behavior |
|---|---|
| EvidenceFormationPort | `abstain`, retry, or failed at the first-order evidence stage. Implementation waits on upstream contract freeze. |
| U2 full | Source degraded; continue with Evidence and other sources if usable. |
| GitHub/dataset | Source degraded; continue with internal corpus. |
| LLM output validation | Stage degraded/failed; keep prior snapshots. |
| Notion export | Export failed; internal novelty result remains intact. |

## Progress Streaming Pattern

SSE is the primary v1 progress channel, but it is a new component in this repo. Keep the v1 shape small:

- persisted `ProgressEvent` is the read model,
- SSE emits current and newly persisted events,
- status/result polling reads the same persisted state,
- reconnect recovery uses current status and latest snapshots,
- Last-Event-ID event-log replay is excluded from v1.

This preserves live exploration UX without building a full resumable event log.

## Artifact Snapshot Pattern

RDS stores metadata and references. Large JSON artifacts are written to S3/object storage with stage-level keys.

| Artifact | Storage Pattern |
|---|---|
| job metadata | RDS |
| progress events | RDS |
| export status | RDS |
| similar work table | S3 JSON + RDS ref when large |
| external findings | S3 JSON + RDS ref when large |
| risk signals | S3 JSON + RDS ref when large |
| novelty candidates | S3 JSON + RDS ref when large |
| experiment plan | S3 JSON + RDS ref when large |

## Output Validation Pattern

Novelty output validation is local to the novelty unit:

- schema validation,
- required `source_refs`,
- unsupported cell abstain,
- DocModel anchor existence through shared anchor utility direction,
- no U6 `GroundingEnforcementHook` duplication.

U6 remains the system gateway grounding authority. Novelty validation prevents unsupported novelty artifacts from being stored as supported claims.

## Manuscript Parsing Pattern

v1 backend manuscript analysis supports Markdown and TXT object refs only. PDF and DOCX are deferred until shared ingestion/doc-model or evidence parser boundaries provide a parsed attachment handle. Novelty worker consumes parsed attachment/Evidence handles and does not add a separate PDF/DOCX parser.

`EvidenceFormationPort` is still PROVISIONAL. Code generation for novelty must either wait for the upstream port freeze or use a narrow fixture/adapter seam without importing upstream internals.

## Notion Export Safety Pattern

Notion is greenfield in this repo, so the first design is deliberately small:

| State | Meaning |
|---|---|
| `not_requested` | No export flow started. |
| `preview_ready` | Internal result rendered for approval. |
| `approved` | User approved export. |
| `exporting` | Worker is calling Notion. |
| `exported` | Export succeeded and location is stored. |
| `failed` | Export failed; internal result remains. |

Tokens are user-specific, encrypted at rest, revocable, and never stored in job payloads.

## Cooperative Cancel Pattern

Cancel is cooperative. The worker checks a cancel flag at stage boundaries and before new external calls. Completed snapshots stay available for owner review or deletion. Cancel does not instantly delete artifacts.

## Security Compliance

| Rule | Status | Rationale |
|---|---|---|
| SECURITY-01 | Deferred to Infra | RDS/S3/token encryption mapping belongs to Infrastructure Design. |
| SECURITY-05 | Compliant | API/input/output schemas and state transitions are explicit design constraints. |
| SECURITY-08 | Compliant | All job, artifact, and export reads/writes are owner-scoped. |
| SECURITY-09 | Compliant | User-facing parser/tool/export errors hide internals. |
| SECURITY-12 | Deferred to Infra/Code | Notion token storage must use encrypted secret storage. |
| SECURITY-15 | Compliant | Source-level failures degrade or fail safely without corrupting prior results. |

## Resiliency Compliance

| Rule | Status | Rationale |
|---|---|---|
| RESILIENCY-01 | Compliant | Critical worker, queue, U2, Agent-Browser, LLM, Notion, RDS/S3 dependencies are identified. |
| RESILIENCY-05 | Compliant | Progress, degraded counts, stage latency, and export failures are observable. |
| RESILIENCY-09 | Compliant | Worker concurrency and fan-out are bounded. |
| RESILIENCY-10 | Compliant | Timeout/retry/degraded behavior prevents dependency cascades. |

## PBT Compliance

| Rule | Status | Rationale |
|---|---|---|
| PBT-01 | Compliant | QT-10 properties already identified in Functional/NFR Requirements. |
| PBT-02/03/07/08/09 | Deferred | Code Generation selects concrete generators/tests using existing Hypothesis. |
