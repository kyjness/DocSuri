# component-dependency.md — 의존성 매트릭스·통신 패턴·데이터 흐름 (Application Design)

> kind 표기: **sync**(요청→응답, 블로킹) / **event**(이벤트 백본, 비동기 fire-and-forget·구독) / **lib**(프로세스 내 라이브러리/함수 호출).
> 잠금 결정 준수: 디스커버리 사용자 READ 경로는 전부 sync(DQ6); 인제스천·이력 쓰기·인시던트·관측성은 event 백본.

## 비평 반영 요약 (이 문서 관련)
- 팬텀 `U2.DiscoveryService`/`U2-DiscoveryAPI`/`U2 Discovery(consumer)` 명칭을 실재 표면(`QueryIntakeController`(REST 진입), `SearchOrchestrationService`(서비스 파사드))로 통일.
- **SearchExecuted 생산자 엣지 신설**: `U2.SearchOrchestrationService → Event Backbone (event)`.
- **rerun 게이트웨이 재진입**: `U4.* → U6.ApiGatewayMiddleware (sync, 게이트웨이-프런티드 검색 계약)`로 재배선(U2 직접 호출 제거).
- 팬텀 `IncidentSignalPublisher`를 `IncidentEventPublisher`/`HallucinationDetector`(실재 U6 컴포넌트)로 대체. 세 탐지기를 1급 엔드포인트로 선언.
- SEC-8 소유권: `U6.AuthnAuthzGuard → U3.AuthorizationGuard (lib, 위임)`; `U4.* → U3.AuthorizationGuard (sync)`는 단일 결정점; `U4.UserDataRepository`는 데이터 백스톱.
- U2↔U6 의존 방향: 게이트웨이=호출자(U6→U2 핸들러), 근거화·비용 후크=주입 lib(U2→U6 hooks, kind:lib) — sync 순환 아님.
- VectorSpec 공유 계약 엣지 신설: `U1.EmbeddingGatewayAdapter`·`U2.QueryUnderstandingExpander` → Shared Embedding Gateway VectorSpec.

---

## 1. U1 — Corpus Ingestion (이벤트/스케줄 백본)

| from | to | kind | purpose |
|---|---|---|---|
| CorpusRefreshScheduler | Scheduler/Timer (shared capability) | event | source별 스케줄 시간 트리거로 증분 갱신·backfill·rebuild 잡 개시(US-I2, FR-6). |
| RefreshOrchestrationService | IngestionPipelineService | lib | 스케줄/이벤트 생성 잡의 논문을 파이프라인 오케스트레이터로 분배(워커 내부). |
| IngestionPipelineService | CorpusSourceAdapterSet | lib | arXiv·Semantic Scholar·OpenAlex 메타·전문 후보 조회(FR-6, C-1). |
| CorpusSourceAdapterSet | arXiv / Semantic Scholar / OpenAlex (external upstreams) | sync | 워커→외부 학술 소스 동기 조회(레이트/쿼터 RES-8, 타임아웃 RES-9). **사용자 동기 경로 아님 — 워커 내부 업스트림.** |
| IngestionPipelineService | FullTextExtractionProcessor | lib | HTML/PDF 원천에서 FullText 추출, PDF는 transient GROBID 처리, 라이선스 검증(C-1, SEC-5). |
| FullTextExtractionProcessor | GROBID Runtime (shared capability) | sync | Semantic Scholar/OpenAlex PDF 및 arXiv PDF fallback 전문 구조화 추출. 원시 PDF 저장 없음. |
| IngestionPipelineService | SourcePriorityDeduplicationGuard | lib | DOI→arXiv id→title/author/year 기준 cross-source 중복 제거와 canonical version 결정(NFR-C1, QT-9). |
| IngestionPipelineService | DocModelBuildCoordinator | lib | `(paperId, version)`별 eager DocModel 생성·검증·S3 저장(FR-18, QT-9). |
| DocModelBuildCoordinator | Object Storage (shared capability) | sync | DocModel JSON과 FullText/asset 참조 저장. 원시 PDF 저장 금지(C-1, SEC-9). |
| IngestionPipelineService | DocModelBlockChunker | lib | DocModel Block 경계 기반 결정적 청크 생성(FR-6, FR-5 지원). |
| IngestionPipelineService | EmbeddingGatewayAdapter | lib | 청크 배치 벡터화 호출(FR-6). |
| EmbeddingGatewayAdapter | Embedding Gateway (shared capability) | sync | 워커→임베딩 게이트웨이 동기 호출로 벡터 생성(타임아웃·서킷 RES-9). |
| **EmbeddingGatewayAdapter** | **Shared Embedding Gateway VectorSpec (shared contract)** | **lib** | **공유 임베딩 스키마(차원·모델·거리 메트릭) 단일 진실 원천 소비 — U2 reader와 벡터 공간 호환 보장(인덱스 정합성).** |
| EmbeddingGatewayAdapter | Cost Telemetry (shared X-cutting) | event | 임베딩 사용량/비용 텔레메트리 발행(NFR-C1, DQ5 횡단 레이어). |
| IngestionPipelineService | CorpusIndexWriter | lib | 임베딩+lexical+DocModel Block anchor를 공유 OpenSearch generation에 멱등 기록(FR-6, FR-2, FR-18). |
| CorpusIndexWriter | OpenSearch / Vector Store (shared capability) | sync | 워커→인덱스 스토어 동기 upsert/tombstone. U2 reader 공유 인덱스 generation 생성(재생성 가능 RES-2). |
| IngestionPipelineService | IngestionResilienceService | lib | 모든 단계 오류 분류·재시도/백오프·DLQ·경보 위임(US-I3, RES-9/8/7). |
| IngestionResilienceService | Dead-Letter Queue (shared capability) | event | 소진/영구 실패 격리로 인덱스 정체·손상 방지(US-I3). |
| IngestionResilienceService | Observability/Alerting (shared X-cutting) | event | 실패 신호·잡 건강도 발행(RES-7, NFR-O1); 운영 U6 라우팅. |
| U1-Ingestion | U6.ObservabilityHub | event | 인제스천 워커 갱신 성공/실패·재시도 텔레메트리 비동기 제출(RES-7, US-I2). |

