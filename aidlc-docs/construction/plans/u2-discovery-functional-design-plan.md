# u2-discovery-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (유닛별 루프) · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거(SSOT)**: `aidlc-docs/inception/` — `unit-of-work.md`, `unit-of-work-story-map.md`, `application-design/{components,component-methods,services,component-dependency}.md`, `user-stories/stories.md`, `requirements/requirements.md` · `aidlc-docs/construction/shared/{dtos,events,ports,vector-spec}.md` · `shared/`(동결 계약)
**원칙**: 이 단계는 **기술 무관(technology-agnostic)** — 비즈니스 로직·도메인 모델·비즈니스 규칙만 설계한다. 임베딩/벡터 스토어/랭킹 모델/언어·런타임 등 구체 기술과 수치형 NFR(P50<3s 등)은 **NFR Requirements/Infra Design**에서 확정. (성능·스택 고도 항목은 본 단계로 끌어오지 않는다.)
**프로덕션 직행**: U1과 동일하게 데모 트랙 폐기 — 단일 프로덕션 트랙으로 설계한다.
**Track 3 mock-first**: U2는 **mock 선행** 유닛이다. **FD는 U2의 실(real) 읽기 경로 비즈니스 로직을 설계**하고, mock은 동일 `SearchResponse` 계약(`shared/dtos`)을 충족하는 **Code Generation 단계의 교체 가능한 어댑터 구현**이다(아래 §3 AS-3, §4 Q8/Q9). FD 산출물 자체는 mock/real 무관.

---

## 1. 유닛 컨텍스트 (Step 1 — Analyze Unit Context)

- **책임**: 자연어 질의에 대한 **동기 검색 읽기 경로**(질의 검증/정규화 → 이해·확장 → 하이브리드 검색 → 랭킹 → 근거화 어댑팅 → 결과 조립)의 도메인 주체. 배포 ① API의 **모듈**(독립 앱 아님; app-shell·게이트웨이는 U6/@ELSAPHABA 조율 존). 성공 응답 후 `SearchExecutedEvent` 발행(FR-10 이력 생산자, 비차단).
- **스토리(Owner)**: **US-D1**(자연어 질의 입력) · **US-D2**(시맨틱 검색) · **US-D3**(상위 N 랭킹) · **US-D4**(폰 카드 조립) · **US-D6**(기권). **기여**: US-D5(근거화 어댑터)·US-D7(저하/상태 표면)·US-R1/R2(할루시네이션·반쪽짜리 폴백)·US-H1(히어로 백킹)·US-L3(SearchExecuted 생산).
- **컴포넌트(7, component-methods.md 잠금)**: `QueryIntakeController` · `QueryValidator` · `QueryUnderstandingExpander` · `HybridRetriever` · `RelevanceRanker` · `GroundingAdapter`(얇은 어댑터) · `ResultAssembler`.
- **서비스(1)**: `SearchOrchestrationService` — 동기 순차 파이프라인 조정(`executeSearch`) + `publishSearchExecuted`(비차단 이벤트).
- **capability 어댑터 이음새(mock 교체 지점, component-dependency.md §2)**: `VectorStoreAdapter`(ANN 벡터 검색) · `LexicalIndexAdapter`(BM25 lexical·하이브리드/저하 폴백) · `LlmGatewayAdapter`(질의 임베딩 생성·LLM 질의 확장·선택적 리랭킹 — U6 게이트웨이 경유). **이 셋이 mock-first에서 mock↔real로 교체되는 포트**(§4 Q9). 실 스토어=OpenSearch·임베딩=Bedrock Cohere는 NFR/Infra 확정이며 FD는 어댑터 경계만 정의(기술 무관).
- **공유 계약(소비, 동결/잠금)**:
  - `shared/vector-spec`(🔒FROZEN, **reader**) — 질의 임베딩이 U1 writer와 **동일 임베딩 공간**(Cohere Embed Multilingual v4·1024·코사인·**inputType 비대칭: reader=`search_query`**; v3→v4 마이그레이션 완료 2026-06-24, 정합 정정 2026-06-30). **cross-lingual 시스템 결정(TD-3)**: 사용자는 **한국어로 질의**하고 **영어 arXiv 코퍼스**를 검색한다(KR↔EN 동일 공간). → 질의 임베딩은 reader=`search_query`로 호출, **QT-2 관련도 평가셋에 한국어 질의 포함**이 필수(검증 표면).
  - `shared/dtos/search`(🟡PROVISIONAL, 카드 FROZEN-인접, **생산**) — `SearchRequest`/`SearchResponse` union(성공/기권/저하/검증오류) + `ResultCardVM` 7필드.
  - `shared/events/search-executed`(🔒FROZEN, **생산**) — `SearchExecutedEvent` → U4.
  - `shared/ports`(**의존**) — `GroundingEnforcementHook.enforce`(🔒, U6 호출), `CostGuardCircuitBreaker.getBudgetState`(🔒, U2 조회), `ObservabilityHub.emit*`. **U2는 근거화·비용을 재구현하지 않는다**(단일 권위 = U6).
