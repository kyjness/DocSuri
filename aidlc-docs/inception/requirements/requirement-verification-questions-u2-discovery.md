# U2 검색(Discovery) — 요구사항 명확화 질문 (Requirement Verification — U2 Discovery)

**단계**: INCEPTION → Requirements Analysis 재진입 (재인셉션 **페이즈 2** / U2) · **일자**: 2026-06-29
**담당**: 유진
**대상 기능**: U2 검색 — 자연어 의도 → 정규화/확장 → **하이브리드 검색**(k-NN ∥ BM25 → RRF) → **랭킹** → **Grounding(Search)** → 결과 카드/저하/기권. 멀티소스·DocModel(Block) 인덱스 전환 정합·검색 API 완성·Grounding(Search) 완성.
**영향 유닛**: U2(`backend/modules/discovery/`) 핵심 · 공유 계약(`shared/vector-spec/index-record.schema.json`·`shared/dtos/search.schema.json`·`shared/ports`) · U1(인덱스 생산자) · U6(`GroundingEnforcementHook` 단일권위·`CostGuardCircuitBreaker`) · U7/Agent(검색을 Tool로 소비).
**근거 SSOT**: 재인셉션 차터 `inception/plans/reinception-2026-06-charter.md`(페이즈 2·**D3** Grounding·**D6** 인덱싱) · 코드 베이스라인 `inception/reverse-engineering/code-baseline-2026-06.md`(§2 페이즈 2·§3.1 `shared/ports` FROZEN).
**답변 상태**: ✅ **답변 확정(2026-06-29)** — 전 문항 **A**(사용자 확정). #236 머지 후 기정선 반영: Q1·Q5·Q6 = #236 선완료분 **확인·안정화**, **Q2·Q3·Q4 = 실제 결정**(소스 중립 카드 계약 확장 · Block 앵커 내부 근거경로만(외부노출 페이즈 3·4 이월) · Grounding(Search) 단일권위 유지·Validator 레지스트리 페이즈 3), Q7·Q8·Q9 = 경계 이월.

> ⚠️ **이 페이즈의 성격 — 그린필드 아님**: `discovery/` 모듈은 이미 도메인(validator·expander·retriever·ranker·grounding_adapter·assembler)·adapters(bedrock_embedding·opensearch_index·event_publisher)·ports·real_wiring·mocks까지 존재한다. 따라서 페이즈 2의 실체는 "신규 구축"이 아니라 **① D6 인덱스 전환(full-text→DocModel Block·멀티소스) 소비 정합, ② 검색 API/저하/기권 안정화, ③ Grounding(Search) 완성(페이즈 3 통합 프레임워크와의 경계 합의)** 이다.
>
> 🟢 **#236 머지 반영(2026-06-29, base 갱신)**: PR #236(`feat: PDF 경로 구조화 doc-model + 검색 lite/full + 수식 안정화`)이 develop에 머지됐다. 이로써 **검색 lite/full 분기·`search.schema.json` `scope` 필드·멀티소스 TEI 구조화 doc-model·section 케이싱 정규화(`abstract`)·reindex→cutover 순서**가 **이미 코드/계약으로 랜딩**됐다(검색창=lite 전용·full=에이전트, "본문까지 검색 토글"은 #236에서 폐기). → 본 질문지에서 **Q1·Q5·Q6은 "결정"이 아니라 #236 기정선의 "확인·안정화"** 로 다루고, **진짜 열린 결정은 Q2·Q3·Q4** 다.
>
> **실질 갈림길**: **Q2(멀티소스 카드·근거)·Q3(Block 앵커 노출)·Q4(Grounding(Search) 경계 ↔ 페이즈 3)**. 나머지는 대부분 정합·운영 정책 확정.
>
> **코드에서 이미 확인된 사실(발명 아님)**:
> - 인덱스 레코드 계약에 `blockRefs`(DocModelBlockRef: paperId·version·sectionId·blockId·blockType)·`sourceProvenance`(sourceName·sourceId·sourceTier·sourceUrl·doi·arxivId) **존재하나 둘 다 INTERNAL**(외부 DTO 미투영, SEC-9).
> - 외부 노출 카드(`ResultCardVM`)는 **arXiv 중심 6필드**(title·authors·year·arxivId·abstractSnippet·arxivUrl). `arxivUrl`이 Grounding 실재 링크 검증 대상.
> - 리트리버는 full-body 멀티청크 인덱싱에 맞춰 `RETRIEVAL_TOP_K=150` 과대수집 + PaperId 디덥(PBT-07). vector-spec = Cohere Embed v4 / 1024 / cosine **FROZEN**.
> - 오케스트레이터는 grounding seam에서 분리(INV-1): U2 도메인 코어는 `enforce`를 **호출하지 않음**, 게이트웨이 seam이 U6 `enforce` 수행 후 `finalize`.

