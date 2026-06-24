# U5 Frontend — Domain Entities (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U5 Frontend (Track 3) · **일자**: 2026-06-16
**스코프**: 히어로 슬라이스(가입→로그인→검색→근거화 결과 + 상태 UX). 라이브러리/이력은 **계약만** 명시(구현 후속 패스).
**원칙**: 기술 무관. U5는 **자체 도메인을 소유하지 않는다** — 모든 데이터 엔티티는 `shared/dtos/*.schema.json`(SSOT)에서 소비하는 **뷰모델/표시 모델**이다. 발명 금지.

> 표기 규약: 외부 노출 DTO 필드만 다룬다. 내부 필드(raw 점수·timings·vector·lexicalTerms·chunkId·section·categories·owner id)는 **U5 도메인에 존재하지 않는다**(SEC-9).

---

## 1. 소비 엔티티 (shared/dtos 소유, U5는 읽기 전용)

### 1.1 SearchRequest (생산: U5 입력 → 소비: U2)
| 필드 | 타입 | 제약 | 출처 |
|---|---|---|---|
| `query` | string | 1~500자, 무해화(trim·정규화) | FR-1, SEC-5 |
| `options?` | (provisional) | U2 FD에서 확정 전까지 미사용 | dtos.md §1 |

### 1.2 SearchResponse (생산: U2 → 소비: U5) — **터미널 상태 union(oneOf)**
U5 ApiClient가 4분기로 분기해 화면 상태를 결정한다(FR-11).

```
SearchResponse
 ├─ SearchResultPageDTO  { cards: ResultCardVM[], meta: ResultMeta }      → 결과 페이지
 ├─ AbstainDTO           { reason }                                       → 기권(근거 없음)
 ├─ DegradedResultDTO    { cards: ResultCardVM[], meta(degraded=true), mode } → 저하 결과
 └─ ValidationErrorDTO   { field?, message }                              → 입력 검증 실패
```

### 1.3 ResultCardVM (표시 전용 카드 뷰모델) — **7필드 고정**
| 필드 | 타입 | 비고 |
|---|---|---|
| `title` | string | 외부 데이터 → 이스케이프 렌더(XSS) |
| `authors` | string[] | 〃 |
| `year` | integer | |
| `arxivId` | string | 표시용(버전 포함 가능) |
| `abstractSnippet` | string | 스니펫만(전문 초록 비노출) |
| `relevance` | (계약 유지·미렌더) | 계약상 VM에 유지하나 **화면 미표시**(2026-06-22 UX 패스). 순서는 받은 랭킹 기반 + 클라 정렬 토글. raw 점수 ❌(SEC-9) |
| `arxivUrl` | string | 실재 링크(FR-5 근거화) — http/https 검증 + noopener |

> `additionalProperties: false` — 이 7필드 외 어떤 카드 필드도 렌더하지 않는다(SEC-9, FROZEN-adjacent).

### 1.4 ResultMeta
| 필드 | 타입 | 화면 의미 |
|---|---|---|
| `resultCount` | integer | 결과 수(0이면 빈 상태) |
| `degraded` | boolean | true → 상단 저하 배너 |
| `degradationMode?` | (provisional) | **내부 분기 힌트 — 화면 비노출** |

### 1.5 계정 DTO (생산: U3 → 소비: U5)
| DTO | 필드 | 불변식 |
|---|---|---|
| `SignupRequest` | `email`, `password` | `password`=입력 전용·로그/응답/저장소 금지(SEC-12/3) |
| `SignupResult` | `accountId` | 성공 식별자만 |
| `LoginRequest` | `email`, `password` | 〃 password 입력 전용 |
| `SessionInfo` | `userId`, `expiresAt(ISO8601)` | 토큰/자격증명 비노출(SEC-9) |
| `SessionCookie` | — (transport) | **본문 DTO 아님** — secure/httpOnly/sameSite 쿠키. JS·본문에서 토큰 접근 불가 |

### 1.6 라이브러리/이력 (생산: U4 → 소비: U5) — **계약만, 후속 패스**
- `library.schema.json`의 커서 기반 목록 계약을 소비. 무한스크롤 누적 모델은 후속 패스 FD에서 상세화.

---

## 2. U5 로컬 표시 엔티티 (화면 상태 — DTO 아님)

U5가 소유하는 유일한 "엔티티"는 **화면 상태 머신의 상태값**이다(서버 데이터가 아님).

### 2.1 SessionContext (앱 전역, AppShell 소유)
```
SessionContext = { status: 'anonymous' | 'authenticated', user?: { userId, expiresAt } }
```
- `SessionInfo`에서 파생. 토큰은 포함하지 않음(쿠키 transport). 보호 라우트 가드의 클라이언트측 입력(SEC-8 편의 반영, 권위는 백엔드).

### 2.2 ScreenState (화면 로컬 상태 머신)
검색 화면의 터미널 상태 — `SearchResponse` union + 진행/입력에 대응:
```
ScreenState = idle | loading | page | empty | abstain | degraded | invalid | error
```
(상세 전이는 business-logic-model.md §검색 흐름 참조)

---

## 3. 엔티티 관계도

```
[SessionContext]──guards──▶[보호 라우트]
      ▲ (SessionInfo 파생)
      │
[AppShell]
   └─[SearchScreen]──submitQuery──▶[ApiClient.search]──▶[SearchResponse union]
                                                            │
                          ┌───────────────┬────────────────┼─────────────┐
                       page            abstain          degraded      invalid
                          │               │                │             │
                    [ResultList]      [StateView]      [ResultList      [StateView
                       └[ResultCard×N]  .기권          +저하배너]        .invalid]
```
