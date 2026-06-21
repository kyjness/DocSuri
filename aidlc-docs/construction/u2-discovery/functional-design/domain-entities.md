# domain-entities.md — U2 Discovery 도메인 엔티티 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: 계획서(`u2-discovery-functional-design-plan.md`, §4 답변 전부 A) · `application-design/{components,component-methods,services,component-dependency}.md`(U2 시그니처 잠금) · `shared/{dtos,events,ports,vector-spec}.md`(소비 계약) · `requirements.md`
**원칙**: 기술 무관(엔티티 = 도메인 개념·관계·식별 규칙). 직렬화/저장/HTTP 매핑은 NFR/Infra/API Design. 구체 스토어(OpenSearch)·임베딩 모델(Cohere)·랭킹 알고리즘 파라미터는 NFR Requirements 소관.
**프로덕션 스코프**: 단일 프로덕션 트랙(데모 폐기). U2는 배포 ① API의 **모듈**(독립 앱 아님) — app-shell·게이트웨이는 U6/@ELSAPHABA 조율 존.
**cross-lingual(TD-3)**: 사용자는 **한국어로 질의**하고 **영어 arXiv 코퍼스**를 검색한다(KR↔EN 동일 임베딩 공간; reader=`search_query`).

---

## 1. 식별자 & 표시 값타입

| 엔티티 | 정의 | 규칙 |
|---|---|---|
| **PaperId** | 버전 없는 arXiv ID(예 `2401.01234`) | 정규 식별자. **하이브리드 디덥 키**(Q2=A: 한 논문의 여러 청크 후보를 1건으로 축약). vector-spec.md `paperId`와 동일. |
| **ArxivId** | 표시용 arXiv ID(버전 포함 가능, 예 `2401.01234v2`) | 카드 표시 전용(`ResultCardVM.arxivId`). 식별/디덥엔 PaperId 사용. |
| **ChunkId** | `chunkId(PaperId, ordinal)` (U1 소유, 내부) | **U2 외부 DTO 비노출(SEC-9)**. 후보 단계 내부 추적에만 사용(인덱스 문서 ID). |
| **Relevance** | **표시용 관련도 신호**(순위 파생) | **Q3=A**: 정렬 순위에서 파생한 비-raw 표시값. **내부 raw 점수/RRF 점수는 비노출(SEC-9)**. 구체 표시 형태(등급/별점/퍼센트)는 U5 UI 연동 — FD는 "순위 파생 비-raw"로 의미만 고정. |
| **DegradationMode** | enum `NORMAL` \| `RERANK_OFF` \| `LEXICAL_ONLY` | 저하 단계(Q6=A 2단계 + 정상). `BudgetState.degradeMode`에서 파생, `ResultMeta`/`DegradedResultDTO`에 표면화. |
| **GroundingVerdict** | enum `pass` \| `block` \| `abstain` | U6 `GroundingDecision.verdict`(포트 소유). U2는 매핑만. |

---

## 2. 입력 · 검증 엔티티 (FR-1 / SEC-5)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **SearchRequest** | `query: string`, `options?` | 동기 검색 진입 입력(`shared/dtos`). `query`는 FR-1/SEC-5 검증 대상. `options`는 잠정(타입 정제 시 확정). |
| **RequestContext** | `authSession`, `degradationSignal`, `requestId` | 게이트웨이(U6)가 주입. **Q5=A**: `authSession`은 인증 필수(deny-by-default) — userId 출처. `degradationSignal`은 비용 저하 신호. `requestId`는 관측성 상관 키. |
| **ValidationResult** | `ok: bool`, `reason?` | `QueryValidator.validate` 산출. ok=false → `ValidationErrorDTO`(fail-closed, SEC-15). |
| **NormalizedQuery** | `text: string` | `QueryValidator.normalize` 산출. **Q7=A**: 트림+공백 collapse+**유니코드 NFC**로 결정적(PBT-02 멱등). **한국어 포함 다국어 허용**(cross-lingual). |

---

## 3. 질의 계획 · 검색 · 랭킹 엔티티 (FR-2 / FR-3)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **DegradationSignal** | `llmEnabled: bool`, `rerankEnabled: bool` | `BudgetState`(U6 포트)에서 파생. **Q6=A**: `rerankEnabled=false`→LLM 리랭킹 생략(U2 baseline은 Q3=A로 이미 리랭킹 없음 → 사실상 무변화), `llmEnabled=false`→질의 임베딩 생략·lexical-only 폴백. |
| **QueryPlan** | `embeddingVector?`, `lexicalTerms`, `filterHints?`, `mode` | `QueryUnderstandingExpander.expand` 산출. **Q1=A**: `embeddingVector`=질의 임베딩(공유 VectorSpec, **reader=`search_query`**, cross-lingual)·`lexicalTerms`=질의 토큰화. **동의어/LLM 재작성 없음.** `mode`=hybrid \| lexical-only(저하 시). |
| **Candidate** | `paperId`, `arxivId`, **retrievedRecord 참조**(실재 IndexRecord), `retrievalScore`(내부) | 단일 후보. **FR-5 사전조건**: 실재 IndexRecord(해소 가능 arXiv ID/링크)에 매핑. `retrievalScore`는 **내부(SEC-9 비노출)**. |
| **CandidateSet** | `candidates[]`, `retrievalMode` | `HybridRetriever.retrieve` 산출. **Q2=A**: 벡터+lexical 후보를 **RRF 병합**, **PaperId 단위 디덥**(같은 논문 복수 청크→최상위 1건, PBT-07 멱등·결과셋 보존). `retrievalMode`=hybrid \| lexical-only. |
| **RankedResults** | `ranked[]`(순서 보존), `rankingMode` | `RelevanceRanker.rank` 산출. **Q3=A**: 병합 점수 내림차순·상위 N 절단(**Q10=A: N=20**), **LLM 리랭킹 없음(baseline)**. N 미만이면 가용분만(US-D3). `rankingMode`=baseline. 순서 안정성 PBT-03. |

