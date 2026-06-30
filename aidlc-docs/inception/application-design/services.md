# services.md — 서비스 정의·오케스트레이션 (Application Design)

> 각 서비스의 책임 + 오케스트레이션을 **동기 읽기(sync)** vs **이벤트 백본(event)** 으로 구분 명시한다(DQ6 재조정).
> 동기 경로: 사용자向 디스커버리 READ(NFR-P1 P50<3s), 계정, 라이브러리 CRUD.
> 이벤트 백본: 인제스천, 이력 쓰기, 비용/인시던트 탐지, 관측성 팬아웃.

## 비평 반영 요약 (이 문서 관련)
- **[blocking] 근거화 단일 invocation site**: 응답 엣지 근거화 게이트는 **U6.GatewayPipelineService의 U2 라우트 post-handler 단계 한 곳**에서만 실행된다. U2.SearchOrchestrationService는 더 이상 독자적으로 enforce를 호출하지 않고 `GroundingAdapter`로 후크 입력/출력을 정형화만 한다.
- **[blocking] SearchExecuted 생산자**: U2.SearchOrchestrationService가 성공 검색 후 `publishSearchExecuted`로 이벤트 백본에 발행(FR-10 이력 쓰기 생산자 — 비차단, P50<3s 경로 밖).
- **[major] rerun 게이트웨이 재진입**: U4 SavedSearchService/SearchHistoryService의 rerun은 게이트웨이-프런티드 검색 계약을 통해 U6 횡단 계층(근거화·비용·관측성)을 다시 통과한다.
- **[major] QT-3 평가 서비스**: U6.HealthMonitoringService가 ReliabilityEvalProbe를 통해 QT-3 신뢰성/저하 평가셋을 소유.

---

## U1 — Corpus Ingestion 서비스 (전부 이벤트/스케줄 백본, 사용자 동기 경로 아님)

### IngestionPipelineService
- **책임**: 멀티소스 논문 후보를 fetch→license/fulltext→source-priority dedup→eager DocModel→DocModel Block chunk→embed→index generation/S3 저장→watermark까지 끝에서 끝으로 처리하는 핵심 오케스트레이터. **FR-6 파이프라인 본체이자 U1 Corpus phase-1 빌드·정기 인제스천의 실현 주체.**
- **오케스트레이션 (워커 내부 비동기 흐름)**: `CorpusSourceAdapterSet.fetchMetadataPage/fetchFullTextCandidate`(arXiv HTML 우선/PDF 폴백, Semantic Scholar/OpenAlex PDF 후보) → `FullTextExtractionProcessor.validateLicense/extractFullText`(PDF는 transient GROBID, 원시 PDF 미저장) → `SourcePriorityDeduplicationGuard.deduplicate/canonicalize` → `DocModelBuildCoordinator.buildDocModel/storeDocModel` → `DocModelBlockChunker.chunkDocModel` → `EmbeddingGatewayAdapter.embedBatch`(공유 VectorSpec 공간) → `CorpusIndexWriter.prepareGeneration/upsert` → `CorpusRefreshScheduler.advanceWatermark`. 모든 단계 오류는 IngestionResilienceService로 위임(재시도/DLQ/경보). **단계 간은 워커 내부 비동기(DQ6 비동기 백본), 사용자 동기 경로와 완전 분리.**
- **Trace**: FR-6, FR-18, US-I1, NFR-R1, NFR-C1, QT-9

### RefreshOrchestrationService
- **책임**: source별 스케줄 갱신, phase-1 seed/backfill, DocModel/index 재생성을 통합 관리한다. **US-I2 최신성 갱신·US-I1 Corpus 빌드·RES-2 재구축 런북의 제어 평면.**
- **오케스트레이션 (event + schedule)**: `CorpusRefreshScheduler.onSchedule`이 arXiv/Semantic Scholar/OpenAlex source별 IngestionJob을 생성 → 각 source의 `sourceWatermark` 이후 페이지를 열거 → IngestionPipelineService에 분배(배치/동시성은 RES-8 쿼터 준수). `triggerBackfill`은 최근 AI/ML 1년 phase-1 Corpus를 비용 상한 안에서 진행하고, `triggerRebuild`는 DocModel/parser/index version 변경 시 재생성한다. 잡 단위 실패율·진행도·watermark 지연을 관측성 노출.
- **Trace**: FR-6, FR-18, US-I1, US-I2, RES-2, RES-7, RES-8, QT-9

