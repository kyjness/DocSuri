# u2-discovery-code-generation-plan.md — Code Generation 계획 (Part 1) + 승인 게이트

**단계**: CONSTRUCTION → Code Generation (유닛별 루프, U2 · **mock-first**) · **유닛**: U2 Discovery · **트랙**: Track 3(@kyjness) · **일자**: 2026-06-16
**근거**: `construction/u2-discovery/{functional-design,nfr-requirements,nfr-design}/`(전부 승인) · `shared/python`(docsuri_shared 계약) · `project-structure-and-parallel-dev.md`(코드 위치·소유)
**원칙(code-generation.md)**: 본 계획이 생성의 **단일 진실 원천(SSOT)**. 승인 전 코드 미생성. 단계 번호순·스토리 추적·계약 정합. 애플리케이션 코드=`backend/modules/discovery/`(절대 aidlc-docs/ 아님); 문서 요약=`aidlc-docs/construction/u2-discovery/code/`.
**mock-first 범위**: U2의 **실(real) 비즈니스 로직 전부 + mock 어댑터/스텁**을 생성한다. real 어댑터(opensearch-py·Bedrock)는 포트 뒤 **인터페이스만**(U1 코퍼스·OpenSearch·Bedrock·Infra 후 교체, MR-1/4). U5는 동일 `SearchResponse` 계약 mock으로 병렬.

---

## 1. 유닛 컨텍스트 (Step 1)

- **책임**: 동기 검색 읽기 경로(검증→확장→하이브리드 검색→랭킹→근거화 정형/매핑→조립) + 비차단 SearchExecuted 발행.
- **스토리**: US-D1(검증)·US-D2(확장+검색)·US-D3(랭킹)·US-D4(카드 조립)·US-D6(기권). 기여: US-D5/D7/R1/R2(근거화 정형·저하)·US-L3(SearchExecuted 생산).
- **계약 정합(docsuri_shared)**: DTO=`docsuri_shared.dtos`(SearchRequest·SearchResponse[RootModel union]·SearchResultPageDTO·AbstainDTO·DegradedResultDTO·ValidationErrorDTO·ResultCardVM·ResultMeta·DegradationMode) · IndexRecord/EMBEDDING_SPEC/assert_same_space=`docsuri_shared.vector_spec` · 포트=`docsuri_shared.ports`(GroundingEnforcementHook.enforce·CostGuardCircuitBreaker.get_budget_state·ObservabilityHub.emit_*) · SearchExecutedEvent=`docsuri_shared.events`. **DTO 필드는 camelCase**(arxivId·abstractSnippet·arxivUrl·resultCount·degradationMode); 카드 7필드만(SEC-9).
- **불변식**: INV-1(U2 enforce 미호출 — 포트 주입·매핑만)·INV-2(SEC-9 비노출)·INV-3(fail-closed). 단일 권위(근거화·비용·인증·레이트리밋=U6).

---

## 2. 코드 구조 (생성 대상 — `backend/modules/discovery/`)

