# business-logic-model.md — U2 Discovery 비즈니스 로직 모델 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: 계획서(§4 답변 전부 A) · `application-design/{component-methods,services,component-dependency}.md` · `shared/{dtos,ports,vector-spec,events}.md`
**원칙**: 기술 무관 알고리즘 수준. 타임아웃·동시성 수치, RRF 가중치/k, 임베딩·스토어 구현은 NFR/Infra. FD는 단계·변환·분기·계약만.
**고도**: NFR-P1(P50<3s) 동기 경로의 **정책 형태(shape)만** — 확정 수치는 NFR Requirements(AS-2).

---

## 1. 서비스 오케스트레이션 — `SearchOrchestrationService` (동기 순차)

U2 동기 읽기 경로의 단일 도메인 오케스트레이터. 요청→응답 파이프라인을 순차 조정하고, 성공 후 이력 이벤트를 비차단 발행한다.

### 1.1 `executeSearch` 파이프라인 (FR-1..5, FR-11, NFR-P1)

```
입력: SearchRequest{query}, RequestContext{authSession, degradationSignal, requestId, personalizationDecision}
출력: SearchResponse (4 종단 상태 중 하나)

1. validate/normalize  (QueryValidator)
   └─ ok=false → ValidationErrorDTO 반환 (업스트림 미전송, fail-closed) ── 종료
2. degradation 파생     (RequestContext.degradationSignal ← BudgetState.degradeMode)
   └─ DegradationSignal{llmEnabled, rerankEnabled} 계산
3. expand               (QueryUnderstandingExpander)  — Q1=A
   ├─ llmEnabled=true  → QueryPlan{embeddingVector(search_query, cross-lingual) + lexicalTerms, mode=hybrid, scope}
   └─ llmEnabled=false → QueryPlan{lexicalTerms, mode=lexical-only, scope}  (임베딩 생략, 저하)
   · scope ← SearchRequest.scope (lite 기본 | full). 저하 여부와 독립.
4. retrieve             (HybridRetriever)  — Q2=A
   ├─ hybrid      → 벡터 ANN + lexical BM25 후보 → RRF 병합 → PaperId 단위 디덥
   │   · **scope=lite**(사람 검색창, P50<3s): ANN=**초록 chunk 한정**(section=abstract, 논문당 1벡터) · BM25=**title+abstract**. 교차언어 유지(벡터 살림), 본문 미검색.
   │   · **scope=full**(문헌·근거 에이전트 / "본문까지 검색" 토글): ANN=**전체 chunk** · BM25=**title+abstract+lexicalTerms**(본문 포함). 고recall.
   └─ lexical-only→ lexical BM25 후보만 (저하 폴백; scope의 BM25 필드 규칙은 동일 적용)
   └─ 후보 0 → NoMatchResult로 종단 (명시적 빈 페이지 resultCount=0 — abstain 아님)
5. rank                 (RelevanceRanker)  — Q3=A, Q10=A
   └─ 병합 점수에 personalizationDecision.searchBoosts 가산 → 내림차순 · 상위 N=20 절단 · LLM 리랭킹 없음 · 안정 정렬(PBT-03)
6. toGroundingInput     (GroundingAdapter)  — INV-1
   └─ RankedResults + retrievedRecords → GroundingInput 정형화 (enforce 호출 안 함)
   ▼ [U6 게이트웨이 post-handler: GroundingEnforcementHook.enforce → GroundingDecision]
7. mapDecision          (GroundingAdapter)  — Q4=A
   ├─ verdict=pass         → GroundedResults
   └─ verdict=abstain|block→ AbstainResult
8. assemble             (ResultAssembler)  — FR-4, FR-11, SEC-9, PBT-09
   └─ GroundedResults → SearchResultPageDTO | (degradeMode 활성 시) DegradedResultDTO
   └─ AbstainResult   → AbstainDTO
9. (응답 후, 비차단)     publishSearchExecuted(userId, requestId, query, timestamp, resultCount)  — Q11=A
```

