# 코드 베이스라인 (Reverse-Engineering Baseline) — 2026-06

**단계**: INCEPTION 재진입 · 리버스 엔지니어링 · **작성일**: 2026-06-26 · **상태**: 초안(1차 패스)
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

## 2. 페이즈별 코드 현황 (8 로드맵 대응)

| 페이즈 | 영역 | 코드에 있는 것 | 없는 것(=신규) |
|---|---|---|---|
| **1** U1 Corpus | `ingestion/` | arXiv 어댑터(**HTML 우선 → PDF 폴백**, SourceTier ar5iv/native_html)·**단일소스 watermark**(`postgres.py` `watermark` 테이블·`get/advance/reset_watermark`)·`docmodel/`(builder·parser·mathml)·`full_text_extraction`·`asset_extraction`·dedup 테스트·`migrate`·resilience·observability | **Semantic Scholar·OpenAlex 어댑터·GROBID 연동·cross-source watermark·DLQ/scheduler 운영 표면** |
| **2** U2 검색 | `discovery/` | domain(retriever·ranker·assembler·validator·expander·grounding_adapter)·adapters(bedrock_embedding·opensearch·event_publisher)·ports/search_ports·mocks·real_wiring | 페이즈 8 개선 항목(reranker·LTR·click log 등) |
| **3** U7 요약/번역 | `summarization/` | domain(refiner·grounding·map_reduce·structured_translator·glossary·source_selector·length_router·cache_key)·adapters(bedrock_llm·s3_docmodel·s3_full_text·s3_redis_store·rds_*·sqs_*)·worker | (요약/번역은 상당 구현됨 — 페이즈 3은 정합·개선 성격) |
| **4** Grounding | `shared/ports`·`discovery/domain/grounding_adapter`·`summarization/domain/grounding` | **단일 프레임워크 통합**: enforce 단일권위(현재 U6) ↔ 도메인별 Validator(Search/Summary/**Agent**) 레지스트리 재조정 |
| **5** 문헌탐색 Agent | — | **전부 그린필드** (`research_agent` 모듈 부재) |
| **6** 연구아이디어 Agent | — | **전부 그린필드** |
| **7** Corpus 대량 | `ingestion/migrate`·재처리 경로 | 대량 스케일 운영(Reindex·재생성 파이프라인 운영 표면) |
| **8** 검색 품질 | `discovery/domain/ranker`·`expander` | reranker·LTR·query expansion 고도화·feedback/click log |

---

## 3. 에이전트가 소비할 계약 인벤토리 (D5 병렬의 출발점)

페이즈 5·6 에이전트는 Search·DocModel·Summary·Citation을 **Tool**로 소비한다. 그 계약은 이미 코드에 존재:

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

1. **D3 grounding 통합 ↔ 현 "단일권위 enforce" 긴장**
   현재 계약은 `GroundingEnforcementHook.enforce`를 **U6 단일권위**로 못박고 U2는 어댑팅만 한다.
   페이즈 4의 "도메인별 Validator(Search/Summary/Agent)"는 이 단일권위 모델과 **재조정**이 필요하다.
   선택지: (a) U6가 도메인별 Validator를 내부 보유하고 enforce가 디스패치, (b) 각 도메인이 shared 추상
   인터페이스를 구현하되 enforce 호출 지점은 게이트웨이 단일 유지. → application-design에서 확정.

2. **D5 에이전트 포트 = 기존 `shared/ports` 패턴 그대로 적용 가능**
   문헌탐색 유닛이 추상 포트를 `shared/ports`에 선언(impl=문헌탐색 유닛), 연구아이디어 유닛이 소비.
   FROZEN 동결·사인오프 정책이 이미 있으므로 **D5 "계약 선행 동결"의 제도적 틀이 코드에 존재**.

3. **요약/번역(페이즈 3)은 그린필드가 아니라 정합 작업** — domain·adapters·worker가 상당 구현됨.
   페이즈 3의 실체는 "신규 구축"보다 **DocModel 완성형·grounding 통합 반영한 정합·개선**.

4. **citation_graph·ops 모듈이 얇음** — 각 `controller.py`만 관찰. 실제 책임 분포 **추가 확인 필요**.

5. **DocModel 빌드/인덱싱 위치 — D6 핵심 갭 (코드 실측)**
   - 현재 **인덱싱은 full-text 청크 기반**: `ingestion/processors.py::Chunker`가 `ParsedPaper` 본문을
     섹션 분할(추상 청크 + 본문 청크)해 임베딩→OpenSearch. **DocModel은 인덱싱에 미사용.**
   - 현재 **DocModel은 요약 시점 lazy 빌드**: `summarization/adapters/sqs_docmodel_build.py::SqsDocModelBuildQueue.enqueue_build`
     가 U1 워커 형식의 `BUILD_DOC_MODEL` 잡을 적재(dedup TTL 120s) → `ingestion/runtime.py`의
     `DocModelBuilder`가 빌드해 S3 `doc-model/` 저장. 주석: "Drives BUILD_DOC_MODEL jobs only — the index [is separate]".
   - **D6 목표**: 빌드를 **수집 시점 eager**로 당기고 **인덱싱 소스를 DocModel(Block)로 전환**.
     → 청킹 전략 변경·코퍼스 전량 빌드 비용·lazy 큐 역할 재정의가 페이즈 1 requirements 대상.

---

## 5. 추가 확인 필요 (다음 패스)

- [ ] `frontend/`(U5) 현황 베이스라인 — 이번 패스 제외.
- [ ] `citation_graph` 실제 계약/거동(Tool로 쓰일 인용 데이터 표면).
- [ ] `backend/modules/ops` vs top-level `ops/` 책임 중복 실측.
- [ ] DocModel "완성형 v1" 정의를 `construction/shared/docmodel.md`와 대조(번역 계약 정합).
- [ ] discovery/summarization 런타임 거동(grounding 호출 지점) 실측 — D3 재조정 입력.
