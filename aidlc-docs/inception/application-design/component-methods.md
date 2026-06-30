# component-methods.md — 메서드 시그니처 (Application Design)

> 시그니처 + 목적 + 입출력 타입만 기술한다. **상세 비즈니스 규칙은 Functional Design 산출물**에서 명시한다.
> 잠금 결정 준수: 사용자向 디스커버리 READ는 동기(DQ6), 인제스천/운영 백본은 이벤트(DQ3/DQ6).

## 비평 반영 요약 (이 문서 관련)
- U2 `GroundingAbstainEnforcer.enforce` 제거 → 얇은 `GroundingAdapter`의 `toGroundingInput`/`mapDecision`으로 대체(독자 강제 없음).
- U2 `SearchOrchestrationService.publishSearchExecuted` **신설** — FR-10 이력 쓰기의 생산자 절반(SearchExecuted 발행).
- U6 `GroundingEnforcementHook.enforce`가 단일 권위 근거화 게이트 메서드.
- U6 `AuthnAuthzGuard.authorize`는 U3.AuthorizationGuard로 위임(재구현 아님).
- U6 `ReliabilityEvalProbe.runReliabilityEvalSet` 신설 — QT-3 평가 진입점.

---

## U1 — Ingestion

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| CorpusSourceAdapterSet | `fetchMetadataPage(source: SourceName, slice: CorpusSlice, cursor: PageCursor, sinceWatermark: Timestamp) -> MetadataPage` | 소스별 watermark 이후 메타데이터 페이지를 레이트 한도 준수 조회 | SourceName, CorpusSlice, PageCursor, Timestamp → MetadataPage{records[], nextCursor, hasMore} |
| CorpusSourceAdapterSet | `fetchFullTextCandidate(record: SourceMetadataRecord) -> FullTextCandidate \| RejectedRecord` | arXiv HTML 우선/PDF 폴백, Semantic Scholar/OpenAlex PDF 후보를 조회 | SourceMetadataRecord → FullTextCandidate{sourceTier, payloadRef, license} \| RejectedRecord{reason} |
| CorpusSourceAdapterSet | `sourceWatermark(source: SourceName) -> Watermark` | source별 incremental 기준점 조회 | SourceName → Watermark |
| FullTextExtractionProcessor | `extractFullText(candidate: FullTextCandidate) -> FullText \| RejectedRecord` | HTML 또는 transient PDF→GROBID 결과를 정규화 FullText로 변환 | FullTextCandidate → FullText{text, structureHints, provenance} \| RejectedRecord{reason} |
| FullTextExtractionProcessor | `validateLicense(candidate: FullTextCandidate) -> LicenseDecision` | OA/인덱싱 허용 여부를 fail-closed 판정 | FullTextCandidate → LicenseDecision{ALLOW \| REJECT, reason?} |
| FullTextExtractionProcessor | `normalizeSource(fullText: FullText) -> ParsedPaper` | 메타데이터+전문을 canonical ParsedPaper로 정규화 | FullText → ParsedPaper |
| SourcePriorityDeduplicationGuard | `deduplicate(records: Sequence[ParsedPaper]) -> DedupResult` | DOI → arXiv id → 정규화 title/author/year 순으로 중복 제거 | ParsedPaper[] → DedupResult{winners[], duplicates[]} |
| SourcePriorityDeduplicationGuard | `canonicalize(paper: ParsedPaper) -> CanonicalPaperRef` | canonical paperId/version/sourceTier 결정 | ParsedPaper → CanonicalPaperRef{paperId, version, sourceTier} |
| SourcePriorityDeduplicationGuard | `fingerprint(paper: ParsedPaper) -> ContentHash` | 변경 감지·멱등 키용 결정적 지문 생성 | ParsedPaper → ContentHash |
| DocModelBuildCoordinator | `buildDocModel(paper: ParsedPaper, ref: CanonicalPaperRef) -> DocModel` | 수집 시점 eager DocModel 완성형 생성 | ParsedPaper, CanonicalPaperRef → DocModel |
| DocModelBuildCoordinator | `storeDocModel(doc: DocModel) -> ObjectRef` | `(paperId, version)` 키로 DocModel 저장 | DocModel → ObjectRef |
| DocModelBuildCoordinator | `validateDocModel(doc: DocModel) -> ValidationResult` | schema roundtrip/negative validation과 provenance 검사 | DocModel → ValidationResult |
| DocModelBlockChunker | `chunkDocModel(doc: DocModel) -> ChunkSet` | DocModel Block 경계 기반 결정적 청크 생성 | DocModel → ChunkSet{chunks[] with blockId, sectionPath} |
| DocModelBlockChunker | `chunkId(paperId: PaperId, version: int, blockId: BlockId, ordinal: int) -> ChunkId` | version+Block 기반 멱등 chunk id 생성 | PaperId, int, BlockId, int → ChunkId |
| EmbeddingGatewayAdapter | `embedBatch(chunks: ChunkSet) -> EmbeddingBatch` | 청크 배치를 임베딩 게이트웨이로 벡터화(타임아웃·비용 텔레메트리 연동) | ChunkSet → EmbeddingBatch{vectors[] aligned to chunkId} |
| EmbeddingGatewayAdapter | `embeddingSchema() -> VectorSpec` | **공유 VectorSpec(차원·모델·거리 메트릭) 노출 — U2 reader와 동일 진실 원천 소비** | (none) → VectorSpec{dimensions, modelRef, distanceMetric} |
| CorpusIndexWriter | `prepareGeneration(spec: IndexGenerationSpec) -> IndexGenerationRef` | DocModel 기반 신규 index generation 생성 준비 | IndexGenerationSpec → IndexGenerationRef |
| CorpusIndexWriter | `upsert(records: IndexRecordBatch, generation: IndexGenerationRef) -> WriteResult` | 임베딩+lexical+DocModel Block anchor를 OpenSearch generation에 멱등 기록 | IndexRecordBatch, IndexGenerationRef → WriteResult{written, skipped, failed[]} |
| CorpusIndexWriter | `tombstone(paperId: PaperId, version: int, generation: IndexGenerationRef) -> WriteResult` | 철회/버전변경 논문 제거로 정합성 유지 | PaperId, int, IndexGenerationRef → WriteResult |
| CorpusIndexWriter | `indexStats(generation: IndexGenerationRef) -> IndexStats` | 인덱스 건강도·규모 통계와 cutover smoke 입력 제공 | IndexGenerationRef → IndexStats{docCount, vectorCount, lastWrite} |
| CorpusRefreshScheduler | `onSchedule(trigger: ScheduleTrigger) -> IngestionJob` | source별 증분 갱신 잡 생성·발행 | ScheduleTrigger → IngestionJob |
| CorpusRefreshScheduler | `advanceWatermark(source: SourceName, watermark: Timestamp) -> void` | 성공 처리 후 source watermark 단조 전진 | SourceName, Timestamp → void |
| CorpusRefreshScheduler | `triggerBackfill(scope: CorpusScope) -> IngestionJob` | phase-1 Corpus/backfill 잡 생성 | CorpusScope → IngestionJob |
| CorpusRefreshScheduler | `triggerRebuild(reason: RebuildReason) -> IngestionJob` | DocModel/index 재생성 잡 생성 | RebuildReason → IngestionJob |
| IngestFailureHandler | `classify(error: IngestError) -> FailureClass` | 오류를 재시도 가능/영구로 분류 | IngestError → FailureClass{RETRIABLE \| PERMANENT} |
| IngestFailureHandler | `scheduleRetry(item: IngestItem, attempt: int) -> RetryDecision` | 백오프·재시도 한도·쿼터 인지 재시도 결정 | IngestItem, int → RetryDecision{RETRY at delay \| EXHAUSTED} |
| IngestFailureHandler | `sendToDLQ(item: IngestItem, reason: FailureReason) -> void` | 소진/영구 실패 항목 DLQ 격리 | IngestItem, FailureReason → void |
| IngestFailureHandler | `emitFailureSignal(jobId: JobId, error: IngestError) -> void` | 실패를 관측성/경보 신호로 발행 | JobId, IngestError → void |

