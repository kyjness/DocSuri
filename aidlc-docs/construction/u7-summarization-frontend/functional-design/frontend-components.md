# U7 Summarization Frontend — Frontend Components (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U7 Summarization Frontend 슬라이스 · **일자**: 2026-06-19
**스코프**: 단일 논문에 대한 온디맨드 **요약 / 초록 번역 / 전문 번역** 클라이언트 표면 + **출처 보기(전문 하이라이트 뷰어, Q5=C)**. 진입 = 검색·라이브러리 공용 카드(US-S1~S5).
**근거**: 계획서 `construction/plans/u7-summarization-frontend-functional-design-plan.md`(§확정 결정 8문) · 백엔드 계약 `backend/modules/summarization/`(`POST /api/summarize`) · 프론트 자산 `frontend/lib/api/*`(ApiClient·classify union)·`StateView`·`ResultCard` · SSOT `inception/requirements/summarization-translation-pipeline.md`(2026-06-19 개정).
**원칙**: 기술 무관 — props/state는 **의미적 계약**. 프레임워크/SSR/transport(BFF 실 경로 — real-first, mock 없음)·타입생성·성능 수치는 NFR.

---

## 0. 설계 편차 — 본문 중심 상세 + 요약 모달 (2026-06-19, 제품 방향 반영)

초기 FD(§2.4/2.5)는 상세 페이지를 **요약 우선**(진입 시 요약 자동 표시, persona 토글 인라인)으로, 전문은 앵커 클릭 시 `FullTextViewer`로 여는 구조였다. 제품 방향에 따라 상세 표면을 다음과 같이 **본문 중심**으로 재구성한다:

- **DocSuri 헤더 바로 아래** = 스티키 액션 바 `[요약]`·`[초록 번역]`·`[전문 번역]` 3버튼. 각 버튼 → 해당 탭으로 **모달 오버레이(`SummaryModal`)** 를 연다.
- **상세 본문** = `PaperHeader`(제목·저자·초록·arXiv 링크) + **정규화 S3 전문(`FullTextViewer`)을 본문으로 직접 표시**(앵커 없이 로드).
- **모달(`SummaryModal`)** 은 액션 바에서 **선택된 한 가지 모드만** 렌더(모달 내부에 모드 전환 탭 없음). 제목 + 닫기(✕)만 두고, `PersonaToggle`(전문가용/입문자용)은 **요약 모달에서만** 표시.
- **앵커 클릭**(요약 내 출처 칩) → 모달 닫힘 + 본문 `FullTextViewer`에서 해당 span 하이라이트(Q5=C 유지).
- **카드 [요약]/TL;DR 인라인 피크 폐지 (2026-06-22 UX 패스)** — 카드에서 `SummaryAction`/`SummaryInline`(§2.1 슬롯·§2.2·§2.3)을 제거한다. 카드 tldr 미리보기 기능 자체를 없애고 요약·번역·출처는 **상세 페이지로 일원화**(상세 [요약] 모달, BR-SF-1). **Q1·Q2의 "카드 인라인 tldr 피크" 결정은 본 패스로 대체된다.** 무거운 액션·번역·persona 전환이 상세에 있다는 원칙은 그대로(이제 가벼운 tldr 피크도 상세로 흡수).
- `PaperHeader` 메타데이터는 **discovery(U2) 논문 메타데이터 엔드포인트**로 채운다: `PaperMetaVM` + `ApiClient.getPaperMeta` (`GET /api/papers/{id}`). 제목·저자·초록은 코퍼스/검색 인덱스 데이터라 U7이 아닌 **discovery(U2) 소관**으로 구현(OpenSearch 단건-read → `PaperMetadataService` → `PaperMetaDTO`). dev는 mock, 실연동은 discovery 엔드포인트. FD §2.5의 "검색 VM 보유분 전달" 대신 직접 진입에서도 헤더를 채우기 위함.
  - **재정합(2026-06-19)**: 프론트 `PaperMetaVM`은 discovery `PaperMetaDTO`(`{arxivId,title,authors,year,abstract,arxivUrl}`)를 1:1 미러. 현재 손수 작성 타입 — shared 스키마 승격(codegen) 시 생성 타입으로 교체 예정(잔여 작업).
- **전문 본문 자동 로드**: `FullTextViewer`는 상세 진입 시 자동 로드(BR-SF-1 탭 트리거의 예외 — business-rules.md BR-SF-1 편차 참조). 라이선스 게이트(OA)는 그대로 적용 — 전문 표시 가능 여부는 백엔드 게이트가 결정.
- **`TranslationView` 표시 변경**: scope 라벨(초록/전문) 중복 표기를 제거(모달 제목이 대체). 데이터 모델 `TranslationVM.scope`는 유지 — 표시만 생략.