```text
backend/modules/discovery/
├── README.md                     # (기존 레인 마커 — 갱신)
├── pyproject.toml                # ⏳ 모듈 로컬(uv) — docsuri_shared path dep + 테스트 deps. backend 통합 pyproject은 app-shell(@ELSAPHABA) 소관(잠정·DS-3)
├── src/discovery/
│   ├── __init__.py
│   ├── domain/
│   │   ├── models.py             # 내부 도메인 엔티티(NormalizedQuery·QueryPlan·DegradationSignal·Candidate·CandidateSet·RankedResults·GroundedResults·AbstainResult) — shared 아님
│   │   ├── validator.py          # QueryValidator.validate/normalize (NFC·≤500·제어문자, PBT-02)  [US-D1·SEC-5]
│   │   ├── expander.py           # QueryUnderstandingExpander.expand (임베딩 search_query + lexical; degrade)  [US-D2·FR-2]
│   │   ├── retriever.py          # HybridRetriever.retrieve (k-NN∥BM25 → RRF → PaperId 디덥, PBT-07)  [US-D2]
│   │   ├── ranker.py             # RelevanceRanker.rank (baseline 점수순 상위 N=20, PBT-03)  [US-D3]
│   │   ├── grounding_adapter.py  # GroundingAdapter.to_grounding_input/map_decision (INV-1)  [US-D5/D6]
│   │   └── assembler.py          # ResultAssembler.assemble (카드 7필드·SEC-9·종단 상태, PBT-09)  [US-D4·FR-11]
│   ├── ports/
│   │   └── search_ports.py       # VectorStoreAdapter·LexicalIndexAdapter·EmbeddingAdapter·EventPublisher Protocol(U2 고유 포트)
│   ├── cache/
│   │   └── embedding_cache.py    # read-through TTL 캐시(인메모리 mock; 공유 캐시는 Infra)
│   ├── service/
│   │   └── orchestrator.py       # SearchOrchestrationService.execute_search (동기 파이프라인+degrade 매트릭스) + publish_search_executed(비차단)  [전 스토리]
│   ├── mocks/
│   │   ├── fixtures.py           # 샘플 IndexRecord 집합(QT-2 평가셋 + 한국어↔영어 cross-lingual, MR-2)
│   │   ├── adapters.py           # MockVectorStore/Lexical/Embedding 어댑터(결정적)
│   │   └── port_stubs.py         # StubGroundingHook(pass-through+abstain)·StubCostGuard(NORMAL)·NoopObservability·InMemoryEventPublisher (MR-3)
│   └── api/
│       └── router.py             # QueryIntakeController — FastAPI 라우터(thin; ⏳ FastAPI 합의 전제, app-shell 마운트). 도메인은 FastAPI 없이도 동작
└── tests/
    ├── test_validator_pbt.py     # PBT-02 normalize 멱등/라운드트립(한국어 포함)
    ├── test_ranker_pbt.py        # PBT-03 랭킹 순서 안정성 + 상위 N 절단
    ├── test_retriever_pbt.py     # PBT-07 디덥 멱등(PaperId) + 결과셋 보존
    ├── test_dto_roundtrip_pbt.py # PBT-09 SearchResponse 4상태 라운드트립
    ├── test_orchestrator.py      # 종단 상태(성공/기권/저하/검증오류) + 인증 컨텍스트
    ├── test_degradation.py       # degrade 매트릭스(RERANK_OFF/LEXICAL_ONLY)
    └── test_fault_injection.py   # RES-12: 임베딩 장애→lexical 폴백 / 인덱스 장애→fail-closed
```

> **계약 import**: 외부 DTO/포트/IndexRecord는 `docsuri_shared`에서 import(포크 금지). U2 내부 엔티티(QueryPlan 등)만 `domain/models.py`에 정의.

---

## 3. 생성 단계 (Part 2에서 순차 실행 — 번호·체크박스·스토리)

- [x] **Step 1 — 프로젝트 구조**: `backend/modules/discovery/` 패키지 스켈레톤 + `pyproject.toml`(모듈 로컬 uv: `docsuri_shared` path dep·pytest·hypothesis; FastAPI는 optional extra) + `README.md` 갱신.
- [x] **Step 2 — 도메인 모델**: `domain/models.py`(NormalizedQuery·DegradationSignal·QueryPlan·Candidate·CandidateSet·RankedResults·GroundedResults·AbstainResult). [기반]
- [x] **Step 3 — U2 고유 포트**: `ports/search_ports.py`(VectorStoreAdapter·LexicalIndexAdapter·EmbeddingAdapter·EventPublisher Protocol).
- [x] **Step 4 — 비즈니스 로직(도메인 6 컴포넌트)**: validator·expander·retriever(RRF·PaperId 디덥)·ranker(N=20)·grounding_adapter(INV-1)·assembler(카드 7필드·SEC-9). [US-D1~D6]
- [x] **Step 5 — 캐시**: `cache/embedding_cache.py`(read-through·TTL·인메모리).
- [x] **Step 6 — 오케스트레이터**: `service/orchestrator.py`(execute_search 파이프라인 + degrade 매트릭스 + fail-fast/폴백 + publish_search_executed 비차단). [전 스토리·US-L3]
- [x] **Step 7 — mock 어댑터/스텁**: `mocks/`(fixtures 한국어 cross-lingual+QT-2 · 결정적 mock 어댑터 · 포트 스텁 pass-through/NORMAL/Noop/InMemory). [MR-2/3]
- [x] **Step 8 — API 라우터**: `api/router.py`(QueryIntakeController FastAPI thin 라우터 · 전역 예외 핸들러 SEC-15). ⏳ FastAPI 합의 전제 — 도메인은 라우터 없이도 import/test 가능.
- [x] **Step 9 — 단위/PBT 테스트**: `tests/`(PBT-02/03/07/09 + 종단 상태 + degrade + RES-12 폴트 인젝션). Hypothesis 도메인 제너레이터(다국어 질의).
- [x] **Step 10 — 문서**: `aidlc-docs/construction/u2-discovery/code/`(README·생성 요약·실행/테스트 방법). 코드 외 마크다운만.

