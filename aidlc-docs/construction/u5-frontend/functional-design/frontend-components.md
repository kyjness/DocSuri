# U5 Frontend — Frontend Components (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U5 Frontend (Track 3) · **일자**: 2026-06-16
**스코프**: 히어로 슬라이스(가입→로그인→검색→근거화 결과 + 상태 UX). 라이브러리/이력 컴포넌트 = 자리만 명시(후속 패스).
**근거**: `inception/application-design/components.md` §U5(7컴포넌트). 기술 무관 — props/state는 의미적 계약이며 프레임워크/SSR/타입생성은 NFR(§5-D).

---

## 1. 컴포넌트 계층

```
AppShell ........................ SSR 루트·라우팅·세션·전역 에러/로딩 바운더리·히어로 골격
└─ PhoneMockupFrame ............. 뷰포트 분기(폰 풀블리드 / 태블릿+ 목업), 리플로우 금지
   ├─ HeroLanding ............... US-H1 랜딩(검색 진입 + 가입/로그인 유도)
   ├─ AuthScreens ............... SignupForm / LoginForm (US-A1/A2 기여)
   ├─ SearchScreen .............. 질의 입력·제출·상태 표시 (히어로 표면 소유)
   │  ├─ ResultList ............. 랭킹순 top-N 목록 + 저하 배너 슬롯
   │  │  └─ ResultCard .......... 단일 논문 카드(7필드)
   │  └─ StateView .............. 빈/기권/저하/로딩/에러 공유 표시
   └─ (후속) LibraryScreen / HistoryScreen ... 커서 무한스크롤(계약만)

ApiClient (공유 레이어, 컴포넌트 트리 밖) ── transport seam → U6 게이트웨이
SessionContext (AppShell 제공) ── useSession()
```

> 새 컴포넌트·훅은 Part 1 근거 있을 때만. 위 트리는 components.md §U5 7컴포넌트 + 슬라이스용 폼/랜딩 분리로 최소 구성.

---

## 2. 컴포넌트별 계약 (props · state · 상호작용 · API 통합점)

### 2.1 AppShell
- **책임**: SSR 루트 레이아웃·라우트 트리, 세션 컨텍스트 전파, 보호 라우트 가드, 전역 로딩/에러 바운더리, 히어로 골격.
- **state**: `SessionContext { status, user? }` (currentSession에서 초기화).
- **메서드(의미)**: `render`, `navigate`, `useSession`.
- **API 통합점**: `ApiClient.currentSession()`(부트), `logout()`.
- **규칙**: BR-U5-11(fail-closed 바운더리), BR-U5-15(가드). 근거: SEC-8, FR-11, NFR-R1, US-H1.

### 2.2 PhoneMockupFrame
- **책임**: 뷰포트 분기 — 폰=풀블리드, 태블릿+=중앙 목업(내부폭=폰 뷰포트 고정, 리플로우 금지).
- **props**: `children`.
- **메서드**: `wrap`, `classifyViewport`.
- **규칙**: 의미 규칙만(B7) — px 경계는 NFR. 근거: NFR-U2, SEC-4(frame-ancestors=self).

### 2.3 HeroLanding (US-H1)
- **책임**: 첫 진입 — 검색 진입 CTA + 비로그인 시 가입/로그인 유도.
- **props**: `sessionStatus`.
- **상호작용**: "검색하기" → authenticated면 SearchScreen, anonymous면 AuthScreens로 유도.
- **근거**: US-H1.

### 2.4 SignupForm / LoginForm (AuthScreens)
- **책임**: 가입·로그인 입력·제출·결과 피드백.
- **props**: `redirectTo?`(로그인 후 복귀 목적지).
- **state(로컬)**: 폼 필드(`email`, `password`), `submitting`, `fieldErrors`.
- **검증**: `accounts.schema.json` 파생(필수·형식). 정책 메시지는 백엔드 응답 표시(BR-U5-2).
- **API 통합점**: `ApiClient.signup(SignupRequest)` → `SignupResult.accountId`; `ApiClient.login(LoginRequest)` → 세션 쿠키 → `currentSession()`.
- **규칙**: BR-U5-13/14/16. `password` 입력 전용(SEC-12/3). 근거: FR-7, US-A1/A2.

