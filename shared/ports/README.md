# shared/ports — Cross-Cutting Hook Interfaces

> **Status:** 🟡 PROVISIONAL (U6 FD/NFR not yet complete; shapes follow inception
> `application-design`, refined in U6 FD). `GroundingEnforcementHook.enforce` and
> `CostGuardCircuitBreaker.getBudgetState` signatures are 🔒 **FROZEN** (locked by
> `component-methods.md`). Everything else is provisional.
> **Source of truth:** `aidlc-docs/construction/shared/ports.md`.

This directory documents **method interfaces**, *not* data schemas. Ports are
backend-language-bound; **§5-A decided backend = Python**, which per **§5-B** provides the
Python `typing.Protocol` stubs in
[`../python/src/docsuri_shared/ports.py`](../python/src/docsuri_shared/ports.py)
(this README's signatures remain the SSOT). See [Per-language stubs](#per-language-stubs).

The data schemas in sibling directories (`../dtos`, `../events`, `../vector-spec`)
are JSON Schema. Ports are different: they are **abstract behavioral seams** that
U6 implements and U2/U1 call. Their *type cards* below describe contract shape
only — not wire/serialization format.

---

## Why `shared/ports` exists — Dependency Inversion (breaks the U2↔U6 cycle)

The interfaces are **declared here (abstract)**; the implementation lives **in U6
alone**; the dependants (callers) are **U2 and U1**.

```
            shared/ports  (abstract interface declarations)
                  ▲                         ▲
        depends-on│ (lib injection)         │ implements
                  │                         │
   U2 / U1 (consumers)                U6 (single implementor)
   - U2: GroundingAdapter shapes enforce input + maps verdict (no own enforcement)
   - U2: getBudgetState drives degrade branching (no own cost judgement)
   - U1: emitFailureSignal → ObservabilityHub.emitMetric / emitLog
```

| Aspect | Detail |
|---|---|
| **Interface declaration** | `shared/ports` (this contract — abstract). |
| **Implementation (producer)** | **U6 only** — `GroundingEnforcementHook`, `CostGuardCircuitBreaker`, `ObservabilityHub`. |
| **Dependant / caller (consumer)** | U2 (grounding mapping, degrade branching), U1 (failure-signal emit), all units (observability). |
| **Coupling direction** | U2/U1 → `shared/ports` (abstract) ← U6 (impl). Both sides depend on the shared abstraction, **not** on a concrete U6 module → compile/dev-time coupling removed. |

**Cycle avoidance** (`component-dependency.md` §7 acyclicity note):

- The gateway is the **caller**: `U6.ApiGatewayMiddleware → U2 handler` (inbound-wrapping sync chain).
- Inside the handler, `GroundingEnforcementHook` and `CostGuardCircuitBreaker` are
  **cross-cutting libs that U6 implements and U2 receives by injection** (`U2 → U6 hooks`, **kind:lib**).
- If U2 imported a concrete U6 module directly, you would get `U6 → U2` (gateway) +
  `U2 → U6` (hooks) = a **sync cycle**. Depending only on the `shared/ports`
  abstraction reduces the topology to **"one inbound chain + injected lib"**, which is **not** a sync cycle.
- Thus `shared/ports` is the dependency-inversion **seam** — the structural basis for removing the U2↔U6 sync cycle.

**Single authority — no re-implementation** (ports.md §5):

- **Grounding**: single authority = `U6.GroundingEnforcementHook`. U2 does the
  `GroundingAdapter` (shaping + verdict mapping) only — **U2 MUST NOT re-implement
  `enforce`**. The only invocation site is the U6 gateway post-handler.
- **Cost**: single authority = `U6.CostGuardCircuitBreaker`. U2 calls `getBudgetState`
  and branches only — **U2 MUST NOT re-implement** accumulation / threshold / circuit judgement
  (`recordSpend` / `evaluateCircuit` are U6-internal, not exposed on this port).
- **Observability**: single collector = `U6.ObservabilityHub`. All units only submit `emit*` / `auditAppend`.

---

## 1. GroundingEnforcementHook — grounding single-authority gate

- **Owner (impl):** U6 — `GroundingGuardService` (single authority).
- **Consumer:** U2 — `GatewayPipelineService` post-handler applies `enforce`;
  U2's `GroundingAdapter` only shapes input / maps verdict.
- **Invariant:** **U2 does not enforce grounding.** The sole invocation site is the
  U6 gateway response edge (post-handler). U2 uses `toGroundingInput` to shape the
  input and `mapDecision` to map verdict → result/abstain only (no independent
  blocking, no incident publishing).

| Method | Signature | State | Meaning | Trace |
|---|---|---|---|---|
| `enforce` | `enforce(candidate: CandidateResponse, retrieved: RetrievedRecordSet) -> GroundingDecision` | 🔒 FROZEN | FR-5/QT-1 single runtime gate. Maps a candidate response to real retrieved records, verifies AI-text provenance, decides pass / block / abstain. | FR-5, QT-1, US-D5/D6/R1 |
| `runEvalSet` | `runEvalSet(evalSet: GroundingEvalSet) -> GroundingEvalReport` | 🟡 PROVISIONAL | Runs the QT-1 eval set through the *same* hook (reports zero-fabrication / out-of-corpus abstain). OP/team owned. | QT-1 |

**Type cards** (contract shape — not wire/serialization format):

| Type | Fields | Meaning |
|---|---|---|
| `CandidateResponse` | U2 ranked candidate response (`RankedResults`, shaped) | The AI-output candidate subject to enforce. |
| `RetrievedRecordSet` | set of real `IndexRecord`s (`../vector-spec/index-record.schema.json`, vector-spec.md §2) | Real records grounding is verified against. |
| `GroundingDecision` | `verdict: pass \| block \| abstain`, `violations[]` | enforce result (verdict + violation list). |
| `GroundingEvalSet` | QT-1 evaluation case set | Eval-set input. |
| `GroundingEvalReport` | per-case results + fabrication/abstain summary | Eval report. |

> **Boundary:** U2.`GroundingAdapter.toGroundingInput(RankedResults, QueryPlan) -> GroundingInput{candidateResponse, retrievedRecords}` shapes the enforce input, and
> `mapDecision(GroundingDecision) -> GroundedResults | AbstainResult` maps the verdict.
> **The `enforce` call itself is made by the U6 gateway.**

---

## 2. CostGuardCircuitBreaker — cost-degrade state query

- **Owner (impl):** U6 — `CostGuardService`.
- **Consumer:** U2 — `SearchOrchestrationService` degrade branching.
- **Invariant:** **U2 does not judge cost/budget independently.** U2 calls
  `getBudgetState` to read the advisory degrade mode and branches (LLM expansion /
  reranking on/off → lexical fallback). Accumulation / threshold evaluation /
  circuit transition (`recordSpend` / `evaluateCircuit`) are **U6-internal** (not on this port).

| Method | Signature | State | Meaning | Trace |
|---|---|---|---|---|
| `getBudgetState` | `getBudgetState() -> BudgetState` | 🔒 FROZEN | Returns near-real-time threshold state + advisory degrade mode (supports synchronous fallback branching). | NFR-C1, US-R2/R3 |

**Type card:**

| Type | Fields | Meaning |
|---|---|---|
| `BudgetState` | `tier`, `degradeMode`, `circuitState` | Budget tier + advisory degrade mode + circuit state (U2 branching signal). |

> `degradeMode` is the signal for U2 to turn off embedding expansion / LLM reranking
> and fall back to lexical-only (`../vector-spec/vector-spec.yaml` degrade mode — the
> embedding space itself is unchanged). `recordSpend` / `evaluateCircuit` are not exposed (U6-internal).

---

## 3. ObservabilityHub — single observability collector (all units depend)

- **Owner (impl):** U6 — `ObservabilityService`.
- **Consumer:** **all units** (NFR-O1). U1.`IngestFailureHandler.emitFailureSignal`
  routes to this port (`emitMetric` / `emitLog`).
- **State:** 🟡 PROVISIONAL (signatures follow `component-methods.md`; refined in U6 FD).
- **Invariant:** logs/metrics/audit carry **no PII/secrets** (SEC-3); internal
  scores/owner/debug fields are forbidden in DTOs/external exposure (SEC-9) — observability entries normalize the same way.

| Method | Signature | State | Meaning | Trace |
|---|---|---|---|---|
| `emitMetric` | `emitMetric(name: MetricName, value: MetricValue, tags: TagSet) -> void` | 🟡 PROVISIONAL | Collect latency / error-rate / throughput / grounding-and-search-health / spend metrics. | NFR-O1, RES-5 |
| `emitLog` | `emitLog(entry: StructuredLogEntry) -> void` | 🟡 PROVISIONAL | Collect request-ID-correlated structured logs (PII/secrets blocked). | NFR-O1, SEC-3 |
| `startSpan` | `startSpan(name: SpanName, context: TraceContext) -> Span` | 🟡 PROVISIONAL | Start a distributed-trace span (sync-path latency tracing). | NFR-O1 |
| `auditAppend` | `auditAppend(event: AuditEvent) -> void` | 🟡 PROVISIONAL | Append-only audit log of core changes / authorization decisions (90 days+). | SEC-13, SEC-14 |

**Type cards:**

| Type | Fields | Meaning |
|---|---|---|
| `StructuredLogEntry` | requestId-correlated structured fields (no PII/secrets) | Structured log entry. |
| `AuditEvent` | core change / authorization decision (append-only) | Audit event. |
| `Span` / `TraceContext` | trace span / propagation context | Distributed-tracing handles. |
| `MetricName` / `MetricValue` / `TagSet` / `SpanName` | metric/span identifier / value / tags | Observability primitive types. |

> **U1 failure-signal routing:** U1.`IngestFailureHandler.emitFailureSignal(jobId, error)`
> routes ingestion failures to this port (`emitMetric` / `emitLog`) as observability/alert
> signals (`services.md` IngestionResilienceService, RES-7). The event-backbone shape of that
> signal is in `../events/ingestion.schema.json` (`IngestionFailureSignal`).

---

## 4. EvidenceFormationPort — 다논문 근거형성 단일 권한 포트 (D5)

- **Owner (impl):** U4 — 문헌탐색·근거형성 Agent (화랑님). 단독 구현자.
- **Consumer:** U12 — 연구아이디어 Agent (석현님). 주입 lib으로 소비. **재구현 금지**.
- **State:** 🔒 **FROZEN** (D5 계약 게이트 — Q1~Q3 확정 후 동결, 2026-06-29).
- **순환 차단:** `U12 → shared/ports(추상) ← U4`. U12가 U4 구체 모듈 직접 import 금지.
- **데이터 스키마 SSOT:** `../dtos/evidence.schema.json` (§5-B, `_generated/dtos/evidence_schema.py`로 생성).

| 메서드 | 시그니처 | 상태 | 의미 | Trace |
|---|---|---|---|---|
| `form_evidence` | `async form_evidence(request: EvidenceRequest, ctx) -> EvidenceResult \| EvidenceAbstainResult` | 🔒 FROZEN | 다논문 교차확인 → 근거 비교·정리 → 출처·기권. U12 Research Gap/Novelty 판단 입력. | Q1, Q3, Q4, Q9, FR-5, SEC-9, C-2, D5 |

**타입 카드** (계약 형태 — 직렬화 포맷 아님. SSOT: `../dtos/evidence.schema.json`):

| 타입 | 필드 | 의미 |
|---|---|---|
| `EvidenceRequest` | `topic`(연구 주제/질문) · `scope`(auto\|explicit\|mixed — Q4=A) · `paperIds?`(명시 집합) · `attachments?`(첨부 — Q6=A) · `constraints?`(기간/분야/논문수 — FD 이월) | 근거형성 입력. |
| `EvidenceResult` | `state: ok` · `claims: EvidenceItem[]` · `coverage: EvidenceCoverage` | 근거형성 성공 산출. |
| `EvidenceAbstainResult` | `state: abstain` · `abstainReason` (비기술 사유 — SEC-9) | 근거 0건/범위 밖 기권(FR-5, 날조 금지). |
| `EvidenceItem` | `statement`(추출 근거 명제) · `supporting: SourceRef[]` · `conflicting: SourceRef[]` (confidence 제외 — Q3=B) | 근거 명제 + 지지/상충 출처. confidence는 U12가 자체 산출. |
| `SourceRef` | `paperId`(arXiv ID) · `recordRef`(IndexRecord 핸들) · `anchor?`(DocModel Block id) · `quote?`(원문 스니펫) | 출처 핸들 — 기존 계약 재사용(vector-spec §2, summarization AnchorTarget). |
| `EvidenceCoverage` | `paperCount: int` · `queryUsed?: str` | 사용 논문 수·쿼리 요약(투명성, 내부 점수 미노출 SEC-9). |

**단일 권한 불변식 (U12 준수 필수):**
- U12는 `form_evidence`를 직접 호출한다 — 재구현하거나 U4 내부 모듈을 import하지 않는다.
- `EvidenceItem.statement`는 논문 추출 근거 명제만 — 생성 산문 금지(C-2).
- `state=abstain`이면 U12는 날조 없이 기권으로 처리(FR-5).
- `abstainReason`은 비기술 코드만 — 내부 위반 상세/점수 비노출(SEC-9).

**변경 정책:** 동결된 시그니처 변경 시 **shared 계약 PR + U4(화랑님)·U12(석현님) 사인오프** 필수 (기존 ports 변경정책 준용).

---

## Per-language stubs

Ports are method interfaces bound to a backend language; unlike the JSON Schema data
contracts (`../dtos`, `../events`, `../vector-spec`), they cannot be generated
language-neutrally. This README's signatures are the **normative SSOT**; per-language
stubs are derived from it (no shape changes).

- **Python** — ✅ **provided** at
  [`../python/src/docsuri_shared/ports.py`](../python/src/docsuri_shared/ports.py)
  (§5-B, enabled by §5-A=Python). `typing.Protocol` (structural) stubs, e.g.
  `class GroundingEnforcementHook(Protocol): def enforce(self, candidate, retrieved) -> GroundingDecision: ...`.
  Method names are pythonic `snake_case`; each docstring cites the spec's camelCase name
  and FROZEN/PROVISIONAL state. Provisional payload shapes are loose aliases until U6 FD.
- **TypeScript** — deferred to U5 (frontend stack confirmed in U5 NFR Requirements, §5-D):
  `export interface GroundingEnforcementHook { enforce(candidate: CandidateResponse, retrieved: RetrievedRecordSet): GroundingDecision }`.

U6 implements; U2/U1 depend on the abstraction by injection (kind:lib). The frozen
signatures (`enforce`, `getBudgetState`) MUST NOT change without a shared-contract PR
+ affected-unit (U2/U1/U6) sign-off; provisional items sync to U6 FD when it completes.

---

## Change policy

Port interface changes require a **shared contract PR + affected-unit (U2/U1/U6)
sign-off** (00-shared-contracts-overview.md §4). When U6 FD is finalized, the
PROVISIONAL items here are synchronized.
