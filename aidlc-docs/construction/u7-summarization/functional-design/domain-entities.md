# U7 Summarization — 도메인 엔티티 (Domain Entities)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U7 Summarization · **일자**: 2026-06-18
**원칙**: **기술 무관(technology-agnostic)**. 본 문서의 엔티티는 비즈니스 의미만 정의하며, 구체 기술(Bedrock·S3·Redis·직렬화/와이어 형식)은 **NFR/Infra**에서 바인딩한다. 어댑터 결정(real-first, mock 대역 없음)은 구현 전략이며 도메인 타입에는 기술명을 박지 않는다.
**근거**: `../../../inception/requirements/summarization-translation-pipeline.md` §3·§5·§6·§9·§11 · 계획서 §1·§4 답변(Q1~Q17) · `construction/shared/{ports,dtos}.md`.

---

## 0. 엔티티 관계 한눈에 보기

```
 SummaryRequest ──(+RequestContext)──▶ SummaryCacheKey ──▶ CacheLookup
       │                                                      │ miss
       ▼                                                      ▼
   SourceText ──▶ RefinedSource ──(+Glossary)──▶ [LLM] ──▶ SummaryDraft / TranslationDraft
                       │                                        │ (anchors[])
                       └────────────────────────┐               ▼
                                                 └──▶ GroundingInput ──▶ AnchorVerdict
                                                                              │
                                                            ┌─────────────────┴───────────────┐
                                                         (pass)                            (fail/abstain)
                                                            ▼                                  ▼
                                                  SummaryResponse =  SummaryResultDTO | AbstainDTO | CostDegradedDTO | SourceUnavailableDTO
```

- **소유(생산) 타입**: U7이 정의·생산하는 도메인/DTO. **신규 `shared/dtos/summarization` 계약**(현재 부재 — U4 library PROVISIONAL 패턴으로 신설).
- **소비(참조) 타입**: `shared/ports`의 U6 소유 타입(`BudgetState`, `GroundingDecision` 등) — U7은 참조만, 재정의(포크) 금지.

---

## 1. 입력 · 컨텍스트

### `SummaryRequest` (요청, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `paperId` | `PaperId` | 대상 논문(버전 없는 식별자) | §6 |
| `version` | `Version` | 코퍼스 논문 버전(앵커·캐시 신원 일부) | §11 |
| `task` | `enum{summary, translate}` | 요약 또는 번역 | §5 |
| `targetLang` | `enum{ko}` | 번역 대상 언어(v1 한국어 단일, Q7=A) | FR-13 |
| `persona` | `enum{expert, beginner}?` | 요약 수준(생성 변형, 논문당 최대 2벌) | FR-14, Q9 |
| ~~`view`~~ | — | **폐기(Q9 / 코드 부재)** — `view` 요청 필드 없음. 표시 슬라이싱은 U5 클라이언트 렌더(생성·캐시 무관) | §9.2, Q9 |

> `view`는 **생성 신원이 아니다**(캐시 키 미포함). 같은 §3 출력의 클라이언트 렌더 변형(재생성 0). 서버는 풍부한 전체 출력을 생산하고 `view` 적용은 U5.

### `RequestContext` (실행 컨텍스트, 소유)
| 필드 | 타입 | 의미 |
|---|---|---|
| `authSession` | `AuthSession` | 인증 주체(게이트웨이/U3 위임 — SEC-8). U7은 신뢰만 |
| `budgetSignal` | `BudgetState`(참조) | 비용 게이트 입력(U6 `get_budget_state()` 산출) |
| `requestId` | `RequestId` | 추적·텔레메트리 상관키 |

---

## 2. 캐시 키 · 조회 (immutable, §11 / Q7)