---

## U2 — Discovery/Search

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| QueryIntakeController | `search(request: SearchRequest, ctx: RequestContext) -> SearchResponse` | 동기 검색 진입: 검증→오케스트레이션→폰 DTO 직렬화. 종단 상태 명시 HTTP 매핑 | SearchRequest{query, options?}, RequestContext{authSession, degradationSignal, requestId} → SearchResultPageDTO \| AbstainDTO \| DegradedResultDTO \| ValidationErrorDTO |
| QueryValidator | `validate(rawQuery: string) -> ValidationResult` | FR-1/SEC-5 도메인 검증(길이·빈값·허용문자·새니타이즈) | string → ValidationResult{ok, reason?} |
| QueryValidator | `normalize(rawQuery: string) -> NormalizedQuery` | 결정적 정규화(트림·공백·유니코드)로 재현성 확보(PBT-02 라운드트립) | string → NormalizedQuery{text} |
| QueryUnderstandingExpander | `expand(query: NormalizedQuery, degradation: DegradationSignal) -> QueryPlan` | 질의를 임베딩 벡터+lexical 텀+필터 힌트로 확장; 저하 시 lexical-only(임베딩은 공유 VectorSpec 공간) | NormalizedQuery, DegradationSignal{llmEnabled, rerankEnabled} → QueryPlan{embeddingVector?, lexicalTerms, filterHints?, mode} |
| HybridRetriever | `retrieve(plan: QueryPlan, degradation: DegradationSignal) -> CandidateSet` | 벡터+lexical 후보 검색·병합·디덥(멱등, PBT-07); 장애 시 부분/폴백 | QueryPlan, DegradationSignal → CandidateSet{candidates[], retrievalMode} |
| RelevanceRanker | `rank(candidates: CandidateSet, plan: QueryPlan, degradation: DegradationSignal, topN: int) -> RankedResults` | 관련도순 상위 N 절단(순서 안정성 PBT-03); LLM 리랭킹 여부는 cost-circuit 결정 | CandidateSet, QueryPlan, DegradationSignal, int(제안 20) → RankedResults{ranked[], rankingMode} |
| **GroundingAdapter** | `toGroundingInput(results: RankedResults, plan: QueryPlan) -> GroundingInput` | **U6 근거화 후크 입력으로 후보+검색 레코드 정형화(독자 검사 없음)** | RankedResults, QueryPlan → GroundingInput{candidateResponse, retrievedRecords} |
| **GroundingAdapter** | `mapDecision(decision: GroundingDecision) -> GroundedResults \| AbstainResult` | **U6 후크 verdict를 종단 결과/기권으로 매핑(독자 차단·인시던트 발행 없음)** | GroundingDecision{verdict, violations[]} → GroundedResults{items[]} \| AbstainResult{reason} |
| ResultAssembler | `assemble(input: GroundedResults \| AbstainResult, degradation: DegradationSignal) -> SearchResponse` | 근거화 결과/기권을 폰 카드 DTO+상태 플래그로 조립(DTO 라운드트립 PBT-09) | GroundedResults \| AbstainResult, DegradationSignal → SearchResultPageDTO \| AbstainDTO \| DegradedResultDTO |