### IngestionResilienceService
- **책임**: source/GROBID/DocModel/embedding/index 단계의 타임아웃·재시도/백오프·서킷·DLQ·쿼터와 실패·갱신 건강도 신호 발행. **US-I3 복원력 + US-I2 실패 경보의 횡단 서비스.**
- **오케스트레이션 (event)**: `IngestFailureHandler.classify` 분류 → 재시도 가능 시 `scheduleRetry`(source 쿼터/GROBID 처리량/임베딩 한도 인지) → 소진/영구 시 `sendToDLQ` → `emitFailureSignal`로 구조화 로그·경보 발행(운영 U6 라우팅, RES-7). CorpusSourceAdapterSet/FullTextExtractionProcessor/DocModelBuildCoordinator/EmbeddingGatewayAdapter/CorpusIndexWriter 외부 호출에 타임아웃·서킷 주입(RES-9). `(paperId, version)` 불일치나 Block anchor 결함은 cutover 전 차단한다(QT-9).
- **Trace**: FR-6, FR-18, US-I3, RES-7, RES-8, RES-9, NFR-R1, QT-9

---

## U2 — Discovery 서비스 (동기 읽기 경로의 주체)

### SearchOrchestrationService
- **책임**: U2 동기 읽기 경로 도메인 오케스트레이터. 질의 이해/확장 → 하이브리드 검색 → 랭킹 → **근거화 어댑팅(U6 후크 위임)** → 결과 조립의 단일 요청→응답 파이프라인을 순차 조정. 횡단 계층(U6)이 주입한 degradation/cost-circuit 신호를 각 단계 전파. **성공 응답 후 SearchExecuted 이벤트를 발행(FR-10 이력 생산자).** NFR-P1(P50<3s) 동기 경로의 주체.
- **오케스트레이션 (sync 순차)**: `QueryValidator.normalize` → `QueryUnderstandingExpander.expand`(공유 VectorSpec) → `HybridRetriever.retrieve` → `RelevanceRanker.rank` → `GroundingAdapter.toGroundingInput`(U6 게이트웨이 post-handler 단계가 `GroundingEnforcementHook.enforce` 적용) → `GroundingAdapter.mapDecision` → `ResultAssembler.assemble`. 각 단계 명시 타임아웃/폴백(RES-9); 저하 신호 시 LLM 확장·리랭킹 건너뛰고 lexical 경로(NFR-C1, US-R2/R3).
- **근거화 invocation 주석**: **U2는 enforce를 직접 호출하지 않는다.** 근거화 강제는 U6.GatewayPipelineService가 U2 라우트의 응답 엣지(post-handler)에서 단일 적용한다. U2는 후크 입력을 정형화하고 verdict를 결과/기권으로 매핑만 한다(이중 강제 방지).
- **이벤트 (off the blocking path)**: 성공 응답 후 `publishSearchExecuted(userId, query, timestamp, resultCount)` → 이벤트 백본(FR-10, NFR-P1 비차단). 관측성 스팬/메트릭은 ObservabilityHub로 emit. 할루시네이션 인시던트 신호는 U6 GroundingEnforcementHook→HallucinationDetector 경로가 단독 담당(U2 미발행).
- **Trace**: FR-1, FR-2, FR-3, FR-4, FR-5, FR-11, NFR-P1, NFR-C1, RES-9, QT-2, US-D1..D7

---

## U3 — Accounts/Auth 서비스