> **읽기/쓰기 분리 주석**: U1.CorpusIndexWriter는 공유 Corpus 인덱스의 **write-only 생산자**, U2.HybridRetriever는 **read 소비자**. 단일 writer·단일 reader.

---

## 2. U2 — Discovery (동기 읽기 경로)

| from | to | kind | purpose |
|---|---|---|---|
| QueryIntakeController | SearchOrchestrationService | sync | 검증된 동기 검색 요청을 도메인 오케스트레이터로 위임(요청→응답, NFR-P1). |
| QueryIntakeController | QueryValidator | lib | 진입 시 도메인 입력 검증·정규화(FR-1/SEC-5; 실패 시 업스트림 비전송). |
| SearchOrchestrationService | QueryUnderstandingExpander | sync | 정규화 질의를 임베딩+lexical QueryPlan으로 확장(FR-2). |
| SearchOrchestrationService | HybridRetriever | sync | 공유 arXiv 인덱스 하이브리드 후보 검색(FR-2). |
| SearchOrchestrationService | RelevanceRanker | sync | 후보 관련도순 상위 N 정렬(FR-3, QT-2). |
| SearchOrchestrationService | GroundingAdapter | lib | 후보+검색 레코드를 U6 근거화 후크 입력으로 정형화·verdict 매핑(독자 강제 없음, FR-5). |
| SearchOrchestrationService | ResultAssembler | sync | 근거화 결과/기권/저하를 폰 DTO 조립(FR-4, FR-11). |
| QueryUnderstandingExpander | LlmGatewayAdapter (shared X-cutting, U6 게이트웨이 경유) | sync | 임베딩 생성·LLM 질의 확장; 비용/저하 신호 시 우회(NFR-C1). |
| **QueryUnderstandingExpander** | **Shared Embedding Gateway VectorSpec (shared contract)** | **lib** | **질의 임베딩 모델·차원·거리 메트릭을 U1 인덱스와 동일 공유 계약에서 해석 — 벡터 공간 호환 선언 불변식.** |
| HybridRetriever | VectorStoreAdapter (shared adapter) | sync | 벡터 ANN 시맨틱 검색; 공유 AI/ML Corpus 인덱스 읽기(FR-2). |
| HybridRetriever | LexicalIndexAdapter (shared adapter) | sync | lexical 텀 검색; 하이브리드 병합·저하 폴백(FR-2, NFR-R2). |
| RelevanceRanker | LlmGatewayAdapter (shared X-cutting, U6 경유) | sync | 선택적 LLM 리랭킹; cost-circuit 'rerank off' 시 baseline 폴백(NFR-C1, US-R3). |
| SearchOrchestrationService | U6.CostGuardCircuitBreaker (DegradationSignal) | sync | 요청 스코프 degradation/cost-circuit 신호 수신(LLM/rerank on-off) 저하 분기(NFR-C1, RES-9, US-R2/R3). |
| SearchOrchestrationService | U6.ObservabilityHub | event | 지연·검색/근거화 건강도·반쪽짜리 결과 신호를 메트릭/트레이스로 emit(NFR-O1, RES-5, RES-11(c)). |
| **SearchOrchestrationService** | **Event Backbone (shared async)** | **event** | **성공 검색 후 `SearchExecutedEvent{userId, query, timestamp, resultCount}` 발행 → U4 이력 비동기 기록(FR-10, NFR-P1 비차단, P50<3s 경로 밖).** |
| QueryIntakeController | U6.ApiGatewayMiddleware (DQ5 게이트웨이) | sync | 사용자 동기 검색 READ가 게이트웨이 전처리(검증·인증·인가·레이트리밋·관측성)를 통과(DQ6 동기 REST). |