> **SearchOrchestrationService 메서드(서비스 레벨, services.md 참조)**: `executeSearch(...)` (동기 파이프라인 조정), **`publishSearchExecuted(userId, query, timestamp, resultCount) -> void`** — 성공 응답 후 `SearchExecutedEvent`를 이벤트 백본에 발행(FR-10 이력 쓰기 생산자, 비차단·P50<3s 경로 밖).

---

## U3 — Accounts/Auth

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| AccountController | `signup(req: SignupRequest, ctx: RequestContext) -> HttpResponse<SignupResult>` | 가입 요청 수신·검증·SignupService 위임·일반화 응답 | SignupRequest{email, password}, RequestContext{requestId, clientId} → HttpResponse<SignupResult{accountId}> \| 일반화 에러(409/400/429) |
| AccountController | `login(req: LoginRequest, ctx: RequestContext) -> HttpResponse<SessionCookie>` | 로그인 위임·성공 시 보안 세션 쿠키 설정 | LoginRequest{email, password}, RequestContext → HttpResponse w/ Set-Cookie(secure/httpOnly/sameSite) \| 인증 에러(401/429) |
| AccountController | `logout(ctx: AuthenticatedContext) -> HttpResponse<void>` | 현재 세션 서버측 무효화·쿠키 클리어 | AuthenticatedContext{principal, sessionHandle} → HttpResponse w/ cleared Set-Cookie |
| AccountController | `currentSession(ctx: AuthenticatedContext) -> HttpResponse<SessionInfo>` | 검증 세션 비민감 정보 반환(프런트 세션 동기화) | AuthenticatedContext{principal} → HttpResponse<SessionInfo{userId, expiresAt}> \| 401 |
| SignupService | `register(cmd: SignupCommand) -> Result<AccountId, SignupError>` | 정책·유일성 검증·해싱·영속·AccountCreated 발행 오케스트레이션 | SignupCommand{email, password, requestContext} → Result<AccountId, SignupError{POLICY_VIOLATION\|EMAIL_TAKEN\|BREACHED}> |
| AuthenticationService | `authenticate(cmd: LoginCommand) -> Result<IssuedSession, AuthError>` | 자격증명 검증·세션 발급, 실패 시 AuthFailureSignal 발행 | LoginCommand{email, password, requestContext} → Result<IssuedSession{token, cookieMaterial}, AuthError{INVALID_CREDENTIALS}> |
| AuthenticationService | `revoke(sessionHandle: SessionHandle) -> Result<void, AuthError>` | 로그아웃 시 세션 서버측 무효화 위임 | SessionHandle → Result<void, AuthError> |
| SessionManager | `issue(principal: Principal) -> IssuedSession` | 서버검증 세션 발급·보안 쿠키 머티리얼 생성 | Principal{userId} → IssuedSession{token, cookieMaterial, expiresAt} |
| SessionManager | `verify(token: SessionToken) -> Result<AuthenticatedPrincipal, SessionError>` | 토큰 서버측 검증해 주체 해석(fail closed) | SessionToken → Result<AuthenticatedPrincipal{userId, sessionHandle}, SessionError{INVALID\|EXPIRED}> |
| SessionManager | `invalidate(sessionHandle: SessionHandle) -> void` | 세션 서버측 즉시 무효화 | SessionHandle → void |
| SessionVerifier | `verifyRequest(rawToken: string, ctx: RequestContext) -> Result<AuthenticatedPrincipal, AuthRejection>` | 게이트웨이 요청별 인증 강제 시 경량 동기 검증 진입점 | string(쿠키/헤더), RequestContext → Result<AuthenticatedPrincipal, AuthRejection{UNAUTHENTICATED}> |
| **AuthorizationGuard** | `authorize(principal: Principal, action: Action, resourceOwner: UserId) -> Decision` | **객체 단위 소유권 인가 단일 권위 결정(기본 거부) — U6 게이트웨이·U4가 위임** | Principal, Action(enum), UserId → Decision{ALLOW\|DENY} |
| AuthorizationGuard | `authorizeAdmin(principal: Principal, action: AdminAction, mfaContext: MfaContext) -> Decision` | 관리자 역할+MFA 충족 결정 | Principal, AdminAction(enum), MfaContext{mfaVerified} → Decision{ALLOW\|DENY} |
| CredentialStore | `createCredential(accountId: AccountId, password: string) -> CredentialRef` | 적응형 해싱 자격증명 생성·영속(평문 미저장) | AccountId, password(평문, 비로깅) → CredentialRef{credentialId} |
| CredentialStore | `verifyCredential(email: string, password: string) -> CredentialVerification` | 상수시간 의도 검증·재해싱 필요 판정 | email, password(평문, 비로깅) → CredentialVerification{matched, principal?, needsRehash} |
| CredentialStore | `rehash(accountId: AccountId, password: string) -> void` | 노후 해시 파라미터 재해싱 | AccountId, password(평문, 비로깅) → void |
| PasswordPolicy | `evaluate(password: string, ctx: PolicyContext) -> PolicyResult` | 비밀번호 정책+유출 검사 평가 | password, PolicyContext{email?} → PolicyResult{ok, reasons[]} |
| SessionStore | `persist(record: SessionRecord) -> void` | 세션 레코드 영속 | SessionRecord{sessionHandle, userId, expiresAt} → void |
| SessionStore | `load(sessionHandle: SessionHandle) -> Option<SessionRecord>` | 세션 레코드 조회(서버측 검증용) | SessionHandle → Option<SessionRecord> |
| SessionStore | `remove(sessionHandle: SessionHandle) -> void` | 세션 레코드 삭제(무효화) | SessionHandle → void |