> 아래 §2.4(PaperDetailScreen)·§2.5(PaperHeader)의 "요약 우선/전문 비표시" 서술은 본 §0으로 갱신됨. 컴포넌트 단위 계약(props/state/규칙)은 유효.
> 비고: 액션 바 3버튼은 별도 컴포넌트(FD §2.6 `SummaryActions`)를 재사용하지 않고 상세 island 내부에 인라인 구현됨(모달 내부 탭이 사라져 탭 컨테이너 불요). `SummaryActions` 컴포넌트는 제거했고, `DetailView` 타입은 `SummaryModal`로 이전함.

---

## 1. 컴포넌트 계층

```
AppShell (기존 U5) ............... SSR 루트·라우팅·세션·전역 바운더리
├─ (검색/라이브러리 표면 — 기존)
│  └─ ResultCard ................ 단일 논문 카드(우상단 북마크 저장, 푸터 action 슬롯)
│     ├─ SummaryAction .......... [폐지 2026-06-22] 카드 [요약]→tldr 피크 제거 — 요약은 상세로
│     └─ SummaryInline .......... [폐지 2026-06-22] tldr 경량 뷰 제거
│
└─ (라우트) PaperDetailScreen ... /paper/[id] — 전용 상세 라우트(신규, Q1=하이브리드)
   ├─ PaperHeader ............... 제목·저자·영문 초록 + [arXiv에서 원문 보기] 링크아웃
   ├─ SummaryActions ........... [요약] · [초록 번역] · [전문 번역] 액션 바 (Q6)
   ├─ PersonaToggle ............ [전문가용 | 입문자용] 세그먼트 — 요약 전용(Q4=A)
   ├─ SummaryView .............. 구조화 6필드 렌더 + 항목별 AnchorChip
   │  └─ AnchorChip ............ 출처 칩(target·label) → 클릭 시 FullTextViewer 하이라이트
   ├─ TranslationView .......... koreanText + keptTerms 배지 (초록·전문 공용)
   ├─ FullTextViewer→DocModelViewer  doc-model 리치 렌더(목차·KaTeX 수식·표 컴포넌트·webp 그림·앵커 하이라이트) — 피벗 2026-06-23 D4 (Q5=C)
   └─ StateView ................ 로딩/기권/비용저하/소스부재/에러 공유 (기존 확장)

ApiClient (공유 레이어, 트리 밖) ── transport seam → U6 게이트웨이
├─ summarize(SummarizeRequest) → SummarizeOutcome  (status 판별 union)
└─ getFullText(FullTextRequest) → FullTextOutcome   (Q5=C, OA 라이선스 게이트)
```

> 신규 컴포넌트는 결정 게이트 근거가 있는 것만: `PaperDetailScreen`·`SummaryActions`·`PersonaToggle`·`SummaryView`/`AnchorChip`·`TranslationView`·`FullTextViewer`·`SummaryInline`. `ResultCard`/`StateView`/`AppShell`/`ApiClient`는 기존 재사용·확장.

---

## 2. 컴포넌트별 계약 (props · state · 상호작용 · API 통합점)

### 2.1 ResultCard (카드 = 저장 진입점, 요약 진입 아님)
- **책임**: 기존 카드. **카드에서 요약을 트리거하지 않는다**(2026-06-22 UX 패스 — §0). 우상단 `bookmark` 슬롯 = 라이브러리 저장, 푸터 `action` 슬롯 = 라이브러리 화면 제거 등. 요약은 카드 제목 링크로 상세 진입 후.
- **props**: `bookmark?`(우상단 저장), `action?`(푸터). _(구 `action ← SummaryAction` 주입은 폐지.)_
- **규칙**: 카드 자체는 비싼 호출을 트리거하지 않는다(BR-SF-1). 안전 링크(`safeHref`, BR-U5-7) 유지.
- **근거**: US-S1, US-L2. _(Q1·Q2의 카드 tldr 피크 결정은 §0으로 대체.)_