---

## 4. 근거화 경계 엔티티 (FR-5 — U6 포트 정형/매핑만)

> **INV-1**: U2는 `GroundingEnforcementHook.enforce`를 **호출하지 않는다**. enforce는 U6 게이트웨이 응답 엣지(post-handler) 단일 invocation. U2.`GroundingAdapter`는 입력 정형(`toGroundingInput`)·verdict 매핑(`mapDecision`)만.

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **GroundingInput** | `candidateResponse`(RankedResults 정형), `retrievedRecords`(실재 IndexRecord 집합) | `GroundingAdapter.toGroundingInput(RankedResults, QueryPlan)` 산출 → U6 enforce 입력. |
| **GroundingDecision** | `verdict: pass\|block\|abstain`, `violations[]` | **U6 소유 포트 타입(참조)**. enforce 산출. U2는 소비만. |
| **GroundedResults** | `items[]`(근거화 통과 결과) | `mapDecision(verdict=pass)` 산출 → ResultAssembler 입력. |
| **AbstainResult** | `reason`(사유 코드) | `mapDecision(verdict=abstain\|block)` 산출. **Q4=A**: 근거화 기권/코퍼스 밖 — 날조 0건. 내부 위반 상세 비노출. |

---

## 5. 출력 DTO 엔티티 (`SearchResponse` union — 생산: U2 / 소비: U5)

> `shared/dtos/search.schema.json` 정합. **INV-2(SEC-9)**: 내부 필드(owner userId·raw 점수·디버그·`vector`/`chunkId`/`section`) 외부 비노출. 카드는 §5.1 7필드만.

| 엔티티 | 종류 | 필드(외부 노출) | 비고 |
|---|---|---|---|
| **SearchResponse** | 응답(union) | `SearchResultPageDTO \| AbstainDTO \| DegradedResultDTO \| ValidationErrorDTO` | `QueryIntakeController.search` 반환. **Q4=A**: 종단 상태 명시 합집합(FR-11). |
| **SearchResultPageDTO** | 성공 | `cards: ResultCardVM[]`, `meta: ResultMeta` | 정렬 순서 보존 상위 N 카드(verdict=pass & 결과≥1). 카드 배열=랭킹 순서(PBT-03). |
| **ResultMeta** | 값 | `resultCount: int`, `degraded: bool`, `degradationMode?: DegradationMode` | 결과 수·저하 배너 힌트. 내부 점수/타이밍 비노출(SEC-9). |
| **ResultCardVM** | 카드(값) | (§5.1 7필드) | 단일 논문 폰 카드. U5 `ResultCard.render` 소비. |
| **AbstainDTO** | 기권 | `reason` | **근거화 거부 전용**: verdict=abstain/block → 기권(날조 0건). **무매치는 abstain이 아님** — count:0 명시 빈 페이지(SearchResultPageDTO)로 종단(BR-9 / U5 B3-a: 기권 ≠ 빈 결과). |
| **DegradedResultDTO** | 저하 | `cards: ResultCardVM[]`, `meta`(degraded=true), `mode: DegradationMode` | **Q6=A**: degradeMode 활성 & 결과 반환(NFR-C1/US-R2/R3). 카드 형상은 성공과 동일. |
| **ValidationErrorDTO** | 검증오류 | `field?: string`, `message: string` | **INV-3(SEC-15)**: FR-1/SEC-5 검증 실패 인라인 에러(비기술·내부정보 차단, fail-closed). |

### 5.1 `ResultCardVM` 카드 필드 — vector-spec.md IndexRecord 카드 필드(FR-4)와 동일 (FROZEN-인접)

> **불변식**: 6개는 IndexRecord 카드 필드의 외부 투영, `relevance`는 랭킹 파생 표시값. 내부 필드(`vector`·`lexicalTerms`·`chunkId`·`section`·`categories`·전체 `abstract`)는 카드 비노출(SEC-9).