### 2.5 SearchScreen (히어로 표면 소유)
- **책임**: 질의 입력(≤500자)·동기 검색 트리거·상태 표시.
- **state(로컬)**: `query`, `screenState`(idle|loading|page|empty|abstain|degraded|invalid|error), `response?`.
- **메서드**: `submitQuery`, `renderState`, `validateInput`.
- **상호작용**: 입력 → 클라 검증(BR-U5-1) → 제출(로딩, 버튼 비활성·디듀프) → union 분기 렌더. 결과가 있으면 **검색어 저장 + 정렬 토글(관련도순/최신순)** 을 한 툴바로 노출(정렬=클라 측, 받은 top-N 재정렬, BR-U5-5).
- **API 통합점**: `ApiClient.search(SearchRequest)` → `SearchResponse` union.
- **근거**: FR-1, SEC-5, NFR-U1, NFR-P1, FR-11, US-H1.

### 2.6 ResultList
- **책임**: 랭킹순(PBT-03 순서 보존) top-N(~20) 세로 목록, 저하 배너 상단 슬롯, 0건/부분은 StateView 위임.
- **props**: `cards: ResultCardVM[]`, `degraded: boolean`.
- **메서드**: `render`.
- **근거**: FR-3, FR-11, US-D7.

### 2.7 ResultCard
- **책임**: 단일 논문 폰 카드(가로 스크롤 없음). `relevance`는 계약 유지·**화면 미표시**(2026-06-22 UX 패스, BR-U5-4/5).
- **props**: `card: ResultCardVM`, `bookmark?`(우상단 저장 슬롯), `action?`(푸터 슬롯 — 라이브러리 제거 등).
- **상호작용**: `arxivUrl` 외부 링크(http/https + noopener, BR-U5-7); **우상단 북마크 아이콘 = 라이브러리 저장**(`SaveToLibraryButton`, 멱등 add, BR-U5-23). 카드의 tldr 요약 피크 기능은 폐지(요약은 상세로 일원화 — u7-frontend FD §0 참조).
- **규칙**: BR-U5-4/5/6/23. 근거: FR-4, FR-5, NFR-U1, SEC-9, US-L2.

### 2.8a BottomNav (하단 탭바, 2026-06-22 UX 패스)
- **책임**: 인증 상태에서만 노출되는 **모바일 우선 하단 고정 탭바**. 화면 이동(검색/마이페이지) 담당. 상단 `AppHeader`는 브랜드+로그아웃만.
- **탭**: `검색`(/search) · `마이페이지`(/library). 현재 경로로 활성 표시(`aria-current`). "에이전트" 탭은 해당 기능이 생긴 뒤 추가(빈 목적지 탭 금지).
- **규칙**: 인증(`status==='authenticated'`)에서만 렌더. 콘텐츠가 바에 가리지 않도록 in-flow 스페이서로 공간 확보. 근거: US-H1, 모바일 우선.

### 2.8 StateView
- **책임**: 빈/기권/저하/로딩/에러 비기술 공유 표시.
- **props**: `kind: 'loading'|'empty'|'abstain'|'degraded'|'invalid'|'error'`, `message?`, `field?`.
- **메서드**: `renderEmpty`, `renderError`, `renderDegraded`, `renderLoading`(+ 기권 분기).
- **규칙**: BR-U5-8/9/10/11. fail-closed·스택 차단(SEC-15). 근거: FR-11, NFR-R1, FR-5, QT-3.