### SignupService (동기 입구 + 이벤트 발행)
- **책임**: 공개 셀프 가입 전체 흐름 — 입력 정책 검증·이메일 유일성·적응형 해싱 생성·계정 영속·가입 텔레메트리/남용 신호 발행. 평문 비밀번호 비저장·비로깅 불변식 보장(FR-7, SEC-12, SEC-3, US-A1).
- **오케스트레이션**: AccountController(sync) → `register`. 내부: `PasswordPolicy.evaluate`(유출 검사 포함, 위반 시 조기 반환) → `CredentialStore`(중복 검사+createCredential) → 계정 영속 → 이벤트 백본 `AccountCreated` 발행(event), 속도/중복 시 `SignupAbuseSignal`(event). 가입 레이트 리미팅 사전 강제는 게이트웨이(SEC-11)가 컨트롤러 진입 전 수행.
- **Trace**: FR-7, US-A1, SEC-11, SEC-12, SEC-3

### AuthenticationService (동기 입구 + 이벤트 발행)
- **책임**: 로그인/로그아웃 전체 흐름 — 자격증명 검증·세션 발급/무효화·무차별 대입 방어 신호·노후 해시 재해싱. 자격증명 존재 미노출(FR-7, SEC-12, US-A2).
- **오케스트레이션**: AccountController(sync) → `authenticate/revoke`. authenticate: `CredentialStore.verifyCredential` → 성공 시 `SessionManager.issue`(+needsRehash 시 `CredentialStore.rehash`) → 쿠키 머티리얼; 실패 시 `AuthFailureSignal` 발행(event) → 게이트웨이/U6 Ops가 락아웃·지연·CAPTCHA 강제. revoke: `SessionManager.invalidate`.
- **Trace**: FR-7, US-A2, SEC-12

### SessionAuthorizationService (동기 결정 경계)
- **책임**: 요청별 인증 검증(SessionVerifier)과 **객체 단위 소유권 인가(AuthorizationGuard — 시스템 단일 권위 결정점)** 를 묶어 게이트웨이·타 도메인(U4)에 제공. 기본 거부·fail closed 불변식(SEC-8, SEC-12, SEC-15).
- **오케스트레이션**: 게이트웨이(sync) → `SessionVerifier.verifyRequest` → `SessionManager.verify`(+`SessionStore.load`) → AuthenticatedPrincipal 컨텍스트 주입. **사용자 데이터 접근 시 U6.AuthnAuthzGuard·U4 도메인 서비스가 동기로 `AuthorizationGuard.authorize`(소유권 판정)에 위임** — U3가 유일 결정 권위. P50<3s 예산 내 경량 수행(NFR-P1).
- **Trace**: SEC-8, SEC-12, SEC-15, NFR-P1

### AccountDeletionService (비동기 상태 전이 및 캐스케이드 추적)
- **책임**: 계정 파기 요청 처리 및 GDPR 완전 삭제 캐스케이드(Defense-in-Depth). 사용자의 삭제 요청 시 계정을 소프트 비활성화하고 비동기 워커로 실제 삭제와 연계 시스템 데이터 삭제 보장을 오케스트레이션.
- **오케스트레이션**: AccountController(sync) → `requestDeletion` (status=DEACTIVATED 설정 후 `purgeJob` 백그라운드 큐). 비동기 워커가 `purgeJob` 실행: U3 DB 레코드 물리 삭제 → `AccountDeleted` 이벤트 발행 → 구독자(U2, U4)의 `AccountPurged` 완료 이벤트 수신 대기 및 추적. SLA 초과 시 `CascadeOverdue` 경보 트리거(GDPR 보장).
- **Trace**: FR-28, US-A6, SEC-8, GDPR

### PasswordResetService (동기 흐름 위임)
- **책임**: 비밀번호 분실 시 보안 인증 및 재설정 절차.
- **오케스트레이션**: AccountController(sync) → `requestReset` (토큰 생성/영속화) → 외부 Email 어댑터 발송 위임. `confirmReset` 시 토큰 검증, 신규 비밀번호 평가, 저장 및 진행 중인 모든 세션 무효화(`SessionManager.invalidate`).
- **Trace**: FR-26, BR-A8