> **근거화 invocation 주석**: U2는 `GroundingEnforcementHook.enforce`를 직접 호출하지 않는다. 근거화 강제는 U6.GatewayPipelineService가 U2 라우트 응답 엣지(post-handler)에서 단일 적용한다(아래 U6 섹션). 할루시네이션 인시던트 발행도 U6 단독.

---

## 3. U3 — Accounts/Auth

| from | to | kind | purpose |
|---|---|---|---|
| U6.ApiGatewayMiddleware (DQ5) | SessionVerifier | sync | 요청별 인증 강제: 게이트웨이가 토큰을 검증해 주체를 다운스트림 주입(SEC-8/12). |
| U6.ApiGatewayMiddleware (DQ5) | AccountController | sync | 검증·레이트리밋·입력 검증 통과 후 가입/로그인/로그아웃 라우팅(SEC-11/5). |
| AccountController | SignupService | sync | 가입 요청 도메인 로직 위임(FR-7/US-A1). |
| AccountController | AuthenticationService | sync | 로그인/로그아웃 도메인 로직 위임(FR-7/US-A2). |
| SignupService | PasswordPolicy | lib | 비밀번호 정책·유출 검사 평가(SEC-12). |
| SignupService | CredentialStore | lib | 이메일 유일성·적응형 해싱 생성·영속(SEC-12). |
| AuthenticationService | CredentialStore | lib | 자격증명 검증·노후 해시 재해싱(SEC-12). |
| AuthenticationService | SessionManager | lib | 성공 인증 세션 발급·로그아웃 무효화(SEC-12/US-A2). |
| SessionVerifier | SessionManager | lib | 요청 토큰 서버측 검증 위임(SEC-8). |
| SessionManager | SessionStore | lib | 세션 레코드 영속·조회·삭제로 서버측 검증·무효화(US-A2/SEC-8). |
| PasswordPolicy | Breach-Dataset Adapter (shared common adapter) | sync | 유출 비밀번호 검사; 타임아웃·서킷·페일클로즈드(RES-9/SEC-15). |
| SignupService | Event Backbone (shared async) | event | `AccountCreated`·`SignupAbuseSignal` 발행 → 관측성·남용 탐지·Ops(SEC-11/NFR-O1/RES-11). |
| AuthenticationService | Event Backbone (shared async) | event | `AuthFailureSignal` 발행 → 무차별 대입 탐지·락아웃/지연/CAPTCHA·Ops 경보(SEC-12/RES-11). |
| U6.AuthnAuthzGuard | **AuthorizationGuard** | lib | **객체 단위 소유권 결정을 U3 단일 권위 결정점에 위임(재구현 아님, SEC-8) — token-verify 위임과 동형.** |
| U4.SavedSearch/Library/History 도메인 | **AuthorizationGuard** | sync | 사용자 데이터 접근 시 객체 단위 소유권 인가를 U3 단일 결정점에 요청(SEC-8). |