---

## Q1. 페이즈 2 범위 — 정합·안정화 경계

페이즈 2 "U2 검색"의 작업 범위를 다음으로 확정하는가? (대량/품질 고도화는 페이즈 6·7.)

> 🟢 **#236 선완료분**: lite/full 분기·`scope` 계약·멀티소스 TEI 구조화·section 케이싱 정규화는 #236에서 이미 랜딩. 따라서 본 페이즈는 그 위에서 **남은 정합·안정화 + Grounding(Search) 완성**이다.

- **A) 정합·안정화 + Grounding(Search) 완성** (차터 권장):
  ① 새 DocModel(Block)·멀티소스 인덱스를 **올바로 소비**(인덱스 generation/alias·specVersion 동치 게이트), ② 검색 API·저하(degrade)·기권(abstain) 경로 **안정화·검증**(NFR-P1 SLA·QT-3), ③ **Grounding(Search) 완성**(아래 Q4). reranker·LTR·query expansion 고도화·click log는 **페이즈 7로 명시 이월**.
- **B) U2 전면 재작성** — 기존 모듈 폐기·재구축(코드 자산 폐기 비용·리스크↑).
- **X) 기타**(범위 가감)

[Answer]: A
**권장(차터)**: A — 코드 자산 보존, "정합·안정화·Grounding(Search) 완성"으로 한정. 페이즈 7 항목은 명시 이월.

---

## Q2. 멀티소스 결과 카드·근거 식별자 — **실질 갈림길**

멀티소스 코퍼스(arXiv·Semantic Scholar·OpenAlex)에서, **비-arXiv 논문**의 결과 카드 식별자/링크와 근거 검증을 무엇으로 하는가?
(현재 카드 = `arxivId`/`arxivUrl` 중심. `sourceProvenance`는 INTERNAL. 비-arXiv 논문은 arxivId가 없을 수 있음.)

- **A) 소스 중립 식별자/링크로 카드 계약 확장** (차터 권장):
  카드에 **소스 표기(sourceName)** + **소스 중립 resolvable URL**(arXiv면 arxivUrl, 그 외면 sourceUrl/DOI 링크) 노출. Grounding 실재 링크 검증을 `arxivUrl` 단일 → **소스별 실재 링크**로 일반화(FR-5 정신 유지). `search.schema.json`·`index-record.schema.json` 외부 투영 **계약 개정** 필요(U6 사인오프).
- **B) arXiv 카드 계약 유지 + 비-arXiv는 DOI/소스URL을 arxivUrl 자리에 매핑** — 계약 무변경, 단 필드 의미 오버로드(혼란·검증 모호).
- **C) 페이즈 2는 arXiv만 노출, 비-arXiv는 인덱스에만 두고 카드 미노출** — 단순하나 멀티소스 수집 효익 일부 미실현.
- **X) 기타**

[Answer]: A
**권장(차터)**: A — 소스 중립 카드/근거 식별자로 확장. (FROZEN 계약 변경이므로 shared PR + U6 사인오프. 정확한 필드는 `dtos.md §1.1`·`search.schema.json` 대조 후 확정.)

---

## Q3. DocModel Block 앵커의 검색 노출 — **실질 갈림길**

인덱스에 이미 있는 `blockRefs`(섹션/블록 앵커)를 검색 결과/근거에 **노출**하는가, INTERNAL로 유지하는가?
(현재 `blockRefs`는 QT-9 BlockRef 검증용 INTERNAL. "출처 보기"·에이전트 Tool은 Block id 앵커가 필요할 수 있음 — FR-18 리치뷰·FR-12 요약 앵커와 연결.)

- **A) 페이즈 2는 paper-level 유지 + Block 앵커는 Grounding/근거 입력 경로에만 내부 활용, 외부 노출은 페이즈 3·4에서** (차터 권장):
  사람 검색 카드는 paper-level(현행). Block 앵커는 grounding_adapter→근거 입력에 내부 전달(매칭 신뢰도↑). **에이전트 Tool/요약 앵커로의 외부 노출 계약**은 페이즈 3(요약 앵커)·4(에이전트 evidence DTO)에서 동결 — 페이즈 2에서 선반영하지 않음.
- **B) 페이즈 2에서 Block 앵커를 검색 결과 DTO에 즉시 노출** — 에이전트/요약 미착수 상태라 계약이 흔들릴 위험(rework).
- **C) Block 앵커 계속 INTERNAL, 일절 미사용** — grounding 매칭 품질 향상 기회 미실현.
- **X) 기타**