### EmailVerificationService (계정 소유권 확인)
- **책임**: 계정 생성 후 이메일 유효성 확인 및 변경 시 소유권 양방향 승인.
- **오케스트레이션**: AccountController(sync) → `verifyEmail` 시도. 토큰 검증 성공 시 계정 상태 `ACTIVE`로 전환. `requestEmailChange` 시 기존/신규 이메일 양쪽으로 알림 발송 및 새 이메일 토큰 발송.
- **Trace**: BR-A5, BR-A10

### SocialLoginService (위임 인증 흐름)
- **책임**: Google OIDC 등 타사 인증 연동 및 계정 통합(Pre-Hijacking 방어).
- **오케스트레이션**: AccountController(sync) → `start` (OIDC 인가 URL 반환). 콜백 시 `callback` 실행하여 id_token 검증, 이메일 추출 후 매핑. 매핑 시 기존 계정과 병합 또는 거부 판단.
- **Trace**: FR-27, BR-A9

---

## U4 — Saved Searches & Library 서비스

> 공통: 모든 호출은 공유 미들웨어/게이트웨이(DQ5: authn/authz·rate-limit·observability) 통과 후 진입. rerun은 게이트웨이-프런티드 검색 계약으로 재진입.

### SavedSearchService (동기)
- **책임**: 검색 저장 save/list/delete/rerun 오케스트레이션 + SEC-8 소유권 강제(FR-8, US-L1).
- **오케스트레이션**: SavedSearchController(sync) → `UserDataRepository`(SavedSearch 포트, lib)로 owner-scoped 영속(소유권 결정은 U3.AuthorizationGuard 위임, 데이터 계층 owner-scoping은 백스톱) → **rerun 시 게이트웨이-프런티드 검색 계약(U6 ApiGatewayMiddleware 경유 → U2 SearchOrchestrationService, sync)으로 위임 — 근거화·비용·관측성 후크 통과** → 쓰기 시 SharedAuditLogger(공유 횡단)로 감사 이벤트(event).
- **Trace**: FR-8, US-L1, SEC-8, SEC-13, DQ4, DQ6

### LibraryService (동기)
- **책임**: 라이브러리 add/list/remove 오케스트레이션, 멱등성·메타 스냅샷·SEC-8 소유권(FR-9, US-L2).
- **오케스트레이션**: LibraryController(sync) → `UserDataRepository`(LibraryItem 포트, lib)로 owner-scoped 멱등 영속 → add/remove 시 SharedAuditLogger(event). 목록은 보존 메타 스냅샷만 반환(U2/인덱스 비의존, 가용성 격리).
- **Trace**: FR-9, US-L2, SEC-8, SEC-13, DQ4

### SearchHistoryService (쓰기 event · 읽기 sync 분리)
- **책임**: 이력 비동기 기록(write)과 동기 list/rerun/clear(read) 분리 오케스트레이션, SEC-8 소유권(FR-10, US-L3).
- **오케스트레이션 (쓰기 = event)**: **U2.SearchOrchestrationService가 발행한 SearchExecuted 이벤트를 공유 이벤트 버스(event)로 구독** → `UserDataRepository`(SearchHistory 포트, lib)에 비동기 기록(NFR-P1 검색 응답 비차단).
- **오케스트레이션 (읽기 = sync)**: SearchHistoryController(sync) → owner-scoped 조회; rerun은 게이트웨이-프런티드 검색 계약(U6 경유 → U2, sync)으로 위임.
- **Trace**: FR-10, US-L3, SEC-8, DQ6, NFR-P1

---

## U5 — Mobile Web Frontend 서비스

