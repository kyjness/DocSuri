# shared/events — 이벤트 백본 공용 계약 🟡 일부 FROZEN

**상태**: 🟡 **일부 FROZEN**(`SearchExecutedEvent` 형상 동결 — component-methods.md 고정; 그 외 PROVISIONAL — 소유 유닛 FD에서 정제) · **일자**: 2026-06-16
**근거**: `application-design/{component-methods,services,component-dependency}.md`(생산자/소비자·sync/event/lib 엣지) · `00-shared-contracts-overview.md`(상태 범례·트랙 소비) · `vector-spec.md`(IndexRecord 식별자 — `arxivRef`/`paperId` 정합)
**불변식**: 이벤트 백본은 **비동기 fire-and-forget·구독**(component-dependency.md `kind:event`). 사용자 동기 READ 경로(NFR-P1 P50<3s) **밖**. 전 이벤트 **at-least-once 전달** 전제 → 소비자는 **멱등 처리**.

> **상태 범례**(overview.md 준용): 🔒 **FROZEN**(형상 고정 — 변경 시 광범위 영향) · 🟡 **PROVISIONAL**(잠정 — inception application-design 기준; 소유 유닛 FD에서 정제).
> **altitude**: 계약 형상(필드·타입·의미·생산/소비·전달 보장)만 기술. 직렬화 포맷·와이어 프로토콜·토픽명·파티셔닝은 Infra Design.
> **보안**: 이벤트 페이로드에 내부 필드(소유자 외 내부 점수·디버그) 비노출(SEC-9); PII/시크릿 금지(SEC-3) — 로그·이벤트 공통.

---

## 1. 이벤트 카탈로그 (요약)

| 이벤트 | 상태 | 생산자(유닛) | 소비자(유닛) | 전달/멱등 | 트레이스 |
|---|---|---|---|---|---|
| `SearchExecutedEvent` | 🔒 FROZEN | U2.SearchOrchestrationService.publishSearchExecuted | U4.SearchHistoryService.recordSearch | at-least-once · 멱등 기록 | FR-10, NFR-P1 |
| `AccountCreated` | 🟡 PROVISIONAL | U3.SignupService | U6 Observability·Ops(남용/감사) | at-least-once · 멱등 | FR-7, US-A1, NFR-O1 |
| `SignupAbuseSignal` | 🟡 PROVISIONAL | U3.SignupService | U6 Ops(남용 완화) | at-least-once · 멱등 | SEC-11, RES-11 |
| `AuthFailureSignal` | 🟡 PROVISIONAL | U3.AuthenticationService | U6 Ops(무차별대입 락아웃/지연/CAPTCHA) | at-least-once · 멱등 | SEC-12, RES-11 |
| `NewArxivEvent` | 🟡 소비 형상 FROZEN-인접 | (외부/업스트림 → Event Bus) | U1.NewArxivEventHandler.onNewArxivEvent | at-least-once · 멱등(DeduplicationGuard `DUPLICATE`) | FR-6, US-I2, BR-12 |
| 인제스천 실패 신호 | 🟡 PROVISIONAL | U1.IngestFailureHandler.emitFailureSignal | U6.ObservabilityHub | at-least-once · 멱등 | RES-7, US-I2/I3 |
| AI 인시던트(`ClassifiedIncident`) | 🟡 PROVISIONAL | U6.IncidentEventPublisher.publishIncident | Event Backbone → IR/COE·OpsDashboardService | at-least-once · 멱등(requestId 상관) | RES-11(a/b/c), US-R4 |
| 운영 경보(`OpsAlert`) | 🟡 PROVISIONAL | U6.IncidentEventPublisher.publishAlert | Event Backbone → IR/COE | at-least-once · 멱등 | RES-7, RES-11, US-R4 |
| `AccountDeleted` | 🟡 PROVISIONAL | U3.AccountDeletionService.purgeJob (**유예 경과 후 발행**) | U4·U2 (각자 owner-scoped 파기) | at-least-once · **멱등(`accountId` 키)** · DLQ | FR-28, US-A6, SEC-8 |
| `AccountPurged` | 🟡 PROVISIONAL | U4·U2 (파기 완료 후 발행) | U3.AccountDeletionService (완료 추적) | at-least-once · 멱등(`accountId`+`unit`) | FR-28, GDPR |
| `PaperRetractedEvent` | 🟡 PROVISIONAL | U1.VectorIndexWriter (철회 툼스톤 생성 시) | U4.LibraryService (철회 상태 마킹) | at-least-once · 멱등(`paperId`) | BR-L5 보완 |
| `DocModelBuildRequestedEvent` | 🟡 PROVISIONAL | U7.SummaryService (doc-model 캐시 미스 시) | U1.DocModelBuilder | at-least-once · 멱등(`paperId`+`version`) | doc-model lazy build |

