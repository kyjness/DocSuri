# shared/ 공용 계약 — doc-model (구조화 문서모델)

**단계**: CONSTRUCTION → 공용 계약 (DocModel 피벗) · **일자**: 2026-06-23
**상태**: 🔒 **FROZEN** — U1 Corpus build v1 입력·인덱싱·리치뷰 계약. 형상은 본 문서가 SSOT, 런타임 스키마는 `shared/dtos/docmodel.schema.json`(파생).
**근거(SSOT 게이트)**: `aidlc-docs/construction/plans/docmodel-foundation-pivot-plan.md` (결정 D1·D2·D4·D6·D8 + Q1 커버리지 스파이크 + Q3 이 문서). 원장: `aidlc-docs/aidlc-state.md`.
**목적**: 요약/번역 입력·자체 리치뷰 렌더·(후속)에이전트 toolschema **세 소비자의 단일 계약**. `fullText`로 전문 텍스트 투영본을 제공하고, `sections[].blocks[]`로 표·수식·그림·코드까지 구조화해 싣는다.

> **상태 범례**: 🔒 FROZEN · 🟡 PROVISIONAL. 가산적 진화(필드 추가=하위호환; 제거/의미 변경=버전업, `provenance.schemaVersion`).

---

## 1. 한눈에

```
생산자  U1 Ingestion (DocModelBuilder)  ──생성·캐시──▶  doc-model/{paperId}/v{version}.json (S3)
                                                              │
소비자  ├─ U7 요약/번역 입력(.txt→doc-model, 로직 불변 D2)
        ├─ U5/U7-frontend 자체 리치뷰(DocModelViewer 렌더 D4)
        └─ (후속) 근거형성·문헌탐색 에이전트 toolschema

원칙   fullText = 읽기 순서 전문 텍스트 투영본
       표 = 데이터(rows/cols)  ·  수식 = LaTeX  ·  그림/표이미지 = webp assetId 참조(픽셀 미포함)
       arXiv HTML 결정적 파싱(LLM 추출 금지 D1)  ·  Corpus phase-1은 수집 시 eager 생성
```

- **생산자**: U1 — `DocModelBuilder`(HTML/GROBID 결정적 파싱, BR-C6/BR-C7·TD-16). Corpus phase-1은 수집 시점에 **eager 생성**, `(paperId, version)` 키 캐시, version 변경·철회 시 무효화. 기존 read-miss lazy build는 누락/백필 호환 경로다.
- **소비자**: U7(요약 입력 = `RefinedSource`의 섹션·표·수식·캡션을 doc-model에서 직접 취득), U5/U7-frontend(`DocModelViewer`), 에이전트(동일 id로 인용).
- **보안(전 계약 공통)**: 이미지 **픽셀·`object_ref`·서명 URL은 doc-model에 미저장** — `assetId` 참조만(SEC-9). 서명 URL은 읽기 API가 발급. PII/시크릿 금지(SEC-3).

---

## 2. 본문 구조 — 전문 투영본 + 중첩 섹션 트리 (Q3 결정 A)

논문은 `fullText`와 **섹션이 블록과 하위섹션을 품는 재귀 트리**를 함께 가진다(평면 배열 아님). `fullText`는 전문 텍스트 투영본이고, 리치뷰 목차(`DocTOC`)·요약 맵리듀스 섹션분할(P3)·앵커 해석·이미지/표/수식 렌더는 구조화 트리를 그대로 쓴다.

```
DocModel
 ├─ meta : { paperId, version, title, abstract?, provenance }
 ├─ fullText : string  ← 읽기 순서 전문 텍스트 투영본
 └─ sections[] (재귀)
      Section { id, title, blocks[], sections[] }   ← sections = 하위섹션
        blocks[] = Block (type 판별자)
```

### 2.0 `fullText`