### SsrRenderService (서버측, 동기)
- **책임**: SSR 요청을 받아 라우트 해석·세션 부트스트랩·보안 헤더 부착·초기 데이터 프리패치를 거쳐 폰 우선 HTML 합성. PhoneMockupFrame+SecurityHeaderPolicy로 NFR-U2·SEC-4 동시 충족.
- **오케스트레이션**: SsrRequest 수신 → `SecurityHeaderPolicy.buildHeaders/buildCsp` → 세션 쿠키로 SessionState 부트스트랩 → 보호 라우트면 인증 가드(미인증 시 로그인) → 라우트별 초기 데이터 `ApiClient` 프리패치(sync) → `AppShell.render` → `PhoneMockupFrame.wrap` → SSRHtml + SecurityHeaders 응답.
- **Trace**: NFR-U1, NFR-U2, SEC-4, NFR-P1

### SearchInteractionService (클라이언트, 동기)
- **책임**: 검색 화면 상호작용 오케스트레이션 — 입력 검증→동기 검색→상태 전이를 단일 요청/응답으로 묶어 NFR-P1 지원·FR-11 상태 표면화. **히어로 첫 검색(US-H1) 흐름의 클라이언트 주체.**
- **오케스트레이션**: submitQuery → `SearchScreen.validateInput`(빈/≤500자) → 위반 시 인라인 메시지·중단(요청 미전송) → 통과 시 `StateView.renderLoading` → `ApiClient.search`(동기 REST) → 성공: `ResultList.render`(저하 메타 포함) / 빈: `StateView.renderEmpty` / 오류: `StateView.renderError`(fail closed) / 저하: `StateView.renderDegraded`.
- **Trace**: FR-1, FR-11, NFR-P1, US-H1, US-D1..D7

### SessionFlowService (클라이언트, 동기)
- **책임**: 가입·로그인·로그아웃·세션 수명주기 오케스트레이션 — 자격증명 검증·세션 쿠키 인증 상태 반영·레이트리밋/무차별대입 응답 표면화.
- **오케스트레이션**: 폼 제출 → AccountScreens 클라이언트 검증 → `ApiClient.signup/login` → 성공: AppShell 세션 컨텍스트 갱신·보호 라우트 리다이렉트 / 429·락아웃: `StateView.renderError` 비기술 메시지 → logout: `ApiClient.logout` → 세션 초기화·공개 라우트 전환.
- **Trace**: FR-7, SEC-12, SEC-11, FR-11

### UserDataService (클라이언트, 동기)
- **책임**: 저장 검색·라이브러리·이력 조회/재실행/추가/삭제 오케스트레이션. 모든 요청 현재 세션 사용자 범위로만 발행, 소유권 강제는 백엔드 인가 위임(SEC-8).
- **오케스트레이션**: 보호 라우트 진입(미인증 시 SessionFlow 위임) → `ApiClient.list*` 조회 → `LibraryHistoryScreens.render*` → rerun 시 SearchInteractionService로 질의 재실행 → saveSearch/addToLibrary/remove* 시 ApiClient 변이 후 목록 갱신 → 403 등은 `StateView.renderError`.
- **Trace**: FR-8, FR-9, FR-10, SEC-8

---

## U6 — Reliability & Operations 서비스

### GatewayPipelineService (동기 횡단 — DQ5 전용 미들웨어 계층)
- **책임**: 사용자 동기 REST 경로의 횡단 전처리/후처리를 단일 책임으로 묶어 도메인 모듈이 보안·검증·인가·관측성·근거화를 위임만 하도록 함. **응답 엣지 근거화 게이트의 단일 invocation site.**
- **오케스트레이션 (sync)**: 요청 수신 → `applySecurityHeaders` → `InputValidationGuard.validate`(SEC-5) → `AuthnAuthzGuard.authenticate`(U3.SessionVerifier 위임)/`authorize`(**U3.AuthorizationGuard 위임**, SEC-8/12) → `RateLimiter.checkLimit`(SEC-11) → `CostGuardCircuitBreaker.getBudgetState`(저하 분기 컨텍스트 NFR-C1) → 도메인 핸들러(U2/U3/U4) 동기 위임 → **U2 라우트 응답 직전 post-handler 단계에서 `GroundingEnforcementHook.enforce`(FR-5) 단일 적용** → `ObservabilityHub` 메트릭/로그/트레이스 제출 → 예외 시 `toProductionError`(fail-closed SEC-15). 모든 단계 sync.
- **의존성 방향 주석**: 게이트웨이가 호출자(U6 → U2 핸들러). 핸들러 내부의 근거화·비용 후크는 주입된 lib 의존(U2 → U6 hooks = kind:lib)으로, 인바운드 래핑 체인 + 주입 횡단 lib 구조이며 sync 순환이 아니다.
- **Trace**: SEC-4, SEC-5, SEC-8, SEC-9, SEC-11, SEC-12, SEC-15, NFR-O1, FR-5, FR-11