---

## 4. U4 — Saved Searches & Library

| from | to | kind | purpose |
|---|---|---|---|
| U4.SavedSearchController | U6.ApiGatewayMiddleware (authn/authz, rate-limit, observability) | sync | DQ5: 진입 전 인증·인가(SEC-8/12)·레이트리밋(SEC-11)·구조화 로깅(NFR-O1). LibraryController/SearchHistoryController 동일. |
| U4.SavedSearchController | U4.SavedSearchService | sync | REST 요청을 도메인 유스케이스로 위임. |
| U4.LibraryController | U4.LibraryService | sync | REST 요청을 라이브러리 유스케이스로 위임. |
| U4.SearchHistoryController | U4.SearchHistoryService | sync | 이력 읽기/재실행/삭제를 유스케이스로 위임. |
| U4.SavedSearchService | U4.UserDataRepository | lib | owner-scoped 검색 저장 CRUD(SEC-8 데이터 백스톱). |
| U4.LibraryService | U4.UserDataRepository | lib | owner-scoped 라이브러리 멱등 CRUD. |
| U4.SearchHistoryService | U4.UserDataRepository | lib | owner-scoped 이력 기록/조회/삭제. |
| U4.UserDataRepository | Shared.PersistenceAdapter (DB/object storage capability) | lib | DQ4 공유 레이어: 실제 데이터스토어 접근(at-rest 암호화 SEC-1, 타임아웃·재시도 RES-9). |
| U4.SavedSearchService | **U6.ApiGatewayMiddleware (게이트웨이-프런티드 검색 계약 → U2.SearchOrchestrationService)** | sync | **rerun 시 저장 query를 게이트웨이 경유 동기 검색으로 위임 — 근거화·비용·관측성 후크 통과(DQ5/DQ6, U2 직접 호출 아님).** |
| U4.SearchHistoryService | **U6.ApiGatewayMiddleware (게이트웨이-프런티드 검색 계약 → U2.SearchOrchestrationService)** | sync | **이력 rerun 동기 검색을 게이트웨이 경유로 위임(DQ5/DQ6).** |
| **U2.SearchOrchestrationService** | U4.SearchHistoryService (via Event Backbone) | event | U2가 발행한 `SearchExecuted`를 공유 이벤트 버스로 U4가 구독해 이력 비동기 기록(DQ6 백본, NFR-P1 비차단). |
| U4.SavedSearchService | Shared.AuditLogger (append-only) | event | 검색 저장/삭제 핵심 변경 감사 기록(SEC-13/14). |
| U4.LibraryService | Shared.AuditLogger (append-only) | event | 라이브러리 add/remove 감사 기록(SEC-13/14). |
| U4.SavedSearchController | U4.UserDataDTOAndValidation | lib | 입력 검증·새니타이즈(SEC-5)·DTO 매핑. 전 U4 컨트롤러 공통. |
| U4 (all components) | U3.AuthorizationGuard (auth context, via gateway) | sync | 현재 사용자 식별·객체 소유권 인가를 U3 단일 결정점에서 소비(SEC-8/12). 검증은 게이트웨이가 U3 호출해 AuthContext 주입. |

---

## 5. U5 — Mobile Web Frontend

