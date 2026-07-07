# business-rules.md — U2 Discovery 비즈니스 규칙·속성·추적성 (프로덕션)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: 계획서(§4 답변 전부 A) · `application-design/{components,component-methods,services,component-dependency}.md` · `shared/{dtos,ports,vector-spec,events}.md` · `requirements.md`
**원칙**: 기술 무관 결정·검증·제약. 수치(타임아웃·RRF 파라미터·topN 외)는 NFR Requirements 확정.
**프로덕션 스코프**: 단일 프로덕션 트랙(데모 폐기). cross-lingual(한국어 질의·TD-3) 전제.

> **페이즈 2 개정(2026-06-29, 재인셉션)**: 멀티소스·DocModel(Block) 인덱스 소비 반영 — BR-18(근거 전제) 소스 중립화·BR-15(SEC-9 비노출)에 `blockRefs`/`sourceProvenance` 추가·BR-4b(검색 폭 scope·#236) 신설. Grounding(Search) 단일권위(BR-7·INV-1)·개인화 boost(BR-5·FR-20)는 **기존 규칙 유지**(변경 없음).

---

## 1. 비즈니스 규칙 (BR)

| ID | 규칙 | 근거/답 |
|---|---|---|
| **BR-1 (질의 검증)** | `query` 검증: 트림 후 1자 이상·**≤500자**·제어문자/널 거부·과도 공백 정리. 실패 시 업스트림 미전송·`ValidationErrorDTO`(fail-closed). | FR-1, SEC-5, Q7=A |
| **BR-2 (질의 정규화·결정성)** | `normalize` = 트림 + 공백 collapse + **유니코드 NFC**. 결정적·멱등(PBT-02). **한국어 포함 다국어 허용**(스크립트 allowlist 금지 — cross-lingual 보호). | FR-1, PBT-02, Q7=A, TD-3 |
| **BR-3 (질의 확장)** | `expand` = 질의 임베딩(**공유 VectorSpec, reader=`search_query`**, cross-lingual KR↔EN) + lexical 텀(토큰화). **동의어/LLM 재작성 없음**(결정성·NFR-C1). `llmEnabled=false`→임베딩 생략·lexical-only. | FR-2, NFR-C1, Q1=A, TD-3 |
| **BR-4 (하이브리드 병합·디덥)** | 벡터 ANN + lexical BM25 후보를 **RRF 병합**; **PaperId 단위 디덥**(같은 논문 복수 청크→최상위 1건). 멱등·결과셋 보존(PBT-07). | FR-2, PBT-07, Q2=A |
| **BR-4b (검색 폭 scope)** *(2026-06-29 — #236/페이즈 2)* | `SearchRequest.scope`: `lite`(기본·사람 검색창)=제목+초록 BM25 + 초록 chunk k-NN(저지연·**NFR-P1 SLA 대상**); `full`(에이전트 심층)=본문 chunk 포함 하이브리드 고recall(**비-SLA**). 부재⇒lite. RRF 병합·PaperId 디덥(BR-4)은 scope 무관 동일. | FR-2, NFR-P1, #236 |
| **BR-5 (랭킹·상위 N)** | ranker는 **단일 정렬 키 `ranking_score`만** 내림차순 정렬 · **상위 N=20** 절단(N 미만=가용분만, 패딩/오류 없음). 순서 안정성(PBT-03). **공급↔정렬 분리**(2026-07-06 페이즈 7): retrieval이 `ranking_score=retrieval_score`로 시드, cross-encoder 재랭킹(BR-5b)·개인화가 `ranking_score`를 덮어씀(SUPPLY 단계) — ranker는 어느 단계가 값을 넣었는지 모른 채 정렬만 한다. `retrievalScore`는 provenance로 보존(SEC-9 비노출). | FR-3, QT-2, Q3=A, Q10=A, FR-20 |
| **BR-5b (Cross-Encoder 재랭킹)** *(2026-07-06 페이즈 7)* | retrieve→융합 상위 **M** 후보를 cross-encoder 재랭킹 모델로 재정렬해 `ranking_score`를 덮어씀(head만; tail 불변). retrieve 폭(150)은 불변, **M은 보수적 시작값**(정량 평가 확보 후 조정; M ≥ N=20이라 재랭킹 head가 표시 페이지를 덮음). 오케스트레이터에서 게이트(I/O 결정): 어댑터 미배선(feature off)·예산 저하(`rerank_enabled`=False, RERANK_OFF/LEXICAL_ONLY)면 skip, **어댑터 실패는 fail-soft로 베이스라인(RRF) 유지 — 재랭킹은 응답을 절대 막거나 저하 모드로 만들지 않음**(순위 품질 향상일 뿐). 적용=lite·full 둘 다. | FR-3, NFR-C1, NFR-R2 |
| **BR-6 (relevance 표시값)** | 카드 `relevance`=**순위 파생 비-raw 표시 신호**. **내부 raw/RRF 점수·디버그 비노출(SEC-9)**. 구체 표시 형태는 U5 UI 연동. | FR-3/4, SEC-9, Q3=A |
| **BR-7 (근거화 단일 권위 — INV-1)** | U2는 `enforce`를 **호출하지 않는다**. 유일 invocation = U6 게이트웨이 post-handler. U2는 `toGroundingInput`(정형)·`mapDecision`(verdict 매핑)만 — 독자 차단·인시던트 발행 없음. | FR-5, US-D5, INV-1 |
| **BR-8 (verdict 매핑)** | `verdict=pass`→GroundedResults; `verdict=abstain\|block`→AbstainResult(날조 0건). 내부 위반 상세 비노출. | FR-5, US-D5/D6, Q4=A |
| **BR-9 (종단 상태·기권 vs 빈 결과)** | 종단 상태 결정: 검증실패→ValidationError; **verdict=abstain/block→AbstainDTO**(근거화 거부 — 날조 0건); **후보 0/무매치(또는 근거화 통과 후 전량 필터)→SearchResultPageDTO(cards=[], resultCount=0)** — 명시적 빈 페이지(*조용한 결과 아님*); pass&결과≥1&NORMAL→SearchResultPage; pass&결과≥1&저하→DegradedResult. **기권 ≠ 빈 결과**(U5 B3-a): 다른 메시지·다른 분기. (개정: 종전 "무매치→AbstainDTO"를 대체 — 빈 결과는 abstain이 아니라 count:0 명시 페이지로 종단.) | FR-11, US-D6/D7 |
| **BR-10 (기권 우선순위)** | degradeMode 활성 중에도 `verdict=abstain/block`이면 **기권 우선**(날조 금지 최우선) — 저하 카드 미발행. | FR-5, NFR-R1, Q4=A |
| **BR-11 (저하 매트릭스)** | `getBudgetState().degradeMode`(U6 단일 권위 조회): NORMAL=hybrid(+재랭킹); RERANK_OFF=**cross-encoder 재랭킹 생략**(BR-5b — 융합점수 순서로 폴백)·배너 표면화; LEXICAL_ONLY=임베딩+재랭킹 생략·BM25 폴백. 저하는 `ResultMeta.degraded`/`mode`로 명시(US-R2/R3). *(2026-07-06: RERANK_OFF가 실제 재랭킹을 끄는 유효 저하로 전환 — 과거 baseline 무변화 no-op에서 변경.)* | NFR-C1, NFR-R2, US-R2/R3, Q6=A |
| **BR-12 (비용 단일 권위)** | U2는 비용/예산을 **독자 판정하지 않는다**. `getBudgetState` 조회·분기만. 누적/임계/서킷 전이는 U6 내부. | NFR-C1, Q6=A, Q8=A |
| **BR-13 (인증 전제)** | `POST /api/search`는 **인증 필수**(deny-by-default, SEC-8). authn 강제는 U6 게이트웨이; U2는 `RequestContext.authSession` 신뢰·userId 사용(SearchExecuted). 미인증은 게이트웨이 401. | SEC-8, FR-10, Q5=A |
| **BR-14 (SearchExecuted 비차단)** | 성공 응답 **후** `publishSearchExecuted(userId, requestId, query, timestamp, resultCount)` 발행. **fire-and-forget**: 발행 실패는 응답에 무영향(관측 로그만), NFR-P1 경로 밖. | FR-10, NFR-P1, US-L3, Q11=A |
| **BR-15 (SEC-9 비노출 — INV-2)** *(2026-06-29 개정 — 페이즈 2)* | 외부 DTO에 내부 필드(owner userId·raw/RRF 점수·디버그·트레이스·`vector`/`lexicalTerms`/`chunkId`/`section`/**`blockRefs`/`sourceProvenance`**·전체 `abstract`) 비노출(Q3: `blockRefs`/`sourceProvenance` 외부 노출 페이즈 3·4 이월). 카드는 §domain-entities §5.1(페이즈 2: 소스 중립 `sourceName`/`sourceUrl` 추가 투영). | SEC-9 |
| **BR-16 (fail-closed — INV-3)** | 모든 외부 어댑터 호출(expand/retrieve) 타임아웃·서킷(RES-9, 수치 NFR). 처리 중 예외는 전역 핸들러가 **일반화 비기술 에러**로 매핑(스택/내부 식별자 비노출), 권한·검증 우회 없음. | SEC-15, NFR-R1, FR-11 |
| **BR-17 (관측성)** | 단계 지연·검색/근거화 건강도·degradeMode를 `ObservabilityHub.emit*` 제출(requestId 상관). **PII/시크릿 금지(SEC-3)** — 질의 원문 로깅 정책은 SEC-3 준수. | NFR-O1, SEC-3 |
| **BR-18 (FR-5 근거화 전제)** *(2026-06-29 개정 — 페이즈 2/Q2)* | 노출되는 모든 카드는 **실재 IndexRecord**(**소스 중립** 해소 가능 ID/링크 — arXiv=arxivUrl·비-arXiv=sourceUrl/DOI)에 매핑. 후보 단계부터 실재 레코드 참조 보유 — 날조 0건(QT-1, U6 enforce 검증). U6 enforce의 실재 링크 검증도 소스 중립으로 일반화(단일권위 유지, BR-7). | FR-5, QT-1 |

---

## 2. 병렬 개발(mock-first) 규칙 (Track 3 — Q8=A / Q9=A)

| ID | 규칙 |
|---|---|
| **MR-1** | capability 어댑터(`VectorStoreAdapter`·`LexicalIndexAdapter`·`LlmGatewayAdapter`)는 **포트 뒤 교체 가능 구현**. mock=고정 픽스처(결정적 가짜 ANN/BM25/임베딩), real=OpenSearch·Bedrock Cohere(NFR/Infra·U1 코퍼스 후). |
| **MR-2** | mock 픽스처에 **QT-2 평가셋 논문 + 한국어↔영어 cross-lingual 케이스 포함**(TD-3·U1 Q14=A 연동). |
| **MR-3** | U6 포트 스텁: `GroundingEnforcementHook`=pass-through(verdict=pass) + abstain 강제 케이스; `getBudgetState`=정상 티어(NORMAL). **테스트 전용** — 실 강제는 U6(BR-7/12 불변). |
| **MR-4** | mock↔real 교체는 **FD 비즈니스 로직·`SearchResponse` 계약을 바꾸지 않는다**(기술 무관 경계). U5는 동일 계약 mock으로 병렬 개발. |

---

## 3. PBT 속성 (QT-4 — blocking PBT-02·03·07·09)

| 속성 | 진술 | 트레이스 |
|---|---|---|
| **PBT-02 정규화 멱등/라운드트립** | `normalize(normalize(q)) == normalize(q)`; 동일 입력→동일 NormalizedQuery(NFC·공백 collapse 결정적, 한국어 포함). | PBT-02, BR-2 |
| **PBT-03 랭킹 순서 안정성·절단** | 동일 CandidateSet→동일 순서(동률 안정 정렬); 상위 N=20 절단; 후보<N이면 정확히 가용분(패딩/중복 0). | PBT-03, BR-5 |
| **PBT-07 하이브리드 디덥·결과셋 보존** | RRF 병합 후 **PaperId 단위 중복 0**; 후보 조용한 누락/복제 없음(멱등: 동일 입력→동일 후보 집합). | PBT-07, BR-4 |
| **PBT-09 SearchResponse DTO 라운드트립** | 4개 종단 상태(성공/기권/저하/검증오류) 직렬화↔역직렬화 보존; 내부 필드 비노출 유지(SEC-9 카드 7필드). | PBT-09, BR-9/15 |

> 프레임워크는 NFR Requirements(시스템 결정 Hypothesis·Python). 도메인 제너레이터(다국어 질의 포함)·shrinking·시드 재현성. PBT-02/03/07/09 차단성.

---

## 4. 추적성 매트릭스 (요구사항 → 규칙/속성/컴포넌트)

| 요구사항 | 랜딩 |
|---|---|
| **FR-1**(자연어 질의·검증) | BR-1/2, QueryValidator, QueryIntakeController |
| **FR-2**(시맨틱·하이브리드 검색) | BR-3/4, QueryUnderstandingExpander, HybridRetriever |
| **FR-3**(상위 N 랭킹 + 재랭킹) | BR-5/5b/6, RelevanceRanker, RerankAdapter, PBT-03 |
| **FR-4**(폰 결과 카드) | BR-6/15, ResultAssembler, domain-entities §5.1 |
| **FR-5**(엄격 근거화·기권) | BR-7/8/18, GroundingAdapter, INV-1, QT-1 |
| **FR-10**(검색 이력 생산) | BR-13/14, publishSearchExecuted, SearchExecutedEvent |
| **FR-11**(빈/실패/저하 UX) | BR-9/10/11/16, ResultAssembler, SearchResponse union |
| **NFR-P1**(P50<3s) | 동기 순차 파이프라인·BR-14 비차단 이벤트(정책; 수치 NFR) |
| **NFR-C1**(비용·저하) | BR-3/11/12, degradeMode 매트릭스, getBudgetState 조회 |
| **NFR-R2**(우아한 저하) | BR-11, DegradedResultDTO, lexical-only 폴백 |
| **NFR-U1/U2**(폰 카드) | BR-6, ResultAssembler 폰 직렬화 |
| **SEC-5**(입력 검증) | BR-1/2 |
| **SEC-8**(인가·인증) | BR-13, RequestContext.authSession(게이트웨이/U3 위임) |
| **SEC-9**(내부 비노출) | BR-6/15, INV-2 |
| **SEC-15**(fail-closed) | BR-16, INV-3, ValidationErrorDTO |
| **SEC-3**(PII/시크릿 금지) | BR-17 |
| **QT-1**(근거화 평가) | BR-7/8/18(U6 enforce·runEvalSet 소유; U2 표면) |
| **QT-2**(관련도 평가) | BR-5, RelevanceRanker 출력 표면(**한국어 질의 포함**, TD-3) |
| **QT-3**(신뢰성/저하) | BR-9/10/11/16(U6.ReliabilityEvalProbe 소유; U2 저하 폴백 기여) |
| **QT-4 / PBT** | PBT-02/03/07/09 |
| **US-D1..D7** | BR-1~16 (D1 질의·D2 검색·D3 랭킹·D4 카드·D5 근거화·D6 기권·D7 저하/상태) |
| **TD-3 cross-lingual** | BR-2/3, MR-2, QT-2 한국어 질의 |
| **미커버 검증** | 위 표로 U2 트레이스 0 미커버; US-H1(히어로)은 U5 표면+U2 백킹으로 충족 |

---

## 5. 결정된 불변식 (재인용)

- **INV-1 (단일 근거화 게이트)**: U2는 enforce 미호출 — U6 게이트웨이 post-handler 단일 invocation. U2는 정형/매핑만. (BR-7)
- **INV-2 (SEC-9 비노출)**: 카드 7필드만; raw 점수·vector·chunkId·내부 신호 비노출. (BR-6/15)
- **INV-3 (fail-closed)**: 예외는 일반화 에러로, 권한·검증 우회 없음, 빈 화면/스택 금지. (BR-16)

---

## 6. 공유 계약 정합 주석

- **VectorSpec(reader)**: U2.QueryUnderstandingExpander(`expand`, **reader=`search_query`**)는 U1.EmbeddingGatewayAdapter(writer=`search_document`)와 **동일 임베딩 공간**(**Cohere Embed Multilingual v4·1024**·코사인·specVersion v2 일치). cross-lingual(KR↔EN). 변경=전체 재임베딩(단방향). _(2026-06-29 정정: v3→v4 — NFR-S2 반영.)_
- **VectorSpec 런타임 검증(Reader 측)**: 혼합 임베딩 공간으로 인한 시맨틱 오염을 방지하기 위해 `HybridRetriever`는 **인덱스 open(리트리버 초기화) 시점에 활성 인덱스 manifest의 `specVersion`을 컴파일된 reader `specVersion`과 1회 검증**한다. 불일치 시 런타임 호환성 에러로 간주하여 어휘(Lexical) 기반 검색 모드로 저하(fallback) 처리하고 모니터링 시스템에 경보를 전송한다. per-record `modelVer` 재검사는 사용하지 않는다 — alias는 candidate index가 `assert_same_space()`(specVersion·model·dimensions·distanceMetric·normalize)를 통과한 뒤에만 전환되므로 활성 인덱스는 항상 동일-공간이고, `modelVer` 단일 필드는 dim/metric/normalize 변경을 못 잡는 부분 가드라 cutover 불변식과 중복이다. (N1 결정 2026-06-28, @kyjness; `shared/vector-spec.md §4` FROZEN 불변 · 근거=`operations/code-reviews/2026-06-28/designreview-audit.md`.)
- **search DTO 생산 / SearchExecutedEvent 생산 / ports 의존**: 형상·시그니처는 `shared/` SSOT 정합. 가산적 진화만(필드 추가=하위호환). 단일 권위(근거화·비용=U6)·재구현 금지.
- **단일 reader 경계**: U2.HybridRetriever만 공유 벡터 인덱스를 읽는다(U1=단일 writer).