### 2.9 ApiClient (공유 레이어, 단일 진입점)
- **책임**: 타입드 동기 요청/응답, 세션 쿠키 동봉, 401/403/429/5xx → UserFacingError 정규화, 타임아웃, 중복 디듀프.
- **transport seam(B9)**: `MockTransport`(DTO 파생 픽스처) ↔ `HttpTransport`(게이트웨이) 설정 교체.
- **메서드(슬라이스 활성)**: `search`, `signup`, `login`, `logout`, `currentSession`.
- **메서드(계약만, 후속)**: `listSavedSearches`/`saveSearch`/`deleteSavedSearch`, `listLibrary`/`addToLibrary`/`removeFromLibrary`, `listHistory`.
- **규칙**: BR-U5-17/18/19. 근거: SEC-8, SEC-11, SEC-15, NFR-P1, RES-9.

---

## 3. 사용자 인터랙션 흐름 (히어로 슬라이스)

```
HeroLanding ─검색 CTA─▶ [anonymous] ─▶ SignupForm ─성공─▶ LoginForm ─성공(세션)─▶ SearchScreen
                         [authenticated] ────────────────────────────────────▶ SearchScreen
SearchScreen.submitQuery ─validateInput─▶ ApiClient.search ─▶ union 분기
   page→ResultList/ResultCard │ empty/abstain/degraded/invalid/error→StateView
```

## 4. 폼 검증 규칙 요약
| 폼 | 필드 | 클라 검증 | 백엔드 위임 |
|---|---|---|---|
| Search | query | 1~500자·trim·무해화 | 추가 무해화·정책 |
| Signup | email, password | 필수·이메일 형식 | 복잡도·블랙리스트·중복(409) |
| Login | email, password | 필수·형식 | 일반화 인증 에러(401/429) |

## 5. API 통합점 매핑
| 컴포넌트 | ApiClient 메서드 | DTO |
|---|---|---|
| AppShell | currentSession, logout | SessionInfo |
| SignupForm | signup | SignupRequest→SignupResult |
| LoginForm | login | LoginRequest→(세션 쿠키) |
| SearchScreen | search | SearchRequest→SearchResponse(union) |
| (후속) Library/History | list*/save*/add* | library.schema.json(커서) |

> 후속 패스: LibraryScreen/HistoryScreen 컴포넌트 상세, 커서 무한스크롤 상호작용, 검색 저장 진입점 — 본 슬라이스에선 계약/자리만 명시.

---

## 6. doc-model 리치뷰 — 멀티모달 자산 연계 (피벗 2026-06-23, D4)

> **SSOT**: `construction/plans/docmodel-foundation-pivot-plan.md`(D4·D8). 본 파일은 히어로/검색 슬라이스 소유 — **자체 리치뷰의 컴포넌트 계약은 상세 표면을 소유한 `u7-summarization-frontend` `DocModelViewer`(구 `FullTextViewer`, §2.10)에 본문화**한다. 여기서는 U5가 보유한 멀티모달 자산 코드와의 연계만 정리.

- **`AssetGallery`(U5 코드, FR-17)·앵커 매처(`lib/assetAnchor.ts`) 재사용**: 리치뷰 **그림(figure)** 은 기존 webp 썸네일 그리드+라이트박스를 그대로 재사용하고, figure 앵커는 기존 `matchAssetForAnchor`로 매칭한다(재구현 0).
- **표(table)는 더 이상 크롭 이미지가 아니다(D8)**: 기존 `AssetGallery`가 "그림·**도표** 썸네일 그리드"로 표를 크롭 이미지로 보여주던 것을 폐기 → 표는 `DocModelViewer`의 **구조화 표 컴포넌트(rows/cols)** 로 인라인 렌더. `AssetGallery`는 **그림 전용**으로 좁힌다(표 크롭이 폴백으로 남는 비-HTML 논문에 한해서만 이미지 표시).
- **수식·목차·앵커 점프**는 `DocModelViewer` 책임(KaTeX·`DocTOC`). U5 측 변경은 `AssetGallery` 스코프 축소(그림 전용) + 앵커 매처 공유뿐.
