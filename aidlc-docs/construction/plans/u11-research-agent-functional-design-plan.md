# u11-research-agent-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (유닛별 루프) · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `requirements.md`(FR-22~25·NFR-P5·QT-8·NFR-C1 Agent·§12 Agent 카브아웃·C-2 경계), `stories.md`(에픽 9 US-RA1~8), `application-design/{unit-of-work,unit-of-work-dependency,unit-of-work-story-map}.md`(U11 행/주석/의존/스토리맵)
**설계 입력**: `inception/requirements/summarization-translation-pipeline.md` — §6 상세 파이프라인(0~8단계)·§7 근거화·**line 374**("본 파이프라인 6~7단계[LLM+근거화]를 근거형성 에이전트 노드로 재사용 — 앞에 '유사논문 검색' 노드만 추가").
**공유 계약**: `construction/shared/ports.md` — `enforce(candidate, retrieved) -> GroundingDecision` 🔒FROZEN · `getBudgetState() -> BudgetState` 🔒FROZEN (U6 구현·U11 주입 소비, 재구현 금지) · `docmodel.md`(doc-model 계약) · U7 `functional-design/`(근거 추출·앵커 선례).
**원칙(기술 무관)**: 이 단계는 **기술 무관**이다. 외부 학술 API·LLM 모델·RDS/오브젝트 스토리지·잡 큐·스트리밍 프로토콜·캐시 백엔드 세부는 **NFR Requirements/NFR Design/Infrastructure Design/Code Generation**에서 확정한다. 본 문서는 도메인·비즈니스 로직·규칙만 고정한다.

**설계 스탠스(2026-06-24 사용자 확정)**: 기존 코드·구조·설계(frozen 포트 포함)·요구사항은 **"고정 제약"이 아니라 "기본값"**이다. **U11 목표가 진짜로 요구하면 기존 것도 필요한 만큼 고친다**(불필요하면 안 고친다). 단 기존을 변경할 때는 ① 목표상 *왜 필요한지*, ② **blast-radius(영향 받는 기존 문서·계약·코드)**, ③ SSOT **back-sync** 계획을 같이 명시한다. 선례: doc-model 피벗(신규 기능 도입 시 기존 U1/U7/U5 FD·TD-12·requirements를 *편집*하며 blast-radius로 관리). 안전·신뢰의 **정책**(근거 없으면 기권·날조 0건·결정적 검증·U6 단일 근거화 권위·owner-scope·비용 단일 권위)은 제품 목표가 시키는 불변 가치라 유지하되, 그 **메커니즘/형상**(예: `enforce` 시그니처)은 다논문에 맞게 **U6/shared-ports를 확장**할 수 있다(U11이 우회·재구현하는 것과는 다름).

> 본 계획서는 **리뷰 게이트**다. 아래 `[Answer]:`가 모두 확정되기 전에는 FD 산출물(`domain-entities.md`, `business-logic-model.md`, `business-rules.md`)을 만들지 않는다.
> **각 핵심 질문(Q1/Q2/Q7)은 「기존 변경 없음(재사용)」 vs 「기존 확장(blast-radius 명시)」 두 갈래를 함께 제시**하여, 어디까지 손댈지 항목별로 선택하게 한다.

---

## 1. 유닛 컨텍스트 (Step 1 — Analyze Unit Context)