### `SummaryCacheKey` (캐시 신원, 소유 — immutable)
| 필드 | 의미 |
|---|---|
| `paperId` · `version` | 논문·버전 |
| `task` · `targetLang` | 작업·언어 |
| `persona` | 생성 변형(요약만; 번역은 무관) |
| `glossaryVer` | **프롬프트-강제 용어의 콘텐츠 시그니처**(요약·번역 공통; 강한 용어 없음=0=공유 베이스). 약한(후치환) 용어는 키에 미포함·읽기시 오버레이. `signature > 0`은 `ownerId`로 갈라 충돌 방지 |
| `modelVer` · `promptVer` | 모델·프롬프트 버전(업그레이드 시 키 변경 = 자동 무효화) |

> **불변식(INV-5)**: 같은 키 = 항상 같은 산출물. 무효화는 키(경로) 변경에 의한 신규 객체 생성 — 수동 flush 없음.

### `CacheLookup` (조회 결과, 소유)
`{ hit: bool, payload: SummaryResultDTO? }` — read-through(핫→영구) 결과.

---

## 3. 소스 · 정제 (§4·§6 / Q1·Q2·Q6)

> **피벗(2026-06-23, doc-model)**: 요약 입력 = 평문 `.txt` → **구조화 doc-model**(SSOT=`construction/plans/docmodel-foundation-pivot-plan.md`, D2). **입력 업그레이드일 뿐 생성·근거화·캐시·길이분기 로직은 불변.** 섹션·캡션·수식·표를 U7이 정규식으로 추정하던 것을 doc-model에서 직접·신뢰성 있게 받고, **표가 데이터(rows/cols)로 들어와** 표 숫자가 LLM·근거화에 가시화(D8).

### `SourceText` (원문, 소유)
| 필드 | 의미 |
|---|---|
| `kind` | `enum{full_text, abstract}` — 요약=전문(**doc-model** read), 번역=초록 |
| `raw` | 전문 = **U1 doc-model**(구조화: 섹션/블록·앵커 · 표=데이터(rows/cols) · 수식=LaTeX · 그림=webp 참조). 평문 `.txt` 재파싱 아님(D2). 초록 = 메타 초록 텍스트 |
| `fallbackReason?` | 전문 부재/라이선스X로 초록 폴백 시 사유(Q1=A·NFR-R2) |

### `RefinedSource` (정제 결과, 소유)
| 필드 | 의미 | 근거 |
|---|---|---|
| `body` | 정제 본문(노이즈 제거 후) | Q2=B |
| `sections[]` | `Section{label, span}` — **doc-model 섹션/앵커에서 직접 취득**(신뢰; 헤딩-정규식 도출은 doc-model 부재 시 폴백). 실패 시 빈 라벨+span-only | Q6=A, D2 |
| `tables[]` | `Table{label, rows/cols 데이터, caption, anchor}` — **doc-model 구조화 표(보존)**. 표 숫자가 LLM·근거화에 가시(D8 — 크롭 이미지 깜깜이 해소) | D8 |
| `captions[]` | 표/그림 캡션(**보존** — 결과 수치 원천; doc-model 캡션·앵커 연결) | Q2=B |
| `formulas[]` | LaTeX 수식(**보존·번역 금지**; doc-model이 LaTeX로 직접 제공 — MathML 추정 불필요) | §4, D1 |
| `preserved[]` | Appendix·Supplementary Results 등 실험 정보 콘텐츠(**제거 금지**) | Q2=B |

> Q2=B 정제 경계: **제거** = Header/Footer·페이지번호·저작권·저자정보·참고문헌. **보존** = 캡션·Appendix·Supplementary·수식·섹션 구조.

### `SanitizedInput` (LLM 입력, 소유)
`{ text, tokenCount }` — 제어문자 제거·본문 격리(injection 대비)·토큰 카운트(길이 분기 입력). 토큰 캡 수치는 NFR.

---

## 4. 용어집 (§9.1 / Q8)