| from | to | kind | purpose |
|---|---|---|---|
| SearchScreen | ApiClient | sync | 자연어 질의를 동기 REST 검색으로 전송·정렬 결과 수신(DQ6 동기 read, NFR-P1, FR-2). |
| AccountScreens | ApiClient | sync | 가입/로그인/로그아웃 동기 REST·세션 결과(FR-7, SEC-12). |
| LibraryHistoryScreens | ApiClient | sync | 저장 검색/라이브러리/이력 조회·변이 동기 REST(FR-8/9/10, SEC-8). |
| ResultCard | ApiClient | sync | 결과 카드 라이브러리 저장 변이 동기 REST(FR-9). |
| ApiClient | Backend REST API (U6 gateway/middleware) | sync | 프런트 모든 데이터 입출력을 동기 REST로 백엔드 게이트웨이 위임(인증/인가/레이트리밋/근거화는 백엔드 횡단; DQ5, DQ7). |
| SsrRenderService | ApiClient | sync | SSR 시 라우트별 초기 데이터 동기 프리패치로 첫 페인트(NFR-U1, NFR-P1). |
| SsrRenderService | SecurityHeaderPolicy | lib | SSR 응답에 자기-프레이밍 예외 포함 보안 헤더/CSP 부착(SEC-4). |
| SsrRenderService | AppShell | lib | 라우트·세션에 맞춘 화면 트리 렌더 호출. |
| AppShell | PhoneMockupFrame | lib | 데스크톱/태블릿 폰 목업 중앙 배치·폰 풀블리드 분기(NFR-U2). |
| AppShell | SearchScreen | lib | 검색 라우트 화면 마운트(히어로 US-H1 진입). |
| AppShell | AccountScreens | lib | 계정 라우트 화면 마운트·세션 공유(SEC-8). |
| AppShell | LibraryHistoryScreens | lib | 보호된 라이브러리/이력 라우트 마운트·인증 가드(SEC-8). |
| SearchScreen | ResultList | lib | 정렬된 상위 N건 결과 렌더 위임(FR-3). |
| ResultList | ResultCard | lib | 개별 논문 폰 최적화 카드 렌더(FR-4). |
| SearchScreen | StateView | lib | 빈/실패/저하/로딩 상태 렌더 위임(FR-11, NFR-R1, SEC-15, QT-3). |
| ResultList | StateView | lib | 부분 결과/저하 배너 등 결과 영역 상태 위임(FR-11, RES-11). |
| AccountScreens | StateView | lib | 레이트리밋/락아웃/오류 비기술 메시지 표면화(FR-11, SEC-11). |
| LibraryHistoryScreens | StateView | lib | 빈 목록/인가 오류 상태 표면화(FR-11, SEC-8). |
| LibraryHistoryScreens | SearchScreen | lib | 저장 검색/이력 재실행 시 검색 화면 흐름 재사용(FR-8, FR-10). |
| PhoneMockupFrame | SecurityHeaderPolicy | lib | 자기-프레이밍 마크업이 SEC-4 frame-ancestors=self 정합하도록 정책 계약 공유(SEC-4). |

---

## 6. U6 — Reliability & Operations (횡단 미들웨어 + 운영)