---

## U4 — Saved Searches & Library

> **rerun 메서드 주석**: `rerun`은 게이트웨이-프런티드 검색 계약(U6 ApiGatewayMiddleware 경유 → U2)을 통해 재실행한다. 직접 U2 모듈 호출이 아니며 근거화·비용·관측성 후크를 동일하게 통과한다.

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| SavedSearchController | `createSavedSearch(authCtx: AuthContext, body: SavedSearchCreateDTO) -> HttpResponse<SavedSearchDTO>` | 새 검색 저장 생성·반환(동기 REST) | AuthContext{userId}, SavedSearchCreateDTO{query + label?} → HttpResponse<SavedSearchDTO>(201) \| 검증/인가 오류 |
| SavedSearchController | `listSavedSearches(authCtx: AuthContext, page: PageParams) -> HttpResponse<SavedSearchPageDTO>` | 사용자 소유 저장 검색 최근순 목록 | AuthContext, PageParams{limit, cursor} → HttpResponse<SavedSearchPageDTO>(200) |
| SavedSearchController | `deleteSavedSearch(authCtx: AuthContext, savedSearchId: Id) -> HttpResponse<void>` | 소유 저장 검색 삭제(타 소유는 NotFound 일반화) | AuthContext, Id → HttpResponse<void>(204) \| 404 |
| SavedSearchController | `rerunSavedSearch(authCtx: AuthContext, savedSearchId: Id) -> HttpResponse<SearchResultSetDTO>` | 저장 질의로 게이트웨이-프런티드 검색 동기 재실행 | AuthContext, Id → HttpResponse<SearchResultSetDTO>(200, U2 위임) |
| LibraryController | `addLibraryItem(authCtx: AuthContext, body: LibraryItemCreateDTO) -> HttpResponse<LibraryItemDTO>` | arXiv 논문 라이브러리 멱등 추가 | AuthContext, LibraryItemCreateDTO{arXivId + 메타 스냅샷} → HttpResponse<LibraryItemDTO>(201/200 멱등) |
| LibraryController | `listLibrary(authCtx: AuthContext, page: PageParams) -> HttpResponse<LibraryPageDTO>` | 사용자 소유 라이브러리 목록 | AuthContext, PageParams → HttpResponse<LibraryPageDTO>(200) |
| LibraryController | `removeLibraryItem(authCtx: AuthContext, itemId: Id) -> HttpResponse<void>` | 소유 라이브러리 항목 삭제 | AuthContext, Id → HttpResponse<void>(204) \| 404 |
| SearchHistoryController | `listHistory(authCtx: AuthContext, page: PageParams) -> HttpResponse<HistoryPageDTO>` | 최근 검색 이력 목록 | AuthContext, PageParams → HttpResponse<HistoryPageDTO>(200) |
| SearchHistoryController | `rerunHistoryEntry(authCtx: AuthContext, historyId: Id) -> HttpResponse<SearchResultSetDTO>` | 이력 질의로 게이트웨이-프런티드 검색 동기 재실행 | AuthContext, Id → HttpResponse<SearchResultSetDTO>(200, U2 위임) |
| SearchHistoryController | `clearHistory(authCtx: AuthContext) -> HttpResponse<void>` | 사용자 이력 전체 삭제 | AuthContext → HttpResponse<void>(204) |
| SavedSearchService | `save(userId: Id, spec: SavedSearchSpec) -> SavedSearch` | owner-scoped 영속·감사 이벤트 발행 | userId, SavedSearchSpec{query + label} → SavedSearch |
| SavedSearchService | `list(userId: Id, page: PageParams) -> Page<SavedSearch>` | 사용자 소유 저장 검색 페이지 조회 | userId, PageParams → Page<SavedSearch> |
| SavedSearchService | `delete(userId: Id, savedSearchId: Id) -> void` | 소유권 확인 후 삭제·감사 발행 | userId, Id → void(미소유 시 NotFound) |
| SavedSearchService | `rerun(userId: Id, savedSearchId: Id) -> SearchResultSet` | 소유권 확인 후 저장 query를 게이트웨이-프런티드 검색으로 재실행 | userId, Id → SearchResultSet(U2 반환 타입) |
| LibraryService | `addItem(userId: Id, paperRef: PaperRef) -> LibraryItem` | (userId, arXivId) 멱등 추가·메타 스냅샷 보존 | userId, PaperRef{arXivId + 메타 스냅샷} → LibraryItem(신규/기존 멱등) |
| LibraryService | `list(userId: Id, page: PageParams) -> Page<LibraryItem>` | 사용자 소유 라이브러리 페이지 조회 | userId, PageParams → Page<LibraryItem> |
| LibraryService | `removeItem(userId: Id, itemId: Id) -> void` | 소유권 확인 후 삭제·감사 발행 | userId, Id → void(미소유 시 NotFound) |
| SearchHistoryService | `recordSearch(event: SearchExecutedEvent) -> void` | **U2 발행 SearchExecuted 이벤트 구독해 비동기 기록(NFR-P1 비차단)** | SearchExecutedEvent{userId, query, timestamp, resultCount} → void |
| SearchHistoryService | `list(userId: Id, page: PageParams) -> Page<SearchHistoryEntry>` | 사용자 소유 이력 최근순 조회 | userId, PageParams → Page<SearchHistoryEntry> |
| SearchHistoryService | `rerun(userId: Id, historyId: Id) -> SearchResultSet` | 소유권 확인 후 게이트웨이-프런티드 검색 동기 재실행 | userId, Id → SearchResultSet |
| SearchHistoryService | `clear(userId: Id) -> void` | 사용자 소유 이력 전체 삭제 | userId → void |
| UserDataRepository | `insert<T>(userId: Id, entity: T) -> T` | owner 키 강제 포함 영속화 | userId, entity → 영속 엔티티 |
| UserDataRepository | `findByOwner<T>(userId: Id, key: Id) -> Optional<T>` | 소유자 범위 단건 조회(타 소유자 비가시, SEC-8 백스톱) | userId, key → Optional<T> |
| UserDataRepository | `listByOwner<T>(userId: Id, page: PageParams) -> Page<T>` | 소유자 범위 최근순 페이지 조회 | userId, PageParams → Page<T> |
| UserDataRepository | `deleteByOwner<T>(userId: Id, key: Id) -> boolean` | 소유자 범위 삭제·실제 삭제 여부 반환 | userId, key → boolean |
| UserDataDTOAndValidation | `validateAndMap(raw: RawRequest, schema: DTOSchema) -> Result<DTO, ValidationError>` | SEC-5 검증·새니타이즈·DTO 매핑 | RawRequest, DTOSchema → Result<DTO, ValidationError> |
| UserDataDTOAndValidation | `toDTO(entity: DomainEntity) -> DTO` | 도메인 엔티티→외부 DTO(내부 필드 비노출) | DomainEntity → DTO |