- **책임**: 로그인 필수 온디맨드 **대화형 다논문 문헌탐색·근거형성**(모드 A). 사용자 질의/첨부에 대해 여러 논문을 검색·교차확인하여 **추출 기반 근거**(핵심 주장·방법·결과 수치·한계)를 **비교 정리**해 출처와 함께 제시하고, 근거가 없으면 **기권**한다. 결과·대화 세션을 **owner-scoped로 영속**(전용 네비 진입·세션 리스트 재열람). 긴 다논문 분석은 비동기 잡 옵션.
- **Owner 스토리**: US-RA1(전용 진입·모드 선택·대화 입력), US-RA2(문서 첨부), US-RA3(다논문 교차확인 근거 정리·모드 A), US-RA4(근거화·출처·기권), US-RA5(결과·세션 영속·전용 메뉴 재열람), US-RA6(온디맨드 진행상태·부분결과·비차단 저하), US-RA8(novelty·**모드 B·차기**·범위·형태만).
- **기여 스토리**: US-RA7(Owner=U6 — 비용 게이트·근거화 운영 관측성; U11은 신호원·CostGuard 소비자).
- **범위 내(v1)**: 모드 A 대화형 근거형성 전체 흐름 — 모드 선택·자연어 질의·문서 첨부·다논문 검색(U2)·논문별 근거 추출(U7 doc-model 재사용)·교차확인 비교 정리·항목별 출처 부착·근거 없음 시 기권(U6 `enforce` 재사용)·세션/결과 영속·진행상태·부분결과·비차단 저하·비용 게이트(U6 `getBudgetState`)·삭제/초기화 제어.
- **범위 밖**: **모드 B(novelty 비교)의 구현**(차기 사이클·Q4=A — 본 FD는 도메인/포트 seam만 남김)·**외부 학술 API 호출**(모드 B 커버리지 확장·차기)·**생성 산문**(원고·문헌리뷰·연구 갭 산문 작성/합성 — C-2)·**재현성 판정/계산**(선택적 "코드/데이터 공개 사실 추출"만 가능)·**전용 네비/세션 리스트/대화 화면의 UI 구현**(프런트엔드 책임 — §아래 Q 참조)·강한 리랭크·실시간 추천.
- **예비 컴포넌트(잠정 — FD에서 정제)**:
  - `AgentSessionService` — 연구 세션·대화 턴 생애주기, owner-scoped 영속/재열람/삭제
  - `ConversationInputHandler` — 모드 선택 + 자연어 질의 + 첨부 인테이크·검증
  - `AttachmentIngestor` — 첨부 무해화 + doc-model 파이프라인 재사용 파싱(U7)
  - `MultiPaperRetriever` — 질의→U2 검색→교차확인 후보 집합("유사논문 검색" 노드). **출력 = 후보(최소 paper_id+score)**; **block_id locator는 권장 옵션**(시드)
  - `EvidenceExtractor` — doc-model 섹션 읽기 → 논문별 {주장·방법·결과·한계} 추출(U7 6단계 노드 재사용, block-id 앵커 부착). **locator 있으면 시드로 섹션 확장**, 없으면 섹션/문서 단위 읽기
  - `CrossCheckSynthesizer` — 다논문 추출 정렬·비교(합의/상충/공백) → 근거표(추출·비교만, 생성 금지)
  - `AgentGroundingAdapter` — U6 `enforce(candidate, retrieved)` 입력 정형화·verdict 매핑(재구현 금지)
  - `EvidenceTableAssembler` — 출력 스키마 조립·종단 상태(부분/기권/저하)
  - `AgentCostGuardAdapter` — U6 `getBudgetState` 저하 분기(독자 판정 금지)
  - `AgentProgressReporter` — 진행상태·부분결과(NFR-P5)
  - `ResearchResultStore` — 세션·근거표·첨부 owner-scoped 영속·캐시 신원
  - `AgentTelemetryPublisher` — 모드별 호출·지연·기권/저하·비용 라인 관측 이벤트(US-RA7)
  - *(모드 B seam, 차기)* `NoveltyComparator` — 유사논문 비교(빌드 안 함, 포트 자리만)

---

