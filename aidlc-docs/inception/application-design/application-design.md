# application-design.md — 통합 개요 (AI/ML 논문 디스커버리)

> 본 문서는 DocSuri 유닛의 Application Design 통합 개요다. 잠금된 아키텍처 결정(DQ1–DQ7)을 준수하며 **기술 스택 미확정**(언어/프레임워크/구체 AWS 서비스는 NFR Requirements·Construction 단계 소관) — 모든 외부 의존성은 capability로 참조한다.
> 상세는 동봉 4문서를 참조: [`components.md`](./components.md) · [`component-methods.md`](./component-methods.md) · [`services.md`](./services.md) · [`component-dependency.md`](./component-dependency.md).

---

## 1. 아키텍처 스타일 (잠금 결정 — 설계 준수)

| DQ | 결정 | 설계 반영 |
|---|---|---|
| **DQ1=A** | 모듈형 모놀리스 API + **별도** 인제스천 워커 (마이크로서비스 아님) | U2/U3/U4는 프로세스 내 도메인 모듈; U1은 독립 배포 이벤트 드리븐 워커; U6는 미들웨어 + 별도 운영/탐지 워커. |
| **DQ2=A** | SSR 폰 우선 프런트엔드(Next.js-style) + 백엔드 API | U5 SSR 폰 우선 프런트엔드. |
| **DQ3=C** | 이벤트/스케줄 드리븐 인제스천 | U1 CorpusRefreshScheduler(schedule/backfill/rebuild) + 이벤트 백본. |
| **DQ4=C** | 하이브리드 조직: 도메인 모듈(유닛별) + 공유 레이어(공통 어댑터·횡단) | 도메인 모듈 U1–U4 + 공유 어댑터(벡터 스토어/임베딩 게이트웨이/오브젝트 스토리지/영속화) + U6 횡단. |
| **DQ5=A** | 횡단 관심사는 **전용 미들웨어/게이트웨이 계층** | U6가 비용 가드/서킷·**근거화 강제(단일 권위)**·관측성·authn/authz·레이트리밋 소유. |
| **DQ6=C→재조정** | 인제스천/인덱싱/비용·인시던트/운영 = **이벤트 백본**; 사용자 디스커버리 READ = **동기 REST**(NFR-P1 P50<3s) | U2 검색 요청→응답 전 단계 sync; 인제스천·이력 쓰기·인시던트·관측성 event. |
| **DQ7=A** | REST API | U2/U3/U4 컨트롤러·U6 게이트웨이·U5 ApiClient 전부 REST. |

기술-불가지 준수: 외부 의존은 capability("vector store", "embedding/LLM gateway", "event bus/backbone", "object storage", "managed DB/persistence adapter", "breach-dataset adapter", "DLQ", "scheduler/timer")로만 표기. 구체 제품/프레임워크 명칭 없음.

---

## 2. 6 유닛 요약

| 유닛 | 역할 | 경로 종류 | 핵심 컴포넌트 |
|---|---|---|---|
| **U1 Ingestion** | arXiv·Semantic Scholar·OpenAlex AI/ML 논문을 수집하고 FullText→eager DocModel→DocModel Block 청크→임베딩하여 공유 Corpus 인덱스 생성·갱신(write-only 생산자) | 이벤트/스케줄 백본 | CorpusSourceAdapterSet, FullTextExtractionProcessor, SourcePriorityDeduplicationGuard, DocModelBuildCoordinator, DocModelBlockChunker, EmbeddingGatewayAdapter, CorpusIndexWriter, CorpusRefreshScheduler, IngestFailureHandler |
| **U2 Discovery** | 자연어 질의의 동기 검색 읽기 경로(read 소비자) | **동기 REST** | QueryIntakeController, QueryValidator, QueryUnderstandingExpander, HybridRetriever, RelevanceRanker, GroundingAdapter, ResultAssembler |
| **U3 Accounts/Auth** | 가입/로그인/세션·자격증명·**객체 소유권 인가 단일 결정점** | 동기 REST + 이벤트 신호 | AccountController, SignupService, AuthenticationService, SessionManager, SessionVerifier, AuthorizationGuard, CredentialStore, PasswordPolicy, SessionStore |
| **U4 Library** | 검색 저장·라이브러리·이력(소유자 비공개) | 동기 CRUD + 이력 쓰기 event | SavedSearch/Library/SearchHistory Controller·Service, UserDataRepository, UserDataDTOAndValidation |
| **U5 Frontend** | SSR 폰 우선 웹 UI | 동기 REST(프런트) | AppShell, PhoneMockupFrame, SecurityHeaderPolicy, SearchScreen, ResultList, ResultCard, AccountScreens, LibraryHistoryScreens, StateView, ApiClient |
| **U6 Reliability/Ops** | DQ5 전용 횡단 미들웨어/게이트웨이 + 운영(관측성·비용 가드·헬스·AI 인시던트) | 동기 게이트 + 이벤트 운영 백본 | ApiGatewayMiddleware, AuthnAuthzGuard, InputValidationGuard, RateLimiter, CostGuardCircuitBreaker, GroundingEnforcementHook, ObservabilityHub, HealthCheckService, ReliabilityEvalProbe, AiIncidentDetectorSuite(+3 detectors), IncidentEventPublisher, OpsDashboardService |
| **U11 Evidence Agent** *(재인셉션 Phase 4 / requirements "[U4]")* | 로그인 필수 대화형 다논문 문헌탐색·근거형성 Agent. LLM이 Search·DocModel 도구를 자율 오케스트레이션해 EvidenceItem(핵심 주장·방법·결과·한계) 추출·비교; 근거 없으면 기권(FR-5). EvidenceFormationPort(D5) 단일 구현자 | 동기 REST(SSE 스트리밍) + 비동기 잡 | EvidenceChatController, EvidenceAgentOrchestrator, EvidencePaperSearchTool, EvidenceDocModelTool, EvidenceExtractor, EvidenceComparisonAssembler, AttachmentDocModelAdapter, EvidenceSessionRepository, EvidenceFormationService |