### `Glossary` (용어집, 소유)
| 필드 | 의미 | 성격 |
|---|---|---|
| `seedTerms[]` | `TermMapping[]` — AI/ML 표준 핵심 매핑(공유, 고정) | P1 공유 |
| `keepAsIs[]` | 미번역 보존 용어(Transformer·BERT·LoRA·RAG…) | P1 공유 |
| `userOverrides[]` | `TermMapping[]` — 사용자 선호 단순 명사 교정 | P2 개인 |

### `TermMapping`
`{ from, to, kind: enum{prompt_enforced, post_substitution} }`
- `prompt_enforced`: 핵심 용어 보존·매핑 = **프롬프트 강제**(생성 시 일관·문맥 처리).
- `post_substitution`(약한 용어): 사용자 선호 **단순 명사** = **읽기시** 공유 베이스에 **결정적 후치환 오버레이**(조사 안전한 단순 명사 한정, LLM 재호출 0, 캐시 미포함 — NFR-C1).

---

## 5. 생성 드래프트 · 앵커 (§3 / Q6)

### `SummaryDraft` (요약 산출물, 소유 — §3 JSON 계약)
| 필드 | 의미 |
|---|---|
| `tldr` | 문제 + 핵심 주장(1~2문장) |
| `contributions[]` | 저자 주장 기여 |
| `method` | 접근법 한 단락 |
| `results` | 핵심 수치·벤치마크·SOTA 여부(초록 밖 디테일) |
| `limitations` | 한계·가정(재현성·일반화 경계) |
| `reproducibility` | `{ code, data }` 공개 여부·링크(정규식+LLM 병행 추출, Q16) |
| `anchors[]` | `Anchor[]` — 항목별 원문 근거 |

### `Anchor` (근거 앵커, 소유 — Q6)
`{ field, target: enum{section, table, figure}, label?, span }`
- `span`(문자 offset)은 **필수 보증**; `label`은 도출 성공 시 부여(실패 시 span-only로 저하). 라벨·span 모두 없으면 해당 주장 **기권**.

> ⚠️ **앵커 모델 충돌 (미해결) — 2026-06-30 · `aidlc-suite-review` PR #280**
> 본 `Anchor`(레거시 **`{ target ∈ enum{section,table,figure}, quote-span(span), regex-label(label) }`**)는 배포된 U7 요약 경로·`summarization.schema.json`과 일치하며 **U7 백엔드 무변경**이다. 그러나 FROZEN `docmodel.md §3`은 결정적 Section/Block **id 앵커**를 강제하고, `evidence-formation-port.md §3.6`은 id 기반 앵커를 전제한다.
> 명시적 결정(U7/스키마가 id 앵커로 이행하거나 `docmodel.md §3`을 공식 개정·동결해제)으로 셋을 정렬하기 전까지, novelty/근거형성 에이전트의 앵커 실재성 검증은 id 앵커에 의존할 수 없다. **해결 책임자: TBD.**
> 교차 참조: `docmodel.md §3` · `shared/dtos/summarization.schema.json`(Anchor/AnchorTarget) · 본 `domain-entities.md`(Anchor) · `evidence-formation-port.md §3.6`.

### `TranslationDraft` (번역 산출물, 소유) — **개정 (PR-2, BR-S18)**
`{ docModel: DocModel, keptTerms[] }` — **번역본 doc-model**(본문과 동일 구조; 섹션 제목·문단·리스트·표/그림 캡션은 한국어, 표 셀·수식 LaTeX·코드·블록 id·그림 assetRef는 원본 verbatim) + 미번역 유지 용어 목록. 평문 `koreanText` 한 덩어리에서 전환. `summarization.schema.json`이 `docmodel.schema.json#/$defs/DocModel`을 **크로스파일 `$ref`**(복제 회피). 생성: `StructuredTranslator`가 소스 doc-model에서 번역 유닛(id→text)을 추출→게이트웨이 `translate_segments`(id→번역텍스트, 청크별 map-only)→소스 구조에 재주입해 결정적 재조립. doc-model 부재(초록/레거시)는 단일-문단 doc-model로 감싸 계약 통일.