## 2. Functional Design 실행 계획 (Step 2 — 답변 확정 후 수행, 체크박스)

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u11-research-agent/functional-design/`에 작성한다.

- [x] **domain-entities.md** *(생성 완료)*
  - `ResearchSession` / `ConversationTurn` (세션·턴 시퀀스, owner-scoped)
  - `AgentMode` (modeA_evidence | modeB_novelty[차기])
  - `AgentQuery` / `Attachment` / `AttachmentRef` (대화 입력·첨부)
  - `PaperCandidate` / `CandidateSet` (다논문 검색 결과 — `paperId`+score; **선택적 `BlockLocator{section·blockId·score}[]`** 권장 옵션)
  - `PaperEvidence` (논문별 추출 — 주장·방법·결과수치·한계 + `Anchor[]`)
  - `EvidenceTable` / `EvidenceRow` / `CrossCheckTag`(합의/상충/공백) — 출력 스키마(§Q5)
  - `AgentGroundingInput` / `AgentGroundingVerdict` (U6 `enforce` 입출력 매핑)
  - `AgentResponse` (종단 union: EvidenceTable | Partial | Abstain | CostDegraded | InputRejected)
  - `ResearchResult` / `ResultRef` (영속 결과 신원)
  - `AgentCacheKey` (immutable 캐시 신원)
  - `AgentError`
- [x] **business-logic-model.md** *(생성 완료)*
  - `startSession(userId, mode)` / `appendTurn(sessionId, query, attachments)`
  - `runEvidenceFormation(turn)` — 파이프라인: retrieve→extract(논문별)→crossCheck→ground(enforce)→assemble
  - `retrieveCandidates(query, attachmentContext)` (U2 재사용 — 후보 paper_id; 선택적 block_id locator)
  - `extractPaperEvidence(candidate)` (doc-model 섹션 읽기·locator 있으면 시드 확장·U7 추출 노드 재사용)
  - `crossCheck(evidences[])` (합의/상충/공백 — 추출·비교만)
  - `enforceGrounding(table, candidateSet)` (U6 `enforce` — 항목별 기권)
  - `applyCostGate(context)` (U6 `getBudgetState`)
  - `reportProgress` / `assemblePartial` (NFR-P5 부분결과)
  - `listSessions(userId)` / `reopenSession(sessionId)` / `deleteSession` / `deleteAttachment` / `resetHistory`
  - `lookupCache(key)` / `persistResult(result)`
  - (모드 B seam) `compareNovelty(...)` — placeholder, 차기
  - 실패 경로: 비차단 저하·부분결과·기권
- [x] **business-rules.md** *(생성 완료 — BR-RA-1~18·INV·QT-8·추적성)*
  - 로그인 필수·owner-scoped 접근 규칙(SEC-8)
  - 첨부 검증·무해화 규칙(SEC-5/11)·허용 형식/크기 거부
  - 추출·비교 경계 규칙(C-2 — 생성 산문 금지)
  - 재현성 비판정 규칙(사실 추출만)
  - 단일 근거화 권위 규칙(U6 `enforce` 재사용·재구현 금지)·항목별 기권·날조 0건
  - 다논문 교차확인 불변식(동일 입력 집합→동일 비교 결과)
  - 비용 게이트 규칙(U6 `getBudgetState`·중복 호출 캐시 차단)
  - 비차단 저하 규칙(NFR-P5·RES-9·FR-11)
  - 세션·결과 영속/삭제/초기화 규칙(FR-25·Q14=B)
  - 모드 B 경계 규칙(v1 미빌드)
  - QT-8 속성 후보·추적성 매트릭스
- [x] **frontend-components.md** *(Q15=B — 생성 완료)*: 네비 진입·모드 선택·대화 입력+첨부·스트리밍/진행상태·근거표 렌더(표/수식/캡션)·세션 리스트·삭제/초기화. 구현은 별도 `u11-research-agent-frontend` 트랙 예고.

---

## 3. 가정 (명시 — 잘못이면 §4 또는 별도 지적으로 정정 요청)

> **공통**: 아래 가정은 *기본값*이다. U11 목표상 필요하면 위 설계 스탠스에 따라 기존을 변경할 수 있고, 그 경우 해당 질문에서 blast-radius를 명시한다.

- **AS-1**: U11은 **API 모듈**이며 별도 배포 서비스를 새로 만들지 않는다(배포 단위 ①, 긴 다논문 분석만 비동기 잡 옵션 ③ — U7 잡 패턴 재사용). *(기본값.)*
- **AS-2**: U11은 U6 게이트웨이 단일 진입(authn/authz/rate-limit)을 통과한다. **근거화의 단일 권위는 U6**(정책: 근거 없으면 기권·날조 0건), 비용 단일 권위도 U6다. 기본은 `enforce`/`getBudgetState` **소비**이되, 다논문 형상에 맞춰 **U6/shared-ports를 확장**한다. **근거화는 U6로 통일하며, U7이 따로 둔 근거화(`AnchorVerdict`)도 U6 공유 계약으로 이관·수정한다(확정 — Q7).** 형상·이관 범위는 Q7.
- **AS-3** *(2026-06-24 결정 — doc-model 전문 기반 전환)*: **검색 인덱스·근거 모두 doc-model에서 파생**(기원 하나·중복 파이프라인 없음)하되, **런타임은 분리** — `OpenSearch(찾기)→후보+locator→doc-model(근거)`. doc-model을 **eager 생성**(D6 되돌림)하고 **논문 전체(제목+초록+본문, 표=데이터·수식=latex·캡션, +각주·서지메타 보강·DF-6)** 를 담은 뒤, 그 전문을 **OpenSearch 통합 인덱스로 재구축**(제목+초록만 인덱스 폐기, #136 되돌림; U2 검색·U11 공유). 후보 선정=전문 인덱스 검색(A+ 다중쿼리·최소 paper_id; **block_id locator는 권장 옵션**, Q2), 근거 추출=doc-model 섹션 읽기(locator 있으면 시드 확장·block-id 앵커, Q3). **표·수식·캡션이 찾기·근거에 first-class.** 이 전환은 교차 아키텍처 변경이라 **별도 게이트로 관리**(blast-radius: U1·U2·infra·NFR-C1; §6). 논문별 추출은 U7 *배관 노드* 재사용 + **U11 전용 추출 노드**(Q1/Q3). **구조화 인용(출처논문)은 U8 영역·v1 범위 밖**(참고문헌 섹션 텍스트는 doc-model에 평문으로 포함).
- **AS-4**: U11은 추출·비교만 한다. 사용자 원고·문헌리뷰·연구 갭 **산문 생성은 하지 않는다**(C-2). 재현성은 **판정/계산하지 않는다**. *(목표 불변 — 변경 대상 아님.)*
- **AS-5**: 모드 B(novelty)는 **v1 빌드 대상이 아니다**(Q4=A). 본 FD는 모드 B의 도메인/포트 seam만 남기고 외부 학술 API·커버리지 확장은 차기로 미룬다.
- **AS-6** *(Q15=B)*: 전용 네비 메뉴·세션 리스트·모드 선택·대화/스트리밍 화면은 **U11 풀 버티컬의 일부로 프런트엔드까지 진행**한다(U7 `u7-summarization-frontend` 선례). U11 FD에서 `frontend-components.md`를 생성하고, Construction에서 **별도 `u11-research-agent-frontend` 트랙**으로 구현한다.
- **AS-7**: U9 개인화 신호 소비는 **비차단**이다(persona/관심 신호 실패가 본 기능 실패로 승격하지 않음).

---

## 4. 명확화 질문 (Step 3 — `[Answer]:` 태그로 답변; 미답 시 진행 불가)

> 각 질문은 권장안(A)을 제시한다. 권장안 채택 시 `A`, 변경 시 `B/C/X(+사유)`로 답해 주세요.

### Q1 — 에이전트 파이프라인 노드 구성 (line 374) · 기존 변경 범위
모드 A 흐름을 어떻게 잡고, 기존 U7 파이프라인을 어디까지 손댈까요?

> 두 갈래: **변경 없음(재사용)** vs **확장(blast-radius 명시)**. 공통 골격은 `[U6 게이트] → [캐시] → [비용 게이트] → 유사논문 검색(U2) → 논문별 추출(U7 2·3·6단계) → 교차확인 합성 → 근거화 → 조립·영속·관측`이며, 단일 논문 대신 **후보 논문 집합 fan-out 후 합성**이 핵심 신규.

A) **변경 없음 — U7 노드 그대로 재사용 + "유사논문 검색"·"교차확인 합성"만 신규 추가(권장 기본)**. U7 파이프라인 코드/FD 무변경. 🚫 자율 에이전트 루프는 안 함(목표 절제).

A+) **확장 — U7 추출 노드를 다논문 fan-out용으로 일반화**. U7의 단일-논문 추출 노드를 "논문 집합" 입력까지 받도록 공통화(공유 추출 컴포넌트로 승격). **blast-radius**: U7 `business-logic-model.md`(추출 노드 시그니처)·`shared/` 추출 계약 편집 + U7 회귀 검증. 에이전트·U7이 한 추출 엔진을 공유해 중복 제거.

B) U7 파이프라인을 참고만 하고 에이전트 전용 흐름을 **완전 별도**로 정의한다(재사용 안 함).

C) 단순 RAG(검색→단일 LLM 호출) 한 단계로 압축한다.

X) 기타.

**[색인·추출 소스 — 2026-06-24 사용자 결정: doc-model 전문 기반 통합 인덱스] ★아키텍처 변경★**: 앞선 "corpus-v1=초록만·doc-model lazy" 전제를 의식적으로 뒤집는다. 결정: **(1) doc-model을 전 논문 eager 생성**(D6 lazy 되돌림)하고 **논문 전체(제목+초록+본문, 표=데이터·수식=latex·그림 캡션, +각주·서지메타 보강 — 게이트 DF-6)** 를 담는다. **(2) 그 doc-model에서 평탄화한 전문을 OpenSearch 통합 인덱스에 색인**(#136 초록만 되돌림 — **현 "제목+초록만" 인덱스 콘텐츠는 사실상 폐기·재구축**). **U2 검색·U11 에이전트가 단일 인덱스 공유.** **기원은 doc-model 하나**(검색 인덱스·근거 모두 doc-model에서 파생 — 중복 파이프라인 없음)이되, **런타임 흐름은 분리**: `OpenSearch(진입·찾기) → 후보(최소 paper_id) → doc-model(내용·근거 원천) → 근거 생성`. **block_id locator(`section·block_id·score`)는 권장 최적화 옵션**(있으면 추출 시드 → 섹션 확장; 토큰↓·속도↑·비용↓·앵커 사전확보) — **확정 아님**(색인 granularity=GQ1 실험에 종속). 이유: 표·수식·캡션을 *찾기·근거*에 first-class로. **U11 단독 결정 아님 → 별도 게이트 `docmodel-fulltext-index-pivot-plan.md`로 관리**(blast-radius: U1 인제스천·U2 검색·OpenSearch 노드·NFR-C1 비용 추정 +$100~220/월; §6). 커밋 `982f64a`(전문 임베딩 복원, 미승인)는 본 결정으로 *정식 게이트로 승격*해 제대로 수행(소스=doc-model·infra resize·비용 갱신).

[Answer]: **A(파이프라인) + doc-model 전문 통합 인덱스·eager(아키텍처)** *(사용자 2026-06-24)* — 파이프라인: U7 **배관 노드**(doc-model fetch·정제·앵커·근거화) 재사용 + **U11 전용 근거 추출 노드 신규**(U7 요약 노드 리팩터 안 함). 색인/추출 소스 = **eager doc-model(논문 전체) 하나** → OpenSearch 통합 인덱스 재구축. blast-radius·비용·각주/메타 보강은 게이트 문서.

### Q2 — 다논문 후보 선정 (유사논문 검색 노드) · 기존 변경 범위
교차확인할 논문 집합을 어떻게 정하고, 기존 U2 검색을 어디까지 손댈까요?

> 후보 선정은 corpus-v1(**제목+초록 임베딩**)으로 한다 — 유사논문 *발견*엔 제목+초록 의미·어휘 검색이 적합(본문 추출은 이후 S3 경로, Q1).

A) **변경 없음 — U2 검색(RRF·PaperId 디덥) top-K 단발 재사용**. 질의(+첨부 맥락)를 U2에 넣어 상위 후보를 받고 PaperId 디덥. K 상한은 bounded(수치는 NFR). 빈 결과는 빈 성공 금지 — 명시적 기권. U2 무변경.

A+) **확장 — 교차확인 다양성을 위해 bounded 다중쿼리(권장)**. 질의·첨부를 하위질의로 분해해 U2를 **여러 번** 호출·후보 합집합(여전히 U2 위, 자율 반복 루프 X). U2 검색 API가 단발만 가정하면 **blast-radius**: U2 인터페이스에 batch/multi-query 진입 추가(U2 FD·`api` 편집) 또는 U11에서 호출만 반복(U2 무변경). 둘 중 어느 쪽인지는 NFR/Code에서 확정.

B) 사용자가 논문을 직접 골라 넣게 한다.

C) 코퍼스 전수 스캔/임베딩 클러스터링으로 후보를 만든다(별도 검색 경로 신설). **← 에이전트가 U2와 별개 검색·클러스터링 서브시스템을 키우는 오버엔지니어링 위험(사용자 우려 지점) — 기각.**

X) 기타.

[Answer]: **A+** *(사용자 2026-06-24)* — 전문 통합 인덱스(doc-model 기반) 위에서 bounded 다중쿼리(질의·첨부 분해→U2 여러 번→후보 합집합). C(별도 클러스터링 엔진)는 오버엔지니어링으로 기각. **검색 출력 = 최소 후보(paper_id+score)**; **block_id locator(`section·block_id·score`)는 권장 최적화 옵션**(있으면 추출 시드→섹션 확장; 토큰/속도/비용↓·앵커 사전확보). locator 채택·granularity는 **DF-5/GQ1(실험)** — 확정 아님.

### Q3 — 논문별 근거 추출 (extract 노드)
각 후보 논문에서 무엇을, 어떻게 뽑을까요?

A) **U7 doc-model 추출 노드 재사용(권장)** — 논문별 doc-model에서 **{핵심 주장·방법·결과 수치·한계}**를 추출하고 각 항목에 **앵커(doc-model id/섹션·span)**를 부착. 추출 실패/근거 없음 항목은 비우고 기권 후보로 표시. (선택적 "코드/데이터 공개 사실"은 한계/메타로만 — 재현성 판정 아님.)

B) 초록만 가지고 추출한다(전문 멀티청크 미사용).

C) 자유 형식 요약문 한 덩어리로 뽑는다(필드 비구조화).

X) 기타.

[Answer]: **A** *(권장)* — 추출은 eager doc-model에서(표 셀 값·수식 latex·캡션·각주 포함, block-id 앵커). U7 요약 노드 리팩터 아님 — U11 전용 추출 노드.

### Q4 — 교차확인(cross-check)의 비즈니스 의미
여러 논문의 추출 근거를 어떻게 비교할까요?

A) **합의/상충/공백을 추출 근거 위에 태깅(권장)** — 동일 주제축(주장·방법·결과)에서 논문 간 **합의(agreement)·상충(contradiction)·공백(gap)**을 표시하되, **새로운 결론 산문을 생성하지 않는다**(추출된 항목의 정렬·대조만 — C-2). 비교 근거 역시 각 논문 출처로 환원.

B) 합의/상충 판단 없이 논문별 추출만 나열한다.

C) LLM이 종합 결론 문단을 작성한다. *(C-2 위반 — 비권장)*

X) 기타.

[Answer]: **A** *(권장)*

### Q5 — 근거표(Evidence Table) 출력 스키마 ★핵심 결정★
근거 비교 정리의 출력 형태를 어떤 컬럼 구조로 고정할까요?

A) **논문 비교형 표 + 쟁점 오버레이(권장)** — 기본 행=논문, 열=`{핵심 주장 · 방법 · 결과 수치 · 한계 · 출처(앵커)}`; 그 위에 Q4의 합의/상충/공백을 **쟁점 태그**로 오버레이. FR-22 필드 직접 매핑 + 교차확인 가시화.

B) **쟁점 매트릭스 전용** — 행=쟁점/질문, 열=논문별 입장. 교차확인은 선명하나 논문별 방법/한계 필드가 부차화.

C) **최소 근거 리스트** — 표 없이 `{항목 · 근거 문장 · 출처}` flat 리스트.

X) 기타(컬럼 직접 지정).

[Answer]: **A** *(사용자 2026-06-24 — 구조 불변; 전문 인덱스·eager doc-model 결정으로 셀 내용만 강화: "결과 수치" 칸에 표 셀 값·수식 latex·그림 캡션을 block-id 앵커로 first-class 수록.)*

### Q6 — 첨부 문서의 역할
첨부한 초안/논문을 파이프라인에서 어떻게 쓸까요?

A) **질의·비교 기준(분석 대상)으로만(권장)** — 첨부는 doc-model로 파싱해 **질의 맥락/비교 기준**으로 쓰고, **근거 소스는 owned 코퍼스**(검증 가능한 출처)로 한정. 첨부 자체를 근거 출처로 인용하지 않음(외부 미검증 텍스트 그라운딩 방지).

B) 첨부 본문도 근거 소스 코퍼스에 합류시켜 인용한다.

C) 첨부는 키워드만 추출해 검색어로만 쓴다.

X) 기타.

[Answer]: **A** *(권장)*

### Q7 — 근거화 패턴 선택 + 항목별 기권 ★핵심 결정★ · 기존 변경 범위
다논문 근거표를 어떤 근거화로 검증할까요? **정책(근거 없으면 기권·날조 0건·결정적 검증·U6 단일 권위)은 불변**, 결정할 건 **메커니즘/형상**입니다. (U7 선례: 검색=`enforce(candidate, retrieved)`, 단일 논문 문서충실도는 형상이 안 맞아 U7이 자기 `AnchorVerdict`를 별도 정의 — 그래도 단일 권위는 유지.)

A) **확장 — U6 `enforce`를 다논문까지 포괄하도록 U6/shared-ports 확장(권장)**. `retrieved`=교차확인 후보 논문 집합의 doc-model 청크, `candidate`=근거표 항목. 항목별 매핑·검증·기권을 **U6 권위로** 수행하고, 시그니처가 다논문에 안 맞으면 U6가 형상을 넓힌다. **근거 못 붙은 항목만 기권(부분 제시)**, 표 전체를 안 죽임(US-RA6). U11은 정형화·매핑만(재구현 금지). **blast-radius**: `shared/ports.md`(`enforce` 시그니처 FROZEN 해제·다논문 오버로드)·U6 `functional-design`·U6 회귀 검증.

A0) **변경 없음 — 현 `enforce(candidate, retrieved)` 시그니처 그대로**에 후보 논문 집합을 `retrieved`로 욱여넣어 호출(U6/ports 무변경). 형상이 어색할 수 있음(검색용 설계).

B) **U11 내부 결정적 검증(U7식 `AnchorVerdict` 다논문판)** — U6 정책을 따르되 다논문 문서충실도 체크를 U11 안에 둠. U6 권위 위임이 약해질 위험 → 단일 권위 훼손 주의.

C) 표 전체를 한 번에 통과/기권(항목별 분리 없음).

X) 기타.

[Answer]: **A** *(사용자 2026-06-24 — U6 근거화 통일·확정)* — 근거화는 **U6 단일 권위로 통일**한다. U6 계약을 **(1) 검색 enforce + (2) 문서충실도(단일 논문=U7, 다논문=U11)** 를 포괄하도록 **업그레이드(필요시 형상 확장)** 하고, 그 **공유 계약을 `shared/`(U6)에 둔다**. **U11은 이 계약을 채택**하고, **U7이 따로 둔 근거화(`AnchorVerdict`)도 이 통합 계약으로 이관·수정한다 — "선택/후속"이 아니라 확정 작업**(설계 스탠스: 필요시 기존 구조 수정). 검색용 `enforce` 시그니처에 욱여넣기 아님 — *문서충실도* 메커니즘. **blast-radius**: `shared/ports.md`(근거화 계약 확장)·U6 FD·**U7 FD/코드(배포됨 — 근거화 이관 + 회귀 검증)**. ⇒ U7도 더는 자체 근거화를 갖지 않고 U6 공유 계약을 소비.

### Q8 — 멀티턴 대화 맥락
세션 내 후속 질의는 이전 턴을 어떻게 이어받을까요?

A) **세션=턴 시퀀스, 매 턴 재그라운딩(권장)** — 후속 턴 입력=현재 질의+첨부+(요약된) 이전 맥락. 단, 근거표는 **매 턴 실제 코퍼스에서 재추출·재그라운딩**하고 과거 생성물을 출처처럼 재인용하지 않는다(누적 환각 방지).

B) 이전 턴 근거표를 그대로 누적 인용한다.

C) 멀티턴 없이 매 질의를 독립 단발로 처리한다.

X) 기타.

[Answer]: **A** *(권장)*

### Q9 — 종단 상태(응답 union)
모드 A 응답의 종단 상태를 어떻게 나눌까요?

A) **5종 union(권장)** — `EvidenceTableDTO`(완전) · `PartialResultDTO`(진행 중/일부 소스 실패) · `AbstainDTO`(근거 없음/코퍼스 밖) · `CostDegradedDTO`(비용 게이트 기권·FR-11) · `InputRejectedDTO`(첨부 검증 실패). 빈 성공 금지(기권 vs 빈결과 구분).

B) 성공/실패 2종만.

C) 성공 + 기권 + 오류 3종.

X) 기타.

[Answer]: **A** *(권장)*

### Q10 — 비용 게이트 동작
U6 비용 상태에 따라 어떻게 분기할까요?

A) **U6 `getBudgetState` 소비·중복 캐시 차단(권장)** — `NORMAL`→진행, `OPEN/LEXICAL_ONLY`→`CostDegradedDTO` 기권(FR-11 명시 상태). 동일 캐시 키(§Q11) 질의는 LLM 0콜 재사용. U11은 독자 비용 판정 안 함(NFR-C1 Agent 라인 별도 계상).

B) U11이 자체 비용 카운터로 판정한다. *(단일 권위 위반 — 비권장)*

C) 비용 게이트 없이 항상 진행한다.

X) 기타.

[Answer]: **A** *(권장)*

### Q11 — 캐시 신원(immutable key)
무엇을 같은 분석으로 보고 재사용할까요?

A) **결정적 immutable 키(권장)** — `(정규화 질의 · 모드 · 첨부 콘텐츠 해시 · 코퍼스 스냅샷 · 모델/프롬프트 버전 · persona?)`. **단일 턴 다논문 분석만 캐시**(멀티턴 대화 자체는 캐시 아님 — 세션 영속으로 별도 관리). 버전 변경 시 무효화.

B) 질의 문자열만 키로 쓴다.

C) 캐시하지 않는다(매번 재생성).

X) 기타.

[Answer]: **A** *(권장 — Q11 "코퍼스 스냅샷"은 전문 인덱스/doc-model 버전으로 해석)*

### Q12 — 세션·결과·첨부 영속 + 삭제/초기화 제어 (Q14=B 준수)
영속과 사용자 제어를 어떻게 나눌까요?

A) **owner-scoped 무기한 보관 + 분리 제어(권장)** — `ResearchSession`/`ConversationTurn`/`EvidenceTable`/`Attachment`를 owner-scoped 영속·재열람. 사용자 제어 **분리**: `deleteSession`(세션·결과) · `deleteAttachment`(첨부 원본) · `resetHistory`(전체 초기화). 무기한 보관은 명시적 정책(차기 재검토 여지).

B) 단일 "전체 삭제" 액션만 제공.

C) 결과만 저장하고 첨부는 분석 후 즉시 폐기.

X) 기타.

[Answer]: **A** *(권장)*

### Q13 — 개인화(U9) 신호 소비
개인화를 어디까지, 어떻게 쓸까요?

A) **비차단 약신호만(권장)** — persona/관심 프로필을 **모드 기본 제안·근거표 정렬 힌트**에만 약하게 반영. U9 실패/부재 시 무개인화로 진행(본 기능 비차단). 검색 강한 리랭크/추천은 안 함.

B) 개인화로 근거표 내용 자체를 바꾼다.

C) v1에서 개인화 신호를 쓰지 않는다.

X) 기타.

[Answer]: **A** *(권장)*

### Q14 — 모드 B(novelty) 경계 처리
차기 모드 B를 FD에서 어디까지 남길까요?

A) **도메인/포트 seam만, 빌드 안 함(권장)** — `AgentMode.modeB_novelty`·`NoveltyComparator` 포트 자리·외부 학술 코퍼스 포트 placeholder만 표시하고 **로직·외부 API·커버리지 확장은 차기**(Q4=A·Q5=B 커버리지). business-rules에 "v1 미빌드" 경계 규칙 명시.

B) 모드 B 도메인/규칙까지 전부 설계한다(빌드만 보류).

C) 모드 B 흔적을 FD에 전혀 남기지 않는다.

X) 기타.

[Answer]: **A** *(권장)*

### Q15 — `frontend-components.md` 생성 여부
U11 FD에서 프런트엔드 산출물을 만들까요?

A) **만들지 않는다(권장)** — U11=API 모듈. 전용 네비 메뉴·세션 리스트·모드 선택·대화/스트리밍 UI는 **프런트엔드 유닛 책임**(U5 또는 U7식 별도 `*-frontend` 트랙은 Construction에서 결정). U11 FD는 UI **계약**만 business logic/rules에 기록.

B) U11 폴더에 `frontend-components.md`를 만든다(에이전트 UI가 신규·실질적이므로).

X) 기타.

[Answer]: **B** *(사용자 2026-06-24)* — 풀 버티컬. `frontend-components.md` 생성 + 별도 `u11-research-agent-frontend` 트랙(U7 선례).

### Q16 — QT-8 속성(PBT) 후보 범위
Functional Design에서 QT-8 후보를 어디까지 고정할까요?

A) **6종(권장)** — 근거표/DTO roundtrip · **기권 안정성**(근거 없으면 항상 기권·날조 0건) · owner isolation · 캐시 키 immutability/dedupe · 부분결과 불변식(완전≠부분 혼동 금지) · 출처 링크 유효성. PBT는 기존 Partial 모드 유지.

B) DTO roundtrip만.

C) QT-8은 Code Generation에서만 결정.

X) 기타.

[Answer]: **A** *(권장)*

### Q17 — Construction 구현 전략(이월 항목 처리 방침)
NFR/Infra/Code로 넘길 기술 결정을 FD에서 어떻게 표기할까요?

A) **모드 A 우선·재사용 명시·기술은 후속 단계로 이월(권장)** — FD는 도메인/로직/규칙만 고정하고, **외부 학술 API 선택·LLM 모델(게이트웨이 재사용)·스토리지(RDS/오브젝트)·잡 큐·스트리밍 프로토콜·캐시 백엔드**는 NFR/Infra로 이월한다고 각 산출물에 명시. U7(파이프라인·근거 추출)·U6(게이트웨이·enforce·CostGuard)·U2(검색)·U8(외부 API 캐시 패턴, 모드 B 예약) 재사용 지점을 추적성에 박는다.

B) FD에서 기술 결정까지 일부 선확정한다.

X) 기타.

[Answer]: **A** *(권장)* — 단, doc-model 전문 통합 인덱스·eager 전환(Q1)은 NFR/Infra가 아니라 **별도 아키텍처 게이트**에서 확정(§6).

---

## 5. 결정 예정 불변식 (질문 아님 — 명백한 정답, 투명성 위해 명시; 이견 시 지적)

- **INV-U11-1**: U11의 모든 진입은 **로그인 필수·owner-scoped**다(SEC-8, U6 게이트웨이).
- **INV-U11-2**: 근거화 **단일 권위 = U6**(정책 불변: 근거 없으면 **기권**·날조 **0건**·결정적 검증). U11은 정형화·매핑만 하고 **권위를 우회·재구현하지 않는다**. 다논문에 맞춘 **메커니즘/형상 확장은 U6/shared-ports 변경으로** 처리(Q7) — 권위는 U6 유지.
- **INV-U11-3**: U11은 **추출·비교만** 한다. 사용자 원고·문헌리뷰·연구 갭 **산문 생성 금지**(C-2). **재현성 판정/계산 금지**. *(목표 불변.)*
- **INV-U11-4**: 비용 **단일 권위 = U6**. U11은 조회·분기만, 독자 비용 판정 안 함(메커니즘 확장 시에도 권위는 U6).
- **INV-U11-5**: U11 실패/저하는 본 검색(U2) 등 다른 기능을 막지 않는다(비차단·NFR-P5). 부분결과·진행상태 허용, 빈 성공 금지.
- **INV-U11-6**: 결과·세션·첨부는 owner-scoped 영속이며 사용자 삭제/초기화 제어를 분리 제공한다(FR-25·Q14=B).
- **INV-U11-7**: v1은 **모드 A만 빌드**한다. 모드 B(novelty)는 seam만 남기고 다음 사이클(Q4=A).

---

## 6. 현재 상태와 다음 절차

**Q1~Q17 전부 확정(2026-06-24)**: Q1=A+doc-model 전문 통합 인덱스·eager(아키텍처) · Q2=A+ · Q3=A · Q4=A · Q5=A · Q6=A · **Q7=A(U6 통합·단계적)** · Q8~Q14=A · **Q15=B(풀 버티컬)** · Q16=A · Q17=A.

### 6.1 ★선결 게이트★ — doc-model 전문 통합 인덱스 + eager (아키텍처 reversal)
Q1 결정은 U11 단독 범위를 넘어 **본인이 리뷰·승인했던 #136(초록만)과 D6(doc-model lazy)를 되돌린다.** FD 산출물 생성 **전에** 별도 게이트로 명시·승인한다:
- 문서: `aidlc-docs/construction/plans/docmodel-fulltext-index-pivot-plan.md`
- 내용: DF-1(전문 통합 인덱스·U2/U11 공유)·DF-2(eager doc-model)·DF-3(근거화 정합)·DF-4(`982f64a` 승격)·DF-5(색인 granularity)·**DF-6(doc-model 완전성 — 각주 별도 블록 포함·서지메타[저자·발행일·카테고리] 보강·구조화 인용은 U8 이월)** · blast-radius(U1·U2·infra·NFR-C1) · **비용 추정(월 +$100~220, 실측은 배포 후)** · SSOT back-sync · 열린 질문 GQ1~4.

### 6.2 절차
1. **Part 1(본 계획서) 답변 확정 완료.**
2. **6.1 게이트 문서 승인** (교차 유닛·비용 변경이므로 선행).
3. 게이트 승인 후 **Part 2**에서 `u11-research-agent/functional-design/`의 `domain-entities.md`·`business-logic-model.md`·`business-rules.md`·`frontend-components.md`(Q15=B) 생성.
4. FD 승인 후 **NFR Requirements**(전문 인덱스 사이징·외부 API·LLM 모델·보안·운영·테스트).
5. 커밋·푸시·PR(#183 갱신)은 **사용자 명시 승인 후**에만 진행한다.
