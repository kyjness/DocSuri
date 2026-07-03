# DocModel 기반 전환 — 결정 게이트 (Structured Doc-Model Foundation Pivot)

> **상태**: ✅ **확정·구현·배포 완료**(D1~D8 결정 확정 + FR-12/13/17/18 라이브 — develop 반영; 아래 체크리스트 `[x]` 참조). 본 문서는 "요약/번역 입력을 평문→구조화 문서모델(doc-model)로 전환 + 자체 리치뷰 + 에이전트 준비" 피벗의 **단일 진실원천(역사 기록)**이다. _(구 "결정 게이트(미착수)" 표기는 배포 완료로 정정 — 2026-06-30, `aidlc-suite-review` PR #280.)_
> **브랜치 예정**: `feat/docmodel-foundation` (현 작업 `fix/summarization-pipeline` 종료 후 분기)
> **근거 SSOT**: 기존 U1 FD BR-29(전문 HTML 우선) · 멀티모달 FR-17(그림·도표 자산) · `aidlc-state.md:159-162`(비전=에이전트 후속) · `inception/requirements/summarization-translation-pipeline.md`(#9·#12 차별화/근거형성 에이전트)

---

## 0. 왜 (피벗 동기)

현재 파이프라인은 **세 갈래가 따로 논다**:
1. 요약/번역 입력 = **정규화 평문 `.txt`** (표 깨짐·수식 깨짐)
2. 그림·표 = **webp 이미지**(FR-17 표시 전용) — 표가 *데이터*가 아니라 *그림*
3. 추후 문헌탐색/근거형성·아이디어검증 에이전트 = 구조화 표현이 필요

이 셋을 **하나의 구조화 문서모델(doc-model)**로 수렴한다. doc-model은 arXiv HTML(native→ar5iv)을 결정적 파싱해 만든 산출물로, **요약/번역 입력 · 자체 리치뷰 렌더 · 에이전트 소비**의 공통 기반이 된다.

```
            [doc-model (JSON)]  ← arXiv HTML 파싱 · 표=데이터 · 수식=LaTeX · 그림=webp 참조 · 섹션/앵커
            /        |         \
   요약/번역(U7)   리치뷰(U5)    에이전트(신규)
   입력 교체       자체 렌더     데이터 소비
```

---

## 1. 확정 결정 (D — 대화에서 합의됨)

| # | 결정 | 근거 |
|---|---|---|
| **D1** | **doc-model 신설** = arXiv HTML 결정적 파싱 → JSON(섹션/블록·앵커 · **표=구조화 데이터(rows/cols)** · **수식=LaTeX**(MathML 변환) · **그림/표이미지=webp `asset_id` 참조**). LLM 추출 금지(표 숫자 환각 방지) — 결정적 파서만. | 표/수식이 소스에 데이터로 있음; 근거형성은 표 충실도에 의존 |
| **D2** | **U7 요약/번역 입력을 `.txt` → doc-model로 전환.** 요약·번역·근거화·캐시 **로직 불변**(입력 업그레이드, 갈아엎기 아님). | 표·수식을 무시하던 품질 갭 해소 |
| **D3** | **PDF 원문 S3 저장 안 함.** 다운로드 버튼 없음 → 저장 이유 없음. 인제스션 자산추출 폴백용 transient fetch만(현 상태 유지). | arXiv 재취득 가능; PDF는 에이전트에 나쁜 포맷 |
| **D4** | **자체 리치뷰 = doc-model 자체 렌더**(콘텐츠 충실; arXiv HTML(experimental) 방식). 수식 KaTeX/MathJax·표 컴포넌트·그림 webp·목차/앵커. **PDF.js 픽셀 재현 아님.** | 독자 서비스(목적지) — 요약/번역/주석/에이전트 통합 + 로그수집·개인화 표면 확보 |
| **D5** | **비전 모델 = batch 사전처리 안 함.** 에이전트 단계에서 **on-demand 툴**(그림별, 질문 맥락 포함 호출). webp 유지로 재수집 없이 후속 도입. | 비용↓·정확도↑(맥락); `aidlc-state.md:159-162` 권고와 일치 |
| **D6** | **doc-model 생성 = on-demand + `(paper_id, version)` 캐시.** 전 코퍼스 eager 아님(사용량 비례). | 비용 = 코퍼스가 아니라 사용량에 비례 |
| **D7** | **소스 무관(source-agnostic) 설계.** 입력 어댑터 분리. arXiv 너머 = "재취득 불가 소스만 캐시" 별도 결정(PDF 일괄저장 아님). | 업계 AI-over-papers는 코퍼스 API(OpenAlex/S2) 위에 구조화 추출 |
| **D8** | **표·수식을 doc-model 데이터/LaTeX로** (기존 TD-12 "표=PDF 크롭" 재검토). **그림 webp는 유지**(시각물). | 표 이미지는 텍스트 에이전트에 깜깜이 |

### 1.1 저장 레이아웃 (확정)

**구조화 콘텐츠는 하나의 객체로 통합, 이미지 바이너리는 분리·참조.** (이미지 바이트는 JSON에 넣지 않음 — base64 부풀림·개별 presign/lazy/캐시 불가)

```
신규  doc-model/{paper_id}/v{ver}.json   ← 본문 + 표=데이터 + 수식=LaTeX + 그림/표이미지 참조(asset_id·캡션·앵커)
유지  assets/{paper_id}/v{ver}/{asset_id}.webp   ← 이미지 픽셀(그림 + 표 크롭) — doc-model이 참조
유지  RDS paper_asset                     ← 이미지 메타(캡션·page_ref·bbox·ordinal)
선택  full-text/{paper_id}/v{ver}.txt     ← doc-model 파생 평문 투영(검색·청킹용) or 폐기 (Q4)
제거  (PDF 저장 없음)
```

- 버킷은 단일(프리픽스 분리); `doc-model/` 프리픽스 추가.
- **그림 = 픽셀만 바깥, 참조(포인터)는 doc-model 안.** 표 = 데이터는 안, 크롭 이미지(있으면) 바깥.

---

## 2. 열린 Q (게이트 — 코드 전 확정 / 검증 필요)

> 관례대로 각 Q에 **권장안**을 둔다. 진행 시 답을 확정하고 본 표를 갱신한다.

| # | 질문 | 권장안 | 비고 |
|---|---|---|---|
| **Q1 ✅실행** | arXiv HTML/LaTeX **커버리지 스파이크** | **완료(2026-06-23) — §2.1 결과** | 결론: HTML-기반 doc-model 유효(either 90%), ar5iv 필수, e-print/PDF 폴백 ~10% 실필요 |
| **Q2** | 리치뷰 형태 | **(a) 콘텐츠 재렌더**(arXiv HTML 방식, doc-model로 충분·PDF 불필요) | (b) PDF.js 픽셀 재현은 PDF 필요(저장 없이 on-demand 프록시 가능) — 원하면 D3/D4 재검토 |
| **Q3 ✅완료** | **doc-model JSON 스키마** 확정 — 블록 타입·표 구조·수식 표현·앵커·webp 참조·소스 메타(provenance) | **완료(2026-06-23)**: 중첩 섹션 트리 + 결정적 블록 id 앵커. 스펙=`construction/shared/docmodel.md`, 스키마=`shared/dtos/docmodel.schema.json`(검증 통과) | 리치뷰 렌더 + 요약 입력 + 에이전트 toolschema의 계약 |
| **Q4** | `.txt` 보존 여부 | **doc-model을 진실원천, `.txt`는 파생 평문 투영(검색·청킹용)으로 유지** | 또는 `.txt` 폐기하고 필요 시 doc-model에서 평문 도출 |
| **Q5** | 생성 트리거 | **첫 요약/열람/에이전트 사용 시 lazy 생성 + 캐시**; version 변경 시 무효화 | 인제스션 일부 eager는 인기 논문에 한해 후속 고려 |
| **Q6** | 폴백 사다리 동작 정의 | `arXiv HTML → e-print LaTeX → (최후) PDF 파싱(Grobid/Docling류)` | PDF 파싱단은 비-arXiv 대비 최후 폴백(현재 거의 미발동) |
| **Q7 ✅완료** | **요구사항 재진입 여부** — FR-12(요약 입력 형태) 변경 + 리치뷰 1급 기능화는 멀티모달/U8 선례처럼 Requirements Analysis 재진입 후보 | **재진입 완료(2026-06-23)**: 질문지 `requirement-verification-questions-docmodel.md` Q1~Q7(전부 권장안 + 리치뷰=신규 FR-18) → requirements.md 등재(FR-12 개정·FR-17 개정·**FR-18 신설**·§12 카브아웃·QT-5·§13) | — |
| **Q8** | **P3/P4/P5 선후** — P3(#135 맵리듀스 긴 입력·BR-S6)은 입력 형태가 doc-model로 바뀌므로 **doc-model 전환 후로**; P4(번역 품질 게이트)·P5(용어집 P2)는 독립 | **P3 = doc-model 후속**, P4·P5 = 병행 가능 | doc-model이 섹션 경계를 주면 맵리듀스 분할이 더 정확해짐 |

### 2.1 Q1 커버리지 스파이크 결과 (2026-06-23, 표본 41편 · 5cat×5yr)

> 스크립트: `scratchpad/coverage_spike.py`(arXiv API 표본 + arxiv.org/html·ar5iv probe + LaTeXML `ltx_` 카운트). **표본 41편 = 방향성치**(정밀 아님).

| 연도 | native HTML | ar5iv | either |
|---|---|---|---|
| 2017 | 0% | 7/8 | 87% |
| 2019 | 0% | 7/9 | 77% |
| 2021 | 12% | 7/8 | 87% |
| 2023 | 100% | 8/8 | 100% |
| 2025 | 62% | 8/8 | 100% |
| **전체** | **34%** | **90%** | **90%** |

- **native HTML = 2023년+ 전용**(구논문 0%) → 단독 34%, 부족.
- **ar5iv = 백카탈로그 주력**(2017~2021도 77~87%) → **필수**(옵션 아님). BR-29 `native→ar5iv` 사다리 검증.
- **HTML 전무 = 9%** → **e-print/PDF 폴백(Q6) 실필요**(이론 아님).
- **수식**: HTML 보유분 `<math>`(MathML) **94%** → 사실상 해결.
- **표**: 보유 45%는 *표를 가진 논문 비율*(math 증명논문은 원래 0); 표가 **있을 때 전부 `ltx_tabular`=구조화** → 추출 방식 검증.
- **함의**: D6(lazy on-demand) 유리(최신 HTML 생성 지연 회피) · ar5iv 의존 명시 · 폴백 사다리 필수 구현.
- **미측정 단서**: ar5iv 렌더 *품질*(존재만 확인)·표본 소(±오차). 배포 전 더 넓은 표본 권장.

---

## 3. Blast Radius — 편집 대상 체크리스트

> 코드 세션에서 이 순서/대상으로 진행. 각 항목 완료 시 [x]. **대부분 새 문서가 아니라 기존 유닛 문서 *편집*.**

**요구사항/계약**
- [x] `requirements.md` — FR-12(요약 입력 = 구조화 doc-model), 리치뷰 1급화, §12 카브아웃 정합 (Q7 결과 반영) → **FR-12 개정·FR-17 개정·FR-18 신설·§12 doc-model 카브아웃·QT-5 보강·§13 추적성 + 질문지 신설**
- [x] `shared/dtos/` — doc-model 스키마 SSOT 신설(Q3) → **`shared/dtos/docmodel.schema.json` + 스펙 `construction/shared/docmodel.md` + overview/README 포인터**(중첩 트리·블록 id·표=데이터·수식=LaTeX·webp 참조·provenance; 양성/음성 검증 통과)

**U1 Ingestion (생산자)**
- [x] FD `business-logic-model.md` — BR-29 확장: 보관=평문 1종 → **+doc-model**; `ingestOne`에 doc-model 생성/캐시 단계(lazy) → **§7 신설 + §6.3 무효화 연동**
- [x] FD `business-rules.md` — 표=데이터·수식=LaTeX 규칙; 그림 webp 참조 연결 → **BR-29 carve-out 뒤집기 + BR-30 신설(doc-model 구조·생성)**
- [x] NFR `tech-stack-decisions.md` — **TD-12 재검토**(표=PDF크롭 → HTML 표=데이터); HTML 파서 의존성(lxml/BeautifulSoup·MathML→LaTeX) → **TD-12 재작성 + TD-16 신설 + TD-11 최후폴백 강등**
- [x] Infra `infrastructure-design.md` — S3 `doc-model/` prefix(단일 버킷) + **요약 잡 큐·요약 워커 배포 단위 ④ + IAM 3역할**(빌드 큐=ingestion 재사용). PR-1 slice 6 CDK(`compute_stack`·신규 `summarization_stack`·app.py, `cdk synth` 검증·배포 X)와 함께 완료.

**U7 Summarization (소비자 — 입력 교체)**
- [x] FD `domain-entities.md`·`business-logic-model.md` — SourceSelector/full-text 어댑터 입력 = doc-model; 프롬프트가 표·수식 인지 → **SourceText/RefinedSource(+tables[]) · SourceSelector·InputRefiner·프롬프트(표=데이터·수식 LaTeX)**
- [x] FD `business-rules.md` — 입력 계약 갱신(로직 불변 명시) → **BR-S2/BR-S3 doc-model 입력 + 로직 불변 명시**
- [x] NFR/Infra — 입력 어댑터 경량 정합 → **NFR `tech-stack-decisions` TD-S9 비동기 잡(SQS 요약 큐+요약 워커) 구현 반영**(PR-1 slice 5b). Infra 배치(큐·워커 배포)는 slice 6.

**U5 Frontend (리치뷰)**
- [x] 자체 리치뷰 컴포넌트(doc-model 렌더: KaTeX·표·그림·목차/앵커 점프) → **실제 위치는 상세 표면 소유한 `u7-summarization-frontend` `FullTextViewer`→`DocModelViewer`(§2.10)에 본문화**(U5 frontend-components는 히어로/검색 슬라이스 전용). `getFullText`→`getDocModel`·union 매핑·계층도 갱신
- [x] 기존 `AssetGallery`/앵커 매처 재사용 연결 → **U5 `frontend-components.md` §6 신설**: 그림=AssetGallery webp 재사용, **표=크롭 폐기→DocModelViewer 표 컴포넌트(D8)**, AssetGallery 스코프=그림 전용 축소

**원장**
- [x] `aidlc-state.md` — 사후 결정 절에 **PR-1(doc-model 실데이터·비동기) entry** 등재(2026-06-24). 비전(`:159-162`) doc-model 흡수 명시는 후속.

**PR-1 추가(실데이터·비동기, 2026-06-24 back-sync)**
- [x] 공유계약 — `docmodel.schema.json` **building**·`summarization.schema.json` **pending** 신설(재생성) + `shared/docmodel.md` §5 union 갱신
- [x] U1 FD `business-logic-model.md` §7.2 — lazy 빌드 **트리거(경계 B·`BUILD_DOC_MODEL` 큐 잡·building)** 구체화
- [x] U7 FD `business-rules.md`·`business-logic-model.md` — BR-S6(3단계 맵리듀스)·BR-S9(pending)·BR-S12(비동기 잡 구현)·BLM §3.6
- [x] U7 NFR `tech-stack-decisions.md` — TD-S9 비동기 잡 구현 반영
- [x] Infra `infrastructure-design.md` + CDK(slice 6) — 단일 버킷 prefix·요약 큐·워커 배포 단위 ④·IAM, `cdk synth` 검증(배포 X)
- [x] OA 게이트(slice 7) — OA 신호 = U1 인제스션 검증(BR-1); 게이트=운영 토글(논문별 조회 불요), 주석·문서 정합

**PR-2 (구조화 번역, 2026-06-24, doc-first)** — 번역 영역 전부(PR-1에서 의도적 미룸). 설계 게이트 확정: ① 출력 = **번역본 doc-model**(자기완결; `summarization.schema.json`이 `docmodel.schema.json#/$defs/DocModel`을 **크로스파일 `$ref`** — 복제 회피, 생성기 지원 확인) ② 긴 번역 = **비동기**(요약 잡 큐·워커 재사용, `task=translate`).
- [x] 공유계약 — `summarization.schema.json` `TranslationDraft`: `{koreanText}` → `{docModel: $ref DocModel, keptTerms}` 개정 + 재생성 + 프론트 `types/generated/summarize.ts` 수기 갱신(`import DocModel`) + drift `--check`(green)
- [x] U7 FD `business-rules.md` — **BR-S18 신설**(구조화 번역 출력·번역 단위/보존·재조립 안정성·긴 번역 map-only) + BR-S2/S6/S9/S12 정합
- [x] U7 FD `domain-entities.md`·`business-logic-model.md` — `TranslationDraft`=번역본 doc-model; `_run_translate` 구조화/map-only 경로; 잡 큐·워커 task-agnostic 명시
- [x] U7 백엔드 — `StructuredTranslator` 도메인(소스 doc-model 워크→번역 유닛 추출→번역본 doc-model 재조립; 표 셀·수식·코드=verbatim) + 게이트웨이 `translate_segments`(id→ko) + orchestrator MAP_REDUCE 밴드 map-only·enqueue(task-agnostic 워커 재사용). **자기완결 출력이라 parserVersion 캐시키 desync 무관**(번역본이 자체 doc-model 보유·별도 fetch 없음 — 불요로 정정)
- [x] U5/U7-frontend — `DocModelViewer` 렌더부 `DocModelBody`로 분리 → `TranslationView`가 `translation.docModel` 구조 렌더(keptTerms 유지·그림 자산 로드)
- [x] requirements `FR-13` 개정 + 추적성 + 개정 배너 / `aidlc-state.md` PR-2 entry
- [x] 테스트 동반(StructuredTranslator·map-only·orchestrator·assembler·DTO 라운드트립·프론트 렌더) · 배포 X. **검증: summarization pytest green·ruff 베이스라인·shared drift 0·프론트 tsc/lint/vitest 93 green.**
- **후속(PR-2 아님)**: 표 셀 번역(현 verbatim) · 각주 footnote 블록 보존 · 앵커 id 계약 정합 · doc-model 빌드 실패 네거티브캐시

---

## 4. 시퀀싱 (권장 순서)

1. **Q1 커버리지 스파이크** (반나절) — "배포 확정"의 선결 게이트
2. **Q3 doc-model JSON 스키마** 설계 — §3 전부의 계약
3. **U1**: doc-model 생산(파서 + lazy 캐시) + 표/수식 데이터화
4. **U7**: 입력 전환(source → doc-model) — 요약/번역 품질 업그레이드
5. **U5**: 자체 리치뷰 렌더
6. **(별 트랙)** 문헌탐색/근거형성·아이디어검증 에이전트 → 그 안에서 **on-demand 비전 툴**

> 세션 운영: 본 게이트 문서·blast-radius 확정까지가 "문서 수정" 범위. 코드는 **새 세션에서 본 문서를 단일 진실원천으로** 착수(이 대화 history 불요).

---

## 5. 보존 — 안 바뀌는 것 (헛수고 아님)
- **webp 자산 파이프라인**(FR-17) → 그림용으로 유지; 비전 on-demand 입력으로 후속 재사용
- **제목+초록 검색 인덱스**(Q2=B) → 불변(검색은 초록으로 충분; 에이전트 전문 retrieval은 on-demand 별 surface)
- **U7 요약/번역 로직**(생성-버퍼-검증·근거화·캐시·후치환) → 입력만 교체