### 1.2 근거화 invocation 경계 (INV-1)
- **U2는 `enforce`를 직접 호출하지 않는다.** 유일 invocation site = **U6.GatewayPipelineService가 U2 라우트 응답 엣지(post-handler)에서 단일 적용.**
- U2 역할: `toGroundingInput`(입력 정형) + `mapDecision`(verdict→결과/기권 매핑). 독자 차단·인시던트 발행 없음(할루시네이션 인시던트 발행은 U6 단독).
- **개발/테스트 시점**(Q8=A): U6 미완 동안 U2는 `shared/ports`의 **테스트 스텁**(pass-through verdict=pass 기본 + abstain 강제 케이스)으로 검증. 실 강제는 U6 교체.

### 1.3 이벤트 경로 (Q11=A — 비차단)
- 성공(또는 결과 반환) 응답 **후** `publishSearchExecuted(userId, requestId, query, timestamp, resultCount)` 발행 → 이벤트 백본 → U4 이력.
- **fire-and-forget**: 발행 실패는 검색 응답에 영향 없음(관측성 로그만). NFR-P1 P50<3s 경로 **밖**.
- `userId`는 `RequestContext.authSession` 출처(Q5=A 인증 필수).

---

## 2. 저하(degrade) 분기 매트릭스 (Q6=A — NFR-C1/R2, US-R2/R3)

`getBudgetState().degradeMode`(U6 단일 권위 조회 — U2 독자 판정 없음)에 따른 단계 거동:

| degradeMode | DegradationSignal | expand | retrieve | rank | 출력 |
|---|---|---|---|---|---|
| `NORMAL` | llmEnabled=true, rerankEnabled=true | 임베딩(search_query)+lexical | hybrid(RRF) | baseline 상위 N | SearchResultPageDTO |
| `RERANK_OFF` | rerankEnabled=false | 동일 | hybrid | baseline 상위 N | **DegradedResultDTO**(mode=RERANK_OFF) |
| `LEXICAL_ONLY` | llmEnabled=false | **임베딩 생략** | **lexical-only(BM25)** | baseline 상위 N | **DegradedResultDTO**(mode=LEXICAL_ONLY) |

> **Q1=A/Q3=A 정합 주석**: U2 baseline은 **LLM 질의 재작성 없음(Q1=A)·LLM 리랭킹 없음(Q3=A)**이다. 따라서 `RERANK_OFF` 단계는 U2에선 **동작 무변화**(이미 리랭킹 미사용)이나 `BudgetState` 계약상 노출되므로 그대로 표면화(저하 배너). **실효 저하**는 `LEXICAL_ONLY`(질의 임베딩 = U2 동기 경로의 주 비용 동인을 차단 → BM25 폴백)다. 임베딩 공간 자체는 불변(vector-spec.md §1).
> **저하 vs 기권 우선순위(Q4=A)**: degradeMode 활성 중에도 verdict=abstain/block이면 **기권(AbstainDTO) 우선**(날조 금지가 최우선) — 저하 카드를 내보내지 않는다.

---

## 3. 컴포넌트 알고리즘 수준 설계 (7 컴포넌트)

### 3.1 QueryIntakeController — `search(SearchRequest, RequestContext) -> SearchResponse`
동기 REST 진입(`POST /api/search`). 검증 위임 → 오케스트레이션 위임 → 종단 상태를 명시 DTO로 직렬화(HTTP 매핑은 API Design). 전역 fail-close(INV-3).

### 3.2 QueryValidator — `validate` / `normalize` (Q7=A, FR-1/SEC-5)
- `validate`: 트림 후 1자 이상·≤500자·제어문자/널 거부·과도 공백 정리. 실패 시 구조화 ValidationResult.
- `normalize`: 트림 + 공백 collapse + **유니코드 NFC** → 결정적(**PBT-02 멱등**: `normalize(normalize(q)) == normalize(q)`). **한국어 포함 다국어 허용**(스크립트 allowlist 없음 — cross-lingual 보호).