---

## 6. 근거화 · 종단 상태 (Q4·Q5)

### `GroundingInput` (근거화 입력, 소유)
`{ draft, refinedSource }` — **U7 고유 결정적 검증 입력**(검색용 `enforce(candidate, retrieved)`와 형상 다름; Q4=A). 단일 논문 정제 소스 대비 앵커/수치/스키마 검증.

### `AnchorVerdict` (근거화 판정, 소유 — Q4=A)
| 필드 | 의미 |
|---|---|
| `ok` | 통과 여부 |
| `violations[]` | `{ kind: enum{anchor_missing, numeric_mismatch, schema_incomplete, truncated, empty}, field }` |
| `outcome` | `enum{pass, abstain}` — abstain = 코퍼스밖 정당 기권 또는 재시도 후 실패 |

> U6 `GroundingDecision`(검색 근거화, 참조 타입)과 **별개**. U7 `AnchorVerdict`는 *문서-충실도* 검증(LLM-judge 미사용, Q15=A).

### `SummaryResponse` (종단 union, 소유 DTO — Q5=A)
| 변형 | 조건 | 필드 |
|---|---|---|
| `SummaryResultDTO` | 근거화 통과·산출물 완전 | `{ draft\|translation, anchors[], meta }` |
| `AbstainDTO` | 근거화 실패(재시도 후)·코퍼스밖 | `{ reason }` |
| `CostDegradedDTO` | 비용 게이트 OPEN/저하 | `{ message: "AI 요약 일시 중단" }`(FR-11) |
| `SourceUnavailableDTO` | 전문·초록 모두 부재 | `{ reason }` |
| `PendingDTO` | 비동기 잡(map-reduce/번역) 처리 중 | `{ jobId, retryAfterMs }` |

> **비동기 폴링 계약 (Polling Contract)**: `PendingDTO` 수신 시 클라이언트는 `retryAfterMs`(예: 5000ms) 대기 후 `GET /api/summarization/jobs/{jobId}` 엔드포인트를 통해 상태를 폴링한다. 작업 완료 시 `SummaryResultDTO` 또는 실패 상태 DTO가 반환되며, 계속 진행 중일 경우 다시 `PendingDTO`가 반환된다. 최대 폴링 시간(예: 60초) 초과 시 클라이언트는 타임아웃 오류를 표시하고 중단한다.

> **빈 성공 금지**: 근거 없는 빈 산출물을 성공으로 표기하지 않음. 비용저하·소스부재와 무관하게 근거화 실패면 **기권 우선**(INV-4).

---

## 7. 값 타입 (shared 횡단 정합)

- `PaperId`(버전 없는) · `Version` · `ArxivId`(표시용) · `RequestId` · `AuthSession` — `shared/` 규약과 정합.
- `BudgetState` · `GroundingDecision` — **U6 소유(참조)**. U7 재정의 금지.

---

## 8. 공유 계약 정합 (드리프트 0)

| 타입 | 소유 | 정합 |
|---|---|---|
| `SummaryRequest`/`SummaryResponse`·`Anchor` 등 | **U7 신규 생산** | **신규 `shared/dtos/summarization.schema.json`** 신설(현재 부재). SEC-9: 내부 필드(토큰·비용·캐시키·모델/프롬프트 식별자) 외부 DTO 비노출 |
| `BudgetState`·`GroundingDecision`·`CandidateResponse` | U6 (`shared/ports`) | 참조만 — U7 비용/관측 재구현 없음(INV-2) |
| `PaperId`·`Version`·`stored_full_text_ref`·**`docModelRef`** | U1/shared | read capability(코드 의존 아님). **요약 입력 = `docModelRef`**(lazy 생성·캐시 — U1 BR-30); `.txt`는 검색·청킹 투영(D2) |