[Answer]: A
**권장(차터)**: A — Block 앵커는 내부 근거 경로에 활용하되 **외부 노출 계약은 다운스트림 페이즈로 이월**(D5 "계약 선행 동결" 틀과 정합).

---

## Q4. Grounding(Search) 경계 — 단일권위 enforce ↔ 페이즈 3 도메인 Validator — **실질 갈림길**

페이즈 2의 "Grounding(Search) 완성"을 다음 경계로 확정하는가? (D3·베이스라인 §4-1 설계 긴장점.)

- **A) U6 단일권위 enforce + U2 어댑팅 현행 유지, Search Validator '자리'만 확보** (차터 권장):
  `GroundingEnforcementHook.enforce`는 **U6 단일권위 FROZEN** 유지. U2는 grounding seam(orchestrator split·INV-1)·grounding_adapter로 어댑팅만. 페이즈 2 "완성" = **Search 경로의 enforce 호출 지점·verdict 매핑(pass/block/abstain)·grounding-health 신호·기권≠빈결과(BR-9) 일관성**을 검증 완료. **도메인별 Validator 레지스트리(Search/Summary/Agent) 재조정은 페이즈 3**으로 명시 이월.
- **B) 페이즈 2에서 도메인 Validator 레지스트리까지 선구현** — 페이즈 3 통합 프레임워크 선취(요약/에이전트 미착수라 추상화 근거 부족·rework 위험).
- **X) 기타**(enforce 호출 지점을 게이트웨이→도메인 이동 등 — FROZEN 변경 사인오프 수반)

[Answer]: A
**권장(차터·D3)**: A — 단일권위·seam 현행 유지로 Search grounding 완성, Validator 레지스트리 재조정은 페이즈 3.

---

## Q5. 인덱스 컷오버 소비 — generation/alias·specVersion 동치

U2가 D6 전환된 **DocModel(Block) 기반 인덱스**를 어떻게 읽는가?
(U1 Q8=A: Cohere v4/specVersion 불변 + DocModel 인덱스 generation/alias 신규 생성·블루/그린 컷오버. vector-spec writer↔reader specVersion 동치 불변식.)

> 🟢 **#236 선완료분**: #236 PR 노트가 **lite 노출 전 전량 reindex(또는 section 정규화 backfill) 선행 → 검색 cutover → lite 노출** 순서와 `section="abstract"`(소문자) 정규화를 이미 명시. 따라서 Q5는 그 순서를 **U2 소비 관점에서 확인**하는 것(새 결정 아님).

- **A) alias 기반 읽기 + writer/reader specVersion 동치 게이트(CI/배포) 확인** (차터 권장):
  U2는 인덱스 **alias**만 바라보고(세대 전환은 U1/Infra가 컷오버), 부팅/배포 시 reader specVersion == writer specVersion 검증. 임베딩 **모델 변경 아님**(v4 유지) → U2 질의 임베더 무변경, 소스(full-text→Block)·필드만 정합.
- **B) U2가 인덱스 generation 직접 지정** — 컷오버마다 U2 배포 결합(운영 결합도↑).
- **X) 기타**

[Answer]: A
**권장(차터·D6)**: A — alias 읽기 + specVersion 동치 게이트. 임베딩 모델·차원 불변.

---

## Q6. 검색 SLA 재검증 — full-body 멀티청크·코퍼스 증가

NFR-P1(검색 지연 P50<3s·P95<8s)을 멀티청크·멀티소스 인덱스에서 **재검증 대상**으로 다루는가?
(리트리버 `RETRIEVAL_TOP_K=150` 과대수집·PaperId 디덥은 청크 증가에 맞춰 이미 상향. LITE=abstract-only k-NN(사람 검색)·FULL=full-body(에이전트 심층).)

> 🟢 **#236 선완료분**: lite/full 분기 자체와 `scope` 계약 기본값(absent⇒lite·P50<3s, full=에이전트)은 #236에서 랜딩. 따라서 Q6은 그 프로파일을 **확정·문서화**(LITE=NFR-P1 SLA 대상, FULL=비-SLA)하고 콜드스타트/동시성 수치를 NFR로 넘기는 것.

- **A) LITE(사람 검색)는 NFR-P1 유지·재검증, FULL(에이전트 심층)은 별도 프로파일** (차터 권장):
  사람 검색 기본=LITE(abstract chunk·고정밀·저지연)로 NFR-P1 SLA 측정 대상. FULL은 에이전트 Tool 경로로 **검색 SLA 비대상**(요약/에이전트 온디맨드 프로파일에 준함). 콜드스타트·동시성 가정은 NFR Requirements에서 수치 확정.