### 3.3 QueryUnderstandingExpander — `expand(NormalizedQuery, DegradationSignal) -> QueryPlan` (Q1=A)
- 임베딩 벡터 생성(공유 VectorSpec, **reader=`search_query`**, cross-lingual KR↔EN) + lexical 텀(토큰화). **동의어/LLM 재작성 없음**(결정성·비용).
- `llmEnabled=false` → 임베딩 생략, `mode=lexical-only`. 호출 타임아웃·실패 전파(RES-9, 수치 NFR).

### 3.4 HybridRetriever — `retrieve(QueryPlan, DegradationSignal) -> CandidateSet` (Q2=A, PBT-07)
- 벡터 ANN + lexical BM25 후보 검색 → **RRF(Reciprocal Rank Fusion) 병합**(점수 스케일 무관) → **PaperId 단위 디덥**(같은 논문 복수 청크 → 최상위 1건).
- **멱등·결과셋 보존(PBT-07)**: 동일 입력→동일 후보 집합(중복 0, 조용한 누락 0).
- 각 후보는 **실재 IndexRecord 참조 보유**(FR-5 사전조건). `lexical-only` 시 BM25 후보만. 타임아웃·서킷 존중(RES-9).
- RRF 파라미터(k·가중)는 NFR/튜닝.

### 3.5 RelevanceRanker — `rank(CandidateSet, QueryPlan, DegradationSignal, topN, PersonalizationDecision?) -> RankedResults` (Q3=A, Q10=A, PBT-03)
- 병합 점수 산출 후, 전달된 `PersonalizationDecision`이 존재하고 `enabled=true`인 경우, 각 후보의 카테고리/키워드에 매칭되는 `searchBoosts`를 **기본 적합성 점수에 가산(additive)** 방식으로 적용한다.
- **개인화 제약 준수(FR-20)**: U9가 강제하는 boost magnitude bounds(최대 총합 0.2 등)를 신뢰하여, 상위 30% 이내 후보 간의 미세 순위 변동만 발생하도록 가중치를 흡수한다.
- 병합+부스트 조정 점수 기준 내림차순 정렬 → **상위 N=20 절단**(N 미만이면 가용분만, US-D3). **LLM 리랭킹 없음(baseline)**.
- **순서 안정성(PBT-03)**: 동률 안정 정렬, 동일 입력→동일 순서. **QT-2 관련도 평가셋 출력 표면**(한국어 질의 포함 — TD-3). raw 점수 비노출(SEC-9).

### 3.6 GroundingAdapter — `toGroundingInput` / `mapDecision` (INV-1, Q4=A, FR-5)
- `toGroundingInput(RankedResults, QueryPlan) -> GroundingInput{candidateResponse, retrievedRecords}`: U6 enforce 입력 정형(독자 검사 없음).
- `mapDecision(GroundingDecision) -> GroundedResults | AbstainResult`: pass→결과, abstain/block→기권. **enforce 호출은 U6 게이트웨이**.