---

## 1d. U7 → U1 — `DocModelBuildRequestedEvent` 🟡 PROVISIONAL

U7(또는 리치뷰 클라이언트)이 doc-model을 요청했으나 캐시 미스가 발생한 경우, U1에게 비동기 빌드를 지시하기 위해 발행된다. U1 큐에 직접 결합되는 대신 이벤트 버스를 통해 발행하여 생산자와 소비자를 분리한다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `paperId` | string | 대상 논문 ID |
| `version` | int | 논문 버전 |
| `requestedAt` | timestamp | 빌드 요청 시각 |
| `source` | string | 요청 출처 (예: `U7-Summarization`) |

- **생산자**: `U7` — 클라이언트의 첫 열람 또는 요약 요청 시 `doc-model` 캐시가 없으면 발행.
- **소비자**: `U1.DocModelBuilder` — 이벤트를 수신하여 `buildDocModel(paperId, version)` 워커 잡을 실행. **멱등**(동일 논문/버전 중복 빌드 요청 시 인프로세스 디덥 및 기존 캐시 확인 후 무시).
- **상태 확인**: 비동기 빌드 완료 이벤트는 따로 발행하지 않으며, 클라이언트는 getDocModel 응답 union의 `building`(`BuildingDTO` — docmodel.md §5·`docmodel.schema.json`) 수신 시 일정 시간 후 다시 API를 폴링하여 `doc-model` 캐시 히트를 확인한다 (getDocModel 폴링).

## 1c. U1 → U4 — `PaperRetractedEvent` 🟡 PROVISIONAL

U1 인제스천 파이프라인에서 arXiv 원문이 철회(retracted)되거나 철회 툼스톤이 감지되었을 때 발행된다.

| 필드 | 타입 | 의미 |
|---|---|---|
| `paperId` | string | 철회된 논문의 고유 식별자(arxivId 등) |
| `retractedAt` | timestamp | 철회 감지 시각 |

- **생산자**: `U1.VectorIndexWriter` — 기존 논문 식별자에 대해 철회 상태가 업데이트되거나 툼스톤 레코드가 생성될 때 발행.
- **소비자**: `U4.LibraryService` — 이벤트를 수신하여 라이브러리에 저장된 `LibraryItem` 중 해당 `paperId`를 가진 항목의 메타데이터에 `retracted: true` 플래그를 추가로 마킹. 데이터는 삭제하지 않고 보존하여 사용자 경험을 유지하면서 신뢰성 문제만 알린다.

## 1b. U3 → U4·U2 — `AccountDeleted` 🟡 PROVISIONAL *(계정 프로덕션화, 2026-06-24)*

계정 영구 파기(유예 경과 후 `purgeJob`) 시 발행되는 캐스케이드 파기 이벤트. **소프트 삭제 시점이 아니라 파기 시점에 발행**(유예 동안 데이터 보존·복구 가능, H2).

| 필드 | 타입 | 의미 |
|---|---|---|
| `accountId` | string | 파기 대상 계정(**멱등 키** — 구독자 중복 처리 방지) |
| `occurredAt` | timestamp | 파기 확정 시각 |
| `eventId` | string | 발행 단위 유일 ID(at-least-once 중복 식별) |