### CostGuardService (이벤트 소비 + 동기 조회)
- **책임**: 비용 상한(NFR-C1) 준실시간 텔레메트리·임계 평가·서킷 운용으로 상한 초과 이전 우아한 저하 + 비용 폭발 인시던트 신호 공급(RES-11(a)).
- **오케스트레이션**: 이벤트 백본의 usage/cost 이벤트 비동기 소비(event) → `recordSpend` 누적 → `evaluateCircuit` 임계 평가(80% 경보/100% 전 차단) → 임계 시 ObservabilityHub 경보 + CostExplosionDetector로 급증 신호(async) → 동기 경로는 `getBudgetState`로 저하 모드(LLM 리랭킹 비활성→lexical 폴백)를 U2에 노출(sync).
- **Trace**: NFR-C1, NFR-R2, RES-9, RES-11(a), US-R3, QT-3

### GroundingGuardService (동기 강제 + 이벤트 인시던트)
- **책임**: **FR-5/QT-1 엄격 근거화/기권을 동기 경로에서 강제하는 단일 권위 서비스.** 위반을 할루시네이션 인시던트로 전환, QT-1 평가셋 실행 진입점 제공.
- **오케스트레이션**: GatewayPipelineService가 U2 응답 직전 `enforce(candidate, retrieved)` 동기 호출(sync) → block/abstain 시 응답 차단·기권 강제 → 위반 신호를 HallucinationDetector로 전달(async 인시던트) → ObservabilityHub에 근거화 건강도 메트릭 → OP/팀 QT-1 평가셋은 `runEvalSet`으로 동일 후크 재사용.
- **Trace**: FR-5, QT-1, RES-11(b), NFR-R1, US-D5, US-D6, US-R1

### ObservabilityService (동기 제출 + 이벤트 팬아웃)
- **책임**: 메트릭·구조화 로그·트레이스·감사 로그 단일 수집·표준화, 대시보드/탐지기 공급(NFR-O1, RES-5, SEC-14).
- **오케스트레이션**: 도메인·미들웨어·워커가 `emitMetric/emitLog/startSpan/auditAppend` 동기 제출(sync) → 집계·PII 차단 정규화(SEC-3) → 텔레메트리를 이벤트 백본으로 팬아웃(event)해 AiIncidentDetectorSuite·OpsDashboardService 공급 → 임계 위반은 IncidentEventPublisher.publishAlert 라우팅(RES-7).
- **Trace**: NFR-O1, RES-5, RES-7, SEC-3, SEC-13, SEC-14

### HealthMonitoringService (동기 프로빙 + QT-3 평가)
- **책임**: 얕은·깊은 헬스 체크·합성 모니터링으로 비정상 인스턴스를 라우팅에서 제외·건강도 관측성 연동(RES-6). **ReliabilityEvalProbe를 통해 QT-3 신뢰성/우아한 저하 인수 평가셋 소유.**
- **오케스트레이션**: 라우터/LB가 `/health/shallow`·`/health/deep` 주기 프로빙(sync) → `deepCheck` 의존성 연결성 타임아웃 검증(RES-9) → 비정상 시 라우팅 제외 신호 + ObservabilityHub 건강도 메트릭(sync) → **OP/팀은 `ReliabilityEvalProbe.runReliabilityEvalSet`로 업스트림 장애·빈 결과·강제 저하 경로 동작을 검증·보고(QT-3, GroundingEnforcementHook.runEvalSet의 신뢰성 대응물)** → 인제스천/AZ/용량 이상은 ObservabilityService 경유 경보(RES-7).
- **Trace**: RES-6, RES-7, RES-9, QT-3, US-R5