> **NO HARDCODED LOGIC**: 본 계획 단계만 실행. 각 Step 완료 시 [x] 체크 + 해당 스토리 마킹.

---

## 4. 핵심 구현 결정 (FD/NFR 답변 반영 — 생성 시 준수)

- **RRF(BR-4)**: `score = Σ 1/(k + rank_i)`(k 기본값 상수, NFR 튜닝); **PaperId 단위 디덥**(같은 논문 복수 청크→최고 RRF 1건). 멱등·결과셋 보존(PBT-07).
- **relevance 표시값(BR-6/Q3)**: 카드 `relevance` = **1-based 순위 위치(표시 신호)**, raw/RRF 점수 비노출(SEC-9). (display 형태는 U5 연동 — 순위로 단순화.)
- **종단 상태(BR-9/Q4)**: 검증실패→ValidationErrorDTO; **verdict=abstain/block→AbstainDTO**(근거화 거부 전용); **후보 0/무매치→SearchResultPageDTO(cards=[], resultCount=0)**(명시적 빈 페이지 — 기권 ≠ 빈 결과, U5 B3-a); pass&결과≥1&NORMAL→SearchResultPageDTO; pass&결과≥1&저하→DegradedResultDTO. 무매치는 enforce 이전에 종단(기권 아님); 기권 우선은 enforce 후 verdict에만 적용(BR-10).
- **degrade 매트릭스(BR-11/Q6)**: get_budget_state().degrade_mode → NORMAL/RERANK_OFF(무변화·배너)/LEXICAL_ONLY(임베딩 생략·BM25). 의존성 장애 폴백(임베딩→lexical)은 degrade와 별개(BR-16/Q1·Q2).
- **인증(BR-13/Q5)**: orchestrator는 RequestContext.auth_session.user_id 신뢰(게이트웨이 강제); user_id로 SearchExecuted 발행.
- **fail-fast(Q1)**: 동기 외부 호출 재시도 최소; 임베딩 타임아웃→lexical 폴백, 인덱스 타임아웃→fail-closed. (mock은 결정적; 폴트 인젝션 테스트로 검증.)
- **chunk_id/SEC-9**: 내부 식별자·점수 외부 비노출; `docsuri_shared.ids.chunk_id`는 내부만.

---

## 5. 가정 · 조율 (잘못이면 지적)

- **CG-1 [backend-shared]**: `pyproject.toml`은 **모듈 로컬(잠정)** — Track3 단독 테스트 가능하게. backend 통합 패키징/워크스페이스·**FastAPI 확정**은 app-shell(@ELSAPHABA) 소관(DS-3). 합의 시 통합·재정합.
- **CG-2**: real 어댑터(opensearch-py·boto3 Bedrock)는 **본 단계 미구현**(포트 인터페이스만). Infra·U1 코퍼스 후 교체(MR-1/4).
- **CG-3**: U6 포트는 `docsuri_shared.ports`에 의존; mock 스텁은 테스트/로컬 전용(실 강제는 U6).
- **CG-4**: 수치(타임아웃·TTL·RRF k·동시성)는 상수+NFR/Infra 튜닝(설정 가능).
- **CG-5**: app-shell/middleware(U6)·라우터 마운트 결선은 조율 존 — 본 모듈은 `api/router.py` 라우터 객체만 제공(마운트는 app-shell).

---

## 6. 다음 절차

1. 본 계획(Part 1) 승인 대기 — **승인 전 코드 미생성**(code-generation.md Step 7).
2. 승인 시 Part 2: Step 1~10 순차 생성(체크박스 마킹) → 완료 메시지 + 리뷰 게이트.
3. 보안/복원력 준수 요약(SEC-5/9/15·RES-9/12·PBT)·테스트 실행 방법 포함.

> 본 계획은 **승인 게이트**입니다. 아직 코드 미생성·미커밋(백엔드 완료 후 커밋).
