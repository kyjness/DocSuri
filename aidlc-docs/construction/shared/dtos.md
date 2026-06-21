# shared/dtos — API↔클라이언트 DTO 계약 (DTO Contracts)

**상태**: 🟡 PROVISIONAL (U2 검색결과/카드 DTO만 FROZEN-인접) · **일자**: 2026-06-16
**근거**: `application-design/component-methods.md`(U2/U3/U4 시그니처·DTO 타입명) · `services.md`·`component-dependency.md`(생산자/소비자·sync 엣지) · `vector-spec.md`(IndexRecord 카드 필드 — FROZEN) · `00-shared-contracts-overview.md`(상태 범례·소유·트랙 소비)
**1차 생산자**: U2/U3/U4 (API 경계) · **1차 소비자**: U5 (`ApiClient` → 화면 VM)
**불변식**: DTO는 **내부 필드(소유자 userId·내부 점수·디버그) 비노출**(SEC-9). 응답에 **평문 비밀번호·토큰 머티리얼·시크릿 비포함**(SEC-12/SEC-3). owner-scoping은 서버 인가(U3.AuthorizationGuard)로 강제하며 DTO는 owner 키를 외부에 싣지 않는다(SEC-8).

> **상태 범례**(overview §0 재인용): 🔒 **FROZEN**(해당 유닛 FD/NFR 완료) · 🟡 **PROVISIONAL**(형상은 inception application-design 기준, 해당 유닛 FD에서 정제). 현재 **U1 FD만 완료** → U2 검색결과/카드 DTO는 vector-spec IndexRecord(FROZEN)에 묶여 **FROZEN-인접**, U3/U4 DTO는 PROVISIONAL.

> **횡단 규약**(overview §5): `PaperId`=버전 없는 arXiv ID; `ArxivId`/`arxivId`=버전 포함 가능(표시용). 가산적 진화(필드 추가는 하위호환; 제거/의미 변경은 버전업).

> **altitude**: 본 계약은 **형상(필드·타입·의미·생산/소비)만** 기술. HTTP 상태 코드 매핑·쿠키 전송 속성(secure/httpOnly/sameSite)·직렬화는 **API/Infra Design**. 아래 인용된 상태코드/쿠키 플래그는 component-methods.md를 충실히 반영한 **비규범적 API-Design 힌트**다(단 httpOnly/secure/sameSite는 SEC-12 근거로 load-bearing).

---

## 1. U2 — Discovery/Search DTO (생산: U2 / 소비: U5)

> **상태**: 🟡 PROVISIONAL이나 **카드 필드는 FROZEN-인접** — `ResultCardVM`/카드 필드는 vector-spec.md IndexRecord **카드 필드(FR-4)** 에 1:1로 묶인다(아래 §1.1). 시그니처 출처: `QueryIntakeController.search(request: SearchRequest, ctx) -> SearchResponse`(component-methods U2), `ResultAssembler.assemble(...) -> SearchResultPageDTO | AbstainDTO | DegradedResultDTO`.
> **근거화 전제**(FR-5): 모든 노출 카드는 실재 IndexRecord(실재 arXiv ID/링크)에 매핑. U6.GroundingEnforcementHook(ports.md)이 응답 엣지에서 검증 — 날조 0건.