---

## 3. 횡단 미들웨어 계층 (DQ5)

U6 ApiGatewayMiddleware는 모든 사용자向 동기 REST의 단일 진입이다. 전처리 체인: **보안 헤더(SEC-4) → 입력 검증(SEC-5) → 인증/세션(SEC-12) → 객체 단위 인가(SEC-8, U3.AuthorizationGuard 위임) → 레이트 리미팅(SEC-11) → 비용 상태(NFR-C1) → 도메인 핸들러 → [U2 라우트] 응답 엣지 근거화 강제(FR-5) → 관측성 → fail-closed 에러(SEC-15)**.

핵심 단일-소유자 규칙(비평 반영):
- **근거화/기권(FR-5/QT-1)**: U6.GroundingEnforcementHook가 단일 권위 런타임 게이트. U2.GroundingAdapter는 후크 입력/출력 정형화만(독자 강제·인시던트 발행 없음). invocation은 U6 GatewayPipelineService의 U2 라우트 post-handler 한 곳.
- **객체 단위 소유권(SEC-8)**: U3.AuthorizationGuard가 단일 권위 결정점. U6.AuthnAuthzGuard는 위임만, U4.UserDataRepository owner-scoping은 데이터 계층 백스톱.
- **인시던트 발행**: 실재 U6.IncidentEventPublisher/HallucinationDetector로 통일(팬텀 IncidentSignalPublisher 제거).

---

## 4. 이벤트 백본 vs 동기 읽기 (DQ6 재조정)

- **이벤트 백본(비동기·비차단)**: ① 인제스천(source별 스케줄/backfill/rebuild → U1 워커 → Corpus 인덱스), ② 이력 쓰기(U2 `SearchExecuted` → U4.SearchHistoryService), ③ 비용/인시던트 탐지(근거화 위반·지출 급증·완결성 → 탐지기 → IncidentEventPublisher), ④ 관측성 팬아웃·감사.
- **동기 읽기(NFR-P1 P50<3s)**: 사용자 검색 요청→응답(U5 → U6 게이트웨이 → U2 파이프라인 → 응답). U4 rerun도 게이트웨이-프런티드 검색 계약으로 동일 동기 경로 재진입(근거화·비용·관측성 후크 통과 — 백도어 금지).
- **생산자/소비자 정합**: U2가 `SearchExecuted` 생산자(신설 엣지), U4가 소비자. 공유 Corpus 인덱스는 U1 단일 writer·U2 단일 reader. 임베딩 VectorSpec은 공유 임베딩 게이트웨이 레이어가 단일 진실 원천으로 소유하고 U1 writer·U2 reader가 동일 계약 소비(벡터 공간 호환 불변식).

---

## 5. FR → 컴포넌트 추적 요약