### AiIncidentResponseService (전 구간 이벤트 드리븐 — 별도 워커 DQ1)
- **책임**: RES-11 AI 인시던트 탐지·분류·발행 — (a)비용 폭발 (b)할루시네이션 (c)반쪽짜리 결과를 탐지해 IR+COE로 라우팅.
- **오케스트레이션**: 별도 워커가 이벤트 백본에서 텔레메트리/근거화 위반/지출/완결성 이벤트 비동기 소비(event) → 각 탐지기(`CostExplosionDetector`/`HallucinationDetector`/`PartialResultDetector`)의 `onTelemetryEvent` 후보 평가 → `classify`로 클래스·심각도 부여 → `IncidentEventPublisher.publishIncident/publishAlert`로 인시던트·경보 이벤트 발행(event) → COE 후속 컨텍스트 첨부, OpsDashboardService가 상태 소비. **탐지·발행 전 구간 비동기.**
- **Trace**: RES-11(a/b/c), NFR-O1, US-R1, US-R2, US-R3, US-R4, QT-3(PartialResultDetector)

## U10 — Mypage
- `MypageController`
- `UserPreferencesService`
- `DataExportService`

---

## U11 — Evidence Formation Agent 서비스 (재인셉션 Phase 4 / requirements "[U4]")

> 공통: 모든 호출은 U6 게이트웨이(authn/authz·rate-limit·비용·관측성) 통과 후 진입. 스트리밍 응답(SSE)은 응답 엣지 근거화 게이트를 통과한다.

### EvidenceChatService (동기 스트리밍 — SSE)
- **책임**: 사용자 채팅 턴 오케스트레이션 — 세션 진입·생성, Agent 실행, 스트리밍 응답, 턴 영속(FR-36, FR-37, NFR-P6).
- **오케스트레이션**: `EvidenceChatController`(sync, SSE) → 세션 load/create(`EvidenceSessionRepository`) → `EvidenceAgentOrchestrator.run(request, ctx)` → 스트림 `EvidenceChunk` 반환 → 완료 시 `EvidenceSessionRepository.appendTurn`(turn 영속) → SSE 종료. 후속 질문은 `continueSession`(멀티턴 맥락 유지, Q7=A). 긴 분석은 `EvidenceJobService`로 오프로드(NFR-P6, Q9=A).
- **Trace**: FR-36, FR-37, NFR-P6, Q7=A, US-EV1, US-EV2, US-EV5

### EvidenceSessionManagementService (동기 CRUD)
- **책임**: 세션 목록·삭제·초기화 오케스트레이션 — owner-scoped SEC-8 소유권 강제(FR-38).
- **오케스트레이션**: `EvidenceChatController` → 소유권 확인(`U3.AuthorizationGuard` 위임) → `EvidenceSessionRepository.listSessions/deleteSession/resetAllSessions` → 응답. 타 소유자 세션은 NotFound 일반화(SEC-9, SEC-15).
- **Trace**: FR-38, SEC-8, SEC-9, SEC-15, US-EV7, US-EV8

### EvidenceJobService (비동기 잡 옵션 — 긴 다논문 분석)
- **책임**: 스트리밍 SLA를 초과하는 긴 다논문 분석을 비동기 잡으로 오프로드(NFR-P6, Q9=A, U7 잡 패턴 재사용).
- **오케스트레이션**: 요청 수신 → 즉시 `jobId` 응답(폴링 URL 포함) → `EvidenceAgentOrchestrator` 실행을 비동기 잡 큐에 발행(event) → 워커가 결과 완료 후 `EvidenceSessionRepository`에 저장 → 클라이언트는 `GET /api/evidence/jobs/:id`로 상태/결과 폴링.
- **Trace**: NFR-P6, Q9=A, US-EV9