- **핵심 트레이스**: FR-1, FR-2, FR-3, FR-4, FR-5, FR-11, NFR-P1(정책만), NFR-C1(저하 분기), NFR-R2(우아한 저하), NFR-U1/U2(폰 카드), SEC-5(입력 검증), SEC-8(인가 — 게이트웨이/U3 위임), SEC-9(내부 필드 비노출), SEC-15(fail-closed), QT-2(관련도 평가셋 출력 표면), QT-3(저하 폴백), QT-4/**PBT-02·03·07·09**(blocking), US-D1..D7.

---

## 2. Functional Design 실행 계획 (Step 2 — 답변 확정 후 수행, 체크박스)

> 산출물은 모두 `aidlc-docs/construction/u2-discovery/functional-design/` 에 생성한다. **§4 답변 확정 전에는 생성하지 않는다.** (U2는 백엔드 모듈 — `frontend-components.md`는 U5 FD 루프 산출물이며 본 계획 범위 밖.)

- [x] **domain-entities.md** — U2 도메인 엔티티·관계(기술 무관). **잠긴 U2 시그니처(component-methods.md)에 대해 망라적**:
  - 입력/검증: `SearchRequest{query, options?}`, `RequestContext{authSession, degradationSignal, requestId}`, `ValidationResult{ok, reason?}`, `NormalizedQuery{text}`.
  - 질의 계획: `QueryPlan{embeddingVector?, lexicalTerms, filterHints?, mode}`, `DegradationSignal{llmEnabled, rerankEnabled}`(getBudgetState 파생).
  - 검색/랭킹: `CandidateSet{candidates[], retrievalMode}`, `Candidate`(실재 IndexRecord 참조 — FR-5 사전조건), `RankedResults{ranked[], rankingMode}`.
  - 근거화 경계: `GroundingInput{candidateResponse, retrievedRecords}`, `GroundingDecision{verdict, violations[]}`(포트 타입 — U6 소유, 참조), `GroundedResults{items[]}`, `AbstainResult{reason}`.
  - 출력 DTO: `SearchResponse` union(`SearchResultPageDTO{cards, meta}`·`AbstainDTO`·`DegradedResultDTO`·`ValidationErrorDTO`), `ResultCardVM`(§dtos 7필드), `ResultMeta{resultCount, degraded, degradationMode?}`.
  - 값타입: `PaperId`(버전 없는)·`ArxivId`(표시용)·`relevance`(표시 파생값) — `shared/` 횡단 규약 정합.
  - **`shared/dtos`·`vector-spec`·`ports` 타입과 1:1 정합**을 명시(드리프트 0); U2 고유 도메인 타입과 공유 계약 타입의 경계 표기.
- [x] **business-logic-model.md** — `SearchOrchestrationService` 동기 순차 파이프라인 + 7 컴포넌트 알고리즘 수준 설계:
  - 흐름: `normalize → expand(공유 VectorSpec) → retrieve(하이브리드 병합·디덥) → rank(상위 N) → [U6 게이트웨이 post-handler가 enforce] → mapDecision → assemble`.
  - **근거화 invocation 경계 명시**(INV-1): U2는 `toGroundingInput`/`mapDecision`만, enforce 호출은 U6 게이트웨이.
  - **저하 분기**(§4 Q6): `getBudgetState().degradeMode`에 따른 단계 스킵 매트릭스(LLM 확장·리랭킹 on/off → lexical 폴백).
  - **이벤트 경로**(비차단): 성공 후 `publishSearchExecuted(userId, requestId, query, timestamp, resultCount)` — 응답 경로 밖(§4 Q11; `requestId`=U4 멱등 디덥 키 — FROZEN `events.md` 시그니처 정합 2026-06-30).
  - 단계별 타임아웃·폴백 **정책 형태(shape)만**(수치는 NFR, AS-2).
- [x] **business-rules.md** — 결정 규칙·검증·제약:
  - 질의 검증/정규화 규칙(§4 Q7; FR-1/SEC-5/PBT-02 결정성).
  - 하이브리드 병합·디덥 규칙(§4 Q2; PBT-07 paperId 단위 멱등·결과셋 보존).
  - 랭킹·상위 N 절단·`relevance` 표시값 규칙(§4 Q3/Q10; FR-3/SEC-9 raw 점수 비노출).
  - **종단 상태(SearchResponse union) 결정 규칙**(§4 Q4; FR-11) — 성공/기권/저하/검증오류 경계, **기권 vs 빈 결과** 구분(US-D6 vs US-D7), 기권 우선 규칙.
  - 근거화 verdict 매핑 규칙(pass→결과, abstain/block→기권; US-D5/D6).
  - 인가/인증 전제(§4 Q5; SEC-8 — 게이트웨이 authn·U3 위임, U2는 ctx 신뢰).
  - SEC-9 비노출(INV-2)·fail-closed 전역 에러(INV-3, SEC-15).
- [x] **PBT 속성 식별(QT-4 / blocking PBT-02·03·07·09)** — 테스트 가능 속성 명문화:
  - **PBT-02**: `normalize` 멱등/라운드트립(동일 입력→동일 NormalizedQuery, 재정규화 불변).
  - **PBT-03**: 랭킹 순서 안정성 + 상위 N 절단(점수 동률 안정 정렬, N 미만 시 가용분만).
  - **PBT-07**: 하이브리드 디덥 멱등(paperId 단위 중복 0) + 결과셋 보존(병합이 후보를 조용히 누락/복제하지 않음).
  - **PBT-09**: `SearchResponse` DTO 라운드트립(4개 종단 상태 직렬화/역직렬화 보존, 내부 필드 비노출 유지).
- [x] **추적성 매트릭스** — U2 컴포넌트/규칙/속성 → 요구사항 ID 역추적(미커버 0 검증).
- [x] **공유 계약 정합 주석** — VectorSpec 동일 공간 불변식(reader), dtos/events/ports 형상 정합, **단일 근거화 권위(U6)·단일 비용 권위(U6)** 재인용.

---

## 3. 가정 (명시 — 잘못이면 §4 또는 별도 지적으로 정정 요청)

- **AS-1**: 본 단계는 코드 미생성. 산출물은 설계 문서뿐이며 기술 스택·수치 결정 없음.
- **AS-2**: 수치형 NFR(NFR-P1 P50<3s/P95<8s, 타임아웃·동시성, NFR-C1 비용 임계/티어 수치)의 **정책 형태**만 여기서 정하고 **확정 수치는 NFR/Infra Design**에서 검증·고정.
- **AS-3 (mock-first)**: U2가 의존하는 **벡터/lexical 인덱스·임베딩 게이트웨이·근거화 후크·비용 후크**는 포트/capability 추상 뒤에 있다. mock(고정 픽스처 어댑터·스텁 후크)과 real 어댑터는 **Code Generation 단계의 교체 가능한 구현**이며 FD 비즈니스 로직은 동일(§4 Q8/Q9).
- **AS-4**: 근거화 강제(enforce)·비용 누적/서킷 판정·관측성 수집은 **U6 소관**(`shared/ports`). U2 FD는 그 포트에 대한 **소비 계약(입력 정형·verdict 매핑·저하 분기·emit 제출)** 만 설계한다. U6 FD 미완으로 ports는 PROVISIONAL(단 `enforce`/`getBudgetState` 시그니처는 FROZEN).
- **AS-5**: QT-1(근거화)·QT-2(관련도) **평가셋 구축**은 U6/OP 산출물(QT-1)·평가 표면(QT-2). U2는 RelevanceRanker 출력을 QT-2 평가셋이 측정할 수 있는 **표면**으로 제공하는 책임만 진다.

---

## 4. 명확화 질문 (Step 3 — `[Answer]:` 태그로 답변; 미답 시 진행 불가)

> 답변 방법: 각 질문의 `**[Answer]**:` 뒤에 **A/B/C/D** 중 하나(또는 **E = 기타: 직접 기술**). 모호한 답("상황에 따라", "섞어서" 등)에는 후속 질문을 추가한다(규칙 Step 5). overconfidence-prevention 원칙에 따라 카테고리를 빠짐없이 질의한다.

### A. 비즈니스 로직 모델링 · 데이터 흐름

**Q1 — 질의 이해/확장(`expand`) 범위.** `QueryUnderstandingExpander`가 NormalizedQuery를 무엇으로 확장하나?
- A) **임베딩 벡터(공유 VectorSpec) + lexical 텀(토큰화)** — 동의어/LLM 재작성 없음. (권장)
- B) A + **규칙 기반 동의어/약어 확장**(예: "LLM"↔"large language model") — 결정적, lexical 재현율↑.
- C) A + **LLM 기반 질의 재작성** — 재현율↑이나 비용·레이턴시·비결정성↑.
- D) 설정 가능(기본 A).
- **권장**: A — FD 결정성(PBT-02)·NFR-C1 비용 경계. LLM 확장은 cost-circuit 'LLM off' 폴백 대상이라 기본 비활성이 일관(Q6 저하 매트릭스와 연동). C 채택 시 degradeMode·근거화(날조 위험) 영향 동반 검토.
- **[Answer]**: A

**Q2 — 하이브리드 후보 병합·디덥 전략(`retrieve`, PBT-07).** 벡터+lexical 후보를 어떻게 병합·디덥?
- A) **Reciprocal Rank Fusion(RRF)** — 점수 스케일 무관·견고(두 랭킹의 순위만 사용). 디덥은 **paperId(버전 없는) 단위 최상위 1건 축약**. (권장)
- B) **가중 점수 정규화 합**(vector·lexical 정규화 후 가중합) — 튜닝 여지↑·스케일 민감.
- C) **벡터 우선, lexical은 저하 모드 폴백/보강만**.
- D) 기타.
- **권장**: A — U1이 전문 다중 청킹(Q2=C)이라 같은 논문이 복수 청크로 잡힘 → **paperId 단위 디덥**으로 멱등·결과셋 보존(PBT-07). 구체 파라미터/가중치는 NFR. 저하 시 lexical-only 거동은 Q6.
- **[Answer]**: A

**Q3 — 랭킹 기준 + 카드 `relevance` 표시값(`rank`, FR-3/QT-2/SEC-9).**
- A) **정렬 = 병합 점수 내림차순**; 카드 `relevance` = **순위 파생 비-raw 신호**(raw 점수 비노출, SEC-9); **LLM 리랭킹 없음(baseline)**. (권장)
- B) A + **cost-circuit 'rerank on'일 때만 LLM 리랭킹**(off 시 baseline 폴백, US-R3).
- C) raw 유사도 점수를 카드에 직접 노출.
- **권장**: A — SEC-9(내부 점수 비노출)·결정성·비용 경계. B는 degradeMode 분기를 추가(채택 시 baseline 폴백 규칙 정의). C는 SEC-9 위반(배제). `relevance`의 구체 표시 형태(등급/별점/퍼센트)는 U5 UI 연동 — FD에선 "순위 파생 비-raw"로 의미만 고정.
- **[Answer]**: A

### B. 도메인 모델 · 종단 상태

**Q4 — 종단 상태(`SearchResponse` union) 결정 규칙 + 기권 vs 빈 결과(FR-11/US-D6/US-D7).**
- A) **성공**(verdict=pass & 결과≥1) · **기권**(verdict=abstain/block **또는 후보 0/무매치**) · **저하**(degradeMode 활성 & 결과 반환) · **검증오류**(입력 검증 실패). **빈 cards 성공 페이지는 만들지 않음**(조용한 빈 결과 금지). degradeMode 중에도 verdict=abstain이면 **기권 우선**(날조 금지 최우선). (권장)
- B) 후보 0 = **빈 성공**(cards=[]); 기권은 verdict=abstain만.
- C) 기타.
- **권장**: A — US-D6("관련 논문 없음")과 US-D7(저하)을 명확히 분리하고, 무매치를 빈 페이지가 아닌 기권으로 통일(매직 모먼트 신뢰성). B는 빈 성공/기권 경계가 흐려짐.
- **[Answer]**: A

**Q5 — 검색 엔드포인트 인증 요구(SEC-8).** `POST /api/search`는 인증 필요?
- A) **인증 필요**(deny-by-default, SEC-8) — `ctx.authSession`의 userId로 SearchExecuted 발행(FR-10). 미인증은 U6 게이트웨이에서 401(U2는 ctx 신뢰). (권장)
- B) **공개(익명 검색 허용)** — userId 없는(또는 미발행) SearchExecuted.
- C) 기타.
- **권장**: A — SEC-8 deny-by-default·US-H1(가입→검색)·FR-10 이력은 owner 필요. authn 강제는 U6 게이트웨이 소관(U2는 컨텍스트 신뢰). B는 FR-10 이력이 약화됨.
- **[Answer]**: A

### C. 비즈니스 규칙

**Q6 — 저하(degrade) 모드 매트릭스(NFR-C1/R2, US-R2/R3).** `getBudgetState().degradeMode` 단계별 U2 거동?
- A) **2단계**: (1) `rerank off` → LLM 리랭킹만 생략, 임베딩 검색 유지(baseline 랭킹); (2) `LLM off` → expand의 LLM/확장 생략 + lexical-only 검색·baseline 랭킹. 둘 다 **DegradedResultDTO + 사유**. (권장)
- B) **단일 토글**(저하 = lexical-only 전체).
- C) 기타.
- **권장**: A — `BudgetState{tier,degradeMode,circuitState}`와 정합, NFR-C1 "리랭킹 비활성→lexical 폴백" 계단을 그대로 반영(가장 싼 단계부터 차단). 임베딩 검색 자체는 저비용이면 유지. 정확 임계/티어 수치는 NFR. Q1/Q3 선택과 연동.
- **[Answer]**: A

**Q7 — 질의 검증·정규화 규칙(FR-1/SEC-5, PBT-02).**
- A) **검증**: 트림 후 1자 이상·≤500자·제어문자/널 거부·과도 공백 정리. **정규화**: 트림 + 공백 collapse + **유니코드 NFC** → 결정적(PBT-02 멱등). **한국어 포함 다국어 질의 허용 필수**(cross-lingual=시스템 결정 TD-3 — 한국어 질의로 영어 코퍼스 검색). (권장)
- B) A + **허용 문자 allowlist**(특정 스크립트만).
- C) 기타.
- **권장**: A — SEC-5(길이·새니타이즈)·PBT-02(normalize 라운드트립 멱등). **B는 채택 불가에 가까움** — cross-lingual(한국어 질의) 시스템 결정상 스크립트 allowlist는 한국어/혼합 질의를 막아 핵심 기능을 깨뜨림. 길이·제어문자 위주 검증으로 한정. NFC vs NFKC는 한글 자모 결합 고려해 domain-rules에 명시(권장 NFC).
- **[Answer]**: A

### D. 통합 지점 · 병렬 개발(mock-first) · 에러 처리

**Q8 — U6 후크 부재 중 U2 개발/검증(Track 3 병렬).** U6(`GroundingEnforcementHook`·`CostGuardCircuitBreaker`) 미구현 동안?
- A) **`shared/ports`에 대한 테스트 스텁**: 근거화 = pass-through(verdict=pass) 기본 + abstain 강제 케이스, 비용 = 정상 티어 `BudgetState` 스텁. U2는 포트에만 의존(주입), U6 완성 시 실구현 교체. (권장)
- B) U6 완성까지 근거화/저하 분기 개발 보류.
- C) 기타.
- **권장**: A — 의존성 역전(ports) 그대로 활용, 트랙 병렬성 유지. 스텁은 **테스트 전용**, 실 강제는 U6 단일 권위(INV-1 불변).
- **[Answer]**: A

**Q9 — capability 어댑터 mock(mock-first 본체).** `VectorStoreAdapter`·`LexicalIndexAdapter`·`LlmGatewayAdapter`(§1 이음새)가 (U1 코퍼스·OpenSearch·Bedrock 준비 전) 없을 때?
- A) **세 어댑터의 고정 픽스처 mock 구현**(샘플 IndexRecord 집합 + 결정적 가짜 ANN/BM25/임베딩) — `SearchResponse` 계약 충족, U5 병렬 개발 가능. 실 어댑터(OpenSearch·Bedrock Cohere)는 NFR/Infra·U1 코퍼스 후 교체. **픽스처에 QT-2 평가셋 논문 + 한국어↔영어 cross-lingual 케이스 포함**(U1 Q14=A·TD-3 연동). (권장)
- B) U1 코퍼스·실 인덱스 준비까지 U2 보류(병렬성 포기).
- C) 기타.
- **권장**: A — Track 3 mock-first의 핵심. FD는 세 어댑터 경계(포트)만 정의하고 mock/real은 교체 가능 구현(기술 무관). U5가 mock U2로 선행 개발하는 project-structure §4 전략과 일관.
- **[Answer]**: A

**Q10 — 상위 N 기본값(FR-3).**
- A) **20**(FR-3 제안). (권장)
- B) 다른 값(기술).
- **권장**: A.
- **[Answer]**: A

**Q11 — SearchExecuted 발행 실패 격리(FR-10/NFR-P1).** 성공 응답 후 이벤트 발행이 실패하면?
- A) **fire-and-forget, 비차단** — 발행 실패는 검색 응답에 영향 없음(관측성 로그만), 응답 경로 밖. (권장)
- B) 발행 보장(실패 시 재시도/아웃박스).
- **권장**: A — services.md(비차단·P50<3s 경로 밖)·이력은 best-effort. 보장 강화(아웃박스)는 이벤트 백본/U4 NFR 소관.
- **[Answer]**: A

---

## 5. 결정된 불변식 (질문 아님 — 명백한 정답, 투명성 위해 명시; 이견 시 지적)

- **INV-1 (단일 근거화 게이트, FR-5)**: U2는 `enforce`를 **호출하지 않는다**. 유일 invocation site = U6 게이트웨이 응답 엣지(post-handler). U2는 `GroundingAdapter.toGroundingInput`(입력 정형)·`mapDecision`(verdict→결과/기권 매핑)만 수행 — 독자 차단·인시던트 발행 없음.
- **INV-2 (SEC-9 내부 필드 비노출)**: 카드는 `dtos.md §1.1`의 7필드(`title·authors·year·arxivId·abstractSnippet·relevance·arxivUrl`)만. raw 점수·`vector`·`lexicalTerms`·`chunkId`·`section`·소유자·디버그·타이밍은 외부 DTO 비노출.
- **INV-3 (fail-closed, SEC-15/FR-11)**: 처리 중 예외는 전역 에러 핸들러가 **일반화 비기술 에러**로 매핑(스택/내부 식별자 비노출), 권한·검증을 우회하지 않음. 빈 화면/스택 트레이스 금지.

---

## 6. 다음 절차

1. `§4`의 `[Answer]:` 태그를 채운다(또는 채팅으로 A/B/C/D/E 회신). `§5` INV는 이견 시에만 지적.
2. 모호 답변 발견 시 후속 명확화 질문 추가(규칙 Step 5) — 해소 전 진행 불가.
3. 답변 확정 → `§2` 산출물 생성(`u2-discovery/functional-design/` 의 domain-entities·business-logic-model·business-rules + PBT 속성·추적성·정합 주석).
4. 완료 메시지 + 리뷰 게이트 → 승인 시 다음 단계(**U2 NFR Requirements** — 기술 스택은 §5-A=Python 계승, 검색/랭킹/임베딩 어댑터·mock 전략 확정).

> 본 계획·질문은 **리뷰 게이트**입니다. 답변 전까지 Functional Design 산출물을 생성하지 않으며, 아직 커밋하지 않았습니다.