---

## U5 — Mobile Web Frontend

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| AppShell | `render(route: RouteContext, session: SessionState): SSRHtml` | 라우트·세션에 맞춰 SSR 루트 레이아웃·화면 트리 렌더(히어로 골격 포함) | RouteContext, SessionState → SSRHtml |
| AppShell | `navigate(to: RoutePath): void` | 클라이언트 라우트 전환·보호 라우트 가드 | RoutePath → void |
| AppShell | `useSession(): SessionState` | 하위 화면에 인증/세션 상태 제공 | (none) → SessionState |
| PhoneMockupFrame | `wrap(children: ViewTree, viewport: ViewportClass): FramedView` | 뷰포트별 폰 풀블리드/목업 프레임 감싸기 | ViewTree, ViewportClass → FramedView |
| PhoneMockupFrame | `classifyViewport(width: px): ViewportClass` | 뷰포트 폭을 phone/desktop-tablet 분류 | px → ViewportClass |
| SecurityHeaderPolicy | `buildHeaders(req: SsrRequest): SecurityHeaders` | SSR 보안 헤더 세트 구성(자기-프레이밍 예외 포함) | SsrRequest → SecurityHeaders |
| SecurityHeaderPolicy | `buildCsp(): CspDirectiveSet` | frame-ancestors=self만 허용·나머지 제한 CSP 생성 | (none) → CspDirectiveSet |
| SearchScreen | `submitQuery(input: QueryInput): void` | 검증 통과 시 ApiClient.search로 동기 검색 트리거·상태 전이(히어로 진입점) | QueryInput → void |
| SearchScreen | `validateInput(input: QueryInput): ValidationResult` | 빈/길이초과(≤500자) 클라이언트 검증 | QueryInput → ValidationResult |
| SearchScreen | `renderState(state: SearchScreenState): ViewTree` | 로딩/결과/빈/실패/저하 상태를 ResultList·StateView에 위임 렌더 | SearchScreenState → ViewTree |
| ResultList | `render(results: ResultCardVM[], meta: ResultMeta): ViewTree` | 정렬 순서 보존 상위 N건 카드·저하 배너 렌더 | ResultCardVM[], ResultMeta → ViewTree |
| ResultCard | `render(card: ResultCardVM): ViewTree` | 단일 논문 폰 최적화 카드(가로 스크롤 없음) | ResultCardVM → ViewTree |
| ResultCard | `onSaveToLibrary(paperId: PaperId): void` | 라이브러리 저장 액션을 ApiClient에 위임 | PaperId → void |
| AccountScreens | `submitSignup(form: SignupForm): void` | 검증 가입 폼을 ApiClient.signup 제출·상태 반영 | SignupForm → void |
| AccountScreens | `submitLogin(form: LoginForm): void` | 검증 로그인 폼을 ApiClient.login 제출·상태 반영 | LoginForm → void |
| AccountScreens | `logout(): void` | ApiClient.logout 호출·셸 세션 초기화 | (none) → void |
| LibraryHistoryScreens | `renderSavedSearches(items: SavedSearchVM[]): ViewTree` | 소유자 비공개 저장 검색 목록·재실행·삭제 UI | SavedSearchVM[] → ViewTree |
| LibraryHistoryScreens | `renderLibrary(items: LibraryItemVM[]): ViewTree` | 소유자 비공개 라이브러리 목록·삭제 UI | LibraryItemVM[] → ViewTree |
| LibraryHistoryScreens | `renderHistory(items: HistoryItemVM[]): ViewTree` | 소유자 비공개 이력 목록·재실행 UI | HistoryItemVM[] → ViewTree |
| LibraryHistoryScreens | `rerun(searchRef: SavedSearchId \| HistoryId): void` | 저장 검색/이력을 SearchScreen 검색 흐름으로 재실행 | SavedSearchId \| HistoryId → void |
| StateView | `renderEmpty(reason: EmptyReason): ViewTree` | 관련 논문 없음 등 빈 상태 비기술 메시지(날조 0건) | EmptyReason → ViewTree |
| StateView | `renderError(kind: UserFacingErrorKind): ViewTree` | fail closed 일반화 에러·내부정보 차단 | UserFacingErrorKind → ViewTree |
| StateView | `renderDegraded(mode: DegradationMode): ViewTree` | 저하 모드(리랭킹 비활성 등) 명시 렌더(QT-3 저하 UX) | DegradationMode → ViewTree |
| ApiClient | `search(req: SearchRequest): Promise<SearchResponse>` | 동기 REST 검색 요청·정규화 응답/오류 | SearchRequest → Promise<SearchResponse> |
| ApiClient | `signup(req: SignupRequest): Promise<SessionResult>` | 가입 요청·세션/레이트리밋 정규화 | SignupRequest → Promise<SessionResult> |
| ApiClient | `login(req: LoginRequest): Promise<SessionResult>` | 로그인 요청·세션/무차별대입 정규화 | LoginRequest → Promise<SessionResult> |
| ApiClient | `logout(): Promise<void>` | 로그아웃 요청·서버측 세션 무효화 | (none) → Promise<void> |
| ApiClient | `listSavedSearches(): Promise<SavedSearch[]>` | 사용자 저장 검색 목록 조회(소유권 서버 인가) | (none) → Promise<SavedSearch[]> |
| ApiClient | `saveSearch(req: SaveSearchRequest): Promise<SavedSearch>` | 검색을 비공개 목록에 저장 | SaveSearchRequest → Promise<SavedSearch> |
| ApiClient | `listLibrary(): Promise<LibraryItem[]>` | 사용자 라이브러리 항목 조회 | (none) → Promise<LibraryItem[]> |
| ApiClient | `addToLibrary(req: AddLibraryRequest): Promise<LibraryItem>` | 논문을 라이브러리에 추가 | AddLibraryRequest → Promise<LibraryItem> |
| ApiClient | `listHistory(): Promise<HistoryItem[]>` | 사용자 최근 검색 이력 조회 | (none) → Promise<HistoryItem[]> |