| DTO | 종류/형상 | 필드(외부 노출) | 의미·제약 | 상태 | 트레이스 |
|---|---|---|---|---|---|
| `SearchRequest` | 요청 | `query: string`, `options?` _(타입명 잠정 — SSOT는 `options?` 필드만)_ | 동기 검색 진입 입력. `query`는 FR-1/SEC-5 검증(빈값·≤500자·새니타이즈). `options`는 선택(타입 정제 시 확정). | 🟡 PROVISIONAL | FR-1, SEC-5, US-H1 |
| `SearchResponse` | 응답(union) | `SearchResultPageDTO \| AbstainDTO \| DegradedResultDTO \| ValidationErrorDTO` | 종단 상태 명시 합집합. `QueryIntakeController.search` 반환·U5 `ApiClient.search`가 분기 처리(FR-11 상태 표면화). | 🟡 PROVISIONAL | FR-11, US-D1..D7 |
| `SearchResultPageDTO` | 응답(성공/빈 페이지) | `cards: ResultCardVM[]`, `meta: ResultMeta` | 정렬 순서 보존 상위 N건 카드 페이지(FR-3). 카드 배열은 **랭킹 순서**(PBT-03). **`cards=[]`·`resultCount=0`이면 명시적 빈 페이지** — 무매치/코퍼스 밖(및 근거화 통과 후 전량 필터)이 여기로 종단한다(기권 ≠ 빈 결과, U5 B3-a). | 🟡 PROVISIONAL(카드 FROZEN-인접) | FR-3, FR-4, US-D6 |
| `ResultMeta` | 값 | `resultCount: int`, `degraded: boolean`, `degradationMode?: DegradationMode` | 결과 수·저하 여부 배너 힌트. 내부 점수/타이밍 비노출(SEC-9). | 🟡 PROVISIONAL | FR-11, QT-3 |
| `ResultCardVM` | 카드(값) | (§1.1 카드 필드) | 단일 논문 폰 카드 뷰모델. U5 `ResultCard.render(card)` 소비. **6개 필드는 vector-spec IndexRecord 카드 필드의 투영 + `relevance`(파생 표시값)**. | 🟡 FROZEN-인접 | FR-4, FR-5 |
| `AbstainDTO` | 응답(기권) | `reason` _(사유 코드; 타입명 잠정 — SSOT는 `AbstainResult{reason}`)_ | **근거화 거부 전용**(U6 verdict=abstain/block 매핑) — 비기술 메시지, **날조 결과 없음**, 내부 위반 상세 비노출. **무매치/코퍼스 밖은 여기 해당 없음** — 빈 페이지(`SearchResultPageDTO`, resultCount=0)로 종단(BR-9 / U5 B3-a). | 🟡 PROVISIONAL | FR-5, US-D5 |
| `DegradedResultDTO` | 응답(저하) | `cards: ResultCardVM[]`, `meta: ResultMeta`(degraded=true), `mode: DegradationMode` | 부분/lexical-only 폴백 결과를 저하 명시와 함께 반환(NFR-C1/US-R2). 카드 형상은 성공과 동일. | 🟡 PROVISIONAL | NFR-C1, US-R2, US-R3, QT-3 |
| `ValidationErrorDTO` | 응답(검증) | `field?: string`, `message: string` | FR-1/SEC-5 검증 실패 인라인 에러(비기술·내부정보 차단, fail-closed). | 🟡 PROVISIONAL | FR-1, SEC-5, FR-11 |

### 1.1 `ResultCardVM` 카드 필드 — vector-spec.md IndexRecord 카드 필드(FR-4)와 동일

> **불변식**: 6개 필드(`title`·`authors`·`year`·`arxivId`·`abstractSnippet`·`arxivUrl`)는 vector-spec.md §2 **카드 필드(FR-4)** 의 외부 노출 투영이며 IndexRecord 변경 없이 추가/축소하지 않는다(FROZEN-인접). **`relevance`는 IndexRecord 소속이 아니라 랭킹에서 파생한 표시용 값**(raw 점수 비노출, SEC-9). 내부 필드(`vector`·`lexicalTerms`·`chunkId`·`section`·`categories` 등)는 **카드에 비노출**(SEC-9).

| 카드 필드 | 타입 | IndexRecord 출처 | 의미 | 트레이스 |
|---|---|---|---|---|
| `title` | string | IndexRecord.`title` | 논문 제목 | FR-4 |
| `authors` | string[] | IndexRecord.`authors` | 저자 | FR-4 |
| `year` | int | IndexRecord.`year` | 게재 연도 | FR-4 |
| `arxivId` | string | IndexRecord.`arxivId` | 표시용 arXiv ID(버전 포함 가능) | FR-4 |
| `abstractSnippet` | string | IndexRecord.`abstractSnippet`(전체 `abstract`에서 파생) | 카드용 초록 스니펫(전체 초록 비노출, 스니펫만) | FR-4, FR-5 |
| `relevance` | (표시용 관련도) | 랭킹 순서/표시 등급(파생) | **표시용 관련도만** — 내부 raw 점수·디버그 신호는 비노출(SEC-9). | FR-3, FR-4 |
| `arxivUrl` | string | IndexRecord.`arxivUrl` | **해소 가능 실재 링크**(FR-5 근거화 — 날조 금지) | FR-4, FR-5 |