- **B) LITE/FULL 단일 SLA** — FULL 심층 검색이 P95를 흔들 위험.
- **X) 기타**

[Answer]: A
**권장(차터)**: A — LITE=NFR-P1 SLA 대상, FULL=별도 프로파일. 수치·콜드스타트 포함/제외는 NFR에서.

---

## Q7. 개인화 rerank(FR-20) 소유 경계 — U2 ↔ U9

검색 결과 개인화 boost(FR-20·U9)를 페이즈 2 U2 랭커에 넣는가, U2는 hook만 제공하는가?
(FR-20: 기존 관련도 점수 유지 + 관심사 기반 작은 boost로 rerank, 과도 변경 금지·끄기 토글·실패 시 기본 검색 저하.)

- **A) U2는 랭킹 결과에 개인화 boost를 적용할 '주입 지점'만 제공, 개인화 신호·집계는 U9 소유** (권장):
  `RelevanceRanker` 뒤에 선택적 personalization rerank hook(없으면 no-op). 신호 산출·프로필은 U9(`personalization`). 실패 시 기본 랭킹으로 저하(NFR-P4). 페이즈 2는 hook 경계만 확정, U9 연동 구현은 U9 페이즈/사이클.
- **B) 페이즈 2에서 개인화 boost까지 U2가 구현** — U9 소유와 경계 충돌·NFR 프로파일 상이.
- **X) 기타**

[Answer]: A
**권장**: A — U2=주입 지점, 개인화 본체=U9. (U9는 별도 사이클 진행 중 — 경계만 합의.)

---

## Q8. 에이전트-facing 검색(FULL scope) Tool 계약 시점

FULL scope 검색(에이전트 심층 검색)을 **검색 Tool 계약**으로 페이즈 2에서 동결하는가, 페이즈 4·5에서 동결하는가?

- **A) 페이즈 2는 FULL scope 동작만 안정화, Tool 계약(포트·evidence 연계)은 페이즈 4·5 계약 게이트에서 동결** (차터·D5 권장):
  FULL 검색 자체는 페이즈 2에서 동작·검증. 단 에이전트가 소비할 **Tool 포트·근거 출력 DTO**는 D5 "계약 선행 동결" 원칙대로 페이즈 4(문헌탐색·근거형성) 질문지 후 `shared/`에 동결. 페이즈 2에서 에이전트 계약을 선발명하지 않음.
- **B) 페이즈 2에서 에이전트 Tool 계약까지 동결** — 에이전트 요구 미확정 상태 선동결 = rework 위험(D5 전제 위배).
- **X) 기타**

[Answer]: A
**권장(차터·D5)**: A — FULL 동작 안정화 ⊃ 에이전트 Tool 계약 동결(페이즈 4·5).

---

## Q9. 페이즈 7 이월 항목 명시(범위 경계)

다음을 페이즈 2 **제외 → 페이즈 7(검색 품질 개선)** 으로 명시 이월하는가?

- **A) 이월 확정** (차터 권장):
  Cross-Encoder Reranker · Learning to Rank · Query Expansion 고도화 · Chunk 전략 재설계 · Embedding 모델 교체(specVersion 변경=전량 re-embed) · Feedback/Click Log 기반 랭킹 개선. 페이즈 2는 **현행 RRF+RelevanceRanker 안정화**까지.
- **X) 기타**(일부를 페이즈 2로 당김 — 근거 필요)

[Answer]: A
**권장(차터)**: A — 위 항목 전부 페이즈 7 이월. 페이즈 2는 안정화·정합·Grounding(Search) 완성에 한정.

---

## 다음 단계

유진님 답변(특히 **Q2·Q3·Q4**) 확정 후 → 본 질문지 답변을 `requirements.md`에 U2 **FR 개정·NFR·C** 추적성으로 등재(멀티소스 카드·Block 앵커 노출 경계·Grounding(Search) 완성 정의). 이후 `stories.md` 디스커버리 에픽(US-D1..D7) 갱신 → `plans/u2-discovery-workflow-plan.md` → (필요 시) Application Design U2 amendment → Units Generation 리뷰 → Construction(FD→NFR→Infra→Code→Build/Test).

> **별건(병행)**: 페이즈 1 closeout `ingest-one` 라이브 스모크는 본 문서 트랙과 독립으로 진행하되, 페이즈 2 Construction 진입 전까지 닫는다(차터 D4 엄격 순차).