`fullText`는 모든 텍스트 보유 요소를 읽기 순서로 투영한 문자열이다. 포함 대상은 섹션 제목, 문단, 표 캡션·셀, 수식 LaTeX, 그림 캡션, 리스트 항목, 코드다. 단, 그림 픽셀은 포함하지 않는다. 이미지 자체가 필요한 소비자는 `figure.assetRef.assetId`로 `assets/{paperId}/{version}/{assetId}.webp`를 읽는다.

### 2.1 Block 타입 (6)
| type | 핵심 필드 | 비고 |
|---|---|---|
| `paragraph` | `text` | 인라인 수식은 `\( ... \)` LaTeX로 본문에 임베드(KaTeX 렌더·프롬프트가 LaTeX 그대로 읽음) |
| `table` | `rows[]`(셀=`text`·`isHeader`·`colspan`/`rowspan`) · `caption` · `anchorLabel`("Table 3") · `assetRef?` | **D8: 데이터, 크롭 이미지 아님.** `assetRef`는 비-HTML 폴백 시 크롭만 |
| `formula` | `latex` · `display` · `anchorLabel`("(3)") · `mathmlSource?` | 디스플레이 수식. MathML→LaTeX 변환(Q1: `<math>` 보유 94%) |
| `figure` | `assetRef`(assetId·type·ordinal) · `caption` · `anchorLabel`("Figure 2") | webp 참조; U5 `AssetGallery`+앵커 매처 재사용 |
| `list` | `ordered` · `items[]` | 중첩 리스트는 가산적 후속 |
| `code` | `text` · `language?` | 알고리즘/코드 verbatim |

> **헤딩은 블록이 아니다** — `Section.title`이 담는다. 소스 헤딩 부재 시 `title`은 빈 문자열(span-only 섹션, BR-S3 폴백과 정합).
> **v1 제외 확정**: 각주(`ltx_note`)·references 목록 구조화·페이지 번호는 DocModel 블록으로 승격하지 않는다. 본문 인용 마커 텍스트는 보존하지만, 참고문헌/인용 그래프 구조화는 U8 Citation Graph 책임이다. PDF 페이지 딥링크는 소스 간 일관성이 없어 v1 제외이며, 근거 단위는 결정적 Section/Block id가 맡는다.

---

## 3. 앵커 — 결정적 id 핸들 (Q3 결정 A)

**모든 Section·Block·표·그림·수식에 결정적 `id`를 부여**하고, 근거화·리치뷰·에이전트가 **같은 id를 가리킨다**. 기존 "섹션 라벨 + 정규식 매칭"의 취약성을 해소한다.

- **id 규칙(결정성, P7)**: 동일 소스 → 동일 id. 권고 형식: 섹션 `s3`·`s3.2`(번호/위치 기반), 블록 `s3.p2`·`s3.tbl1`·`s3.eq2`·`s3.fig1`(섹션id + type약어 + ordinal). 스키마는 `id`를 문자열로만 제약(형식 규칙은 본 문서·파서 NFR).
- **U7 Anchor 바인딩**: `Anchor.target` = doc-model의 Section/Block **`id`**, 선택적 `span:[start,end]`로 블록 내 문자 범위 정밀 하이라이트, `label`은 표시용("표 2"). `GroundingValidator` 앵커 실재성 체크 = "`target` id가 doc-model에 실재?"(결정적·견고, BR-S7/PBT-S5).
  - ⚠️ **계약 정합(후속)**: `shared/dtos/summarization.schema.json`의 `Anchor.target` 설명을 "섹션 라벨" → "doc-model Section/Block id"로 의미 명확화(가산적, U7 사인오프). 본 문서가 그 의미의 SSOT.

---

## 4. 생성·provenance·캐시