---

## 2. U3 — Accounts/Auth DTO (생산: U3 / 소비: U5) — 🟡 PROVISIONAL (U3 FD에서 정제)

> 시그니처 출처: `AccountController.signup(req: SignupRequest, ctx) -> HttpResponse<SignupResult>`, `login(req: LoginRequest, ctx) -> HttpResponse<SessionCookie>`, `currentSession(ctx) -> HttpResponse<SessionInfo>`(component-methods U3).
> **불변식**(SEC-12/SEC-3): **어떤 응답에도 평문 비밀번호 미포함·비로깅.** `password`는 요청 입력 전용. 세션 토큰 머티리얼은 보안 쿠키(secure/httpOnly/sameSite)로 전달되며 본문 DTO에 노출하지 않는다. 자격증명 존재 여부 미노출(일반화 에러).

| DTO | 종류 | 필드(외부 노출) | 의미·제약 | 상태 | 트레이스 |
|---|---|---|---|---|---|
| `SignupRequest` | 요청 | `email: string`, `password: string` | 셀프 가입 입력. `password`는 입력 전용·비로깅(SEC-3). 정책/유출 검사는 서버(PasswordPolicy). | 🟡 PROVISIONAL | FR-7, US-A1, SEC-12 |
| `SignupResult` | 응답 | `accountId` | 가입 성공 식별자만 반환. 자격증명·내부 상태 비노출. 충돌/정책 위반은 일반화 에러(409/400/429). | 🟡 PROVISIONAL | FR-7, US-A1, SEC-9 |
| `LoginRequest` | 요청 | `email: string`, `password: string` | 로그인 입력. `password` 입력 전용·비로깅. 실패는 일반화 인증 에러(401/429, 자격증명 존재 미노출). | 🟡 PROVISIONAL | FR-7, US-A2, SEC-12 |
| `SessionCookie` | 응답(쿠키) | (쿠키 머티리얼 — 본문 미노출) | `login` 성공 시 **보안 세션 쿠키**(secure/httpOnly/sameSite) 설정. 토큰 평문은 본문 DTO로 노출하지 않음(SEC-12). | 🟡 PROVISIONAL | FR-7, US-A2, SEC-12 |
| `SessionInfo` | 응답 | `userId`, `expiresAt` | `currentSession` 비민감 세션 정보(프런트 세션 동기화). 토큰·자격증명·내부 핸들 비노출(SEC-9). | 🟡 PROVISIONAL | FR-7, US-A2, SEC-9 |

---

## 3. U4 — Saved Searches & Library DTO (생산: U4 / 소비: U5) — 🟡 PROVISIONAL (U4 FD에서 정제)

> 시그니처 출처: `SavedSearchController`·`LibraryController`·`SearchHistoryController`(component-methods U4). 모든 컬렉션 응답은 `PageParams{limit, cursor}` 입력으로 페이지네이션.
> **불변식**(SEC-8/SEC-9): DTO는 **owner `userId`를 외부에 싣지 않는다** — 소유권은 서버 인가(U3.AuthorizationGuard 단일 결정점)로 강제, `UserDataRepository`의 owner-scoping은 데이터 백스톱. 타 소유 리소스 접근은 **NotFound로 일반화**(존재 미노출). 내부 점수/감사 메타 비노출(SEC-9).
> **rerun 주석**: `SearchResultSetDTO`는 게이트웨이-프런티드 검색 계약(U6 ApiGatewayMiddleware → U2)으로 재실행된 결과이며 §1 검색 카드 형상을 재사용한다(직접 U2 호출 아님).