---

## U6 — Reliability & Operations

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| ApiGatewayMiddleware | `handle(request: HttpRequest, next: DomainHandler) -> HttpResponse` | 전처리 체인 적용→핸들러 위임; U2 라우트는 응답 엣지에서 GroundingEnforcementHook.enforce 적용; enforce에서 발생한 모든 예외는 명시적으로 catch하여 fail-closed(toProductionError) 처리함으로써 우회 차단 | HttpRequest, DomainHandler → HttpResponse(정상 \| 일반화 에러) |
| ApiGatewayMiddleware | `applySecurityHeaders(response: HttpResponse) -> HttpResponse` | 제한 CSP·보안 헤더 부착(frame-ancestors=self 카브아웃) | HttpResponse → HttpResponse |
| ApiGatewayMiddleware | `toProductionError(err: Throwable, requestId: RequestId) -> HttpResponse` | 내부 예외를 스택 트레이스 비노출 일반화 에러로 매핑(fail-closed) | Throwable, RequestId → HttpResponse(generic) |
| AuthnAuthzGuard | `authenticate(request: HttpRequest) -> Result<Principal, AuthError>` | 세션/토큰 서버측 검증(U3.SessionVerifier 위임) | HttpRequest → Result<Principal, AuthError> |
| AuthnAuthzGuard | `authorize(principal: Principal, resource: ResourceRef, action: Action) -> AuthzDecision` | **객체 단위 소유권 결정을 U3.AuthorizationGuard에 위임(재구현 아님); 미들웨어는 강제 이음새. 관리자 MFA 확인.** | Principal, ResourceRef, Action → AuthzDecision(allow \| deny) |
| InputValidationGuard | `validate(payload: RawPayload, schemaId: SchemaId) -> Result<ValidatedPayload, ValidationError>` | 선언적 스키마 검증·새니타이즈·인라인 에러 | RawPayload, SchemaId → Result<ValidatedPayload, ValidationError> |
| RateLimiter | `checkLimit(scope: LimitScope, key: ClientKey) -> LimitDecision` | 출처별 슬라이딩 윈도 한도 평가(검색·가입·남용 완화) | LimitScope, ClientKey → LimitDecision(allow \| throttle \| reject) |
| CostGuardCircuitBreaker | `getBudgetState() -> BudgetState` | 준실시간 임계 상태·권고 저하 모드 반환(동기 폴백 분기 지원). 원자적 카운터를 읽어 TOCTOU 경합을 제거함 | (none) → BudgetState{tier, degradeMode, circuitState} |
| CostGuardCircuitBreaker | `recordSpend(usage: UsageEvent) -> void` | 사용량/지출 누적(원자적 카운터 증분)·급증 신호화 트리거 | UsageEvent → void |
| CostGuardCircuitBreaker | `evaluateCircuit() -> CircuitTransition` | 비동기 주기적 실행으로 임계 도달 시 OPEN/반-개방/CLOSE 전이·저하 지시 갱신 | (internal snapshot) → CircuitTransition |
| **GroundingEnforcementHook** | `enforce(candidate: CandidateResponse, retrieved: RetrievedRecordSet) -> GroundingDecision` | **FR-5/QT-1 단일 권위 런타임 게이트. 실재 레코드 매핑·AI 텍스트 출처 검증·통과/차단/기권. 위반 시 HallucinationDetector로 신호.** | CandidateResponse, RetrievedRecordSet → GroundingDecision{verdict: pass\|block\|abstain, violations[]} |
| GroundingEnforcementHook | `runEvalSet(evalSet: GroundingEvalSet) -> GroundingEvalReport` | QT-1 평가셋 동일 후크로 실행·날조 0건/코퍼스 밖 기권 보고(OP/팀 소유) | GroundingEvalSet → GroundingEvalReport |
| **ReliabilityEvalProbe** | `runReliabilityEvalSet(evalSet: ReliabilityEvalSet) -> ReliabilityEvalReport` | **QT-3 신뢰성/우아한 저하 인수 평가 — 업스트림 장애·빈 결과 경로 동작 검증·보고** | ReliabilityEvalSet → ReliabilityEvalReport{cases[], degradedBehaviorOk} |
| ReliabilityEvalProbe | `verifyDegradedMode(mode: DegradationMode) -> DegradedModeReport` | 강제 저하 모드(LLM off/벡터 장애/부분 결과) 동작 검증 | DegradationMode → DegradedModeReport |
| ObservabilityHub | `emitMetric(name: MetricName, value: MetricValue, tags: TagSet) -> void` | 지연·에러율·처리량·근거화/검색 건강도·지출 메트릭 수집 | MetricName, MetricValue, TagSet → void |
| ObservabilityHub | `emitLog(entry: StructuredLogEntry) -> void` | 요청 ID 상관 구조화 로그 수집(PII/시크릿 차단) | StructuredLogEntry → void |
| ObservabilityHub | `startSpan(name: SpanName, context: TraceContext) -> Span` | 분산 트레이스 스팬 시작(동기 경로 지연 추적) | SpanName, TraceContext → Span |
| ObservabilityHub | `auditAppend(event: AuditEvent) -> void` | 핵심 변경·인가 결정 추가 전용 감사 로그(90일+) | AuditEvent → void |
| HealthCheckService | `shallowCheck() -> HealthStatus` | 프로세스 생존/준비성 반환(liveness/readiness) | (none) → HealthStatus |
| HealthCheckService | `deepCheck() -> DependencyHealthReport` | arXiv·LLM 게이트웨이·벡터 스토어 연결성 타임아웃 검증 | (none) → DependencyHealthReport |
| AiIncidentDetectorSuite | `onTelemetryEvent(event: TelemetryEvent) -> Option<IncidentSignal>` | 텔레메트리 소비해 세 인시던트 클래스 후보 평가 | TelemetryEvent → Option<IncidentSignal> |
| AiIncidentDetectorSuite | `classify(signal: IncidentSignal) -> ClassifiedIncident` | 후보를 RES-11 클래스(a/b/c)·심각도 분류 | IncidentSignal → ClassifiedIncident |
| IncidentEventPublisher | `publishIncident(incident: ClassifiedIncident) -> void` | 분류 인시던트 표준 스키마 발행·감사 기록 | ClassifiedIncident → void |
| IncidentEventPublisher | `publishAlert(alert: OpsAlert) -> void` | 운영 경보 IR/COE 라우팅 발행 | OpsAlert → void |
| OpsDashboardService | `getDashboard(window: TimeWindow) -> OpsDashboardView` | 지연·에러율·처리량·건강도·지출·서킷 상태 OP 뷰 모델 | TimeWindow → OpsDashboardView |
| OpsDashboardService | `listIncidents(filter: IncidentFilter) -> IncidentList` | 세 인시던트 클래스 상태·경보 이력 조회 | IncidentFilter → IncidentList |