### 2.2 SummaryAction [폐지 — 2026-06-22 UX 패스]
> 카드 인라인 [요약]→tldr 피크는 제거됨. 요약은 상세 페이지([요약] 모달)로 일원화. 아래 계약은 이력 보존용.
- **책임**: 카드의 [요약] 버튼. 탭 → `summarize(task:"summary")` 호출 → 결과의 `tldr`만 `SummaryInline`으로 인라인 펼침. 항상 `상세히 보기` 링크(→ `/paper/[id]`)를 동반.
- **state(로컬)**: `screenState`(idle|loading|page|abstain|degraded|sourceUnavailable|error), `outcome?`.
- **상호작용**: 탭 → 로딩(또는 `cached:true`면 즉시) → tldr 인라인. 전체/번역/출처는 `상세히 보기`로.
- **API 통합점**: `ApiClient.summarize({ task:"summary", paperId, version, persona })`.
- **규칙**: BR-SF-1(탭 트리거), BR-SF-5(캐시 표기), BR-SF-7(상태 우선순위). 근거: US-S1·S5, Q1.

### 2.3 SummaryInline [폐지 — 2026-06-22 UX 패스]
> 카드 tldr 경량 뷰 제거(카드 요약 피크 폐지에 수반). 아래는 이력 보존용.
- **책임**: `tldr`(3줄) 경량 뷰. 같은 §3 출력의 **뷰 프리셋** — 추가 생성/요청 0.
- **props**: `tldr`, `cached`.
- **규칙**: 외부 텍스트 이스케이프(BR-SF-9). 근거: SSOT §9.2(뷰 프리셋).

### 2.4 PaperDetailScreen (`/paper/[id]`, 신규 라우트)
- **책임**: 단일 논문 상세 표면 소유 — 헤더·액션·결과 렌더·상태. 요약/번역/전문뷰어의 컨테이너.
- **props**: 라우트 파라미터 `paperId`(=arxivId, Q8=A), `version`(=1, Q8=A).
- **state**: `activeView`('summary'|'abstractTrans'|'fullTrans'), `persona`('expert'|'beginner'), 각 작업별 `screenState`+`outcome`(독립), `anchorTarget?`(뷰어 하이라이트 대상).
- **상호작용**: 액션 선택 → 해당 작업 요청/렌더. 앵커 클릭 → `FullTextViewer` 열고 위치 하이라이트.
- **API 통합점**: `summarize(...)`(3종), `getFullText(...)`(앵커 클릭 시).
- **규칙**: BR-SF-2(요청 구성)·BR-SF-6(persona 전환)·BR-SF-7·BR-SF-8(앵커→뷰어). 근거: US-S1~S5, Q1·Q3.

### 2.5 PaperHeader
- **책임**: 제목·저자·영문 초록(검색 VM 보유분) + `[arXiv에서 원문 보기]` 링크아웃.
- **props**: `title`, `authors`, `abstract`, `arxivUrl`.
- **규칙**: 안전 링크(`safeHref` http/https + noopener, BR-U5-7). 영문 원문 전문은 **앱 내 표시 안 함** — arXiv로(라이선스·기계연료). 근거: SSOT §1(라이선스).

### 2.6 SummaryActions
- **책임**: [요약] · [초록 번역] · [전문 번역] 3버튼(Q6=명시 버튼). 각 버튼 = 별도 task/scope 요청.
- **props**: `paperId`, `version`, `persona`, `onSelect(view)`.
- **상호작용**: [요약]→`task:"summary"`(+persona) / [초록 번역]→`task:"translate", scope:"abstract"` / [전문 번역]→`task:"translate", scope:"full"`.
- **규칙**: 전문 번역은 시간·비용 큼 → 로딩 인디케이터(하드 게이트 없음, BR-SF-3). 캐시 적중 시 즉시(BR-SF-5).
- **근거**: US-S1·S2, Q6, SSOT §5(액션 3개).

