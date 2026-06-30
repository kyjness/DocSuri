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
| **Timestamp** | 2026-06-28T21:24:11.249374 |
| **Tool Version** | 0.1.0 |
| **Project** | aidlc-docs |
| **Project Path** | /Users/revenantonthemission/Projects/DocSuri/aidlc-docs |
| **Review Duration** | 255.7s |
| **Model (critique)** | claude-sonnet-4-6 |
| **Model (alternatives)** | claude-sonnet-4-6 |
| **Model (gap)** | claude-sonnet-4-6 |

### Severity Summary

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 5 |
| Medium | 23 |
| Low | 1 |

### Agent Execution Times

| Agent | Time (s) |
|-------|----------|
| critique | 115.9 |
| alternatives | 93.2 |
| gap | 122.5 |

### Token Usage

| Agent | Input Tokens | Output Tokens |
|-------|-------------|--------------|
| critique | 261611 | 5560 |
| alternatives | 265673 | 4171 |
| gap | 261667 | 5581 |

### Configuration

| Setting | Value |
|---------|-------|
| Severity Threshold | medium |
| Alternatives Enabled | True |
| Gap Analysis Enabled | True |

---

## Executive Summary

**Overall Quality: Poor** (Score: 62)

### Top Findings

1. **[HIGH]** U2 VectorSpec Runtime Validation Contradicts Shared Contract
   - U2's business-rules.md documents a per-record `modelVer` runtime validation in `HybridRetriever.retrieve()` that checks returned records' `modelVer` metadata against the compiled `specVersion`. However, an audit note (2026-06-28, N1) explicitly flags this as contradicting `shared/vector-spec.md` §4, which states per-record `modelVer` is not included in the FROZEN IndexRecord contract. This creates a situation where documented business logic cannot be implemented as written without violating the frozen shared contract. The fallback behavior (degrade to lexical-only on mismatch) is sound in principle, but the implementation path is undefined.
   - Source: critique
2. **[HIGH]** AccountDeleted Cascade Has No Bounded Completion Guarantee for Purge of U3 Credentials
   - The `AccountDeleted` cascade design (U3 → U4/U2/U11) requires subscriber units to emit `AccountPurged` events, and U3 tracks completion with a `CascadeOverdue` alarm if subscribers don't confirm within a maximum allowed delay (e.g., 7 days). However, the design does not specify what happens after `CascadeOverdue` is fired: specifically, whether U3 credentials and account records are deleted before or after all `AccountPurged` confirmations are received. If U3 deletes its own records first (before subscriber confirmation), re-authentication is impossible for recovery but GDPR cascade is unverified. If U3 waits for all confirmations, a permanently-down subscriber (e.g., U11 during maintenance) blocks the entire purge indefinitely. Neither path is explicitly resolved, creating a potential GDPR compliance gap.
   - Source: critique
3. **[HIGH]** U4 SearchGatewayPort StubSearchGateway Lacks Enforcement Mechanism for Production Exclusion
   - The design explicitly states that `StubSearchGateway` must never be used in production (ENV=PROD), and that a contract test (`ContractTestHarness`) must verify that `RealSearchGatewayAdapter` passes through `CostGuardCircuitBreaker.getBudgetState()` and `GroundingEnforcementHook.enforce()`. However, the design only describes this as a policy requirement without specifying how production misconfiguration is detected at startup or deployment time. A misconfigured deployment where `StubSearchGateway` reaches production would silently bypass grounding and cost controls on all rerun operations — a critical security and reliability failure.
   - Source: critique
4. **[HIGH]** U6 GroundingEnforcementHook Single Invocation Site Creates Undocumented Bypass Risk for Non-U2 Routes
   - The design establishes that U6 `GroundingEnforcementHook.enforce()` is called as a post-handler exclusively in the U2 route within `GatewayPipelineService`. U4 rerun operations are routed through the gateway (correctly enforcing grounding). However, U7 Summarization and U11 Research Agent each implement their own grounding validators (`GroundingValidator` in U7, `AgentGroundingAdapter` in U11) rather than invoking the shared `enforce` hook. The design acknowledges these are 'different kinds' of grounding, but the audit note in ports.md §2 explicitly raises the question of whether a common anchor validation utility should be extracted. As written, three separate grounding implementations exist with no cross-validation, creating divergence risk where a grounding bypass in U7 or U11 would not be caught by QT-1 evaluations that target U6's hook.
   - Source: critique
5. **[HIGH]** U1 Corpus Phase-1 Eager DocModel Generation Creates Blocking Dependency on GROBID Availability
   - The revised U1 Corpus design (2026-06-26) mandates eager DocModel generation for all Phase-1 corpus papers at ingestion time (BR-C6). For Semantic Scholar and OpenAlex papers (and arXiv PDF fallback — ~9% of corpus), this requires a synchronous GROBID call to extract structure from PDFs. GROBID is listed as a 'shared capability' runtime with no high-availability specification. If GROBID is unavailable or slow during Phase-1 seed/backfill, the entire ingestion pipeline stalls for affected papers (these become retry/DLQ items). Given the Phase-1 seed involves ~1 year of AI/ML papers across 3 sources, a GROBID outage could significantly delay corpus availability. Additionally, the design allows `sourceTier=pdf` DocModels with degraded structure (single paragraph block), but the alias cutover gate requires QT-9 invariants to pass — unclear if degraded PDF DocModels satisfy QT-9.
   - Source: critique

### Recommended Actions

- Approve: The design meets quality standards with minor or no issues.
- **>>> Request Changes** (Recommended): Significant issues found that should be addressed before proceeding.
- Explore Alternatives: Consider alternative approaches to improve the design.

### Severity Distribution

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 5 |
| Medium | 23 |
| Low | 1 |

---

## Design Critique

### High Findings (5)

#### U2 VectorSpec Runtime Validation Contradicts Shared Contract