### 3.7 ResultAssembler — `assemble(GroundedResults | AbstainResult, DegradationSignal) -> SearchResponse` (FR-4/11, SEC-9, PBT-09)
- **근거화 구조적 방어(GroundingStructuralGuard)** *(2026-06-29 개정 — 페이즈 2/Q2)*: U6 게이트웨이의 1차 근거화 후크가 우회되거나 실패할 경우를 대비한 2차(Defense-in-Depth) 구조적 방어 기제로, 모든 조립된 `ResultCardVM`이 알려진 `IndexRecord`의 식별자(`paperId` + 소스 식별자)로 해석 가능한 **소스 중립 실재 링크**(arXiv=`arxivUrl`, 비-arXiv=`sourceUrl`/DOI)를 갖는지 런타임에 확인한다. 위반 카드는 **드롭**하여 근거 없는 카드를 노출하지 않으며(card-level Fail-Closed), 잔여를 1..N로 재랭킹한다; **전량 드롭 시** 명시적 빈 페이지(resultCount=0, BR-9)로 종단한다(abstain 아님) — 단일 불량 레코드가 페이지 전체를 침몰시키지 않는다. (arXiv-only `arxivUrl` 단일 검사는 비-arXiv 카드를 오탈락시키므로 소스 중립으로 일반화.)
- GroundedResults(≥1) → 카드 DTO 매핑(§domain-entities §5.1; 페이즈 2: 소스 중립 `sourceName`/`sourceUrl` 포함) + ResultMeta(건수·degraded·mode). degradeMode 활성 시 DegradedResultDTO.
- NoMatchResult(또는 GroundedResults 빈 items) → SearchResultPageDTO(cards=[], resultCount=0) — 명시적 빈 페이지(배너 없음).
- AbstainResult → AbstainDTO(근거화 거부 전용). 폰 우선 직렬화(NFR-U1). **내부 점수·디버그 비노출(SEC-9)**. **DTO 라운드트립(PBT-09)**.
- **무매치 = 명시적 빈 페이지**(개정): 후보 0/무매치는 §1에서 NoMatchResult로 종단 → count:0 명시. abstain(근거화 거부)과 구분(U5 B3-a). "조용한 결과 금지"는 count:0 명시로 충족.

---

## 4. 종단 상태 결정 (FR-11)

```
검증 실패            → ValidationErrorDTO   (fail-closed, SEC-15)
verdict=abstain|block → AbstainDTO          (기권 — 근거화 거부, 날조 0건, 우선순위 최상)
후보 0 / 무매치       → SearchResultPageDTO  (cards=[], resultCount=0 — 명시적 빈 페이지; abstain 아님, U5 B3-a)
verdict=pass & 결과≥1 & degradeMode=NORMAL → SearchResultPageDTO
verdict=pass & 결과≥1 & degradeMode≠NORMAL → DegradedResultDTO (mode 표면화)
처리 중 예외          → 전역 핸들러 → 일반화 에러 (INV-3, 스택/내부 비노출)
```

---

## 5. 병렬 개발(mock-first) 경계 (Q8=A / Q9=A — Track 3)

- **capability 어댑터 mock(Q9=A)**: `VectorStoreAdapter`(ANN)·`LexicalIndexAdapter`(BM25)·`LlmGatewayAdapter`(임베딩/확장)를 **고정 픽스처 mock**으로 구현 — 결정적 가짜 검색/임베딩, `SearchResponse` 계약 충족. **픽스처에 QT-2 평가셋 + 한국어↔영어 cross-lingual 케이스 포함.** 실 어댑터(OpenSearch·Bedrock Cohere)는 NFR/Infra·U1 코퍼스 후 교체.
- **포트 스텁(Q8=A)**: `GroundingEnforcementHook`=pass-through(verdict=pass) 기본 + abstain 강제 케이스; `CostGuardCircuitBreaker.getBudgetState`=정상 티어(NORMAL) 스텁. U2는 포트에만 의존(주입).
- **U5 병렬**: U5는 U2 mock 응답(동일 `shared/dtos` 계약)으로 선행 개발(project-structure §4).
- **계약 안정성**: mock↔real 교체는 FD 비즈니스 로직·DTO 계약을 바꾸지 않는다(기술 무관 경계).

---

## 6. 관측성 · fail-closed (NFR-O1 / SEC-15)
- 각 단계 지연·검색/근거화 건강도·degradeMode를 `ObservabilityHub.emit*`로 제출(requestId 상관, PII/시크릿 금지 SEC-3).
- **INV-3 fail-closed**: 모든 외부 어댑터 호출(retrieve/expand)은 타임아웃·서킷(RES-9, 수치 NFR); 예외는 전역 핸들러가 일반화 에러로(스택/내부 식별자 비노출), 권한·검증 우회 없음.

> 엔티티 정의는 `domain-entities.md`, 규칙·PBT·추적성은 `business-rules.md`.