| FR | 실현 컴포넌트(대표) |
|---|---|
| FR-1 자연어 질의 | U2.QueryIntakeController/QueryValidator, U5.SearchScreen, U6.InputValidationGuard |
| FR-2 시맨틱·하이브리드 검색 | U1.CorpusIndexWriter(쓰기), U2.QueryUnderstandingExpander/HybridRetriever(읽기) |
| FR-3 상위 N 랭킹 | U2.RelevanceRanker, U5.ResultList |
| FR-4 폰 결과 카드 | U2.ResultAssembler, U5.ResultCard |
| FR-5 엄격 근거화/기권 | **U6.GroundingEnforcementHook(단일 권위)**, U2.GroundingAdapter(어댑팅), U1.DocModelBlockChunker(추적 메타) |
| FR-6 Corpus 생성 파이프라인 | U1 전 컴포넌트 + IngestionPipelineService |
| FR-18 DocModel 리치뷰/eager 생성 | U1.DocModelBuildCoordinator, U1.DocModelBlockChunker, U1.CorpusIndexWriter |
| FR-7 계정 | U3 전 컴포넌트 |
| FR-8 저장 검색 | U4.SavedSearchController/Service |
| FR-9 라이브러리 | U4.LibraryController/Service, U5.ResultCard |
| FR-10 이력 | U4.SearchHistoryController/Service + **U2.SearchOrchestrationService(SearchExecuted 생산자)** |
| FR-11 빈/실패/저하 UX | U5.StateView, U2.QueryIntakeController/ResultAssembler |
| FR-36 근거형성 세션·멀티턴 | U11.EvidenceChatController, U11.EvidenceAgentOrchestrator, U11.EvidenceSessionRepository |
| FR-37 다논문 근거형성·추출·기권 | **U11.EvidenceFormationService(D5 단일 권위)**, U11.EvidenceAgentOrchestrator, U11.EvidenceExtractor, U11.EvidenceComparisonAssembler, U11.AttachmentDocModelAdapter |
| FR-38 근거형성 세션 영속·사용자 제어 | U11.EvidenceSessionRepository, U11.EvidenceChatController |
| NFR-P6 스트리밍 우선·비동기 잡 | U11.EvidenceChatController(SSE), U11.EvidenceJobService |
| QT-8 근거형성 근거화·불변식 | U11.EvidenceExtractor(C-2·FR-5), U11.EvidenceFormationService(D5 계약 테스트) |

### 표준 QT / 스토리 커버리지 (비평 보강 반영)
| ID | 소유자 |
|---|---|
| **QT-1** 근거화 평가 | U6.GroundingEnforcementHook.runEvalSet |
| **QT-2** 관련도 평가 | U2.RelevanceRanker |
| **QT-3** 신뢰성/우아한 저하 평가 *(신설 소유자)* | **U6.ReliabilityEvalProbe.runReliabilityEvalSet**; 교차 트레이스: U2.HybridRetriever·U6.CostGuardCircuitBreaker·AiIncidentDetectorSuite.PartialResultDetector·U5.StateView |
| **QT-4 / PBT** 블로킹 ID | PBT-02 U2.QueryValidator.normalize(라운드트립); PBT-03 U2.RelevanceRanker(랭킹 순서 안정성); PBT-07 U2.HybridRetriever/U1.SourcePriorityDeduplicationGuard(디덥 불변식); PBT-08 U1.DocModelBlockChunker/U1.CorpusIndexWriter(멱등); PBT-09 U2.ResultAssembler·U4.UserDataDTOAndValidation(DTO 라운드트립) |
| **QT-9** U1 Corpus 품질/불변식 | U1.SourcePriorityDeduplicationGuard, U1.DocModelBuildCoordinator, U1.DocModelBlockChunker, U1.CorpusIndexWriter, U1.CorpusRefreshScheduler |
| **US-I1** Corpus 인제스천·인덱싱 *(U1 Corpus 개정)* | **U1.IngestionPipelineService·CorpusIndexWriter·CorpusRefreshScheduler.triggerBackfill/triggerRebuild** |
| **US-H1** 히어로 *(홈 정정)* | **U5.SearchScreen·AppShell**(프런트 표면), U2.QueryIntakeController(백킹 경로) |

> **RES-1 팬텀 트레이스 제거**: U1 source adapter 계층의 RES-1(워크로드 중요도·의존성 맵 문서화)을 삭제. 유효 트레이스(FR-6/C-1/RES-8/RES-9) 유지.

---

## 6. 참조 문서
- [`components.md`](./components.md) — 유닛별 컴포넌트 정의·책임·인터페이스·trace
- [`component-methods.md`](./component-methods.md) — 메서드 시그니처·목적·입출력(상세 규칙은 Functional Design)
- [`services.md`](./services.md) — 서비스 정의·책임·오케스트레이션(동기 vs 이벤트)
- [`component-dependency.md`](./component-dependency.md) — 의존성 매트릭스·통신 패턴·데이터 흐름·ASCII 흐름도