- **생산자**: `U3.AccountDeletionService.purgeJob` — `purge_after` 경과분 일괄 발행.
- **소비자**: U4(라이브러리·저장검색)·U2(이력) — 각자 owner-scoped 데이터 파기. **멱등(`accountId`)**, 실패 시 재시도 → **DLQ**. (분리될 연구 에이전트 유닛은 생성 시 동일 구독 패턴으로 편입.)
- **완료 검증(#1 리뷰, GDPR)**: 각 구독자는 자신의 파기 트랜잭션이 완료되면 `AccountPurged{accountId, unit, purgedAt}` 이벤트를 발행한다. U3는 이를 수신하여 캐스케이드 완료 상태를 추적하고, 최대 허용 지연(예: 7일) 내에 모든 필수 구독자(U2, U4)의 확인이 수신되지 않으면 명시적인 `CascadeOverdue` 경보를 발생시킨다. (단순 감사 로그 의존 배제)
- **유예 기간 N**: 기본 제안 **30일**(운영 정책·법적 요건으로 조정 — Infra Design 확정).
- **순서**: U3 파기와 캐스케이드 간 순서 보장 없음(결과적 일관성); 구독자 멱등으로 재정렬 무해.

### 1b-2. 구독자 → U3 — `AccountPurged` 🟡 PROVISIONAL
각 구독자(U4, U2)가 AccountDeleted에 따른 자원 파기를 완료한 후 발행하는 명시적 확인 신호.
| 필드 | 타입 | 의미 |
|---|---|---|
| `accountId` | string | 대상 계정 ID |
| `unit` | string | 완료한 유닛 식별자 (예: "U4", "U2") |
| `purgedAt` | timestamp | 실제 파기 완료 시각 |

---

## 2. U2 → U4 — `SearchExecutedEvent` 🔒 FROZEN

성공 검색 응답 **후** 발행되는 이력 쓰기 이벤트. **형상 고정**(component-methods.md `publishSearchExecuted`/`recordSearch` 시그니처).

| 필드 | 타입 | 의미 |
|---|---|---|
| `userId` | string | 검색 실행 사용자(소유자 키 — 이력 owner-scoping) |
| `requestId` | string | 이벤트 고유 식별자(의도적 반복 쿼리와 재전달 구분을 위함) |
| `query` | string | 실행된 질의 문자열 |
| `timestamp` | timestamp | 검색 실행 시각 |
| `resultCount` | int | 반환 결과 건수 |

- **생산자**: `U2.SearchOrchestrationService.publishSearchExecuted(userId, requestId, query, timestamp, resultCount) -> void` — 성공 응답 직후 이벤트 백본 발행.
- **소비자**: `U4.SearchHistoryService.recordSearch(event: SearchExecutedEvent) -> void` — 공유 이벤트 버스 구독해 비동기 기록.
- **비차단(NFR-P1)**: ⚠️ **P50<3s 동기 검색 경로 밖**에서 발행·소비. 검색 응답을 블로킹하지 않음(component-dependency.md "P50<3s 경로 밖").
- **at-least-once/멱등**: 중복 전달 가능 → U4는 멱등 기록(예: 동일 `userId`+`requestId`+`query` 재수신 시 중복 행 생성 금지). 내부 필드 비노출(SEC-9) — owner 점수·디버그 미포함.
- **트레이스**: FR-10, NFR-P1, US-L3.

---

## 3. U3 — 계정/인증 신호 (🟡 PROVISIONAL — U3 FD에서 정제)

U3 SignupService/AuthenticationService가 도메인 처리 후 발행하는 이벤트(services.md). **형상은 U3 FD에서 확정**; 아래는 발행 사실·생산/소비·의미만 고정.

### 3.1 `AccountCreated`
- **생산자**: `U3.SignupService` — 정책·유일성 검증·해싱·영속 성공 후 발행(services.md `register` 오케스트레이션).
- **소비자**: U6 Observability/Ops(가입 텔레메트리·감사 팬아웃).
- **at-least-once/멱등**: 중복 전달 가능 → 소비자 멱등(중복 가입 텔레메트리 억제). PII 최소화(SEC-3) — 평문 비밀번호·자격증명 절대 미포함(FR-7/SEC-12 불변식).
- **트레이스**: FR-7, US-A1, NFR-O1.

### 3.2 `SignupAbuseSignal`
- **생산자**: `U3.SignupService` — 속도/중복 등 남용 징후 시 발행.
- **소비자**: U6 Ops(가입 남용 완화 — 게이트웨이 레이트 리미팅 SEC-11과 연동).
- **at-least-once/멱등**: 중복 신호 멱등 처리. 시크릿/PII 비노출(SEC-3).
- **트레이스**: SEC-11, RES-11.

### 3.3 `AuthFailureSignal`
- **생산자**: `U3.AuthenticationService` — 자격증명 검증 실패 시 발행(자격증명 존재 미노출 불변식 유지).
- **소비자**: U6 Ops(무차별 대입 탐지 → 락아웃/지연/CAPTCHA 강제·경보).
- **at-least-once/멱등**: 중복 전달 멱등. 실패 사유 일반화 — 어느 자격증명이 틀렸는지 미노출(SEC-12).
- **트레이스**: SEC-12, RES-11.

---

## 4. U1 — 인제스천 백본 이벤트 (🟡 PROVISIONAL — U1 FD에서 정제)

> 인제스천 전 구간은 이벤트/스케줄 백본 — **사용자 동기 경로 아님**(services.md U1, component-dependency.md §1).

### 4.1 `NewArxivEvent` (소비)
신규-arXiv 통지 이벤트(Q12=B). U1이 **구독·소비**하여 인제스천 잡으로 변환. **소비 형상 `{eventId, arxivRef}`는 완료된 U1 FD(domain-entities.md §5)로 동결(FROZEN-인접)** — 업스트림 **생산자 와이어 계약만 PROVISIONAL**(외부 통지원 미확정).

| 필드 | 타입 | 의미 |
|---|---|---|
| `eventId` | string | 이벤트 식별자(처리 완료 ack 키·멱등 경계) |
| `arxivRef` | string | 신규 논문 arXiv 참조(인제스천 대상 식별 — vector-spec.md `paperId`/`arxivId`로 해소) |

- **생산자**: 외부/업스트림 통지 → Event Bus(shared capability). U1 외부.
- **소비자**: `U1.NewArxivEventHandler.onNewArxivEvent(event: NewArxivEvent) -> IngestionJob` → RefreshOrchestrationService가 IngestionPipelineService로 분배.
- **at-least-once/멱등**: ⚠️ **at-least-once 전달**(component-dependency.md "at-least-once 멱등"). 중복 소비 방지는 **`DeduplicationGuard`가 `DUPLICATE` 판정**(component-methods.md `isNew -> DedupDecision{NEW|CHANGED|DUPLICATE}`)으로 처리 — 중복이면 파이프라인 단락(BR-12). 처리 완료는 `U1.NewArxivEventHandler.ackEvent(eventId) -> void`로 확인.
- **트레이스**: FR-6, US-I2, BR-12, DQ3, DQ6.

### 4.2 인제스천 실패 신호 (발행)
인제스천 단계 실패를 관측성/경보 신호로 발행.

- **생산자**: `U1.IngestFailureHandler.emitFailureSignal(jobId: JobId, error: IngestError) -> void` — 분류·재시도·DLQ 후 실패를 신호화(IngestionResilienceService 오케스트레이션).
- **소비자**: `U6.ObservabilityHub`(구조화 로그·경보 라우팅 — component-dependency.md `U1-Ingestion → U6.ObservabilityHub (event)`).
- **at-least-once/멱등**: 중복 실패 신호 멱등 집계. 페이로드 PII/시크릿 비노출(SEC-3); 내부 스택 트레이스 등 디버그 비노출(SEC-9).
- **트레이스**: RES-7, US-I2, US-I3, NFR-O1.

---

## 5. U6 — AI 인시던트 이벤트 (🟡 PROVISIONAL — U6 FD에서 정제)

RES-11 세 인시던트 클래스(a 비용 폭발 / b 할루시네이션 / c 반쪽짜리 결과)를 탐지·분류·발행. 탐지·발행 **전 구간 비동기**(services.md AiIncidentResponseService, 별도 워커 DQ1).

### 5.1 `ClassifiedIncident` (via `publishIncident`)

| 필드 | 타입 | 의미 |
|---|---|---|
| `class` | enum `a` \| `b` \| `c` | RES-11 인시던트 클래스(a=비용 폭발 / b=할루시네이션 / c=반쪽짜리 결과) |
| `severity` | enum/level | 인시던트 심각도 |
| `requestId` | string | 요청 상관 식별자(correlation — 트레이스·감사 연계) |

- **생산자**: `U6.IncidentEventPublisher.publishIncident(incident: ClassifiedIncident) -> void` — `AiIncidentDetectorSuite.classify` 결과를 표준 스키마 발행·감사 기록. 클래스별 탐지기: `CostExplosionDetector`(a) / `HallucinationDetector`(b) / `PartialResultDetector`(c).
- **소비자**: Event Backbone → IR/COE 라우팅 · `OpsDashboardService`(상태 소비·`listIncidents`).
- **at-least-once/멱등**: 중복 인시던트 전달 가능 → **`requestId` 상관**으로 멱등 디덥(동일 인시던트 중복 페이지/COE 방지).
- **트레이스**: RES-11(a/b/c), NFR-O1, US-R1/R2/R3/R4.

### 5.2 `OpsAlert` (via `publishAlert`)
- **생산자**: `U6.IncidentEventPublisher.publishAlert(alert: OpsAlert) -> void` — 임계 위반/인시던트의 운영 경보 발행.
- **소비자**: Event Backbone → IR/COE 라우팅.
- **at-least-once/멱등**: 중복 경보 멱등 억제. 시크릿/PII 비노출(SEC-3).
- **트레이스**: RES-7, RES-11, US-R4.

---

## 6. 진화·호환 정책 (overview.md §4 준용)
- **가산적 진화**: 필드 추가는 하위호환; 제거/의미 변경은 버전업. 소비자는 미지 필드 무시(forward-compat).
- **FROZEN**: `SearchExecutedEvent` 형상 변경은 광범위 영향(U2 생산·U4 소비) → 공용 계약 PR + 영향 유닛 합의.
- **PROVISIONAL → FROZEN 전환**: 소유 유닛(U1/U3/U6) FD 완료 시 형상 확정·본 문서 동기화.
- **at-least-once 공통 불변식**: 모든 소비자는 멱등(중복 전달 안전). U1은 `DeduplicationGuard`/`ackEvent`, U4는 멱등 기록, U6는 `requestId` 상관 디덥.
