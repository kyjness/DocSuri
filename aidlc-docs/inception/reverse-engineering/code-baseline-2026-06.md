# 코드 베이스라인 (Reverse-Engineering Baseline) — 2026-06

**단계**: INCEPTION 재진입 · 리버스 엔지니어링 · **작성일**: 2026-06-26 · **상태**: 초안(1차 패스) · **back-sync**: 2026-06-30(Phase 1 — GROBID TEI·S2/OpenAlex·소스별 watermark·DLQ/scheduler·DocModel eager 인덱싱 반영 / Phase 2 — U2 검색 정합·소스 중립 카드 Q2 완료 #244 반영 / **Phase 3 — U7 요약/번역 + Grounding 통합 완료 #249 반영**: GroundingValidatorRegistry 등재·수치 임계 재보정·번역 UX/persona·견고성 보강)
**상위 문서**: `aidlc-docs/inception/plans/reinception-2026-06-charter.md` (재인셉션 차터, SSOT 앵커)

> **목적**: 재인셉션(D1)의 사실 기준을 stale 문서가 아니라 **실제 코드**에서 확립한다
> (brownfield, `.aidlc-rule-details/inception/reverse-engineering.md`). 본 문서가 차터 §2
> 드리프트 표의 **정밀판**이며, 이후 requirements·application-design·units-generation이 이를 참조한다.
>
> **관찰 범위 주의**: 본 1차 패스는 **파일 구조·계약 스키마·`shared/ports` 인터페이스**를 코드에서
> 직접 확인한 결과다. 모듈 내부 거동(런타임 로직)은 파일 존재 수준으로만 기술하고, 단정이 필요한
> 부분은 "추가 확인 필요"로 표기한다. 발명하지 않는다.

---

## 1. 실제 패키지/배포 맵 (관찰됨)

```
<repo-root>/
|
+-- frontend/                  # U5 SSR (이번 패스 미베이스라인 — 별도 확인)
+-- backend/
|     +-- middleware/          # U6 게이트웨이: auth/gateway/rate_limit/request_context/security_headers/wiring
|     +-- modules/
|           +-- discovery/        (src-layout 별도 패키지 docsuri-discovery)
|           +-- summarization/    (src-layout 별도 패키지)
|           +-- citation_graph/   (controller.py만 — 얇음)
|           +-- personalization/  (controller/service/repository/models/maintenance)
|           +-- library/          (services/repository/authz/audit/history_consumer 등 풍부)
|           +-- accounts/         (services/repository/integrations 풍부)
|           +-- mypage/           (services/repository/ports — 코드 존재)  [문서엔 "미반영"]
|           +-- ops/              (controller.py만)  [top-level ops/와 별개]
+-- ingestion/                 # U1 워커 (docsuri_ingestion, src-layout)
+-- ops/                       # U6 ops 워커 (docsuri_ops) + cdk/ + migrations/
+-- shared/
      +-- dtos/        (JSON Schema: accounts/docmodel/library/mypage/search/summarization)
      +-- events/      (account-signals/incidents/ingestion/search-executed)
      +-- vector-spec/ (index-record.schema.json / vector-spec.yaml)
      +-- ports/       (README = 인터페이스 SSOT, 데이터 스키마 아님)
      +-- python/      (docsuri_shared: dtos/events/ports/vector_spec/ids + _generated 스텁)
```

> **U6 3분산 확인**: U6 책임이 **세 곳**에 산다 — ① `backend/middleware/`(게이트웨이),
> ② `backend/modules/ops/`(controller), ③ top-level `ops/`(탐지·대시보드 워커 + cdk + migrations).
> 차터 §5-4 "U6 3분산 정리"의 근거. 재인셉션 units-generation에서 경계 재정의 대상.

---

## 2. 페이즈별 코드 현황 (7 로드맵 대응)

> **페이즈 번호 갱신(2026-06-28)**: 기존 페이즈 3(요약/번역)·4(Grounding)를 **하나로 병합**(함께 진행)하고,
> 이후 번호를 한 칸씩 당겼다. 차터 §3 로드맵과 일치. 

| 페이즈 | 영역 | 코드에 있는 것 | 없는 것(=신규) |
|---|---|---|---|
| **1** U1 Corpus | `ingestion/` | arXiv 어댑터(**HTML 우선 → PDF 폴백**, SourceTier ar5iv/native_html)·**소스별 watermark**(`postgres.py` `watermark` 테이블·`get/advance/reset_watermark`, `watermark_name=source` cross-source)·`docmodel/`(builder·parser·mathml·**tei**)·**GROBID TEI 구조화 파서 + 좌표 page-crop(FR-17)**·**Semantic Scholar·OpenAlex 어댑터**(`adapters/corpus_http.py`)·**DLQ**(`failure_handler.send_to_dlq`)·**scheduler**(`on_schedule_tick`)·`full_text_extraction`·`asset_extraction`·dedup 테스트·`migrate`·resilience·observability | (back-sync 후) **실외부호출 라이브 검증 미실행**(테스트는 fake/mock 기준)·**전량 리빌드 운영 게이트**(`validate_corpus_build_settings`로 의도적 동결)·페이즈 6 대량 스케일 운영 표면 |
| **2** U2 검색 ✅**완료(#244)** | `discovery/` | domain(retriever·ranker·assembler·validator·expander·grounding_adapter)·adapters(bedrock_embedding·opensearch·event_publisher)·ports/search_ports·mocks·real_wiring. **(#244, 2026-06-29)** 소스 중립 결과 카드 Q2 — `domain/source_ref.py`(실 도메인, 카드+상세 헤더 공유)·`search.schema.json` sourceName/sourceUrl 계약·실 프론트 컴포넌트(`ResultCard`/`PaperDetailIsland`) 착지 | 페이즈 7 개선 항목(reranker·LTR·click log 등). **이월 2건(→페이즈 7 백로그)**: 연도 facet 필터·상세 라우트 *키* 소스 중립 id. **데이터 조건**: 비-arXiv(S2/OpenAlex) 카드 분기는 코드 준비 완료이나 멀티소스 *적재*(페이즈 1 라이브)가 있어야 실데이터로 보임 |
| **3** U7 요약/번역 + Grounding 통합 ✅**완료(#249)** | `summarization/`·`shared/ports`·`discovery/domain/grounding_adapter`·`summarization/domain/grounding` | 요약: domain(refiner·grounding·map_reduce·structured_translator·glossary·source_selector·length_router·cache_key)·adapters(bedrock_llm·s3_docmodel·s3_full_text·s3_redis_store·rds_*·sqs_*)·worker. **(#249, 2026-06-30)** Grounding 통합 착지 — `shared/ports` **GroundingValidatorRegistry**(도메인별 Validator 카탈로그·summary=`advisory` 권위·enforce는 U6 `search` 단독권위 유지·레지스트리 가드가 타 도메인 enforce 거부)·ports.md §2.1(U6 사인오프 완료). 수치 임계 재보정(실 arXiv 코퍼스→0.5 확정·QT-1 하니스)·전문/초록 번역 UX·persona 구체화·견고성 보강(요약 캐시 비용·프롬프트 격리·DB 풀링·glossary_ver 경쟁) | **이월(→페이즈 4·5)**: **Agent 도메인 Validator** 레지스트리 등재는 연구에이전트(그린필드)에서. 실 Bedrock 요약/번역 **라이브 스모크**는 페이즈 1 라이브 산출 후 단건부터 |
| **4** 문헌탐색·근거형성 Agent | — | **전부 그린필드** (`research_agent` 모듈 부재) — 구체 파이프라인/방식은 인셉션 질문지로 결정 |
| **5** 연구아이디어 Agent | — | **전부 그린필드** |
| **6** Corpus 대량 | `ingestion/migrate`·재처리 경로 | 대량 스케일 운영(Reindex·재생성 파이프라인 운영 표면) |
| **7** 검색 품질 | `discovery/domain/ranker`·`expander` | reranker·LTR·query expansion 고도화·feedback/click log |

---

## 3. 에이전트가 소비할 계약 인벤토리 (D5 병렬의 출발점)

페이즈 4·5 에이전트는 Search·DocModel·Summary·Citation을 **Tool**로 소비한다. 그 계약은 이미 코드에 존재:

| 계약 | 루트 타입 | 핵심 구조 | SSOT |
|---|---|---|---|
| **DocModel** | `DocModelResponse` | `DocModel`/`Section`/`Block`(Paragraph·Table·Formula·Figure·List·Code)·`Provenance`·`SourceTier`·`AssetRef`; 빌드중/라이선스불가/소스불가 상태 DTO 포함 | `aidlc-docs/construction/shared/docmodel.md` |
| **Search** | `SearchResponse`(oneOf) | `SearchResultPageDTO`·`AbstainDTO`·`DegradedResultDTO`·`ValidationErrorDTO`·`ResultCardVM`·`DegradationMode` | `dtos.md §1` |
| **Summary** | `SummaryResponse`(oneOf) | `SummaryDraft`·`TranslationDraft`·`Anchor`/`AnchorTarget`(근거 앵커)·`Reproducibility`·`Pending/Abstain/CostDegraded/SourceUnavailable` | U7 DTO |
| **Citation** | (citation_graph) | `controller.py`만 관찰 — 계약 표면 **추가 확인 필요** | — |

> **"본문=DocModel(v1)" 번역 계약**(차터 §5-3): DocModel 계약이 `Block` 단위 구조화 본문을 이미
> 정의 → 번역(structured_translator)·요약·에이전트가 동일 DocModel을 공유한다. doc-model 피벗
> 이후 계약과 일치함을 코드에서 확인. (세부 버전 표기는 docmodel.md 대조 필요.)

### 3.1 `shared/ports` 현 상태 (D3·D5 직접 연결)

`shared/ports`는 **데이터 스키마가 아니라 메서드 인터페이스**다. 의존성 역전 시임(U2↔U6 순환 차단).

| 포트 | 메서드 | 상태 | 구현(producer) | 소비(consumer) |
|---|---|---|---|---|
| `GroundingEnforcementHook` | `enforce(candidate, retrieved) -> GroundingDecision` | 🔒 **FROZEN** | **U6 단일권위** | U2(어댑팅만) |
| | `runEvalSet(...)` | 🟡 provisional | U6/OP | — |
| `CostGuardCircuitBreaker` | `getBudgetState() -> BudgetState` | 🔒 **FROZEN** | U6 | U2(분기만) |
| `ObservabilityHub` | `emitMetric/emitLog/startSpan/auditAppend` | 🟡 provisional | U6 | 전 유닛 |

> SSOT: `aidlc-docs/construction/shared/ports.md`. Python 스텁: `shared/python/src/docsuri_shared/ports.py`.
> **변경 정책**: FROZEN 시그니처 변경은 shared 계약 PR + 영향 유닛(U2/U1/U6) 사인오프 필요.

---

## 4. 재인셉션에 주는 시사점 (설계 긴장점)

1. **D3 grounding 통합 ↔ 현 "단일권위 enforce" 긴장** → **(#249, 2026-06-30) 해소 — 선택지 (b)**
   현재 계약은 `GroundingEnforcementHook.enforce`를 **U6 단일권위**로 못박고 U2는 어댑팅만 한다.
   페이즈 3에서 **`GroundingValidatorRegistry`**(`shared/ports`)로 정착: 도메인별 Validator를 **카탈로그**로
   등재(summary=`advisory`·search=`enforce`)하되 **enforce 단일권위는 U6 `search`에 유지**(레지스트리 가드가
   타 도메인의 enforce 권위 주장을 거부). U7은 자기 결정적 게이트(`domain/grounding`)를 직접 호출하고 호출
   지점은 그대로 — 즉 "각 도메인이 shared 추상에 등재하되 enforce 호출 지점은 단일"인 (b)안. ports.md §2.1.

2. **D5 에이전트 포트 = 기존 `shared/ports` 패턴 그대로 적용 가능 (의존 채택 시)**
   연구아이디어 유닛이 문헌탐색 유닛을 의존하기로 하면, 추상 포트를 `shared/ports`에 선언(impl=문헌탐색 유닛)·
   연구아이디어 유닛이 소비하는 구조다. FROZEN 동결·사인오프 정책이 이미 있어 **D5 "계약 선행 동결"의
   제도적 틀이 코드에 존재**. *(단 5→4 의존 자체는 기본 제안·requirements 질문지에서 확정 — 차터 §4.)*

3. **요약/번역(페이즈 3)은 그린필드가 아니라 정합 작업** — domain·adapters·worker가 상당 구현됨.
   페이즈 3의 실체는 "신규 구축"보다 **DocModel 완성형·grounding 통합 반영한 정합·개선**.
   → **(#249, 2026-06-30) 완료**: 예상대로 정합·개선 성격으로 종료(신규 모듈 없음). DocModel eager 입력 소비·
   structured 번역·grounding 레지스트리 등재·수치 임계 재보정·견고성 보강까지 착지.

4. **citation_graph·ops 모듈이 얇음** — 각 `controller.py`만 관찰. 실제 책임 분포 **추가 확인 필요**.

5. **DocModel 빌드/인덱싱 위치 — D6 핵심 갭 → (back-sync 2026-06-29) 대체로 해소**
   - **현재 빌드는 수집 시점 eager**: `application.py::IngestionPipelineService._build_doc_model_before_index`
     (arXiv 경로)·`_build_doc_model_from_record`(비arXiv GROBID TEI 경로)가 인덱스 노출 전에 doc-model을
     빌드/캐시한다.
   - **인덱싱 소스가 DocModel(Block)로 전환됨**: `_index_paper`가 `doc_model`이 있으면
     `Chunker.chunk_doc_model(doc_model)`로 청킹→임베딩→OpenSearch. full-text 청크(`chunk(paper)`)는
     doc-model 부재 시 폴백 경로로만 남는다. (D6 목표였던 "eager 전환 + Block 인덱싱" 달성.)
   - **lazy `BUILD_DOC_MODEL` 잡은 역할 재정의됨**: 캐시 미스/백필 전용으로 잔존
     (`build_doc_model` docstring "misses/backfills"). 요약 시점 최초 빌드를 더는 전제하지 않는다.
   - **잔여**: 코퍼스 전량 eager 빌드 비용은 전량 리빌드(`validate_corpus_build_settings` 게이트) 의사결정
     사안으로 남는다. 실라이브 검증(Bedrock/OpenSearch/GROBID/S3 실호출)은 단건 스모크부터.

---

## 5. 추가 확인 필요 (다음 패스)

- [ ] `frontend/`(U5) 현황 베이스라인 — 이번 패스 제외.
- [ ] `citation_graph` 실제 계약/거동(Tool로 쓰일 인용 데이터 표면).
- [ ] `backend/modules/ops` vs top-level `ops/` 책임 중복 실측.
- [ ] DocModel "완성형 v1" 정의를 `construction/shared/docmodel.md`와 대조(번역 계약 정합).
- [x] discovery/summarization 런타임 거동(grounding 호출 지점) 실측 — D3 재조정 입력. **(#249) 해소**: §4-1 참조(레지스트리 정착·enforce 단일권위 U6 유지).
- [ ] **(Phase 1 closeout 선행)** 단건 `ingest-one` 라이브 스모크 — S3 `full-text/`·`doc-model/`·`assets/`
      생성·OpenSearch 청크 업서트·TEI 그림/수식 crop을 실호출로 1회 확인(테스트는 fake/mock 기준).
      > **게이트 성격 명확화(2026-06-29)**: 이 스모크는 **페이즈 3의 *통합 완료* 게이트**이지 **착수 게이트가 아니다.**
      > 차터 §4.2 원칙("인셉션 문서는 계약 레벨 — 코드 가동 불필요")에 따라 페이즈 3의 **문서 정합·질문지(requirements)는
      > 스모크 없이 착수 가능**(소비할 DocModel/Search/grounding 계약은 이미 코드에 존재). 페이즈 3는 D6대로 **실제 DocModel
      > (eager 빌드+Block 인덱싱)을 입력으로 소비**하므로, 페이즈 1이 라이브로 산출물을 내는지 1회 확인되어야 **통합 검증/완료**가
      > 성립한다. 즉 스모크는 "페이즈 3 코드 통합 검증에 들어가기 전"까지만 끝나면 된다(mock/fixture 기반 구현은 그 전에 가능).