| 카드 필드 | 타입 | IndexRecord 출처 | 트레이스 |
|---|---|---|---|
| `title` | string | `title` | FR-4 |
| `authors` | string[] | `authors` | FR-4 |
| `year` | int | `year` | FR-4 |
| `arxivId` | string | `arxivId`(표시용, 버전 포함 가능) | FR-4 |
| `abstractSnippet` | string | `abstractSnippet`(전체 초록 비노출, 스니펫만) | FR-4, FR-5 |
| `relevance` | (표시용) | 랭킹 순위 파생(raw 점수 비노출) | FR-3, FR-4, SEC-9 |
| `arxivUrl` | string | `arxivUrl`(**해소 가능 실재 링크** — FR-5 근거화) | FR-4, FR-5 |

---

## 6. 횡단 후크 포트 타입 (U6 소유 — 참조·소비)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **BudgetState** | `tier`, `degradeMode`, `circuitState` | `CostGuardCircuitBreaker.getBudgetState`(🔒 FROZEN 시그니처) 산출. **Q6/Q8**: U2는 조회·분기만(독자 비용 판정 없음). `degradeMode`→`DegradationSignal` 파생. |
| **(GroundingEnforcementHook)** | `enforce(candidate, retrieved) -> GroundingDecision` | 🔒 FROZEN. **U6 게이트웨이 호출**(U2 호출 아님, INV-1). |
| **(ObservabilityHub)** | `emitMetric`/`emitLog`/`startSpan` | U2는 지연·검색/근거화 건강도 emit 제출만(NFR-O1, SEC-3 PII/시크릿 금지). |

---

## 7. 이벤트 엔티티 (생산 — 비차단)

| 엔티티 | 필드(개념) | 비고 |
|---|---|---|
| **SearchExecutedEvent** | `userId`, `query`, `timestamp`, `resultCount` | 🔒 FROZEN(`shared/events`). `SearchOrchestrationService.publishSearchExecuted` 발행 → U4 이력. **Q11=A**: 성공 응답 **후 fire-and-forget·비차단**(NFR-P1 P50<3s 경로 밖). `userId`=세션 출처(Q5=A). |

---

## 8. 엔티티 관계 (동기 읽기 경로)

```
SearchRequest{query} + RequestContext{authSession(필수,Q5), degradationSignal, requestId}
   │
   ▼ QueryValidator.validate/normalize (FR-1/SEC-5, NFC, 다국어)
NormalizedQuery{text} ──(ok=false)──▶ ValidationErrorDTO (fail-closed, SEC-15)
   │ ok
   ▼ QueryUnderstandingExpander.expand (Q1=A: 임베딩 search_query + lexical 텀; LLM 재작성 없음)
QueryPlan{embeddingVector?(cross-lingual), lexicalTerms, mode} ◀── DegradationSignal(BudgetState.degradeMode)
   │                                                                  (llmEnabled=false → mode=lexical-only)
   ▼ HybridRetriever.retrieve (Q2=A: RRF 병합 · PaperId 단위 디덥, PBT-07)
CandidateSet{candidates[](실재 IndexRecord 참조), retrievalMode}
   │
   ▼ RelevanceRanker.rank (Q3=A: 점수 내림차순 · 상위 N=20(Q10) · LLM 리랭킹 없음, PBT-03)
RankedResults{ranked[], rankingMode=baseline}
   │
   ▼ GroundingAdapter.toGroundingInput  (INV-1: enforce는 U6 게이트웨이 post-handler 단일 호출)
GroundingInput ──[U6 enforce]──▶ GroundingDecision{verdict, violations[]}
   │
   ▼ GroundingAdapter.mapDecision
GroundedResults | AbstainResult (verdict=pass → GroundedResults; verdict=abstain/block → AbstainResult)
   │  (후보 0/무매치는 enforce 이전 단계에서 NoMatchResult로 종단 — mapDecision 미경유)
   ▼ ResultAssembler.assemble (FR-4 카드 · FR-11 상태 · SEC-9 비노출, PBT-09)
                              입력: GroundedResults | AbstainResult | NoMatchResult
SearchResponse = SearchResultPageDTO | AbstainDTO | DegradedResultDTO | ValidationErrorDTO
   │
   └─(응답 후, 비차단 Q11) SearchOrchestrationService.publishSearchExecuted ─event▶ U4
```

> 결정·검증 규칙은 `business-rules.md`, 오케스트레이션·저하 분기는 `business-logic-model.md`.

---

## 9. 공유 계약 참조 (소비 — 소유=공유 레이어, UQ5=A)

| 계약 | 역할 | 불변식 |
|---|---|---|
| **VectorSpec** | reader(질의 임베딩) | U1 writer ↔ U2 reader **동일 임베딩 공간**(Cohere Embed Multilingual v3·1024·코사인·**reader=`search_query`**). specVersion 일치. cross-lingual(KR↔EN). |
| **IndexRecord** | reader(후보 레코드) | 카드 필드 §5.1 투영·근거화 검증 대상(FR-5). 내부 필드 비노출(SEC-9). |
| **search DTO** | 생산 | `SearchResponse` union·`ResultCardVM`. |
| **SearchExecutedEvent** | 생산 | 🔒 FROZEN. 비차단(Q11). |
| **ports**(Grounding·Cost·Observability) | 의존 | 단일 권위=U6. U2는 정형/조회/emit만(재구현 금지). |