| DTO | 종류 | 필드(외부 노출) | 의미·제약 | 상태 | 트레이스 |
|---|---|---|---|---|---|
| `PageParams` | 요청(공통) | `limit`, `cursor` | 커서 기반 페이지네이션 입력(전 컬렉션 조회 공통). | 🟡 PROVISIONAL | FR-8, FR-9, FR-10 |
| `SavedSearchCreateDTO` | 요청 | `query`, `label?` | 새 검색 저장 입력. owner는 세션 컨텍스트에서 서버 결정(본문 미포함, SEC-8). | 🟡 PROVISIONAL | FR-8, US-L1 |
| `SavedSearchDTO` | 응답 | `id`, `query`, `label?`, `createdAt` | 저장 검색 단건(owner userId 비노출). | 🟡 PROVISIONAL | FR-8, US-L1, SEC-9 |
| `SavedSearchPageDTO` | 응답(컬렉션) | `items: SavedSearchDTO[]`, `nextCursor?` | 사용자 소유 저장 검색 최근순 페이지. | 🟡 PROVISIONAL | FR-8, US-L1 |
| `LibraryItemCreateDTO` | 요청 | `arXivId`, `meta`(메타 스냅샷) | 라이브러리 멱등 추가 입력. `(userId, arXivId)` 멱등(서버). 메타 스냅샷 보존(U2/인덱스 비의존). | 🟡 PROVISIONAL | FR-9, US-L2 |
| `LibraryItemDTO` | 응답 | `id`, `arXivId`, `meta`(스냅샷), `addedAt` | 라이브러리 항목 단건(owner userId 비노출). 멱등 추가 시 신규/기존 동형 반환. | 🟡 PROVISIONAL | FR-9, US-L2, SEC-9 |
| `LibraryPageDTO` | 응답(컬렉션) | `items: LibraryItemDTO[]`, `nextCursor?` | 사용자 소유 라이브러리 페이지. 보존 메타 스냅샷만 반환(가용성 격리). | 🟡 PROVISIONAL | FR-9, US-L2 |
| `HistoryEntry` | 응답 | `id`, `query`, `executedAt`, `resultCount` | 단일 검색 이력 항목(`SearchExecutedEvent` 비동기 기록 원천, owner userId 비노출). | 🟡 PROVISIONAL | FR-10, US-L3, SEC-9 |
| `HistoryPageDTO` | 응답(컬렉션) | `items: HistoryEntry[]`, `nextCursor?` | 최근 검색 이력 최근순 페이지. | 🟡 PROVISIONAL | FR-10, US-L3 |
| `SearchResultSetDTO` | 응답(rerun) | (§1 `SearchResultPageDTO` 형상 재사용) | 저장 검색/이력 rerun 결과 — 게이트웨이-프런티드 검색(U6→U2) 반환을 §1 카드 DTO로 표면화. | 🟡 PROVISIONAL | FR-8, FR-10, US-L1, US-L3 |

---

## 4. 비노출 규약 요약 (SEC-8/SEC-9, SEC-12/SEC-3)

- **내부 필드 비노출(SEC-9)**: owner `userId`(U4 DTO 본문)·내부 raw 관련도/랭킹 점수·디버그·트레이스·감사 메타·`vector`/`lexicalTerms`/`chunkId`/`section`(IndexRecord 내부). 카드는 §1.1 7필드만.
- **소유권 서버 강제(SEC-8)**: owner-scoping은 U3.AuthorizationGuard(단일 결정점)+`UserDataRepository`(백스톱). 타 소유 리소스는 NotFound 일반화.
- **자격증명/세션(SEC-12/SEC-3)**: `password`는 요청 입력 전용·비로깅·어떤 응답에도 미포함. 세션 토큰은 보안 쿠키로만, 본문 DTO 비노출.
- **fail-closed(SEC-15/FR-11)**: 에러 DTO는 비기술 일반화 메시지, 스택/내부 식별자 차단.