- **Severity**: High
- **Location**: U2 Discovery — business-rules.md §6 (VectorSpec runtime validation), shared/vector-spec.md §4
- **Description**: U2's business-rules.md documents a per-record `modelVer` runtime validation in `HybridRetriever.retrieve()` that checks returned records' `modelVer` metadata against the compiled `specVersion`. However, an audit note (2026-06-28, N1) explicitly flags this as contradicting `shared/vector-spec.md` §4, which states per-record `modelVer` is not included in the FROZEN IndexRecord contract. This creates a situation where documented business logic cannot be implemented as written without violating the frozen shared contract. The fallback behavior (degrade to lexical-only on mismatch) is sound in principle, but the implementation path is undefined.
- **Recommendation**: Resolve the contradiction before Construction proceeds. Either (a) amend the frozen IndexRecord contract to include a `modelVer` field (requires all-unit sign-off per frozen contract policy), or (b) replace per-record validation with generation-level validation during alias cutover (U1 CorpusIndexWriter already performs same-space checks at cutover), and remove the per-record runtime check from U2 entirely. The generation-level gate is more appropriate since mixing embedding spaces within a generation is not possible by design.

#### AccountDeleted Cascade Has No Bounded Completion Guarantee for Purge of U3 Credentials

- **Severity**: High
- **Location**: U3 Accounts — business-logic-model.md §8.2, shared/events.md §1b AccountDeleted
- **Description**: The `AccountDeleted` cascade design (U3 → U4/U2/U11) requires subscriber units to emit `AccountPurged` events, and U3 tracks completion with a `CascadeOverdue` alarm if subscribers don't confirm within a maximum allowed delay (e.g., 7 days). However, the design does not specify what happens after `CascadeOverdue` is fired: specifically, whether U3 credentials and account records are deleted before or after all `AccountPurged` confirmations are received. If U3 deletes its own records first (before subscriber confirmation), re-authentication is impossible for recovery but GDPR cascade is unverified. If U3 waits for all confirmations, a permanently-down subscriber (e.g., U11 during maintenance) blocks the entire purge indefinitely. Neither path is explicitly resolved, creating a potential GDPR compliance gap.
- **Recommendation**: Define a two-phase purge protocol: Phase 1 — U3 deletes its own credentials/account records atomically and marks state as `PURGED` (this satisfies the user's right to erasure from the authenticating system). Phase 2 — cascade confirmations from U4/U2/U11 are tracked asynchronously; `CascadeOverdue` triggers a manual remediation workflow for stuck subscribers rather than blocking Phase 1. Explicitly document that Phase 1 completes regardless of subscriber state, and that `AccountPurged` from all subscribers closes the audit trail.

#### U4 SearchGatewayPort StubSearchGateway Lacks Enforcement Mechanism for Production Exclusion

- **Severity**: High
- **Location**: U4 Library — business-rules.md BR-L9, business-logic-model.md §5.2
- **Description**: The design explicitly states that `StubSearchGateway` must never be used in production (ENV=PROD), and that a contract test (`ContractTestHarness`) must verify that `RealSearchGatewayAdapter` passes through `CostGuardCircuitBreaker.getBudgetState()` and `GroundingEnforcementHook.enforce()`. However, the design only describes this as a policy requirement without specifying how production misconfiguration is detected at startup or deployment time. A misconfigured deployment where `StubSearchGateway` reaches production would silently bypass grounding and cost controls on all rerun operations — a critical security and reliability failure.
- **Recommendation**: Add a startup-time guard: on application boot, if ENV=PROD and the injected `SearchGatewayPort` implementation is `StubSearchGateway` (or any non-production adapter), the application must fail to start with a clear error. Additionally, the CI/CD pipeline should require the `ContractTestHarness` to pass as a blocking gate before any production deployment, not just as a post-deployment check. Document this as a hard invariant in `wiring.py` assertions.

#### U6 GroundingEnforcementHook Single Invocation Site Creates Undocumented Bypass Risk for Non-U2 Routes

- **Severity**: High
- **Location**: U6 — ports.md §2 (design note), U7 business-rules.md BR-S7, U11 business-rules.md INV-U11-2
- **Description**: The design establishes that U6 `GroundingEnforcementHook.enforce()` is called as a post-handler exclusively in the U2 route within `GatewayPipelineService`. U4 rerun operations are routed through the gateway (correctly enforcing grounding). However, U7 Summarization and U11 Research Agent each implement their own grounding validators (`GroundingValidator` in U7, `AgentGroundingAdapter` in U11) rather than invoking the shared `enforce` hook. The design acknowledges these are 'different kinds' of grounding, but the audit note in ports.md §2 explicitly raises the question of whether a common anchor validation utility should be extracted. As written, three separate grounding implementations exist with no cross-validation, creating divergence risk where a grounding bypass in U7 or U11 would not be caught by QT-1 evaluations that target U6's hook.
- **Recommendation**: Formally document the grounding taxonomy with clear boundaries: (1) U6 `enforce` = search result exposure gate (HARD, fail-closed, system-wide invariant); (2) U7 `GroundingValidator` = single-document fidelity check (SOFT, item-level abstain); (3) U11 `AgentGroundingAdapter` = multi-document evidence formation gate. Extract shared anchor existence validation logic (`assertAnchorExists(target, docModel)`) into `shared/ports` or a utility so all three implementations use the same primitive. Add QT coverage that specifically tests U7 and U11 grounding paths, not only U6.

#### U1 Corpus Phase-1 Eager DocModel Generation Creates Blocking Dependency on GROBID Availability

- **Severity**: High
- **Location**: U1 Ingestion — business-logic-model.md §0.3, business-rules.md BR-C6/BR-C10, shared/docmodel.md §4
- **Description**: The revised U1 Corpus design (2026-06-26) mandates eager DocModel generation for all Phase-1 corpus papers at ingestion time (BR-C6). For Semantic Scholar and OpenAlex papers (and arXiv PDF fallback — ~9% of corpus), this requires a synchronous GROBID call to extract structure from PDFs. GROBID is listed as a 'shared capability' runtime with no high-availability specification. If GROBID is unavailable or slow during Phase-1 seed/backfill, the entire ingestion pipeline stalls for affected papers (these become retry/DLQ items). Given the Phase-1 seed involves ~1 year of AI/ML papers across 3 sources, a GROBID outage could significantly delay corpus availability. Additionally, the design allows `sourceTier=pdf` DocModels with degraded structure (single paragraph block), but the alias cutover gate requires QT-9 invariants to pass — unclear if degraded PDF DocModels satisfy QT-9.
- **Recommendation**: Add GROBID to the explicit resilience budget in U1's NFR design: (1) define GROBID SLA requirements and failover behavior; (2) clarify whether `sourceTier=pdf` degraded DocModels (single paragraph block) are acceptable for alias cutover or whether they are quarantined until GROBID processing succeeds; (3) consider making GROBID processing async-within-pipeline (complete ingestion with placeholder DocModel, schedule GROBID enrichment separately) so GROBID availability does not block watermark advancement; (4) add a specific PBT property verifying that GROBID failure results in graceful degradation rather than pipeline stall.

### Medium Findings (7)

#### U9 Personalization Boost Magnitude Contract Not Enforced at System Boundary

- **Severity**: Medium
- **Location**: U9 Personalization — business-rules.md BR-P8, domain-entities.md PersonalizationDecision; U2 Discovery — business-rules.md BR-5
- **Description**: The design specifies a boost magnitude contract (BR-P8, domain-entities.md `PersonalizationDecision.searchBoosts`): individual boost values must be in `[-0.1, +0.1]` and total boost sum must not exceed `0.2`. This contract is documented in both U9 and U2 (business-rules.md BR-5 references 'U9 PersonalizationDecision boost magnitude bounds'). However, the contract enforcement responsibility is ambiguous: U2 states it 'trusts' the bounds provided by U9, while U9 states it 'produces' bounded values. Neither unit performs a runtime assertion at the API boundary. If U9 has a bug producing out-of-bounds values, U2 would silently apply inflated boosts, potentially reversing ranking for top results.
- **Recommendation**: Add a defensive assertion in U2's `RelevanceRanker.rank()` that validates the received `PersonalizationDecision.searchBoosts` against the contract bounds before applying them. If bounds are violated, log a telemetry event and fall back to the non-personalized ranking (same behavior as `enabled=false`). This is a cheap defense-in-depth measure consistent with the design's existing fail-open pattern for U9 failures.

#### U7 Map-Reduce Summarization Grounding Contract Is Underspecified for Cross-Chunk Claims

- **Severity**: Medium
- **Location**: U7 Summarization — business-rules.md BR-S6 (Map-Reduce Grounding Contract), business-logic-model.md §3.6/§3.8
- **Description**: Business-rules.md BR-S6 specifies a 'Map-Reduce Grounding Contract' requiring that the reduce step's output anchors must not exceed the scope of the source chunks. However, the reduce step synthesizes content from multiple map outputs, and the design acknowledges that `GroundingValidator` validates anchors against 'the entire `RefinedSource`' (not individual chunks). This means the reduce step could synthesize a claim whose anchor points to a section that was in a different chunk than the one that generated the sub-claim — technically valid by the full-source anchor check but potentially representing cross-chunk inference that violates the spirit of the contract. The distinction between 'this section exists in the document' and 'this claim was derived from this section' is not checked.
- **Recommendation**: For map-reduce summaries, enhance the grounding validation to track which chunks contributed to each map output, and require that reduce-step anchors be resolvable to a chunk that actually produced content for that claim. This can be implemented by having each map output include a `chunkId` tag on its anchors, and the reduce step must preserve these tags. The `GroundingValidator` then checks both anchor existence in the full document AND chunk attribution consistency. If this is too complex for v1, explicitly document that map-reduce summaries have weaker grounding guarantees than single-call summaries and surface this in the `SummaryResultDTO` metadata.

#### U11 Research Agent Cache Key Includes corpusSnapshot But Definition Is Underspecified

- **Severity**: Medium
- **Location**: U11 Research Agent — domain-entities.md §6 AgentCacheKey
- **Description**: The U11 Research Agent defines `AgentCacheKey` (domain-entities.md §6) with a `corpusSnapshot` field described as 'the corpus index/doc-model version.' However, the corpus index version is not a single atomic value — it is an OpenSearch alias pointing to a generation (`CorpusIndexGeneration.generationId`), and individual papers within a generation may have different DocModel versions (parserVersion/schemaVersion). If `corpusSnapshot` is defined as the alias generation ID, cached results may become stale when individual papers are updated within the same generation (e.g., retraction tombstoning). If it's undefined, cache invalidation is non-deterministic.
- **Recommendation**: Define `corpusSnapshot` precisely as the tuple `(indexAlias, generationId, chunkerVersion)` sourced from `CorpusIndexGeneration`. Document that cached agent results are invalidated when the active generation changes (alias cutover), but not on individual paper updates within a generation — this aligns with U7's caching behavior. Add a note that paper retraction events do not automatically invalidate agent cache; stale agent results citing retracted papers will persist until the next generation cutover. If real-time retraction accuracy is required, add `PaperRetractedEvent` as a cache invalidation trigger for affected sessions.

#### U3 Social Login Pre-Hijacking Defense Creates Orphaned PENDING_CONFIRMATION Identities

- **Severity**: Medium
- **Location**: U3 Accounts — business-rules.md BR-A9, domain-entities.md §4.2 SocialIdentity
- **Description**: Business-rules.md BR-A9 defines a `PENDING_CONFIRMATION` state for `SocialIdentity` when an existing password-account user initiates social login. The design requires either current password re-authentication or an email ownership round-trip to promote the identity to `LINKED`. However, the design does not specify: (1) the TTL for `PENDING_CONFIRMATION` identities before they expire; (2) what happens if a user initiates multiple social login attempts (multiple `PENDING_CONFIRMATION` records); (3) whether an attacker can use the `PENDING_CONFIRMATION` flow to enumerate whether a given email has a password account. The third point is particularly relevant given the design's careful attention to account enumeration prevention elsewhere.
- **Recommendation**: Add: (1) a TTL for `PENDING_CONFIRMATION` SocialIdentity records (suggest 30 minutes, consistent with PasswordResetToken); (2) a uniqueness constraint on `(provider, providerSubject)` in `PENDING_CONFIRMATION` state so multiple attempts replace rather than accumulate; (3) explicit confirmation that the `PENDING_CONFIRMATION` error response does not reveal whether a password account exists — the response should be identical regardless of whether the blocker is 'email has password account' or any other condition, directing users to the same confirmation flow either way.

#### OpenSearch Index Generation Alias Cutover Race Condition Between U1 Writer and U2 Reader

- **Severity**: Medium
- **Location**: U1 Ingestion — business-logic-model.md §0.5, business-rules.md BR-C10; U2 Discovery — business-logic-model.md §3.4
- **Description**: U1's corpus design (business-logic-model.md §0.5) performs alias cutover atomically using `CorpusIndexWriter.switchAlias()` after QT-9 validation. However, U2's `HybridRetriever` reads from the alias continuously. During the cutover window, there is a potential race: in-flight U2 searches that began on the old generation may still be executing when the alias switches, and searches that begin immediately after cutover target the new generation. The design does not specify whether OpenSearch alias cutover is atomic from the perspective of in-flight queries, or whether partial results mixing old/new generation records are possible. Additionally, the blue/green generation model does not specify a rollback window or rollback procedure if the new generation is found to have quality issues post-cutover.
- **Recommendation**: Document the alias cutover atomicity guarantee explicitly: OpenSearch alias updates are atomic at the cluster level, so in-flight queries complete against their originally-resolved shard set. Add to the operations runbook: (1) the rollback window duration after cutover (suggest 24h); (2) the rollback procedure (switch alias back to previous generation); (3) the condition that triggers rollback (e.g., QT-2 evaluation score drops below threshold post-cutover). Add a smoke test step in §0.5 that runs a sample U2 query set against the new generation before alias switch, in addition to the existing QT-9 invariant checks.

#### U8 Citation Graph Provider Failure Fallback Does Not Handle Partial Provider Responses

- **Severity**: Medium
- **Location**: U8 Citation Graph — business-logic-model.md (Use Case: Get Citation Tree), domain-entities.md CitationSnapshot
- **Description**: U8's failure model (business-logic-model.md) specifies that provider timeouts fall back to cached snapshots. However, the design does not address the scenario where a provider returns a partial response (e.g., first 20 of 100 backward references due to pagination timeout or truncation). The `CitationTreeBuilder` applies a 50-node limit, but if the provider returns a truncated set of 20 references and the system caches this as a complete snapshot (`depthCovered=1`), subsequent requests will receive stale partial data without indication that the original provider response was itself incomplete. The `truncated` flag in `CitationGraphResponse` tracks the 50-node display limit, not the provider completeness.
- **Recommendation**: Add a `providerCompleteness` field to `CitationSnapshot` with values `complete`, `truncated_by_limit`, `truncated_by_timeout`, `paginated_partial`. When caching a provider response, record whether the provider indicated more results were available (via pagination cursor or response metadata). Expose this in the API response so clients can distinguish between 'these are all citations' and 'these are the first N citations we could retrieve.' The `Partial` response state should be used when `providerCompleteness` is not `complete`, even if no individual items are `UnresolvedCitation`.

#### Shared DocModel Schema Evolution Has No Migration Path for Cached Artifacts

- **Severity**: Medium
- **Location**: shared/docmodel.md §4/§6, U1 Ingestion — business-logic-model.md §0.6, U7 Summarization — business-rules.md BR-S1
- **Description**: The DocModel contract (shared/docmodel.md §6) specifies that schema version changes trigger new cache keys via `provenance.schemaVersion`. U7 business-rules.md BR-S1 and U1 business-logic-model.md §0.6 note that `version mismatch` is treated as a cache miss. However, for large-scale schema changes (e.g., adding a new block type across the entire corpus), this would cause a corpus-wide cache miss storm where every paper's DocModel is regenerated on first access. The Phase-1 corpus covers ~1 year of AI/ML papers from 3 sources — a schema version bump could trigger thousands of concurrent DocModel builds. There is no circuit breaker or rate limiting specified for this scenario.
- **Recommendation**: Add a schema migration strategy to the DocModel contract: (1) distinguish between 'additive' schema changes (new optional fields — existing cached DocModels remain valid) and 'breaking' changes (field removal, semantic change — requires cache invalidation); (2) for breaking changes, implement a staged migration: update schema version, then run a background backfill job (using `triggerRebuild`) rather than lazy-on-demand regeneration; (3) add a DocModel rebuild rate limiter in U1 to prevent concurrent rebuild storms. The build/backfill budget gate (BR-C5) already exists but should explicitly cover schema migration scenarios.

### Low Findings (1)

#### U6 CostGuardCircuitBreaker Degradation Mode RERANK_OFF Has No Real Effect in Current U2 Baseline

- **Severity**: Low
- **Location**: U2 Discovery — business-rules.md BR-11, business-logic-model.md §2; U6 — CostGuardCircuitBreaker
- **Description**: The design acknowledges (U2 business-rules.md BR-11, business-logic-model.md §2) that `RERANK_OFF` degradation mode has no behavioral effect on U2 because U2's baseline already does not perform LLM reranking (Q3=A decision). The `DegradedResultDTO` with `mode=RERANK_OFF` is still surfaced to users with a degradation banner, creating a confusing UX where the system reports degradation when no actual capability reduction has occurred. This also pollutes cost guard telemetry with false degradation signals that are not actionable.
- **Recommendation**: Either (a) suppress `RERANK_OFF` degradation banners in U2 since they are not meaningful (U2 can treat `RERANK_OFF` identically to `NORMAL` and not emit `DegradedResultDTO`), or (b) update the `BudgetState` contract so `RERANK_OFF` is only emitted when the system actually has reranking capability that is being disabled. Option (a) is simpler for the current implementation. Document this as a known no-op mode in U2's code to prevent future confusion when a reranking capability is added.


---

## Alternative Approaches

### Alternative 1: Current Approach — Modular Monolith with Distributed Concern Ownership

The current design implements a modular monolith API (U2–U4, U7–U11 as in-process modules) with separate ingestion (U1) and ops (U6) workers, all communicating through a combination of synchronous REST, event backbone (EventBridge/SQS), and in-process library calls. Cross-cutting concerns (grounding, cost, auth) are centralized in U6, with strict single-authority ownership rules enforced via `shared/ports` dependency inversion. The design prioritizes correctness invariants (single-writer corpus, single grounding authority, owner-scoped data) and has explicit FROZEN contracts for inter-unit communication.

**What Changes**: This is the baseline — no changes. Components include ApiGatewayMiddleware, GroundingEnforcementHook, CostGuardCircuitBreaker, HybridRetriever, DocModelBuildCoordinator, and 11 domain units with their current orchestration.

**Implementation Complexity**: High — The current design already exists and is partially implemented across 11 units with extensive FROZEN contracts, but the identified contradictions (VectorSpec validation, cascade ordering, StubSearchGateway enforcement) require targeted fixes without breaking frozen interfaces.
**Advantages**:
- Single-authority ownership rules (U3 for authz, U6 for grounding/cost) eliminate duplication and reduce divergence risk across the 11 units
- FROZEN shared contracts (SearchExecutedEvent, VectorSpec, ports.md) provide stable integration points that prevent drift during parallel development
- Modular monolith avoids distributed transaction complexity for synchronous user-facing paths while preserving independent deployability for ingestion and ops workers
- Layered defense (U6 gateway + U3 AuthorizationGuard + U4 UserDataRepository owner-scoping) provides security depth without redundant logic ownership

**Disadvantages**:
- The VectorSpec per-record `modelVer` runtime validation documented in U2 business-rules.md §6 contradicts the FROZEN IndexRecord contract in shared/vector-spec.md §4 — the fallback is sound but the implementation path is undefined and creates a frozen-contract violation
- Three separate grounding implementations exist (U6 GroundingEnforcementHook, U7 GroundingValidator, U11 AgentGroundingAdapter) with no cross-validation, meaning QT-1 evaluations targeting U6's hook do not cover U7/U11 grounding paths
- The AccountDeleted cascade does not specify whether U3 deletes its own credentials before or after receiving all AccountPurged confirmations, creating a potential GDPR compliance gap when a subscriber (e.g., U11) is permanently down
- The StubSearchGateway production-exclusion policy in U4 is enforced only by documentation and a contract test requirement, with no startup/deployment-time mechanism to detect misconfiguration
- RERANK_OFF degradation mode in CostGuardCircuitBreaker produces misleading degradation banners to users when U2's baseline never performs LLM reranking, polluting telemetry with non-actionable signals



---

### Alternative 2: Unified Grounding Pipeline with Shared Anchor Validation Utility

This alternative resolves the most critical architectural divergence in the current design: three separate grounding implementations across U6, U7, and U11. Rather than maintaining parallel grounding logic, a shared `AnchorValidationService` is extracted into `shared/` that performs deterministic anchor existence checks (the common foundation across all three), while each unit retains its policy-level enforcement wrapper. U6's `GroundingEnforcementHook` handles search-result grounding (fail-closed, HARD block), U7's `GroundingValidator` handles document-fidelity grounding (SOFT anchor-drop), and U11's `AgentGroundingAdapter` handles evidence-table grounding (item-level abstention) — but all three invoke the same underlying anchor resolution logic from the shared utility, making QT-1 evaluation coverage transitive across all grounding paths.

**What Changes**: Extract `shared/anchor-validation` module containing `AnchorResolver.resolveAnchors(docModel, anchors[]) -&gt; AnchorResolutionResult[]` — the deterministic 'does this anchor exist in this DocModel?' check currently duplicated across U6, U7, and U11. U6 `GroundingEnforcementHook.enforce()` delegates to `AnchorResolver` for existence checks before applying its HARD block policy. U7 `GroundingValidator` delegates to `AnchorResolver` for its SOFT anchor-drop policy. U11 `AgentGroundingAdapter` delegates to `AnchorResolver` for item-level abstention. The `shared/ports.md` GroundingEnforcementHook interface gains a `resolveAnchors` method that U7/U11 can call directly without invoking the full U6 enforcement pipeline. QT-1 evaluation set expands to cover all three grounding paths via the shared utility. The VectorSpec `modelVer` runtime validation in U2 is resolved by moving the check to index generation cutover validation in U1 (asserting same-space at write time) rather than per-record at read time, removing the FROZEN contract violation.

**Implementation Complexity**: Medium — The anchor resolution logic is already written three times — the refactor is primarily about extraction and wiring, not new algorithmic work. The main risk is versioning the shared module against DocModel schema evolution, but the additive evolution policy already in place mitigates this.
**Advantages**:
- Eliminates the grounding divergence risk identified in constraint #901907c2c31846f3 — a single anchor resolution implementation means a grounding bypass anywhere triggers QT-1 failures
- Resolves the VectorSpec runtime validation contradiction (constraint #0d862b5723ef4afb) by relocating same-space validation to the U1 generation cutover gate where it belongs, without modifying the FROZEN IndexRecord contract
- U7 and U11 grounding remains semantically distinct (document-fidelity vs. search-result grounding) while sharing reliable anchor resolution infrastructure, preserving the design rationale documented in ports.md §2
- QT-1 evaluation set becomes meaningful for the entire system rather than only the U2/U6 search path

**Disadvantages**:
- Requires coordinated changes across U6, U7, and U11 plus a new shared module, touching FROZEN/PROVISIONAL contracts in ports.md — this is a non-trivial cross-unit refactor that must be carefully sequenced
- The `shared/anchor-validation` module creates a new shared dependency that all three units must keep synchronized with DocModel schema evolution, adding a coupling surface



---

### Alternative 3: Event-Sourced Account Lifecycle with Deterministic Cascade Completion

This alternative addresses the GDPR cascade gap (constraint #924536e4a4b54492) and the StubSearchGateway enforcement gap (constraint #317c0c826f9a4548) by applying event-sourcing principles to the account deletion lifecycle and startup-time invariant enforcement respectively. For account deletion, U3 shifts from an imperative cascade model (fire AccountDeleted, wait for AccountPurged confirmations) to an event-sourced deletion ledger where U3's own credential purge is the final event in a deterministic sequence: U3 marks the account as `PURGING`, emits `AccountDeleted`, waits for subscriber `AccountPurged` events with individual per-subscriber deadlines (not a single 7-day wall clock), and only executes U3's own credential deletion after all required confirmations arrive or a per-subscriber override is recorded. For the StubSearchGateway gap, a startup invariant check is added to the app-shell that fails fast if `ENV=production` and the injected `SearchGatewayPort` implementation is `StubSearchGateway`, making misconfiguration a deployment-time failure rather than a runtime silent bypass.

**What Changes**: U3 `AccountDeletionService.purgeJob` gains a `DeletionLedger` entity tracking per-subscriber purge state (`PENDING \| CONFIRMED \| OVERRIDDEN`) with individual deadlines. U3 credentials are deleted only when all required subscribers (U2, U4, U11) are in `CONFIRMED` or `OVERRIDDEN` state — this is the FINAL step, not an intermediate one. `CascadeOverdue` becomes per-subscriber rather than system-wide, and the design explicitly states that a permanently-down subscriber results in a manual `OVERRIDDEN` entry by an operator (with audit log), unblocking the U3 deletion. The `AccountDeletion` domain entity gains `ledgerEntries: DeletionLedgerEntry[]`. For StubSearchGateway: `backend/wiring.py` `_mount_library` adds a startup assertion `assert not (ENV == 'production' and isinstance(search_gateway, StubSearchGateway))` that raises at container start, not at first rerun request. The ContractTestHarness becomes a required CI gate (not just documented policy) that runs in the CD pipeline before ECS deploy.

**Implementation Complexity**: Medium — The DeletionLedger is a small schema addition to an existing entity, and the startup assertion is a single conditional. The main complexity is in the per-subscriber deadline logic and the operator override workflow, but neither requires new infrastructure.
**Advantages**:
- Resolves the GDPR cascade ordering ambiguity (constraint #924536e4a4b54492) with a deterministic rule: U3 credentials are the last data deleted, after all subscriber confirmations, making the compliance audit trail unambiguous
- Per-subscriber deadlines with operator override mechanism handles the permanently-down subscriber scenario (e.g., U11 during maintenance) without blocking the entire purge indefinitely
- Startup invariant enforcement for StubSearchGateway (constraint #317c0c826f9a4548) converts a silent production bypass risk into a deployment-time hard failure, detectable in staging before reaching production
- The DeletionLedger pattern naturally extends to future subscriber units without modifying the core cascade logic

**Disadvantages**:
- The `DeletionLedger` adds state management complexity to U3's purge job, which is already a sensitive, infrequently-exercised path — increased surface area for bugs in GDPR-critical code
- Making the ContractTestHarness a blocking CI gate requires the test to reliably mock U6's CostGuardCircuitBreaker and GroundingEnforcementHook calls, which may increase CI fragility if those interfaces evolve



---

### Alternative 4: Corpus Schema Evolution Rate Limiter with Generation-Scoped Cache Invalidation

This alternative addresses two related medium-severity issues: the DocModel schema evolution cache-miss storm (constraint #353161328dc34b27) and the OpenSearch alias cutover race condition (constraint #54efd911141b4cdb). Both problems stem from treating schema/generation changes as instantaneous global events when the corpus has thousands of papers. This alternative introduces a `SchemaEvolutionCoordinator` that manages schema version bumps as rate-limited rolling migrations rather than flag-day cutover events, and specifies explicit semantics for in-flight U2 queries during alias cutover.

**What Changes**: Add `SchemaEvolutionCoordinator` to U1 that, on parserVersion/schemaVersion bump, enqueues DocModel rebuilds into the existing ingestion SQS queue with a `SCHEMA_MIGRATION` job kind at a configurable rate (e.g., 100 papers/hour), respecting the existing NFR-C1 cost gate. Papers not yet migrated continue serving their old-schemaVersion DocModel (old cache key) — U7/U11 consumers treat schema mismatch as a `building` state with fallback to the old version rather than a hard cache miss. The U1 `CorpusIndexWriter.switchAlias()` is documented to use OpenSearch's atomic alias swap (which is consistent from the perspective of new queries but not in-flight queries) — the design is amended to specify that in-flight U2 requests using the old generation complete normally (OpenSearch does not interrupt in-flight requests on alias swap), and the rollback window is defined as 24 hours with `rollbackAlias` pointing to the previous generation. For the `AgentCacheKey.corpusSnapshot` gap (constraint #87fd1f852de94973), `corpusSnapshot` is defined as `(indexAliasGenerationId, docModelSchemaVersion)` — a paper-level retraction within the same generation does not invalidate the cache key (the retraction is surfaced via `PaperRetractedEvent` to U4.LibraryService metadata, not via cache invalidation). The U9 boost magnitude enforcement gap (constraint #60c8577e17bf47b4) is resolved by adding a `PersonalizationDecision.validate()` assertion in U2's `RelevanceRanker.rank()` that clamps out-of-bounds boosts with an observability warning, rather than trusting U9 unconditionally.

**Implementation Complexity**: Medium — Most changes are additive: a new job kind in the existing SQS queue, a clamping assertion in an existing method, and documentation of existing OpenSearch alias semantics. The schema migration coordinator is the most complex addition but reuses the existing ingestion pipeline infrastructure.
**Advantages**:
- Rate-limited schema migrations eliminate the cache-miss storm risk (constraint #353161328dc34b27) by spreading DocModel rebuilds over hours/days rather than triggering them all on first access
- Defining `corpusSnapshot` as `(generationId, schemaVersion)` (constraint #87fd1f852de94973) makes U11 cache invalidation deterministic and unambiguous without requiring paper-level version tracking
- Adding a clamping assertion in U2 for U9 boost bounds (constraint #60c8577e17bf47b4) provides defense-in-depth without requiring U9 to change its contract, and the observability warning surfaces U9 bugs without failing user requests
- The 24-hour rollback window with explicit `rollbackAlias` resolves the alias cutover gap (constraint #54efd911141b4cdb) and gives the team a defined recovery procedure

**Disadvantages**:
- The `SchemaEvolutionCoordinator` introduces a new coordination layer in U1 that must interact correctly with the existing REBUILD_LOCK mutual exclusion (BR-C10/BR-13), adding complexity to an already complex ingestion control plane
- Defining 'old-schemaVersion DocModel as valid fallback' during rolling migrations requires U7/U11 consumers to handle version-heterogeneous DocModel responses, which may complicate the FROZEN DocModel contract guarantees



---

### Recommendation

The project should pursue Alternative 2 (Unified Grounding Pipeline) as the highest-priority architectural fix, followed by targeted elements from Alternative 3 and Alternative 4. Alternative 2 directly resolves the most dangerous systemic risk: three parallel grounding implementations (U6/U7/U11) that create audit blind spots where QT-1 evaluations do not cover U7 or U11 grounding paths. This is not a theoretical risk — the design explicitly acknowledges it in ports.md §2. The same refactor also eliminates the FROZEN contract violation in U2's VectorSpec runtime validation by relocating same-space checking to the U1 generation cutover gate where it architecturally belongs. Alternative 2 is rated medium complexity because the anchor resolution logic already exists three times; it is primarily an extraction-and-wiring exercise. From Alternative 3, the two highest-value targeted fixes should be implemented independently: the startup-time StubSearchGateway invariant check (a single conditional in backend/wiring.py) and the ContractTestHarness as a blocking CI gate — both are low-complexity changes that convert silent production failures into deployment-time failures. The per-subscriber DeletionLedger for GDPR cascade ordering is also worth implementing given the compliance stakes. From Alternative 4, the U9 boost clamping assertion in U2's RelevanceRanker and the corpusSnapshot definition for U11 cache keys should be adopted as they are low-cost, high-value fixes. The RERANK_OFF false degradation signal (Alternative 1 disadvantage, constraint #2cfc771922cd4758) should be fixed independently by simply removing RERANK_OFF from the degradation signal surface since U2 never performs LLM reranking — this is a one-line change with significant UX and telemetry clarity benefits. Alternative 1 (current approach) should not be left as-is given the four high-severity constraints that have defined implementation gaps. Alternative 4's SchemaEvolutionCoordinator should be deferred until Phase-1 corpus build is complete and schema stability is better understood.

---

## Gap Analysis

### Medium Gaps (16)

#### U10 Mypage Unit Incompletely Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U10 Mypage is referenced throughout the design as 'another team member's implementation in progress' but its components (MypageController, UserPreferencesService, DataExportService) are only briefly listed in components.md without full FD artifacts (business-logic-model.md, business-rules.md, domain-entities.md). The unit-of-work-story-map.md explicitly states 'U10=마이페이지(타 팀원) is not reflected in this document.' The boundary between U10 (UI only) and U3 (backend endpoints/domain rules) is declared via Q2=A but the interface contract between them is absent.
- **Recommendation**: 

#### U11 ResearchAgent U6 Grounding Contract Extension Not Finalized

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U11 domain-entities.md and business-rules.md state that U6's grounding is the single authority (INV-U11-2) and that 'U11 formats/maps only, no reimplementation.' However, the mechanism for applying U6 grounding to a multi-paper evidence table (item-level abstain, not whole-response abstain) is described as 'U6 unified shared contract (Q7 unification)' with a note 'synchronize when shared/ports.md is finalized.' The current shared/ports.md GroundingEnforcementHook.enforce signature takes a single CandidateResponse + RetrievedRecordSet, which is designed for search results, not for multi-paper evidence rows.
- **Recommendation**: 

#### SearchGatewayPort Real Binding Verification Mechanism Underspecified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U4 business-logic-model.md §5.2 states that when StubSearchGateway is replaced by RealSearchGatewayAdapter, 'a blocking contract test must be executed verifying that at least 1 CostGuardCircuitBreaker.getBudgetState() call occurs and the response path passes GroundingEnforcementHook.enforce().' However, no specification exists for how this contract test is structured, where it lives, what triggers it in CI, or how the verification of 'passes through GroundingEnforcementHook' is asserted without tightly coupling to U6 internals.
- **Recommendation**: 

#### VectorSpec Per-Record modelVer Runtime Validation Conflict Unresolved

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U2 business-rules.md §6 documents an 'Known Inconsistency (2026-06-28 audit)': the per-record modelVer query-time validation described in HybridRetriever conflicts with shared/vector-spec.md §4 which states 'per-record modelVer is NOT included in the FROZEN IndexRecord contract.' The note recommends 'implementation hold until resolved' and references designreview-audit.md (N1). This conflict is documented but not resolved.
- **Recommendation**: 

#### AccountDeleted Cascade Overdue SLA and Manual Intervention Process Not Defined

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U3 business-rules.md BR-A11 and shared/events.md §1b specify that a CascadeOverdue alert fires if U2/U4/U11 do not send AccountPurged within a 'maximum allowed delay (e.g., 7 days).' However, the operational response to CascadeOverdue is not defined: who receives it, what manual remediation looks like, whether partial purge states are recoverable, and how the GDPR compliance audit trail is maintained when cascade is incomplete.
- **Recommendation**: 

#### U7 DocModelBuildRequestedEvent Consumer Acknowledgment Missing

- **Severity**: Medium
- **Category**: missing_component
- **Description**: shared/events.md §1d defines DocModelBuildRequestedEvent where the client polls getDocModel after receiving PendingDTO. The event specifies 'no build completion event is published' and 'client polls after retryAfterMs.' However, there is no specification for: maximum polling duration before client gives up, what happens if U1 DocModelBuilder enqueues the job but the worker crashes before completing, DLQ behavior for BUILD_DOC_MODEL jobs, or how the 'building' status transitions back to 'source_unavailable' if all build attempts fail.
- **Recommendation**: 

#### U9 PersonalizationDecision Boost Magnitude Contract Not Enforced at Boundary

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U9 business-rules.md BR-P8 and domain-entities.md PersonalizationDecision define that boost values must be in [-0.1, +0.1] with total sum ≤ 0.2. U2 business-rules.md BR-5 states 'trusting U9's boost magnitude bounds.' However, there is no specification for what U2 does if U9 returns out-of-bounds boost values (e.g., U9 bug or data corruption), and there is no validation step defined at the U2 intake of PersonalizationDecision.
- **Recommendation**: 

#### U8 CitationSnapshot TTL Value Not Defined

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U8 business-rules.md BR-CG9 and BR-CG10 reference 'TTL' for cache snapshots ('manual refresh is tried even before TTL') but the TTL value, unit, and where it is configured are never specified. The domain-entities.md CitationSnapshot has a createdAt field for 'TTL judgment basis' but no expiry field or TTL constant.
- **Recommendation**: 

#### PasswordResetService Email Delivery Failure Handling Not Specified

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U3 business-logic-model.md §5.1 and business-rules.md BR-A8 specify that reset tokens are generated and sent via Resend (EMAIL_PROVIDER=resend). However, there is no specification for what happens when Resend fails to deliver the email: whether the token is still persisted, whether the user gets an error or a generic 'check your email' response, retry behavior, or whether a failed send should be treated as a security event.
- **Recommendation**: 

#### Corpus Index Generation Alias Cutover Rollback Procedure Not Defined

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U1 business-logic-model.md §0.5 defines the alias cutover gate (QT-9 + smoke check + indexStats bounds). However, there is no specification for the rollback procedure if issues are discovered post-cutover: how to switch back to the previous generation alias, what the rollback window duration is (referenced in §0.5 as 'preserved during rollback window'), or who/what triggers rollback.
- **Recommendation**: 

#### U11 Mode B (Novelty Comparison) Seam Interface Not Defined

- **Severity**: Medium
- **Category**: missing_component
- **Description**: U11 business-rules.md BR-RA-17 and domain-entities.md §7 state that Mode B (novelty comparison) has 'port/domain seam only, not built.' However, the seam itself (NoveltyComparator port interface, external academic corpus port placeholder) is not defined anywhere in the design documents. The unit-of-work.md notes 'external API cache pattern reuse (U8) for Mode B coverage' but no interface is specified.
- **Recommendation**: 

#### LibraryItemMeta retracted Field Propagation Race Condition Not Addressed

- **Severity**: Medium
- **Category**: unaddressed_scenario
- **Description**: U4 business-rules.md BR-L5 specifies that PaperRetractedEvent causes LibraryService to set retracted=true on matching LibraryItems. However, there is no specification for: what happens to SavedSearches referencing retracted papers (only LibraryItems are addressed), whether rerun of a saved search returns retracted papers, how the UI handles a search result card for a retracted paper that is in the user's library, and whether CorpusIndexWriter tombstones papers before or after PaperRetractedEvent is published (ordering).
- **Recommendation**: 

#### Social Login Pre-Hijacking Defense for Email-Only Social Accounts Not Fully Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U3 business-rules.md BR-A9 defines the pre-hijacking defense: if an existing password account matches the social login email, require explicit linking via /auth/social/link with PENDING_CONFIRMATION state. However, the case where a social account exists (email_verified=true, no password credential) and a new password signup is attempted with the same email is not explicitly addressed. BR-A9 focuses on social→password direction but not password→social direction.
- **Recommendation**: 

#### ObservabilityHub PII Scrubbing Rules Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: shared/ports.md §4 and U6 ObservabilityHub specify 'PII/secrets blocked (SEC-3)' and 'normalized with PII blocking.' However, the specific scrubbing rules are not defined: which fields are considered PII (email? userId? query text? arXivId?), whether query text in SearchExecutedEvent telemetry is scrubbed or hashed, and how the scrubbing is implemented (allowlist vs. denylist, field-level vs. regex).
- **Recommendation**: 

#### Missing Bulkhead Pattern for Ingestion Worker Resource Isolation

- **Severity**: Medium
- **Category**: missing_pattern
- **Description**: The design describes U1 as an independently deployed ingestion worker (배포 단위 ②) that makes synchronous calls to arXiv, Semantic Scholar, OpenAlex, GROBID, and Embedding Gateway. However, no bulkhead pattern is specified to isolate resource consumption between these external source calls. A slow GROBID processing queue or Embedding Gateway saturation could starve arXiv source fetching or vice versa.
- **Recommendation**: 

#### U2 PersonalizationDecision Injection Source Not Specified

- **Severity**: Medium
- **Category**: underspecified
- **Description**: U2 business-logic-model.md §1.1 references RequestContext containing a personalizationDecision field used in step 5 (RelevanceRanker). U2 business-rules.md BR-5 references 'U9 PersonalizationDecision.' However, the mechanism by which PersonalizationDecision is injected into RequestContext is not specified: does U6 gateway call U9 before routing to U2, does U2 call U9 directly, or does U5 frontend pass it? The unit-of-work-dependency.md shows U2→U9 as 'sync(profile read) + event(search/open)' but the gateway flow is not detailed.
- **Recommendation**: 


---

## Appendix

### Agent Status

| Agent | Status | Findings | Execution Time |
|-------|--------|----------|---------------|
| critique | Completed | 13 | 115.9s |
| alternatives | Completed | 4 | 93.2s |
| gap | Completed | 16 | 122.5s |


### Token Usage

| Agent | Input Tokens | Output Tokens |
|-------|-------------|--------------|
| critique | 261611 | 5560 |
| alternatives | 265673 | 4171 |
| gap | 261667 | 5581 |

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