- **소스 사다리(Q6)**: `native HTML → ar5iv → e-print LaTeX → (최후) PDF 파싱`. `provenance.sourceTier ∈ {native_html, ar5iv, eprint_latex, pdf}`. Q1 스파이크: native+ar5iv 90%·HTML 전무 ~9%(PDF 폴백 실필요).
- **결정성(D1)**: LLM 추출 금지(표 숫자 환각 방지) — 결정적 파서만(BR-30·TD-16: lxml/BeautifulSoup·MathML→LaTeX).
- **캐시/생성(D6 개정)**: `(paperId, version)` 키. `provenance.parserVersion`/`schemaVersion` 변경 또는 version 변경·철회(tombstone) 시 무효화. U1 builder와 U7/S3 reader는 shared doc-model version contract를 사용하며, reader도 version mismatch를 cache miss로 취급해 stale S3 object를 노출하지 않는다. Corpus phase-1은 수집 시 eager 생성하며, legacy lazy build는 누락분·재빌드·백필 호환 경로로만 사용한다.
- **저장**: `doc-model/{paperId}/v{version}.json`(단일 버킷·prefix, SSE-KMS, 공개 차단 — U1 Infra §1.1b). 이미지 바이트 분리: `assets/{paperId}/{version}/{assetId}.webp`(유지) + RDS `paper_asset`(유지) 재사용 — **재추출 0**.
- **PDF/GROBID 폴백 결정**: rich HTML이 없는 논문은 `sourceTier=pdf` DocModel로 degrade하고, 구조를 추정하지 않은 단일 paragraph block을 만든다. Phase 7에서 PDF/GROBID 구조화 품질을 올리기 전까지 이 downgrade는 승인된 v1 동작이다.

---

## 5. 읽기 API — getDocModel 응답 union

루트 스키마 = `DocModelResponse`(union, U5/U7-frontend ApiClient가 status로 분기):

| status | 페이로드 | 매핑 |
|---|---|---|
| `ok` | `docModel` + `cached?` | 리치뷰 렌더·요약 입력 |
| `building` | `retryAfterMs?` | lazy 빌드 진행 중(미스→`BUILD_DOC_MODEL` 큐 잡 enqueue, 경계 B) → 클라이언트 폴링(BR-30 트리거) |
| `license_unavailable` | `reason` · `arxivUrl?` | OA 게이트 OFF → arXiv 링크아웃(BR-SF-11). **OA 신호 = U1 인제스션 검증**(CC-BY/CC-BY-SA/CC0만 저장, 비-OA 거부 — BR-1) → 코퍼스 논문은 전부 OA·인앱 렌더 안전이라 게이트는 **운영 토글**(논문별 라이선스 조회 불요); 활성화는 팀 deploy |
| `source_unavailable` | `reason` | 빌드했으나 전 소스 폴백 실패(Q6) — `building`(진행 중)과 구분 |

- `building`은 비종단(폴링 → 캐시 히트로 `ok`). 빌드 트리거 미배선 시 미스는 `source_unavailable`(기존 동작). 프론트는 폴링 상한 후 종료(소스 없는 논문 무한 폴링 방지).
- (네트워크/5xx는 transport 계층 — 스키마 밖, 기존 union 관례와 동일.)

---

## 6. 버전·호환
- **가산적 진화**: 블록 타입·필드 추가 = 하위호환(소비자는 미지 필드 무시). 제거/의미 변경 = `schemaVersion` 버전업 + 영향 유닛(U1/U7/U5) 사인오프.
- `consumers ignore unknown fields` 불변(forward-compat). 내부 필드 비노출(SEC-9).

---

## 7. 링크
- 런타임 스키마(파생): [`shared/dtos/docmodel.schema.json`](../../../shared/dtos/docmodel.schema.json)
- 게이트(SSOT): [`construction/plans/docmodel-foundation-pivot-plan.md`](../plans/docmodel-foundation-pivot-plan.md)
- 생산자 FD: U1 `business-logic-model.md §7` · `business-rules.md BR-30` · `tech-stack-decisions.md TD-12/TD-16` · `infrastructure-design.md §1.1b`
- 소비자 FD: U7 `domain-entities`/`business-logic-model`/`business-rules` · U7-frontend `frontend-components §2.10 DocModelViewer`