### 2.7 PersonaToggle (요약 전용)
- **책임**: [전문가용 | 입문자용] 세그먼트(Q4=A). 전환 시 해당 persona로 **재요청**, 이미 만든 벌은 `cached:true`로 즉시.
- **props**: `value`('expert'|'beginner')`, `onChange`.
- **규칙**: 번역에는 노출하지 않는다(번역=단일, BR-SF-6). 전환=재생성 0(캐시), 추가비용 0.
- **근거**: US-S4, Q4, SSOT §9.2(persona=요약 한정).

### 2.8 SummaryView + AnchorChip
- **책임**: 구조화 6필드(`tldr`·`contributions[]`·`method`·`results`·`limitations`·`reproducibility`) 렌더. 각 항목 옆 `anchors[]` 기반 `AnchorChip`("출처: §Results · 표2").
- **props(SummaryView)**: `summary: SummaryVM`, `onAnchor(anchor)`.
- **props(AnchorChip)**: `anchor: AnchorVM`(`field`·`target`·`span`·`label`), `onClick`.
- **상호작용**: AnchorChip 클릭 → `PaperDetailScreen.anchorTarget` 설정 → `FullTextViewer` 열림·하이라이트(Q5=C).
- **규칙**: 외부 텍스트(요약·span) React 이스케이프(BR-SF-9). 날조 0 — 백엔드 근거화 통과분만 옴(표시 측 가공 금지, BR-SF-10).
- **근거**: US-S1·S3, §3 스키마.

### 2.9 TranslationView (초록·전문 공용)
- **책임**: `translation.koreanText` 렌더 + `keptTerms[]`(미번역 보존 용어) 배지. 전문 번역은 긴 스크롤 텍스트 블록.
- **개인 용어집 편집(BR-SF-17, BR-S4)**: `keptTerms[]` 배지는 탭 가능 — 탭하면 인라인 편집창에서 "내 번역어"를 저장(`POST /api/glossary`)하고, 재오픈 시 저장값을 미리채운다(`GET /api/glossary`). 편집창은 동시 1개만 열리며 바깥 클릭/Esc로 닫힘(모바일 기준 폭 보정). 저장값 조회 실패는 미리채우기 생략으로 degrade.
- **props**: `translation: TranslationVM`, `scope`('abstract'|'full'), `cached`.
- **API 통합점**: `ApiClient.listGlossaryTerms()`(미리채우기) · `ApiClient.upsertGlossaryTerm({termFrom, termTo})`(저장). 게이트웨이 미설정 dev에서는 in-browser fixture로 미리보기.
- **규칙**: 외부 텍스트 이스케이프(BR-SF-9). 번역은 앵커 없음(요약 전용). 근거: US-S2, Q6.

### 2.10 FullTextViewer → **DocModelViewer (자체 리치뷰, 피벗 2026-06-23)**
> **피벗(doc-model, SSOT=`construction/plans/docmodel-foundation-pivot-plan.md` D4)**: 평문 전문 렌더 → **doc-model 자체 리치 렌더**(콘텐츠 충실; arXiv HTML(experimental) 방식, **PDF.js 픽셀 재현 아님**). 요약·번역·앵커·(후속)에이전트가 통합되는 **목적지 표면** + 로그수집·개인화 표면.
- **책임**: 논문 **doc-model**(구조화 본문)을 렌더 — 섹션/블록·**목차(TOC)·앵커 점프**, **수식=KaTeX/MathJax(LaTeX 렌더)**, **표=구조화 표 컴포넌트(rows/cols)**, **그림=webp**(아래 AssetGallery 재사용). 요약 출처 앵커(`target`/`span`)를 doc-model 앵커로 하이라이트·스크롤.
- **props**: `paperId`, `version`, `anchorTarget?`.
- **state(로컬)**: `screenState`(loading|page|licenseUnavailable|sourceUnavailable|error), `docModel?`.
- **API 통합점**: `ApiClient.getDocModel({ paperId, version })` → `DocModelOutcome`(cache miss 시 백엔드 lazy 생성 — U1 BR-30). 그림 자산은 기존 `GET /api/papers/{id}/assets`(서명 URL, AssetGallery 재사용).
- **하위 렌더 요소**: `DocTOC`(섹션 목차·앵커 점프) · `FormulaBlock`(KaTeX, LaTeX) · `TableBlock`(구조화 표 — **크롭 이미지 아님**, D8) · `FigureBlock`(webp, AssetGallery/라이트박스·앵커 매처 재사용) · 블록 텍스트(이스케이프).
- **규칙**: **OA 라이선스 미허용 → 'licenseUnavailable' 상태**(뷰어 대신 arXiv 링크아웃 안내, BR-SF-11). 외부 콘텐츠 이스케이프(BR-SF-9); **수식 LaTeX·표 데이터는 신뢰 렌더러(KaTeX·표 컴포넌트) 경유**(원시 HTML 주입 금지, SEC-5). 구조화 콘텐츠(참고문헌·저자 정규화 제거)임을 안내(BR-SF-12).
- **근거**: US-S3, Q5=C, **D1/D4/D8**. ⚠️ **백엔드 의존 변경**: 전문 평문 API → **doc-model 반환 API**(lazy 생성·캐시).

> **구현 정합 (back-sync, 2026-06-23 UX 패스)**: 구현은 §2.4의 "상세 진입 시 인라인 본문 자동 로드"에서 다음으로 이탈했고, 이 문단이 실제 형상의 SSOT다.
> - **본문은 인라인이 아니라 별도 전체화면 in-app 라우트** `/(paper)/[id]/doc-model`로 분리(브라우저 새 탭 아님 — 같은 탭 라우트). 상세 페이지엔 메타 아래 **`본문` 링크**(+`본문 번역` 링크 = `/(paper)/[id]/translate`, `FullTranslationIsland`)만 두고, 헤더 좌상단 **← 뒤로가기**(`AppHeader back`, `router.back()`)로 복귀. 상세 페이지 헤더도 브랜드 로고 대신 ← 뒤로가기.
> - **요약 출처 앵커** 클릭 → 모달 닫고 `router.push(.../doc-model?anchorLabel=…)`로 본문 라우트를 열어 해당 블록으로 스크롤(현재 매칭은 `anchorLabel` 기준; id 기반 앵커 계약은 후속).
> - **그림은 `AssetGallery` 재사용이 아니라 `DocModelViewer`가 `FigureBlock`에서 인라인 `<img>`로 직접 렌더**(assetId로 `/assets` 서명 URL 조인). 별도 그림/도표 썸네일 갤러리(`AssetGallery`/`AssetLightbox`/앵커 매처)는 중복이라 **제거**. (§1·§2.4의 "AssetGallery" 언급은 본 노트로 대체.)
> - 레거시 `FullTextViewer`/`useFullText`/`getFullText`(평문 뷰어 경로)는 `DocModelViewer`로 대체되어 **제거**.

### 2.11 StateView (기존 확장)
- **책임**: 비-해피 상태 공유 표시. U5 `StateViewKind`에 **`degraded`·`sourceUnavailable`·`licenseUnavailable`** 추가.
- **메시지 매핑(요약 전용 카피)**: 아래 §3 표.
- **규칙**: 무한 로딩 금지·스택/내부식별자 비노출(BR-U5-11, SEC-15). 근거: US-S3, FR-11.

### 2.12 ApiClient 확장 (공유 레이어)
- **신규 메서드**:
  - `summarize(req: SummarizeRequest): Promise<SummarizeOutcome>` — `POST /api/summarize`, 응답을 `classifySummarizeResponse`로 분류(status 판별).
  - `getDocModel(req: DocModelRequest): Promise<DocModelOutcome>` — Q5=C 엔드포인트(라이선스 게이트). **피벗(D4)**: 전문 평문 → doc-model 반환(cache miss 시 백엔드 lazy 생성·캐시, U1 BR-30). (구 `getFullText` 대체.)
- **규칙**: 단일 진입·transport seam·검증 기존 패턴 미러(`search()` 형). 토큰 클라이언트 비노출(SEC, `frontend/CLAUDE.md`). 근거: 기존 `lib/api/*`.

---

## 3. 응답 union → screenState 매핑 (전수 · 누락 0)

요약 응답은 **`status` 판별자**가 있어 구조 추정 불요(검색과 다름).

| 백엔드 응답 | 분류(`kind`) | screenState | StateView/렌더 |
|---|---|---|---|
| `{ status:"ok", summary }` | `summary` | `page` | SummaryView(+AnchorChip), `cached` 표기 |
| `{ status:"ok", translation }` | `translation` | `page` | TranslationView |
| `{ status:"abstain", reason }` | `abstain` | `abstain` | "근거가 부족해 요약을 보류했어요" |
| `{ status:"cost_degraded", message }` | `degraded` | `degraded` | "AI 요약이 일시 중단됐어요" |
| `{ status:"source_unavailable", reason }` | `sourceUnavailable` | `sourceUnavailable` | "원문을 가져올 수 없어요" |
| (HTTP 4xx 검증) | `invalid` | `invalid` | "입력을 확인해 주세요" |
| (네트워크/5xx) | `error` | `error` | "문제가 발생했어요 · 재시도" |
| (요청 중) | — | `loading` | "요약/번역 생성 중…" |

리치뷰(`getDocModel`, 구 `getFullText`) 매핑: `ok`→page(doc-model 리치 렌더) · `license_unavailable`→`licenseUnavailable`(arXiv 안내) · `source_unavailable`→`sourceUnavailable` · 네트워크→`error`.

---

## 4. 상호작용/접근성 노트 (의미만; 수치는 NFR)

- 모바일 터치 타깃(액션 3버튼·persona 토글·AnchorChip)·키보드/스크린리더 라벨.
- 로딩·기권·비용저하·소스부재·라이선스부재 상태를 **각각** 동반 설계(무한 로딩 금지).
- 전문 번역·전문뷰어는 긴 스크롤 — 점진 렌더/스트리밍 동반(구체는 NFR).
- 앵커 클릭 → 뷰어 하이라이트는 포커스 이동·복귀 처리.
