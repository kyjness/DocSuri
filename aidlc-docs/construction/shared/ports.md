# shared/ports — 횡단 후크 인터페이스 공용 계약 🟡 PROVISIONAL

**상태**: 🟡 PROVISIONAL (U6 FD/NFR 미완 — 형상은 inception application-design 기준; U6 FD에서 정제) · **일자**: 2026-06-16
**근거**: `component-methods.md` U6(GroundingEnforcementHook·CostGuardCircuitBreaker·ObservabilityHub) · `services.md`(GatewayPipelineService·CostGuardService·GroundingGuardService·ObservabilityService) · `component-dependency.md` §2/§6 + §7 비순환성 주석(U2↔U6) · `00-shared-contracts-overview.md` §2(Ports = U6 구현·U2/U1 의존)
**불변식**: **인터페이스는 `shared/ports`에 선언, 구현은 U6 단독, 의존(호출)은 U2/U1.** U2는 근거화·비용을 **재구현하지 않는다**(단일 권위 = U6). U2 → U6 후크는 주입된 `kind:lib` 의존(`component-dependency.md` §2/§6).

> **상태 범례**: 🔒 **FROZEN**(해당 시그니처가 `component-methods.md`로 잠김 — 변경 시 광범위 영향) · 🟡 **PROVISIONAL**(형상은 application-design 기준; U6 FD에서 정제). 본 계약은 **U6 FD 미완으로 전반 PROVISIONAL**이되, `enforce`/`getBudgetState` 시그니처는 component-methods.md에 잠겨 있어 **그 두 시그니처만 FROZEN**.

---

## 1. 의존성 역전 (Dependency Inversion) — 왜 `shared/ports`인가

| 항목 | 내용 |
|---|---|
| **인터페이스 선언** | `shared/ports`(본 계약 — 추상) |
| **구현(producer)** | **U6 단독** (GroundingEnforcementHook·CostGuardCircuitBreaker·ObservabilityHub) |
| **의존/호출(consumer)** | U2(근거화 매핑·저하 분기), U1(실패 신호 emit), 전 유닛(관측성) |
| **결합 방향** | U2/U1 → `shared/ports`(추상) ← U6(구현). 양쪽 모두 **구상 U6 모듈이 아니라 공용 추상에 의존** → 컴파일·개발 타임 결합 제거. |

**순환 회피 메커니즘** (`component-dependency.md` §7 비순환성 주석):
- 게이트웨이는 **호출자**다: `U6.ApiGatewayMiddleware → U2 핸들러`(인바운드 래핑 sync 체인).
- 핸들러 내부의 `GroundingEnforcementHook`·`CostGuardCircuitBreaker`는 **U6가 구현하고 U2가 주입받는 횡단 lib**(`U2 → U6 hooks`, **kind:lib**).
- U2가 구상 U6 모듈을 직접 import하면 `U6 → U2`(게이트웨이) + `U2 → U6`(후크)로 **sync 순환**이 생긴다. `shared/ports`의 추상 인터페이스에만 의존시키면 토폴로지는 **"1개 인바운드 체인 + 주입 lib"**로 환원되어 **sync 순환이 아니다.**
- 즉 `shared/ports`가 의존성 역전 이음새(seam)이며, U2↔U6 동기 순환 제거의 구조적 근거다.

```
            shared/ports (추상 인터페이스 선언)
                  ▲                       ▲
        depends-on│ (lib 주입)            │ implements
                  │                       │
   U2 / U1 (consumer)              U6 (single implementor)
   - U2: GroundingAdapter로 enforce 입력 정형화·verdict 매핑(독자 강제 없음)
   - U2: getBudgetState로 저하 분기(독자 비용 판정 없음)
   - U1: emitFailureSignal → ObservabilityHub.emitMetric/emitLog
```

---

## 2. GroundingEnforcementHook (근거화 단일 권위 게이트)