| from | to | kind | purpose |
|---|---|---|---|
| U2.QueryIntakeController | ApiGatewayMiddleware | sync | 사용자 동기 검색 READ가 게이트웨이 전처리 통과(DQ6 동기 REST, NFR-P1). |
| U3.AccountController | ApiGatewayMiddleware | sync | 가입/로그인/세션 요청이 입력 검증·레이트리밋·보안 헤더 적용(SEC-5/11/12). |
| U4.* Controllers | ApiGatewayMiddleware | sync | 검색 저장/라이브러리/이력 요청이 객체 단위 소유권 인가를 미들웨어 위임(SEC-8). |
| ApiGatewayMiddleware | InputValidationGuard | lib | 입력 검증·새니타이즈 위임(SEC-5, FR-1). |
| ApiGatewayMiddleware | AuthnAuthzGuard | lib | 인증/세션 검증·객체 단위 인가 결정 위임(SEC-8/12). |
| ApiGatewayMiddleware | RateLimiter | lib | 검색·가입 엔드포인트 레이트 리미팅 위임(SEC-11). |
| AuthnAuthzGuard | U3.SessionVerifier | sync | 서버측 토큰/세션 검증을 U3와 동기 협력(SEC-12). |
| AuthnAuthzGuard | U3.AuthorizationGuard | lib | **객체 단위 소유권 결정을 U3 단일 권위 결정점에 위임(재구현 아님, SEC-8).** |
| ApiGatewayMiddleware | GroundingEnforcementHook | lib | **U2 라우트 응답 엣지(post-handler) 단일 근거화 강제 호출(FR-5, US-D5/D6) — 유일 invocation site.** |
| U2.SearchOrchestrationService | CostGuardCircuitBreaker | sync | 동기 경로 `getBudgetState`로 비용 저하 모드 조회·분기(NFR-C1, NFR-R2). |
| ApiGatewayMiddleware | ObservabilityHub | lib | 요청/응답 단위 메트릭·구조화 로그·트레이스·감사 제출(NFR-O1, SEC-3/14). |
| GroundingEnforcementHook | **HallucinationDetector** (AiIncidentDetectorSuite 서브컴포넌트) | event | 근거화 미통과 위반 신호 비동기 방출 → 할루시네이션 인시던트 탐지(RES-11(b)). |
| CostGuardCircuitBreaker | **CostExplosionDetector** (AiIncidentDetectorSuite 서브컴포넌트) | event | 인트라데이 지출 급증 신호 비동기 방출 → 비용 폭발 인시던트 탐지(RES-11(a)). |
| CostGuardCircuitBreaker | ObservabilityHub | event | usage/cost 텔레메트리·임계 경보 비동기 공급(NFR-C1, RES-5). |
| ObservabilityHub | AiIncidentDetectorSuite | event | 수집 텔레메트리를 이벤트 백본 팬아웃해 세 인시던트 클래스 탐지기 공급(RES-11, DQ6 비동기). |
| ObservabilityHub | OpsDashboardService | sync | 대시보드가 집계 텔레메트리 동기 조회해 OP 뷰 구성(NFR-O1, US-R4). |
| AiIncidentDetectorSuite | IncidentEventPublisher | lib | 분류 인시던트·경보를 발행 어댑터로 전달(RES-11). |
| IncidentEventPublisher | Event Backbone | event | typed 인시던트/경보 이벤트 발행해 IR/COE 라우팅(RES-11, US-R4). |
| AiIncidentDetectorSuite | Event Backbone | event | 탐지 워커가 텔레메트리/위반/지출/완결성 이벤트 비동기 소비(DQ1 별도 워커, DQ6 비동기). |
| HealthCheckService | ObservabilityHub | lib | 얕은·깊은 헬스 체크·의존성 건강도 관측성 제출(RES-6/7). |
| ReliabilityEvalProbe | (HealthMonitoringService 내부) | lib | QT-3 신뢰성/저하 평가셋 실행(GroundingEnforcementHook.runEvalSet의 신뢰성 대응물). |
| Router/LoadBalancer | HealthCheckService | sync | 라우팅 계층이 헬스 엔드포인트 동기 프로빙해 비정상 인스턴스 제외(RES-6, US-R5). |
| HealthCheckService | External Dependencies (arXiv/LLM gateway/vector store) | sync | 깊은 체크가 핵심 의존성 연결성 타임아웃 검증(RES-6/9). |
| OP-Operator | OpsDashboardService | sync | OP가 관리자 인가(SEC-8)+MFA(SEC-12)로 대시보드/인시던트 뷰 동기 조회(NFR-O1, US-R4). |

---

## 7. 통신 패턴 요약

- **동기(sync) 경로 = 사용자向 READ/CRUD (NFR-P1 P50<3s 적용 대상)**
  - 프런트(U5.ApiClient) → U6.ApiGatewayMiddleware → 도메인 핸들러(U2/U3/U4) → 응답.
  - U2 검색 파이프라인 전 단계 sync; 어댑터(VectorStore/Lexical/LLM 게이트웨이) 호출도 sync.
  - U4 rerun도 게이트웨이-프런티드 검색 계약으로 **동일 sync 경로 재진입**(후크 통과).
- **이벤트(event) 백본 = 인제스천·이력 쓰기·인시던트·관측성·감사 (비차단)**
  - 인제스천: source별 스케줄/backfill → U1 워커 → Corpus 인덱스(write-only).
  - 이력 쓰기: U2 `SearchExecuted` → U4.SearchHistoryService 비동기 기록.
  - 인시던트: 근거화 위반/비용 급증/완결성 → 탐지기 → IncidentEventPublisher → 백본 → IR/COE.
  - 관측성: 전 유닛 → ObservabilityHub → 팬아웃 → 탐지기·대시보드.
- **lib = 프로세스 내 호출**: 도메인 모듈 내부, 가드 위임, 어댑터 호출, 공유 VectorSpec 계약.

