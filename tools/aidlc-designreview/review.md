# Design Review Report

## Table of Contents

- [Metadata](#metadata)
- [Executive Summary](#executive-summary)
- [Design Critique](#design-critique)
- [Alternative Approaches](#alternative-approaches)
- [Gap Analysis](#gap-analysis)
- [Appendix](#appendix)

---

## Metadata

| Field | Value |
|-------|-------|
| **Timestamp** | 2026-06-26T11:23:36.044666 |
| **Tool Version** | 0.1.0 |
| **Project** | aidlc-docs |
| **Project Path** | /Users/revenantonthemission/Projects/DocSuri/aidlc-docs |
| **Review Duration** | 279.5s |
| **Model (critique)** | claude-sonnet-4-6 |
| **Model (alternatives)** | claude-sonnet-4-6 |
| **Model (gap)** | claude-sonnet-4-6 |

### Severity Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 4 |
| Medium | 30 |
| Low | 0 |

### Agent Execution Times

| Agent | Time (s) |
|-------|----------|
| critique | 86.5 |
| alternatives | 111.4 |
| gap | 174.2 |

### Token Usage

| Agent | Input Tokens | Output Tokens |
|-------|-------------|--------------|
| critique | 241665 | 3753 |
| alternatives | 244525 | 4773 |
| gap | 241721 | 8039 |

### Configuration

| Setting | Value |
|---------|-------|
| Severity Threshold | medium |
| Alternatives Enabled | True |
| Gap Analysis Enabled | True |

---

## Executive Summary

**Overall Quality: Poor** (Score: 72)

### Top Findings

1. **[HIGH]** AccountDeleted Event Cascade Lacks Verified Completion Guarantee Within GDPR Timeframe
   - The AccountDeleted event (events.md §1b) relies on at-least-once delivery to U4/U2/U11 for GDPR-compliant data erasure. While the design acknowledges DLQ and completion verification, the 'maximum allowed delay' SLA for cascade completion is deferred to Infra Design. If a subscriber is permanently down or DLQ accumulates silently, personal data may persist indefinitely past the purge window. The 30-day grace period design is sound, but the operational runbook for verifying cascade completion across all subscribers before the legal erasure deadline is not defined at the design level.
   - Source: critique
2. **[HIGH]** SearchGatewayPort Stub Creates Untested Rerun Path Until U6 Integration
   - U4's rerun functionality (SavedSearchService.rerun, SearchHistoryService.rerun) is wired through SearchGatewayPort with a StubSearchGateway providing deterministic placeholder results. The invariant INV-L2 correctly prohibits direct U2 calls. However, until U6/Infra binds the real gateway, all integration tests pass against a stub that bypasses the GroundingEnforcementHook, CostGuardCircuitBreaker, and RateLimiter. If the real gateway binding is delayed or misconfigured, reruns in production could silently bypass the cost/grounding hooks that are core security and quality guarantees.
   - Source: critique
3. **[HIGH]** VectorSpec Contract Enforcement Is Declarative Only — No Runtime Compatibility Gate
   - The design repeatedly references the shared VectorSpec (dimensions, modelRef, distanceMetric) as a binding invariant between U1 (writer) and U2 (reader). Both units declare they consume the same spec, but the enforcement mechanism is entirely static (shared contract in shared/vector-spec) with no runtime validation. If U1 is redeployed with a new embedding model version (modelVer bump) before U2 is updated, the vector index will contain mixed-space embeddings. Queries will return semantically incorrect but syntactically valid results with no error signal. The design mentions 'full re-embedding required' on change but provides no gate to prevent partial migration.
   - Source: critique
4. **[HIGH]** GroundingEnforcementHook Single-Invocation Site Creates High-Impact Single Point of Failure
   - The design correctly enforces that GroundingEnforcementHook.enforce() has exactly one invocation site (U6.GatewayPipelineService post-handler). This is architecturally clean but means any bug, misconfiguration, or exception in that single code path bypasses grounding for all U2 search responses. The design states fail-closed behavior (SEC-15) but the specific failure mode—what happens if enforce() throws an unhandled exception in the post-handler—is not specified. If the hook throws and the gateway's error handler returns the pre-hook response, grounding is silently bypassed.
   - Source: critique
5. **[MEDIUM]** U7 Grounding Validator Is Semantically Different from U6 GroundingEnforcementHook but Shares No Common Abstraction
   - The design correctly argues that U7's GroundingValidator (document fidelity for summarization) is a different concern from U6's GroundingEnforcementHook (search result grounding). However, both implement anchor-based provenance checking with similar abstractions (AnchorVerdict vs GroundingDecision). The design explicitly states 'U7 고유 결정적 게이트' as justification for not reusing U6's hook. This creates two parallel implementations of anchor validation logic with diverging SOFT/HARD check semantics (U7 BR-S7) that could drift. The QT-5 evaluation for U7 grounding is also separate from QT-1.
   - Source: critique

### Recommended Actions

- Approve: The design meets quality standards with minor or no issues.
- **>>> Request Changes** (Recommended): Significant issues found that should be addressed before proceeding.
- Explore Alternatives: Consider alternative approaches to improve the design.

### Severity Distribution

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 4 |
| Medium | 30 |
| Low | 0 |

---

## Design Critique

### High Findings (4)

#### AccountDeleted Event Cascade Lacks Verified Completion Guarantee Within GDPR Timeframe

- **Severity**: High
- **Location**: shared/events.md §1b AccountDeleted, U3 business-logic-model.md §8, business-rules.md BR-A11
- **Description**: The AccountDeleted event (events.md §1b) relies on at-least-once delivery to U4/U2/U11 for GDPR-compliant data erasure. While the design acknowledges DLQ and completion verification, the 'maximum allowed delay' SLA for cascade completion is deferred to Infra Design. If a subscriber is permanently down or DLQ accumulates silently, personal data may persist indefinitely past the purge window. The 30-day grace period design is sound, but the operational runbook for verifying cascade completion across all subscribers before the legal erasure deadline is not defined at the design level.
- **Recommendation**: Define a maximum cascade completion SLA (e.g., 24 hours after purge_after expiry) at the requirements/design level, not deferred entirely to Infra. Add a compensating saga: U3.AccountDeletionService.purgeJob should track which subscribers have confirmed completion (AccountPurged signal) and escalate to a dead-letter runbook if any subscriber exceeds the SLA. Consider a design-level invariant that purge is not marked PURGED in U3 until all mandatory subscribers confirm, or accept eventual consistency with explicit monitoring thresholds.

#### SearchGatewayPort Stub Creates Untested Rerun Path Until U6 Integration

- **Severity**: High
- **Location**: U4 business-logic-model.md §5, business-rules.md BR-L9, INV-L2, component-dependency.md §4
- **Description**: U4's rerun functionality (SavedSearchService.rerun, SearchHistoryService.rerun) is wired through SearchGatewayPort with a StubSearchGateway providing deterministic placeholder results. The invariant INV-L2 correctly prohibits direct U2 calls. However, until U6/Infra binds the real gateway, all integration tests pass against a stub that bypasses the GroundingEnforcementHook, CostGuardCircuitBreaker, and RateLimiter. If the real gateway binding is delayed or misconfigured, reruns in production could silently bypass the cost/grounding hooks that are core security and quality guarantees.
- **Recommendation**: Add a design-level contract test that the real SearchGatewayPort implementation must pass before production deployment: verify that a rerun request triggers at least one call to CostGuardCircuitBreaker.getBudgetState() and that the response path traverses GroundingEnforcementHook.enforce(). This should be a blocking integration test, not just a unit test against the stub. Document that StubSearchGateway must never be used in production environment configuration.

#### VectorSpec Contract Enforcement Is Declarative Only — No Runtime Compatibility Gate

- **Severity**: High
- **Location**: U1 business-rules.md §6, U2 business-rules.md §6, shared/ports.md §3, component-dependency.md VectorSpec shared contract edges
- **Description**: The design repeatedly references the shared VectorSpec (dimensions, modelRef, distanceMetric) as a binding invariant between U1 (writer) and U2 (reader). Both units declare they consume the same spec, but the enforcement mechanism is entirely static (shared contract in shared/vector-spec) with no runtime validation. If U1 is redeployed with a new embedding model version (modelVer bump) before U2 is updated, the vector index will contain mixed-space embeddings. Queries will return semantically incorrect but syntactically valid results with no error signal. The design mentions 'full re-embedding required' on change but provides no gate to prevent partial migration.
- **Recommendation**: Add a runtime compatibility check: U2.HybridRetriever should read the VectorSpec from a shared capability (e.g., a metadata record written by U1 alongside the index) and compare against its compiled-in specVersion at startup and periodically. If versions diverge, U2 should degrade to lexical-only mode (already defined) and emit an alert rather than silently returning semantically invalid results. This is a design-level requirement, not just an operational concern.

#### GroundingEnforcementHook Single-Invocation Site Creates High-Impact Single Point of Failure

- **Severity**: High
- **Location**: U6 components.md ApiGatewayMiddleware/GroundingEnforcementHook, services.md GatewayPipelineService, application-design.md §3
- **Description**: The design correctly enforces that GroundingEnforcementHook.enforce() has exactly one invocation site (U6.GatewayPipelineService post-handler). This is architecturally clean but means any bug, misconfiguration, or exception in that single code path bypasses grounding for all U2 search responses. The design states fail-closed behavior (SEC-15) but the specific failure mode—what happens if enforce() throws an unhandled exception in the post-handler—is not specified. If the hook throws and the gateway's error handler returns the pre-hook response, grounding is silently bypassed.
- **Recommendation**: Explicitly specify in the design that if GroundingEnforcementHook.enforce() throws any exception, the gateway MUST return AbstainDTO (not the candidate response and not a generic 500 error). This fail-closed behavior for the hook itself should be a named invariant (e.g., INV-G1). Add a property-based test: for any exception thrown by enforce(), the response observable to the client must be AbstainDTO or a generic error DTO, never SearchResultPageDTO.

### Medium Findings (6)

#### U7 Grounding Validator Is Semantically Different from U6 GroundingEnforcementHook but Shares No Common Abstraction

- **Severity**: Medium
- **Location**: U7 business-rules.md BR-S7, U7 domain-entities.md §6, shared/ports.md §2, application-design.md §3
- **Description**: The design correctly argues that U7's GroundingValidator (document fidelity for summarization) is a different concern from U6's GroundingEnforcementHook (search result grounding). However, both implement anchor-based provenance checking with similar abstractions (AnchorVerdict vs GroundingDecision). The design explicitly states 'U7 고유 결정적 게이트' as justification for not reusing U6's hook. This creates two parallel implementations of anchor validation logic with diverging SOFT/HARD check semantics (U7 BR-S7) that could drift. The QT-5 evaluation for U7 grounding is also separate from QT-1.
- **Recommendation**: While the current design justification is sound, document explicitly at the shared contract level that AnchorVerdict (U7) and GroundingDecision (U6) are intentionally parallel with different semantics, and add a design note explaining what conditions would warrant unification (e.g., if a third consumer needs anchor validation). Consider extracting the common anchor-existence check into a shared utility (not a hook) to prevent duplicate logic for the 'does this anchor target exist in the source?' check, while keeping enforcement policy separate.

#### SearchHistoryService Dedupe Key Has Collision Risk for Rapid Re-queries

- **Severity**: Medium
- **Location**: U4 business-logic-model.md §6.1, business-rules.md BR-L7, shared/events.md §2
- **Description**: The deduplication key for SearchHistoryService is defined as sha256(owner_id \| executed_at.isoformat() \| query) (U4 business-logic-model.md §6.1). If a user submits the same query twice within the same second (timestamp resolution), and both SearchExecutedEvents are delivered (at-least-once), the second event will be deduplicated. This is the intended behavior. However, if a user intentionally runs the same query twice (e.g., to check if results changed after index update), the second genuine query will be silently dropped from history. The design treats this as acceptable but it is not documented as a known limitation.
- **Recommendation**: Document this as an explicit design decision and known limitation in the business rules. Consider whether the deduplication window should be time-bounded (e.g., dedupe only within a 5-second window using a rounded timestamp) rather than exact-timestamp-based, to distinguish retry-induced duplicates from legitimate repeat queries. Alternatively, include a nonce or request-id in the dedupe key sourced from the original SearchRequest, which would allow legitimate repeat queries to create separate history entries.

#### U7 Map-Reduce Summary Grounding Uses Full RefinedSource but Partial Chunks Were Generated From

- **Severity**: Medium
- **Location**: U7 business-logic-model.md §3.6, §3.8, business-rules.md BR-S6, BR-S7
- **Description**: In U7's map-reduce path (BR-S6, LengthRouter), the document is split into chunks, each generating a partial summary (map phase), then combined (reduce phase). The GroundingValidator is specified to validate against 'the full RefinedSource' (business-logic-model.md §3.8: '근거화는 전체 RefinedSource 기준 검증'). However, each map-phase partial summary was generated with only its chunk as context, meaning anchors may reference sections outside the generating chunk. The reduce-phase LLM combines partial summaries and may synthesize claims that span chunks, creating anchors that technically exist in RefinedSource but were never the actual evidence for the synthesized claim.
- **Recommendation**: Add a design constraint: in map-reduce mode, the reduce-phase prompt must be instructed that all anchors in the final output must reference sections that were actually present in the partial summary input that contributed the corresponding claim. Alternatively, accept that grounding validation in map-reduce mode is necessarily weaker and document this explicitly with a quality caveat in the UX (e.g., a different confidence indicator for map-reduce summaries). The current design implies full grounding strength for map-reduce which may be misleading.

#### CostGuardCircuitBreaker State Is Read Synchronously But Written Asynchronously Creating Stale Budget State Risk

- **Severity**: Medium
- **Location**: U6 component-methods.md CostGuardCircuitBreaker, services.md CostGuardService, shared/ports.md §3
- **Description**: U2 and U7 call CostGuardCircuitBreaker.getBudgetState() synchronously to gate LLM calls. CostGuardCircuitBreaker.recordSpend() is called after LLM usage and CostGuardCircuitBreaker.evaluateCircuit() updates the threshold state. Under high concurrency, multiple requests can pass getBudgetState() (returning NORMAL) before any recordSpend() calls update the state, allowing significantly more LLM spend than the circuit threshold before the OPEN state propagates. This is a classic TOCTOU issue in rate/budget enforcement.
- **Recommendation**: Document the acceptable overshoot window explicitly (e.g., 'up to N concurrent requests may proceed past the threshold before circuit opens'). Consider whether the budget threshold should include a safety margin (e.g., circuit triggers at 85% rather than 100%) to account for concurrent overshoot. Specify in the NFR that CostGuardCircuitBreaker state updates must use atomic operations or a compare-and-swap pattern to minimize the overshoot window. This is a known tradeoff in distributed rate limiting and should be explicitly acknowledged.

#### LibraryItemMeta Snapshot Does Not Version-Track Source Data

- **Severity**: Medium
- **Location**: U4 business-rules.md BR-L5, domain-entities.md §2.1, U1 business-rules.md BR-14, shared/events.md
- **Description**: LibraryItemMeta stores a snapshot of ResultCardVM fields at add-time and intentionally never refreshes from the live index (availability isolation, BR-L5). This is a sound design for availability. However, if a paper is retracted (U1 tombstone), the library item will continue to display the pre-retraction metadata including title and arxivUrl. Users navigating to the stored arxivUrl may find a retracted or withdrawn paper without any indication in their library. The design has no mechanism to propagate retraction signals to U4 library items.
- **Recommendation**: Add a retraction propagation event: when U1 generates a tombstone for a paperId, publish a PaperRetractedEvent to the event backbone. U4.LibraryService should subscribe and mark affected LibraryItems with a 'retracted' flag (not delete, to preserve user data). U5.ResultCard should display a retraction notice when rendering a retracted library item. This preserves the availability isolation design while preventing users from unknowingly sharing or citing retracted work.

#### U9 PersonalizationDecision searchBoosts Lack Explicit Magnitude Bound in Design

- **Severity**: Medium
- **Location**: U9 business-rules.md BR-P7, BR-P8, domain-entities.md PersonalizationDecision, UserInterestProfile
- **Description**: U9 provides 'small category/keyword bounded boost' (BR-P8) to U2's ranking. The design correctly states that U9 does not determine final ranking and provides only bounded boosts. However, neither the business rules nor domain entities define what 'bounded' means quantitatively at the design level (only that weights are in a 'bounded range'). If the boost magnitude is not bounded at design time, the implementation could produce boosts that effectively override the relevance ranking, violating the design intent that personalization is a minor adjustment.
- **Recommendation**: Define the boost magnitude contract at the design level: e.g., 'searchBoosts values must be in range [-0.1, +0.1] relative to the base relevance score' or 'applying all boosts must not change the relative order of more than 30% of results'. This constraint should be part of the PersonalizationDecision contract, not just an NFR. U2 should also define how it applies the boost (additive to score, multiplicative, rerank window) as a design-level invariant, not deferred to Construction.


---

## Alternative Approaches

### Alternative 1: Current Approach — Modular Monolith with U6 Centralized Cross-Cutting Gateway

The current design implements a modular monolith (DQ1) where U2–U4 are in-process domain modules sharing a single deployment unit, while U1 and U6's ops worker run as separate workers. All user-facing synchronous REST traffic flows through U6's ApiGatewayMiddleware, which enforces a strict sequential pipeline: security headers → input validation → authn/authz (delegating to U3.AuthorizationGuard) → rate limiting → cost state → domain handler → grounding enforcement (post-handler, U2 routes only) → observability → fail-closed error. Cross-cutting concerns like grounding, cost gating, and observability are owned by U6 as single authorities, with U2/U7 consuming them via shared/ports interfaces to avoid sync circular dependencies. The design achieves strong separation of concerns but creates a critical single-invocation-site for grounding enforcement and a synchronous budget state read that is subject to TOCTOU races under concurrency.

**What Changes**: N/A — this is the baseline design.

**Implementation Complexity**: High — The design is already built and documented at FD level across 10+ units with intricate cross-cutting invariants, shared contract versioning, and a layered security model. Maintaining internal consistency across this surface area is inherently high complexity.
**Advantages**:
- Single deployment unit for U2–U4 simplifies operational complexity, reduces network latency between domain modules, and avoids distributed transaction overhead for in-process calls
- Single-authority pattern for grounding (U6.GroundingEnforcementHook) and cost (U6.CostGuardCircuitBreaker) prevents duplication and drift across units, enforced via shared/ports dependency inversion
- Event backbone decoupling of ingestion, history writing, and incident detection from the synchronous read path directly satisfies NFR-P1 (P50&lt;3s) without complex distributed saga coordination
- Modular monolith boundary discipline (lib/sync/event kind tagging in component-dependency.md) provides a clear upgrade path to microservices if a specific module needs independent scaling

**Disadvantages**:
- GroundingEnforcementHook single invocation site is a high-impact single point of failure: if enforce() throws an unhandled exception in the post-handler and the gateway error handler returns the pre-hook response, grounding is silently bypassed with no observable signal (finding f511c8edb8814846 adjacent risk)
- CostGuardCircuitBreaker.getBudgetState() read is synchronous but spend recording is async, creating a TOCTOU window under high concurrency where multiple requests pass the budget gate before the circuit state updates (finding c84e644eefef48e1)
- SearchGatewayPort StubSearchGateway means all U4 rerun integration tests pass against a stub that bypasses GroundingEnforcementHook and CostGuardCircuitBreaker until U6/Infra binding is complete, with no automated gate to detect misconfiguration (finding 2e6c4ef7d938441b)
- VectorSpec contract enforcement is purely declarative with no runtime compatibility gate, so a U1 redeployment with a new embedding model before U2 update produces mixed-space vectors returning semantically incorrect results with no error signal (finding 9759f887337641d5)



---

### Alternative 2: Defense-in-Depth Grounding with Dual-Layer Enforcement and Runtime VectorSpec Gate

This alternative keeps the modular monolith structure intact but hardens three specific structural weaknesses identified in the critique: (1) the single-point-of-failure grounding invocation site, (2) the declarative-only VectorSpec compatibility check, and (3) the TOCTOU budget state race. Rather than restructuring the architecture, it adds defense-in-depth layers at the identified failure boundaries. Grounding gains a secondary fail-closed guard at the ResultAssembler level (a lightweight structural check, not a full enforce() re-invocation) so that if the post-handler hook is skipped or throws, a secondary gate prevents ungrounded responses from reaching serialization. VectorSpec gains a startup compatibility assertion and a write-path version tag on IndexRecords. CostGuardCircuitBreaker switches to a token-bucket model with atomic counters, trading exact budget tracking for concurrency-safe approximate enforcement.

**What Changes**: U2.ResultAssembler gains a GroundingStructuralGuard that checks that every ResultCardVM has a non-null arxivUrl resolvable to a known IndexRecord paperId — a cheap structural check requiring no U6 port call, acting as a secondary fail-closed gate. U6.ApiGatewayMiddleware.handle() explicitly catches all exceptions from GroundingEnforcementHook.enforce() and routes them to toProductionError() with a specific 'grounding_hook_error' code, ensuring enforce() exceptions never return pre-hook responses. U1.VectorIndexWriter.upsert() stamps each IndexRecord with the modelVer from EmbeddingGatewayAdapter.embeddingSchema() as a metadata field. U2.HybridRetriever.retrieve() reads modelVer from retrieved records and emits a metric to ObservabilityHub when modelVer mismatches the current QueryPlan VectorSpec; queries are rejected with a degraded fallback signal rather than returning mixed-space results. U6.CostGuardCircuitBreaker.recordSpend() is refactored to use an atomic in-memory counter (or Redis INCRBY if distributed) for the hot path getBudgetState() check, with the full evaluateCircuit() running asynchronously on a short interval — this removes the TOCTOU window for the common case while accepting that the budget can be slightly exceeded during a single evaluation interval.

**Implementation Complexity**: Medium — Changes are surgical additions to existing components rather than architectural restructuring. The atomic counter refactor and IndexRecord version tagging are straightforward engineering tasks; the secondary structural guard requires careful definition of its semantics relative to the primary hook to avoid divergence.
**Advantages**:
- Eliminates the silent grounding bypass failure mode without restructuring the single-invocation-site architecture — the secondary structural guard at ResultAssembler is cheap and can catch both hook exceptions and misconfiguration without adding a full LLM-based judge
- Runtime VectorSpec version tagging on IndexRecords converts the declarative-only contract into an observable runtime signal, enabling automatic degradation and alerting during mixed-space migration windows rather than silent semantic corruption
- Atomic counter approach for CostGuard eliminates the TOCTOU race for the synchronous getBudgetState() read path while preserving the existing synchronous API contract consumed by U2 and U7 — no changes to shared/ports required
- All changes are additive to the existing design — no unit boundaries, event contracts, or FD documents need restructuring, minimizing regression risk

**Disadvantages**:
- The secondary structural guard at ResultAssembler creates a second enforcement layer with slightly different semantics than U6.GroundingEnforcementHook, which could diverge over time and create confusion about which layer is authoritative — the design already documents the single-authority principle which this partially violates
- Atomic counter for CostGuard means budget can be exceeded by up to one evaluation interval's worth of spend under burst traffic — acceptable for a soft budget but requires explicit documentation of the deliberate 'approximate' semantics
- VectorSpec version tagging in IndexRecords adds a migration complexity: existing records without the modelVer tag need a backfill strategy or the retriever needs to handle the absence gracefully during the transition window



---

### Alternative 3: Event-Sourced Budget and Grounding Audit Trail with Async Cascade Verification

This alternative addresses the two most consequential data-integrity weaknesses in the current design: the GDPR AccountDeleted cascade completion gap and the CostGuardCircuitBreaker TOCTOU problem, using a unified event-sourcing pattern for both. Rather than relying on at-least-once delivery with deferred SLA definition, AccountDeletion becomes a tracked saga with explicit subscriber acknowledgment events and a saga coordinator that drives the cascade to verified completion within a configurable window. Simultaneously, CostGuardCircuitBreaker is refactored to emit a spend event on every LLM call, with the budget state derived by consuming the event stream — this eliminates the async write / sync read race by making all state changes explicit events. The SearchGatewayPort binding gap is also addressed by introducing a contract test that runs in CI against a lightweight integration harness, ensuring the real gateway binding is validated before production deployment.

**What Changes**: AccountDeletion gains a DeletionSaga entity in U3 with states (DEACTIVATION_REQUESTED → PURGE_INITIATED → CASCADE_IN_PROGRESS → CASCADE_VERIFIED → PURGED). U3.AccountDeletionService.purgeJob() publishes AccountDeleted as before, but each subscriber (U4, U2, U11) is required to publish an AccountPurged{accountId, unit, purgedAt} event upon completion. A new U3.DeletionSagaCoordinator (lightweight async component, runs in the Ops worker DQ1) subscribes to AccountPurged events and updates the saga state. If all expected subscribers have not published AccountPurged within the configured maximum cascade window (e.g., 7 days &lt; 30-day GDPR deadline), the coordinator emits a CascadeOverdue alert to IncidentEventPublisher. This replaces the 'SLA deferred to Infra Design' with a design-level mechanism. CostGuardCircuitBreaker is split into a SpendEventEmitter (synchronous, fires-and-forgets a SpendEvent on every LLM call) and a BudgetStateProjector (async, maintains a projected BudgetState by consuming SpendEvents with a short lag). getBudgetState() reads from the projected state; because the projection is eventually consistent with bounded lag (configurable, e.g., 500ms), the TOCTOU window is bounded rather than unbounded. SearchGatewayPort gains a ContractTestHarness that runs in CI: it boots the modular monolith with the real U6 gateway binding and exercises rerun paths through at least one SearchExecutedEvent, GroundingEnforcementHook invocation, and CostGuard gate check, failing the build if any hook is bypassed.

**Implementation Complexity**: High — The DeletionSaga coordinator is a new stateful distributed component requiring its own persistence, replay, and alerting logic. The SpendEvent/BudgetStateProjector split requires careful latency budgeting and documentation of the soft-cap semantics. The ContractTestHarness requires non-trivial CI infrastructure work. However, none of these require restructuring existing unit boundaries or FD contracts.
**Advantages**:
- DeletionSaga with explicit AccountPurged acknowledgment events provides a design-level GDPR cascade completion guarantee with observable state — the 'SLA deferred to Infra Design' gap (finding f511c8edb8814846) is closed at the architecture level with a configurable but bounded cascade window
- Event-sourced budget state eliminates the TOCTOU race by construction: SpendEvents are emitted synchronously (fire-and-forget, non-blocking to the LLM call path), and BudgetStateProjector maintains a lag-bounded projection — the maximum over-budget window is the projection lag, not the full async cycle
- SearchGatewayPort ContractTestHarness closes the gap where stub-passing tests do not validate real gateway hook binding (finding 2e6c4ef7d938441b), converting the integration risk from a runtime production discovery to a CI-blocking failure
- DeletionSaga pattern is reusable: when U11 Research Agent sessions and U9 personalization data need cascade deletion, they follow the same AccountPurged acknowledgment contract without new coordination infrastructure

**Disadvantages**:
- DeletionSaga coordinator adds a new stateful component to the Ops worker that must itself be resilient to restarts and replay — if the saga state store is lost, in-progress cascades need recovery procedures, adding operational surface area
- BudgetStateProjector introduces eventual consistency into budget enforcement: during the lag window, concurrent requests can collectively exceed the budget by more than one request's worth (though bounded by lag × request rate), requiring the team to accept and document that the budget is a soft cap with a defined over-spend envelope rather than a hard limit
- ContractTestHarness requires the CI environment to be able to boot a partial version of the modular monolith with real (or realistic mock) U6 gateway and U2 handler — this is more infrastructure than unit tests and may slow CI pipelines if not carefully scoped



---

### Alternative 4: Simplified Synchronous Grounding Co-location with U2 and Explicit VectorSpec Migration Protocol

This alternative takes a fundamentally different architectural stance on the grounding single-invocation-site problem and the VectorSpec contract enforcement gap by making grounding a first-class synchronous step within U2's SearchOrchestrationService pipeline rather than a post-handler hook in U6, and by formalizing VectorSpec changes as versioned migration events with a blue-green index handoff protocol. The motivation is that the current design's 'single invocation site in U6 post-handler' creates fragility precisely because grounding is architecturally distant from the data it validates — moving it closer to where ranked results are assembled eliminates the bypass failure mode by construction. The U6 single-authority principle is preserved by having U2 call a dedicated GroundingDecisionPort (still U6-implemented) synchronously within the pipeline, replacing the post-handler pattern.

**What Changes**: U6.GatewayPipelineService no longer owns a post-handler grounding invocation. Instead, U2.SearchOrchestrationService calls GroundingDecisionPort.decide(GroundingInput) as an explicit synchronous step between RelevanceRanker.rank() and ResultAssembler.assemble() — this is still U6-implemented via shared/ports, so the single-authority invariant is preserved, but the invocation site moves into the domain pipeline where exceptions are handled by U2's existing fail-closed error handling. The GroundingDecisionPort interface replaces GroundingEnforcementHook in shared/ports; it has the same enforce() semantics but is explicitly typed as a synchronous domain pipeline step rather than a middleware hook, making the call site semantics unambiguous. For VectorSpec: U1 publishes a VectorSpecChanged event when EmbeddingGatewayAdapter.embeddingSchema() detects a modelVer bump. U1.VectorIndexWriter uses a blue-green index pattern: writes during migration go to a new index (index-v2) while the old index (index-v1) remains live. U2.HybridRetriever reads from a configurable active index name; a new U6.IndexMigrationCoordinator (lightweight Ops component) monitors both indexes for docCount parity and flips the active index atomically, then publishes IndexMigrationComplete. This replaces the declarative-only VectorSpec contract with an operational migration protocol.

**Implementation Complexity**: High — Changing the grounding invocation site requires updating the single-authority contract across multiple FD documents, redesigning the shared/ports GroundingEnforcementHook interface, and validating that the U2 pipeline error handling correctly fails closed. The blue-green index protocol requires new infrastructure components and operational runbooks. Together these represent substantial cross-cutting changes even if individual components are straightforward.
**Advantages**:
- Moving grounding into the U2 pipeline eliminates the post-handler bypass failure mode by construction — if GroundingDecisionPort.decide() throws, U2's existing SearchOrchestrationService error handling applies the same fail-closed path as any other pipeline step, with no special gateway exception routing needed
- Blue-green index migration protocol converts the VectorSpec TOCTOU problem from a silent semantic corruption risk into an observable operational event with a defined completion gate — mixed-space queries are impossible because the index flip is atomic and only happens after docCount parity is verified
- The single-authority principle for grounding is preserved (U6 still implements GroundingDecisionPort) while the invocation site moves to where the data context is richest — U2 has ranked results, the full query plan, and retrieval metadata in scope, enabling richer grounding input without extra data marshaling across the post-handler boundary
- Removing the post-handler grounding step from GatewayPipelineService simplifies the gateway's responsibility to pure cross-cutting concerns (authn, authz, rate limiting, observability) without domain-level result validation logic

**Disadvantages**:
- Moving grounding into U2 creates a tighter coupling between U2 and the GroundingDecisionPort interface — if U7 or U11 also need grounding with the same hook, each must independently call the port rather than receiving it 'for free' via the gateway post-handler, potentially leading to duplicated integration points across units
- Blue-green index migration adds operational complexity and storage cost: during migration, two full indexes must be maintained simultaneously, and the IndexMigrationCoordinator must handle rollback if the new index has lower recall than the old one — this requires additional NFR work to define rollback criteria
- This is a significant restructuring of the grounding invocation contract documented across application-design.md, services.md, component-dependency.md, and shared/ports.md — the ripple of documentation changes is large even if the code change is localized



---

### Recommendation

Alternative 2 (Defense-in-Depth Grounding with Dual-Layer Enforcement and Runtime VectorSpec Gate) is the best fit for this project at its current stage. The project has completed Functional Design across all units and is moving into Construction; this is not the right moment for the architectural restructuring that Alternative 4 requires or the new stateful saga coordinator that Alternative 3 introduces. Alternative 2 is specifically designed to close the four highest-severity findings (f511c8edb8814846 is partially addressed via the telemetry path already designed; 2e6c4ef7d938441b via the ContractTestHarness concept, which can be borrowed from Alternative 3 as a low-cost addition; 9759f887337641d5 via runtime VectorSpec version tagging; 4a9c6efb907d4441 via explicit exception handling on the enforce() call and the secondary structural guard) through additive, non-restructuring changes that respect existing FD boundaries. The atomic counter refactor for CostGuard (closing finding c84e644eefef48e1) is a focused implementation change that does not alter the shared/ports API contract consumed by U2 and U7. The one element worth borrowing from Alternative 3 is the AccountPurged acknowledgment pattern from the DeletionSaga (closing finding f511c8edb8814846 properly at the design level) — this can be added to U3's business-logic-model.md as a lightweight tracking addition without the full saga coordinator infrastructure, deferring the coordinator to when U11 and additional subscribers make the complexity worthwhile. Alternative 1 (current design) should not be left as-is given the identified high-severity silent failure modes, particularly the grounding bypass risk (finding 4a9c6efb907d4441) and the mixed-space vector corruption risk (finding 9759f887337641d5), both of which can produce incorrect results with no observable error signal in production.

---

## Gap Analysis

### Medium Gaps (24)

#### AccountDeletionService and purgeJob Not Listed as Components

- **Severity**: Medium
- **Category**: missing_component
- **Description**: The events.md contract defines AccountDeleted as being produced by 'U3.AccountDeletionService.purgeJob', but AccountDeletionService is not listed in components.md or services.md for U3. The business-logic-model.md for U3 describes the deletion logic but no corresponding component definition exists in the architecture documents.
- **Recommendation**: 

#### PasswordResetService and EmailVerificationService Not Listed as Components

- **Severity**: Medium
- **Category**: missing_component
- **Description**: U3 business-logic-model.md and business-rules.md define PasswordResetService (FR-26/BR-A8) and email verification flows (BR-A5) with detailed algorithms, but these are not listed as named components in components.md or services.md. The email delivery dependency (Resend) is mentioned in unit-of-work-story-map.md but has no adapter component defined.
- **Recommendation**: 

#### SocialLoginService (OIDC) Component Not Defined

- **Severity**: Medium
- **Category**: missing_component
- **Description**: U3 business-logic-model.md describes SocialLoginService with start/callback methods and BR-A9 defines OIDC rules including CSRF state/nonce, pre-hijacking defense, and PENDING_CONFIRMATION flows. However, SocialLoginService is not listed in components.md, services.md, or component-dependency.md. The external Google OIDC dependency has no adapter component.
- **Recommendation**: 

#### U11 Research Agent Has No Functional Design Documents

- **Severity**: Medium
- **Category**: underspecified
- **Description**: unit-of-work.md and unit-of-work-story-map.md define U11 Research Agent with US-RA1–RA8, but there are no corresponding business-logic-model.md, business-rules.md, or domain-entities.md files for U11. The requirement-verification-questions-research-agent.md establishes Q18=A meaning only Requirements registration was completed, but US-RA1–RA8 are listed as Owner=U11 in the story map implying construction intent.
- **Recommendation**: 

#### SearchGatewayPort Real Binding Mechanism Unspecified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U4 business-logic-model.md and business-rules.md (BR-L9/INV-L2) require all rerun operations to go through SearchGatewayPort rather than calling U2 directly. The design states 'StubSearchGateway' is used by default and 'real binding is injected by U6/Infra when available'. However, no component, service, or infra document specifies how the real gateway binding is wired, what the concrete implementation looks like, or when/how the transition from stub to real occurs.
- **Recommendation**: 

#### U10 Mypage Unit Entirely Undefined

- **Severity**: Medium
- **Category**: missing_component
- **Description**: unit-of-work.md reserves U10 for a Mypage feature being implemented by another team member, but provides no definition of its responsibilities, component boundaries, or interfaces. Several other units (U3 US-A5/account settings, U9 US-P6/personalization controls) reference UI owned by U10. The unit-of-work-dependency.md matrix omits U10 entirely.
- **Recommendation**: 

#### GroundingEnforcementHook Reuse for U7 Not Formally Validated

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U7 business-rules.md BR-S7 states 'U7 고유 결정적 게이트(검색용 U6 enforce와 형상 다름 — 단일 논문 충실도 검증)' and notes the grounding check is different from U6's enforce. However, ports.md declares GroundingEnforcementHook as the single authority gate and U7 FD states it uses a separate GroundingValidator component. The relationship between U7's GroundingValidator and U6's GroundingEnforcementHook is explicitly unresolved in summarization-translation-pipeline.md §12 ('U6 grounding 재사용 검증 필요').
- **Recommendation**: 

#### VectorSpec PIN Process and Ownership Transfer Underspecified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: Multiple documents state that VectorSpec (dimensions, model, distance metric) is 'pinned by U1 (build #1) but owned by the shared embedding gateway layer' and that 'subsequent units cannot re-decide'. The concrete mechanism by which U1 sets the PIN, how the shared contract is updated, and what happens if the embedding model changes (full re-ingestion required) is not specified.
- **Recommendation**: 

#### Event Consumer Failure and DLQ Handling for AccountDeleted Not Fully Specified

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: events.md §1b defines AccountDeleted with DLQ and completion verification requirements, noting 'U3/Ops must alert on incomplete cascade (max allowed delay exceeded / DLQ backlog)'. However, no component is specified to perform this monitoring, no alert threshold is defined, and no runbook exists for manually reconciling a permanently-down subscriber. The 'maximum allowed delay' is explicitly deferred to Infra Design.
- **Recommendation**: 

#### PendingDTO Polling Contract for U7 Async Jobs Underspecified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U7 BR-S12 and domain-entities.md define PendingDTO with a retryAfterMs hint for async map-reduce/map-only jobs, but no API endpoint is specified for polling. The client-side polling mechanism, maximum poll duration, what happens when polling times out, and how the job ID is correlated between the initial enqueue response and subsequent polls are not defined.
- **Recommendation**: 

#### doc-model Lazy Build Trigger Queue Endpoint Not Defined

- **Severity**: Medium
- **Category**: missing_component
- **Description**: shared/docmodel.md and U1 business-logic-model.md §7.2 specify that doc-model is built lazily via a BUILD_DOC_MODEL queue job enqueued by the consumer (U7). The document states 'reading side enqueues only, builder creation is U1 worker'. However, no API endpoint or event contract is defined for how U7 triggers the enqueue, what queue/topic is used, or how U7 knows the job completed (other than polling getDocModel).
- **Recommendation**: 

#### U9 Personalization Read Port Interface Not Formally Defined in shared/ports

- **Severity**: Medium
- **Category**: missing_component
- **Description**: unit-of-work-dependency.md shows U2 and U7 consuming U9 via sync reads for search boost and summary defaults. U9 business-logic-model.md defines PersonalizationReadPort as a component. However, shared/ports.md only defines GroundingEnforcementHook, CostGuardCircuitBreaker, and ObservabilityHub. The PersonalizationReadPort interface is not in shared/ports, meaning U2 and U7 have no stable contract to depend on.
- **Recommendation**: 

#### U8 CitationProviderPort Concrete Provider and Fallback Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U8 business-logic-model.md references CitationProviderPort for backward references and mentions 'Semantic Scholar' in unit-of-work.md notes, but no adapter component is defined, no API rate limit policy is specified beyond 'NFR', and no cache TTL value is given for CitationSnapshot. The fallback chain when Semantic Scholar is unavailable or returns a 429 is described at the state machine level but not as a concrete component.
- **Recommendation**: 

#### Incremental Ingestion Watermark Behavior During Concurrent Events Not Specified

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U1 business-logic-model.md defines REBUILD_LOCK mutual exclusion (Q16=A, BR-13) to prevent concurrent rebuild and incremental operations. However, when multiple NewArxivEvents arrive concurrently (Q12=B active), the interaction between parallel fetch/embed operations and the single VectorIndexWriter is described as 'write serialized' but the concrete serialization mechanism is not specified. The advanceWatermark max-clamp (BR-11/Q17) with concurrent jobs could result in watermark regression if out-of-order jobs complete.
- **Recommendation**: 

#### U5 LibraryHistoryScreens Rerun Flow Integration with U4 Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U5 components.md shows LibraryHistoryScreens.rerun() delegates to SearchScreen search flow, but U4 SavedSearchService.rerun() and SearchHistoryService.rerun() go through SearchGatewayPort (U6→U2). The frontend flow for rerun appears to bypass the backend rerun and re-trigger a frontend search. It is unclear whether the frontend rerun calls U4's rerun endpoint (which uses the gateway) or directly calls U2 search via ApiClient.search(), which would be the equivalent of the 'backdoor' that INV-L2 prohibits at the backend level.
- **Recommendation**: 

#### SEC-9 Compliance for ObservabilityHub Structured Logs Not Enforced by Contract

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U6 ObservabilityHub requires PII/secret exclusion from all logs (SEC-3/SEC-9). The StructuredLogEntry type in shared/ports.md is defined as '(requestId correlated structured fields — PII/secrets excluded)' but there is no enforcement mechanism, schema validation, or field allowlist defined. Any unit can call emitLog() with arbitrary content.
- **Recommendation**: 

#### Glossary Version Conflict Between Users Sharing Cache Key Not Resolved

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U7 business-rules.md BR-S1 and domain-entities.md §2 note that baseline translations (glossaryVer=0, no personal terms) are shared across users, but personalized translations (glossaryVer&gt;0) include ownerId in the cache key to prevent cross-user contamination. However, the mechanism by which glossaryVer is determined for a given user at request time, how the ownerId is included in the S3 object path without exposing it in URLs, and how glossaryVer increments are serialized are not specified.
- **Recommendation**: 

#### U2 SearchOrchestrationService NoMatchResult Path Not Wired Through GroundingAdapter

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U2 business-logic-model.md §1.1 step 4 states 'candidates 0 → NoMatchResult → terminal (explicit empty page resultCount=0 — not abstain)'. The flow diagram shows this terminates before the GroundingAdapter.toGroundingInput step. However, the component-dependency.md flow diagram shows GroundingAdapter.toGroundingInput as a step in the pipeline without a bypass branch for the zero-candidate case.
- **Recommendation**: 

#### Rate Limiting Scope and Per-Endpoint Configuration Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U6 RateLimiter is responsible for SEC-11 rate limiting across search, signup, and other endpoints. The component defines checkLimit(scope: LimitScope, key: ClientKey) but no concrete LimitScope values, rate limit thresholds, window sizes, or per-endpoint configurations are specified in any design document. BR-A4 defines CAPTCHA after 10 login failures but this is a different mechanism from the RateLimiter.
- **Recommendation**: 

#### U4 Library and U2 Search History Cascade on AccountDeleted Not Implemented in FD

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: events.md §1b and U3 BR-A11 specify that U4 and U2 subscribe to AccountDeleted and purge owner-scoped data. U4 business-logic-model.md and business-rules.md have no mention of AccountDeleted event handling or a data purge use case. U2 FD documents similarly have no AccountDeleted handler. The event is defined but no consuming component is specified in the FD documents of U4 or U2.
- **Recommendation**: 

#### Translation Output Migration from koreanText to docModel TranslationDraft Not Backward Compatible

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U7 BR-S18 (PR-2) changes TranslationDraft from a flat koreanText string to a structured docModel. This is a breaking change to the SummarizeOutcome DTO. The cache key design (BR-S1) uses promptVer to differentiate, meaning existing cached translations (koreanText format) will not be served to clients expecting docModel format. The migration path for existing cache entries is not specified.
- **Recommendation**: 

#### U9 Behavior Event Retention Policy Conflicts with U3 AccountDeleted Cascade

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U9 BR-P12 specifies a default 90-day retention for raw behavior events. U3 BR-A11 specifies that AccountDeleted triggers cascade data purge in U4, U2, and U11, but does not mention U9. Events.md §1b lists U4, U2, and U11 as AccountDeleted consumers but does not list U9. U9 business-logic-model.md Use Case 'Delete Behavior Events' describes user-initiated deletion but not system-triggered deletion on account purge.
- **Recommendation**: 

#### U7 Full Text Translation Grounding Policy Inconsistent with GroundingAdapter Pattern

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U7 BR-S18 states 'translation is grounding-free (BR-S7 not applied)' because translation is a faithfulness task. However, the GroundingEnforcementHook.enforce in U6 is applied at the response edge for all U2 routes and potentially for U7 routes. If U7 translation responses pass through the U6 gateway post-handler, it is unclear whether GroundingEnforcementHook.enforce is called on translation responses and how a pass-through verdict is achieved.
- **Recommendation**: 

#### U5 Frontend Transport Seam Real Implementation Binding Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U5 business-logic-model.md §3 and frontend-components.md §2.9 define a MockTransport/HttpTransport seam for ApiClient. The design states 'real transition is a transport swap' but does not specify: the gateway base URL configuration mechanism, how session cookies are forwarded in SSR context vs client context, or how the transport is configured in different environments (development, staging, production).
- **Recommendation**: 


---

## Appendix

### Agent Status

| Agent | Status | Findings | Execution Time |
|-------|--------|----------|---------------|
| critique | Completed | 10 | 86.5s |
| alternatives | Completed | 4 | 111.4s |
| gap | Completed | 24 | 174.2s |


### Token Usage

| Agent | Input Tokens | Output Tokens |
|-------|-------------|--------------|
| critique | 241665 | 3753 |
| alternatives | 244525 | 4773 |
| gap | 241721 | 8039 |

---

## Legal Disclaimer

**IMPORTANT**: This report is generated by an AI-powered automated design review tool and is provided for **advisory purposes only**. The recommendations, findings, and assessments contained herein:

- ✅ **Are advisory only** - Not binding recommendations or requirements
- ✅ **Require human review** - Must be reviewed and validated by qualified professionals before implementation
- ✅ **May contain errors** - AI-generated content may include inaccuracies or incomplete analysis
- ✅ **Not a substitute for professional judgment** - Does not replace expert architectural or security review
- ✅ **Context-dependent** - May not consider organization-specific constraints or requirements

**Limitations**:
- AI models may produce biased, incomplete, or incorrect recommendations
- Analysis is limited to information provided in design documents
- Does not guarantee compliance with security, regulatory, or industry standards
- Tool and models are continuously updated; results may vary over time

**No Warranties**: This report is provided "AS IS" without warranties of any kind, express or implied, including but not limited to warranties of merchantability, fitness for a particular purpose, or non-infringement. The authors and providers assume no liability for any errors, omissions, or damages arising from the use of this report.

**User Responsibility**: Users are solely responsible for:
- Validating all recommendations before implementation
- Verifying compliance with applicable standards and regulations
- Conducting thorough security and architectural reviews
- Making final design and implementation decisions

---

*Report generated by AIDLC Design Reviewer v0.1.0*

**Copyright (c) 2026 AIDLC Design Reviewer Contributors**
Licensed under the MIT License
See LICENSE file for details