**상태**: `enforce` 🔒 FROZEN (component-methods.md 잠금) · `runEvalSet` 🟡 PROVISIONAL
**Owner(구현)**: U6 — `GroundingGuardService`(단일 권위) · **Consumer**: U2 — `GatewayPipelineService` post-handler가 `enforce` 적용, U2.`GroundingAdapter`는 입력 정형화/verdict 매핑만
**불변식**: **U2는 근거화를 강제하지 않는다.** 유일 invocation site = U6 게이트웨이 응답 엣지(post-handler). U2는 `toGroundingInput`로 입력 정형, `mapDecision`로 verdict→결과/기권 매핑만 수행(독자 차단·인시던트 발행 없음).

| 메서드 | 시그니처 | 의미 | 트레이스 |
|---|---|---|---|
| `enforce` 🔒 | `enforce(candidate: CandidateResponse, retrieved: RetrievedRecordSet) -> GroundingDecision` | FR-5/QT-1 단일 런타임 게이트. 후보 응답을 실재 검색 레코드에 매핑·AI 텍스트 출처 검증·통과/차단/기권 결정. | FR-5, QT-1, US-D5/D6/R1 |
| `runEvalSet` 🟡 | `runEvalSet(evalSet: GroundingEvalSet) -> GroundingEvalReport` | QT-1 평가셋을 동일 후크로 실행(날조 0건/코퍼스 밖 기권 보고). OP/팀 소유. | QT-1 |

**타입 카드** (계약 형상 — 직렬화/와이어 형식 아님):

| 타입 | 필드 | 의미 |
|---|---|---|
| `CandidateResponse` | (U2 랭킹 후보 응답 — `RankedResults` 정형 입력) | enforce 대상 AI 출력 후보 |
| `RetrievedRecordSet` | (실재 IndexRecord 집합 — vector-spec.md §2) | 근거 검증 대상 실재 레코드 |
| `GroundingDecision` | `verdict: pass \| block \| abstain`, `violations[]` | enforce 결과(verdict + 위반 목록) |
| `GroundingEvalSet` | (QT-1 평가 케이스 집합) | 평가셋 입력 |
| `GroundingEvalReport` | (케이스별 결과·날조/기권 요약) | 평가 보고 |

> **GroundingInput/GroundingDecision 경계**: U2.`GroundingAdapter.toGroundingInput(RankedResults, QueryPlan) -> GroundingInput{candidateResponse, retrievedRecords}`가 enforce 입력을 정형화하고, `mapDecision(GroundingDecision) -> GroundedResults \| AbstainResult`가 verdict를 매핑한다. **enforce 호출 자체는 U6 게이트웨이가 수행.**

> **설계 주석 (U7 GroundingValidator와의 관계)**: U6의 `GroundingDecision`과 U7의 `AnchorVerdict`는 근거 기반의 출처 확인이라는 개념적 공통점이 있으나, 의도적으로 병렬 설계되었다. U6는 시스템의 최전방 검색 결과 노출을 차단(HARD check, fail-closed)하는 전역 보안/품질 게이트인 반면, U7은 생성된 요약문의 신뢰도를 측정하고 사용자에게 표시 가능한 메타데이터(SOFT check)로 변환하는 목적이 크기 때문이다. 만약 향후 U11과 같은 제3의 컨슈머가 문서 앵커 유효성 검증을 요구할 경우, 공통 앵커 확인 로직을 공유 유틸리티로 추출하되 강제 정책(enforcement policy)은 여전히 분리 유지하는 방향으로 통합을 고려해야 한다.

---

## 3. CostGuardCircuitBreaker (비용 저하 상태 조회)

**상태**: `getBudgetState` 🔒 FROZEN (component-methods.md 잠금)
**Owner(구현)**: U6 — `CostGuardService` · **Consumer**: U2 — `SearchOrchestrationService` 저하 분기
**불변식**: **U2는 비용/예산을 독자 판정하지 않는다.** U2는 `getBudgetState`로 권고 저하 모드만 조회하고 분기(LLM 확장·리랭킹 on/off → lexical 폴백). 누적/임계 평가/서킷 전이(`recordSpend`/`evaluateCircuit`)는 **U6 내부**(본 포트 비노출).

| 메서드 | 시그니처 | 의미 | 트레이스 |
|---|---|---|---|
| `getBudgetState` 🔒 | `getBudgetState() -> BudgetState` | 준실시간 임계 상태·권고 저하 모드 반환(동기 폴백 분기 지원). | NFR-C1, US-R2/R3 |