> **신규 DTO 계약(`shared/dtos/summarization`)은 PROVISIONAL** — 정제 스펙은 별도 shared PR(Track 사인오프)로 승격. 본 FD 코드 검증과는 무관하게 진행 가능(U4 library 선례).

---

## 9. 멀티모달 자산 읽기 계약 (FR-17 — 표시 전용, 2026-06-22 확장)

> 근거: `requirements.md` FR-17·FR-12(앵커 자산 연결) · U1 FD/Infra(`paper_asset` RDS·S3 `assets/`). **U7은 읽기·노출 측**(생산=U1). 요약/번역 생성·근거화·캐시 로직 **불변**.

### 9.1 자산 읽기 DTO (소유·생산 — SEC-9)

| 엔티티 | 필드 | 비고 |
|---|---|---|
| **`AssetRef`** | `assetId` · `type`(figure\|table) · `ordinal` · `caption` · `sourceMode`(structured\|page-crop) · **`url`**(단기 만료 **서명 URL**) · `pageRef?` · `bbox?` | **SEC-9**: `object_ref`·내부 메타 비노출 — **서명 URL만**. `ordinal`=표시 순서. (D2) |
| **`PaperAssetsResponse`** (union) | `AssetsOkDTO{status:'ok', assets: AssetRef[]}` · `AssetsLicenseDTO{status:'license_unavailable'}` · `UnauthorizedDTO{status:'unauthorized'}` | OA 미허용 → `license_unavailable`(BR-SF-11 재사용); 비인증 → `unauthorized`(갭#3). OA·자산 0 = `ok`+빈 배열. |

### 9.2 엔드포인트 (D1)

- **`GET /api/papers/{paperId}/assets?version=N`** (U7 라우터, full-text와 병렬·독립). 인증 필수(principal, SEC-8). OA 라이선스 게이트(BR-SF-11). 매니페스트 조회 → 각 `object_ref` 서명 URL 발급 → `AssetRef[]`(ordinal 정렬).
- 독립 엔드포인트 = 전문 뷰어 미오픈에도 상세 그림·도표 표시 가능(관심사 분리).

### 9.3 읽기 포트 (참조 — U1 생산 `paper_asset` 소비)

| 포트 | 시그니처(개념) | 비고 |
|---|---|---|
| **`AssetManifestReadPort`** | `read_assets(paperId, version) -> StoredAssetMeta[]` | 공유 RDS `paper_asset` 조회(읽기 전용, owner 무관 공개 코퍼스). |
| **`AssetUrlSigner`** | `presign(objectRef, ttl) -> url` | S3 `assets/` GetObject 서명(단기 만료). 내부 키 비노출. |

> U7은 `paper_asset`을 **읽기만**(U1이 단일 writer). 서명 URL TTL·정책은 NFR/Infra.

### 9.4 앵커 ↔ 자산 연결 (D3 / 인셉션 Q5 · FR-12)

- 요약 `Anchor{ target: figure|table, label, span }`은 **불변**(백엔드 변경 없음). 프론트(U5)가 `label`("Figure 1")·순서를 `AssetRef`(`caption`·`ordinal`)에 매칭해 "출처 보기 → 해당 도표" 연결.

### 9.5 계약 SSOT 수립 (갭 #1 — D4, §8 예고 이행)

- 기존 **수기 `frontend/types/generated/summarize.ts`** → **`shared/dtos/summarization.schema.json` SSOT 승격**: SummarizeRequest/Response·AnchorVM·FullText* + 신규 `AssetRef`/`PaperAssetsResponse`. 프론트는 스키마에서 **생성**(드리프트 0). SEC-9 비노출 불변.

### 9.6 상태 매핑 정합 (갭 #2/#3 — D5)

- summarize·full-text·assets 응답 union에 **`unauthorized`**(401) 명시; **`validation_error`는 `message` 포함**(프론트 'invalid'(입력 확인) 분기 동작). 프론트 분류기가 일반 'error' 뭉개기 대신 **상태로 판정**.