### 비순환성(acyclicity) 주석 — U2↔U6
게이트웨이는 호출자다: `U6.ApiGatewayMiddleware → U2 핸들러`(인바운드 래핑). 핸들러 내부의 `GroundingEnforcementHook`·`CostGuardCircuitBreaker`는 **주입된 횡단 lib**(U2 → U6 hooks, kind:lib)다. 따라서 토폴로지는 "1개 인바운드 체인 + 주입 lib"이며 sync 순환이 아니다. U4↔U2 back-edge(`SearchExecuted`)는 event-kind라 순환 아님.

---

## 8. 데이터 흐름 ASCII

### (A) Corpus 인제스천 이벤트 경로 (비동기 백본, 사용자 경로 아님)
```
[Scheduler/Timer] ──event──▶ CorpusRefreshScheduler ──▶ RefreshOrchestrationService
                                                             │ lib
                                                             ▼
 CorpusSourceAdapterSet ──sync(upstream)──▶ [arXiv / Semantic Scholar / OpenAlex]
        │ lib
        ▼
 FullTextExtractionProcessor ──sync──▶ [GROBID Runtime]  (PDF transient, raw PDF not stored)
        │ lib
        ▼
 SourcePriorityDeduplicationGuard ─lib▶ DocModelBuildCoordinator ─sync▶ [Object Storage]
        (DOI→arXiv→title/author/year)     (eager DocModel, paperId+version)
                                                    │ lib
                                                    ▼
 DocModelBlockChunker ─lib▶ EmbeddingGatewayAdapter ─sync▶ [Embedding Gateway]
        (Block anchors)                 (VectorSpec shared contract)
                                                    │
                                                    ▼
                                   CorpusIndexWriter ─sync▶ [OpenSearch / Vector Store]
                                   (generation upsert, write-only producer)
 실패 전 단계 ─lib▶ IngestionResilienceService ─event▶ [DLQ] / [Observability/Alerting → U6]
```

### (B) 디스커버리 동기 경로 (NFR-P1 P50<3s, 요청→응답)
```
[Phone/Browser]
   │ sync REST
   ▼
U5.ApiClient ──sync──▶ U6.ApiGatewayMiddleware ──(전처리: 헤더→검증→authN/Z(→U3.AuthorizationGuard)→rate-limit→cost-state)
   │                                  │ sync 위임
   │                                  ▼
   │                       U2.QueryIntakeController ─sync▶ SearchOrchestrationService
   │                                  │ sync 순차
   │   QueryValidator.normalize ──▶ Expander.expand ──▶ HybridRetriever.retrieve ──▶ RelevanceRanker.rank
   │        (PBT-02)              (VectorSpec 공유)     [Vector/Lexical adapters]      (PBT-03)
   │                                  │
   │                                  ▼ lib (정형화)
   │                          GroundingAdapter.toGroundingInput
   │                                  │
   │       ┌── 응답 엣지(post-handler) U6.GatewayPipelineService 단일 적용 ──┐
   │       ▼                                                                │
   │  U6.GroundingEnforcementHook.enforce (FR-5/QT-1 단일 게이트)            │
   │       │  pass/block/abstain                위반 ─event▶ HallucinationDetector (RES-11(b))
   │       ▼                                                                │
   │  GroundingAdapter.mapDecision ──▶ ResultAssembler.assemble (PBT-09) ◀──┘
   │                                  │
   ◀──────────── sync 응답(폰 DTO) ───┘
   │
   └─(응답 후, 비차단) U2.SearchOrchestrationService ─event▶ [Event Backbone] ─▶ U4.SearchHistoryService.recordSearch (FR-10)
```

### (C) 저하/인시던트 경로 (비동기 운영 백본)
```
CostGuardCircuitBreaker ─sync getBudgetState─▶ U2 (LLM/rerank off → lexical 폴백, QT-3 검증 대상)
        │ event 급증
        ▼
CostExplosionDetector ─┐
HallucinationDetector ─┼─▶ AiIncidentDetectorSuite.classify ─lib▶ IncidentEventPublisher ─event▶ [Event Backbone] ─▶ IR/COE, OpsDashboard
PartialResultDetector ─┘            ▲
                                    │ event 팬아웃
        전 유닛 ─sync/event─▶ ObservabilityHub ─event▶ (탐지기 공급) / ─sync▶ OpsDashboardService
ReliabilityEvalProbe.runReliabilityEvalSet (QT-3) ──▶ HealthMonitoringService 보고
```