**타입 카드**:

| 타입 | 필드 | 의미 |
|---|---|---|
| `BudgetState` | `tier`, `degradeMode`, `circuitState` | 예산 티어 + 권고 저하 모드 + 서킷 상태(U2 분기 신호) |

> `degradeMode`는 U2가 임베딩 확장/LLM 리랭킹을 끄고 lexical-only로 폴백하는 신호다(vector-spec.md §1 저하 모드 — 임베딩 공간 자체는 불변). `recordSpend`/`evaluateCircuit`는 포트로 노출하지 않는다(U6 내부 운용).

---

## 4. ObservabilityHub (관측성 단일 수집 — 전 유닛 의존)

**상태**: 🟡 PROVISIONAL (시그니처는 component-methods.md 형상 기준; U6 FD에서 정제)
**Owner(구현)**: U6 — `ObservabilityService` · **Consumer**: **전 유닛**(NFR-O1). U1.`IngestFailureHandler.emitFailureSignal`이 본 포트(`emitMetric`/`emitLog`)로 라우팅.
**불변식**: 로그·메트릭·감사에 **PII/시크릿 비포함**(SEC-3). 내부 점수·소유자·디버그 필드는 DTO/외부 노출 금지(SEC-9) — 관측성 엔트리도 동일 정규화 대상.

| 메서드 | 시그니처 | 의미 | 트레이스 |
|---|---|---|---|
| `emitMetric` 🟡 | `emitMetric(name: MetricName, value: MetricValue, tags: TagSet) -> void` | 지연·에러율·처리량·근거화/검색 건강도·지출 메트릭 수집. | NFR-O1, RES-5 |
| `emitLog` 🟡 | `emitLog(entry: StructuredLogEntry) -> void` | 요청 ID 상관 구조화 로그 수집(PII/시크릿 차단). | NFR-O1, SEC-3 |
| `startSpan` 🟡 | `startSpan(name: SpanName, context: TraceContext) -> Span` | 분산 트레이스 스팬 시작(동기 경로 지연 추적). | NFR-O1 |
| `auditAppend` 🟡 | `auditAppend(event: AuditEvent) -> void` | 핵심 변경·인가 결정 추가 전용 감사 로그(90일+). | SEC-13, SEC-14 |

**타입 카드**:

| 타입 | 필드 | 의미 |
|---|---|---|
| `StructuredLogEntry` | (requestId 상관 구조화 필드 — PII/시크릿 비포함) | 구조화 로그 엔트리 |
| `AuditEvent` | (핵심 변경/인가 결정 — append-only) | 감사 이벤트 |
| `Span` / `TraceContext` | (트레이스 스팬·전파 컨텍스트) | 분산 트레이싱 핸들 |
| `MetricName` / `MetricValue` / `TagSet` / `SpanName` | (메트릭/스팬 식별·값·태그) | 관측성 원시 타입 |

> **U1 실패 신호 라우팅**: U1.`IngestFailureHandler.emitFailureSignal(jobId, error)`은 본 포트(`emitMetric`/`emitLog`)로 인제스천 실패를 관측성/경보 신호화한다(`services.md` IngestionResilienceService, RES-7).

---

## 5. 단일 권위·재구현 금지 (요약)

- **근거화**: 단일 권위 = U6.`GroundingEnforcementHook`. U2는 `GroundingAdapter`(정형화/매핑)만 — **enforce 재구현 금지**, 유일 invocation site = U6 게이트웨이 post-handler.
- **비용**: 단일 권위 = U6.`CostGuardCircuitBreaker`. U2는 `getBudgetState` 조회·분기만 — **누적/임계/서킷 판정 재구현 금지**.
- **관측성**: 단일 수집 = U6.`ObservabilityHub`. 전 유닛은 `emit*`/`auditAppend` 제출만.
- **버전 정책**(00-overview §4): Ports 인터페이스 변경은 공용 PR + 영향 유닛(U2/U1/U6) 합의. U6 FD 확정 시 PROVISIONAL 항목 동기화.