---

## U11 — Evidence Formation Agent

> **스트리밍 주석**: `sendMessage`는 SSE 청크 스트림을 반환(NFR-P6). 긴 분석은 `EvidenceJobService`가 비동기 잡으로 처리하며 `getJobResult`로 폴링.

| 컴포넌트 | 시그니처 | 목적 | 입력 → 출력 |
|---|---|---|---|
| EvidenceChatController | `createSession(authCtx: AuthContext, body: SessionCreateDTO) -> HttpResponse<EvidenceSessionDTO>` | 새 근거형성 세션 생성 | AuthContext, SessionCreateDTO{title?} → HttpResponse<EvidenceSessionDTO>(201) |
| EvidenceChatController | `listSessions(authCtx: AuthContext, page: PageParams) -> HttpResponse<EvidenceSessionPageDTO>` | 소유자 세션 목록 조회 | AuthContext, PageParams → HttpResponse<EvidenceSessionPageDTO>(200) |
| EvidenceChatController | `getSession(authCtx: AuthContext, sessionId: Id) -> HttpResponse<EvidenceSessionResultDTO>` | 특정 세션 결과·이력 재열람 | AuthContext, Id → HttpResponse<EvidenceSessionResultDTO>(200) \| 404 |
| EvidenceChatController | `sendMessage(authCtx: AuthContext, sessionId: Id, body: EvidenceMessageDTO) -> StreamingResponse<EvidenceChunkDTO>` | 채팅 턴 전송 → 스트리밍 근거형성 응답(SSE) | AuthContext, Id, EvidenceMessageDTO{topic, scope?, paperIds?, attachments?} → SSE stream |
| EvidenceChatController | `deleteSession(authCtx: AuthContext, sessionId: Id) -> HttpResponse<void>` | 소유 세션 삭제(타 소유 NotFound) | AuthContext, Id → HttpResponse<void>(204) \| 404 |
| EvidenceChatController | `resetAllSessions(authCtx: AuthContext) -> HttpResponse<void>` | 전체 세션 초기화 | AuthContext → HttpResponse<void>(204) |
| EvidenceAgentOrchestrator | `run(request: EvidenceRequest, ctx: AgentContext) -> AsyncStream<EvidenceChunk>` | 첫 질문: 도구 자율 오케스트레이션 → 스트리밍 근거형성 | EvidenceRequest, AgentContext → AsyncStream<EvidenceChunk>(EvidenceResult \| EvidenceAbstainResult 종착) |
| EvidenceAgentOrchestrator | `continueSession(sessionId: Id, followUp: str, ctx: AgentContext) -> AsyncStream<EvidenceChunk>` | 후속 질문: 이전 턴 맥락 참조 → 스트리밍 | Id, str, AgentContext → AsyncStream<EvidenceChunk> |
| EvidencePaperSearchTool | `searchPapers(query: str, scope: EvidenceScope, paperIds?: str[]) -> IndexRecord[]` | Agent 호출 논문 검색 도구 | str, EvidenceScope, str[]? → IndexRecord[] |
| EvidenceDocModelTool | `fetchBlocks(paperId: str, recordRef: str, anchor?: str) -> DocModelBlock[]` | Agent 호출 DocModel 블록 읽기 | str, str, str? → DocModelBlock[] |
| EvidenceExtractor | `extractItems(blocks: DocModelBlock[], paperId: str, recordRef: str) -> EvidenceItem[]` | 블록에서 EvidenceItem 추출(추출 전용, C-2) | DocModelBlock[], str, str → EvidenceItem[](statement+supporting+conflicting, confidence 없음 Q3=B) |
| EvidenceComparisonAssembler | `assemble(items: EvidenceItem[], coverage: EvidenceCoverage) -> EvidenceResult` | EvidenceItems → 비교표+쟁점 오버레이 EvidenceResult | EvidenceItem[], EvidenceCoverage → EvidenceResult(state=ok) |
| EvidenceComparisonAssembler | `buildConflictOverlay(items: EvidenceItem[]) -> ConflictMatrix` | 지지/상충 출처 기반 쟁점 오버레이 계산 | EvidenceItem[] → ConflictMatrix |
| AttachmentDocModelAdapter | `processAttachment(handle: AttachmentHandle) -> DocModelBlock[]` | 첨부 문서 doc-model 파이프라인 일시 처리(원시 파일 미저장) | AttachmentHandle → DocModelBlock[] |
| EvidenceSessionRepository | `createSession(userId: Id, meta: SessionMeta) -> EvidenceSession` | owner 키 강제 포함 세션 영속화 | Id, SessionMeta → EvidenceSession |
| EvidenceSessionRepository | `loadSession(userId: Id, sessionId: Id) -> Optional<EvidenceSession>` | 소유자 범위 세션 단건 조회 | Id, Id → Optional<EvidenceSession> |
| EvidenceSessionRepository | `listSessions(userId: Id, page: PageParams) -> Page<EvidenceSession>` | 소유자 범위 세션 최근순 목록 | Id, PageParams → Page<EvidenceSession> |
| EvidenceSessionRepository | `appendTurn(sessionId: Id, turn: EvidenceTurn) -> void` | 세션 턴 추가 영속 | Id, EvidenceTurn → void |
| EvidenceSessionRepository | `deleteSession(userId: Id, sessionId: Id) -> boolean` | 소유자 범위 세션 삭제 | Id, Id → boolean(삭제 성공 여부) |
| EvidenceSessionRepository | `resetAllSessions(userId: Id) -> void` | 소유자 전체 세션 삭제 | Id → void |
| EvidenceFormationService | `async form_evidence(request: EvidenceRequest, ctx: Any) -> EvidenceResult \| EvidenceAbstainResult` | **EvidenceFormationPort(D5) 구현 — U12 Tool 진입점**. EvidenceAgentOrchestrator 라우팅; 긴 분석은 잡 오프로드 | EvidenceRequest, Any → EvidenceResult(state=ok) \| EvidenceAbstainResult(state=abstain) |
