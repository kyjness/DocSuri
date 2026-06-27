# business-logic-model.md — U4 Library 비즈니스 로직 및 알고리즘 설계

**단계**: CONSTRUCTION → Functional Design (유닛별 루프, Track 2 두 번째 유닛) · **유닛**: U4 Library (검색 저장 · 라이브러리 · 검색 이력) · **일자**: 2026-06-17
**근거(SSOT)**: `u4-design-brief.md` (D1~D12 결정 · BR-L1~L10 · INV-L1~L4 반영) · `construction/shared/dtos.md §3`·`§1.1` · `shared/dtos/library.schema.json` · `shared/events/search-executed.schema.json` (🔒FROZEN) · `inception/application-design/{components,component-methods,services}.md` (U4) · `inception/user-stories/stories.md` (US-L1/L2/L3, epic 3)
**소유**: Track 2 (@revenantonthemission) — Track 2 flow = U3 Accounts → **U4 Library** (final unit)
**상속 규약**: 인가 단일 권위점은 **U3 `AuthorizationGuard` (SEC-8)** — 재정의 금지. `Principal`·`Action`·`AccountId`·`Decision`는 `backend.modules.accounts`에서 **REUSE**. 영속은 포트 기반(D10), 기본 `InMemoryUserDataRepository`(라이브 인프라 없이 마운트·테스트 그린), 프로덕션 `SqlUserDataRepository`(U3의 RDS PostgreSQL 상속).

> **altitude(고도) 주석**: 본 FD는 U4의 **세 서비스 오케스트레이션과 알고리즘(비즈니스 로직)** 을 기술한다. HTTP 상태 코드 매핑·라우터 prefix·DI 시임·쿠키/직렬화 같은 구체 배선은 NFR/Infra Design 및 component-methods에 위임하되, 본 문서가 load-bearing으로 명시하는 결정(generalized-404·게이트웨이 경유 rerun·멱등 이력 소비·메타 스냅샷 가용성 격리)은 코드 불변식으로 강제한다.

---

## 0. 유닛 개요 — 세 개의 소유자-사설 하위 도메인

U4는 인증된 사용자의 **개인 데이터**(소유자별로 격리된 검색 저장·라이브러리·검색 이력)를 관리하는 동기 CRUD 모듈이며, 검색 이력만 **이벤트 기반 비동기 기록**을 추가로 가진다. 세 하위 도메인은 각자 컨트롤러·서비스·리포지토리를 가지지만, 단일 `UserDataRepository` 포트(3개 서브-리포 집합)와 단일 인가 권위점(U3 `AuthorizationGuard`)으로 횡단 일관성을 유지한다.

| 하위 도메인 | 스토리 | FR | Controller | Service | Repository | 경로 |
|---|---|---|---|---|---|---|
| Saved Searches | US-L1 | FR-8 | `SavedSearchController` | `SavedSearchService` | `SavedSearchRepository` | `/library/saved-searches` |
| Library | US-L2 | FR-9 | `LibraryController` | `LibraryService` | `LibraryRepository` | `/library/items` |
| Search History | US-L3 | FR-10 | `SearchHistoryController` | `SearchHistoryService` | `SearchHistoryRepository` | `/library/history` |

**횡단 협력자**:
- **`UserDataRepository`** — 3개 서브-리포를 집합하는 포트. 소유자-스코핑 데이터 백스톱(INV-L1, SEC-8 데이터 계층).
- **`UserDataDTOAndValidation`** — DTO 매핑(`validate_and_map`/`to_dto`)·정규화·커서 코덱·SEC-5 검증·PBT-09 라운드트립 담당.
- **`SearchGatewayPort`** — rerun을 게이트웨이-프런티드 검색으로 재진입시키는 포트(D9/INV-L2). U4는 `StubSearchGateway`(결정적 플레이스홀더) 동봉, 실 바인딩은 U6/Infra.
- **`AuditSink`** — 변이 연산 감사 이벤트 싱크 포트(D12/BR-L10), 기본 in-memory/no-op.
- **U3 `AuthorizationGuard`** — `authorize(principal, action, AccountId(owner_id)) -> Decision` 단일 권위점(SEC-8). U4는 재정의하지 않고 위임만 한다.

**동기/비동기 경계(NFR-P1)**: 모든 CRUD 엔드포인트(save/list/delete/rerun, add/list/remove, history list/rerun/clear)는 **동기**다. 단 검색 이력의 **WRITE** 경로(`SearchExecutedEvent` 소비 → `recordSearch`)는 동기 검색 응답 경로(P50<3s) **밖에서** 비동기·논블로킹으로 수행되며 검색 응답을 절대 지연시키지 않는다(D7, NFR-P1).

---

## 1. 공통 인가·소유자-스코핑 오케스트레이션 (전 서비스 선행 단계)

세 서비스의 모든 변이/조회 연산은 동일한 인가 선행 게이트를 거친다. 이 게이트는 U4가 자체 판단하지 않고 U3 `AuthorizationGuard`에 위임하며, 거부는 **generalized-404**로 일반화한다(D11/INV-L4/SEC-9).

### 1.1. `Principal` 획득 (`get_principal` 의존성)
1. 컨트롤러는 `get_principal` 의존성을 통해 `request.state.principal`을 읽는다 — 이 값은 조립된 모놀리식에서 **U6 게이트웨이 미들웨어**가 세션 검증 후 주입한다.
2. `principal`이 부재하면(세션 없음) **HTTP 401**을 발생시킨다(INV-L4). 테스트/스탠드얼론 실행은 이 의존성을 오버라이드하여 고정 `Principal`을 주입한다.

### 1.2. 소유권 인가 (`AuthorizationGuard` 위임) — generalized-404
1. **컬렉션 생성/조회** (`save`, `add`, `list`, history `list`): owner는 본문이 아니라 `principal.userId`에서 서버가 결정한다(SEC-8). 따라서 리소스 owner_id == principal.userId가 구조적으로 보장된다.
2. **단건 변이/실행** (`delete {id}`, `remove {id}`, `rerun {id}`): 서비스는 먼저 소유자-스코프 조회로 대상 리소스를 적재한 뒤, `AuthorizationGuard.authorize(principal, action, AccountId(resource.owner_id))`를 호출한다.
   - `action`은 연산별로 `READ`/`WRITE`/`DELETE`/`RERUN` 중 하나(U3 `Action` enum, REUSE).
   - 판정이 `DENY`(타 소유자 OR `principal` 없음/`userId` 공백)이면 즉시 거부한다.
3. **거부 일반화(SEC-9)**: 타 소유자 접근과 "리소스 없음"은 **구분 불가능한 동일 응답 = HTTP 404 NotFound** 로 수렴한다. 존재 여부를 외부에 노출하지 않는다(INV-L4/SEC-9). `403`을 쓰지 않는다.
4. **데이터 계층 백스톱(INV-L1)**: 인가 판정과 독립적으로, 모든 리포지토리 read/write는 `owner_id`로 구조적 필터링한다. 어떤 쿼리도 타 소유자의 row를 반환할 수 없다(방어 심층화). 따라서 `delete/remove/rerun {id}`의 소유자-스코프 조회는 타 소유자 row를 애초에 적재하지 못하며, 이 경우에도 동일한 404로 일반화된다.
5. **Fail-Closed(INV-L4/SEC-15)**: 인가·`principal` 관련 어떠한 오류도 항상 DENY로 종결 → 리소스 컨텍스트는 404, 세션 부재는 401. 절대 fail-open 하지 않는다.

---

## 2. 검색 저장 오케스트레이션 (SavedSearchService)

US-L1 / FR-8. 사용자가 검색 쿼리를 재사용 가능한 형태로 저장·열람·삭제·재실행하는 하위 도메인이다.

### 2.1. 검색 저장 (`save`) — 멱등 + 정규화 + 쿼터 (BR-L1/BR-L2)
1. **입력 수신**: `SavedSearchCreateDTO` (`query`, `label?`) + `Principal`.
2. **SEC-5 입력 검증** (`UserDataDTOAndValidation.validate_and_map`):
   - `query`는 빈 값 아님·≤500자. `label`은 ≤200자(선택). 위반 시 422 + 일반화 메시지.
3. **쿼리 정규화 (BR-L1)**: `normalized_query` = Unicode **NFC** → 양끝 strip → 내부 연속 공백 1칸 축약 → **casefold**. 정규화 결과를 멱등 키로 사용한다.
4. **멱등 조회 (BR-L1, D1)**: `(owner_id, normalized_query)` 유일 키로 기존 SavedSearch를 조회한다.
   - **이미 존재**: 멱등 반환 — 기존 SavedSearch를 반환한다.
     - 새 비-null `label`이 들어온 경우에만 `label`을 갱신한다(라벨 정정 허용).
     - `created_at`은 변경하지 않는다(최초 저장 시각 보존).
     - 새 row를 생성하지 않는다(중복 방지).
   - **미존재**: 신규 생성으로 진행.
5. **쿼터 검사 (BR-L2, D2)**: 소유자별 SavedSearch가 **200건**에 도달했으면 `QuotaExceededError`를 던진다(→ HTTP 409). 멱등 경로(기존 반환)는 카운트를 늘리지 않으므로 쿼터를 소모하지 않는다.
6. **엔티티 영속화**: `SavedSearch{id=uuid4, owner_id=principal.userId, query, label, normalized_query, created_at=datetime.now(UTC)}`를 소유자-스코프로 기록한다.
7. **감사 이벤트 발행 (BR-L10/D12)**: `AuditSink`에 `saved_search.created` 이벤트를 발행한다(민감/내부 필드 비포함 — owner_id/normalized_query/scores 미포함, SEC-9).
8. **출력**: `to_dto(SavedSearch)` → `SavedSearchDTO` (`id`, `query`, `label?`, `createdAt`; owner userId 비노출, SEC-9).

### 2.2. 검색 저장 목록 조회 (`list`) — 커서 페이지네이션 (BR-L8)
1. **입력 수신**: `PageParams{limit, cursor?}` + `Principal`.
2. **페이지 파라미터 검증 (BR-L8, D8)**: `limit` 기본 **20**, **최대 100**. 100 초과는 **REJECT (422)** (명시성 우선 — 클램프 아님). `cursor`가 주어지면 디코드; 변조/가비지 커서는 422.
3. **커서 디코드**: `cursor` = URL-safe base64 of `{"ts": <sort-instant iso>, "id": <id>}`. 디코드 실패·스키마 불일치는 변조로 간주 → 422.
4. **소유자-스코프 keyset 조회 (INV-L1)**: `owner_id` 필터 하에 `created_at DESC, id DESC` 정렬로 `limit + 1`건을 keyset(`< (ts, id)`) 조회한다(최근순).
5. **다음 페이지 커서 산출**: `limit + 1`건이 조회되면 마지막 표시 항목의 `(created_at, id)`로 `nextCursor`를 인코딩한다. 마지막 페이지면 `nextCursor`를 생략한다(부재 = 종료 신호).
6. **출력**: `SavedSearchPageDTO{items: SavedSearchDTO[], nextCursor?}`.

### 2.3. 검색 저장 삭제 (`delete`) — 소유자-스코프 + generalized-404
1. **입력 수신**: `id` + `Principal`.
2. **소유자-스코프 조회**: `(owner_id=principal.userId, id)`로 적재. 없으면(미존재 또는 타 소유자) → §1.2 일반화로 **404**.
3. **인가 위임**: `AuthorizationGuard.authorize(principal, Action.DELETE, AccountId(owner_id))` → DENY면 404.
4. **삭제 실행**: 소유자-스코프 삭제. 멱등성(이미 삭제됨)도 404로 일관 처리.
5. **감사 이벤트**: `AuditSink`에 `saved_search.deleted` 발행(내부 필드 비포함).
6. **출력**: 성공(204/200 — 상태코드는 API Design). 응답 본문에 존재 단서 비노출.

### 2.4. 검색 저장 재실행 (`rerun`) — 게이트웨이 경유 (BR-L9/INV-L2) → §5
1. **입력 수신**: `id` + `Principal`.
2. **소유자-스코프 조회 + 인가**: 대상 SavedSearch를 적재(없으면 404), `AuthorizationGuard.authorize(principal, Action.RERUN, AccountId(owner_id))` → DENY면 404.
3. **저장된 쿼리 해소**: 재실행 입력은 저장된 `query`(정규화 전 원본 표시 쿼리)다.
4. **게이트웨이 재진입 (§5 참조)**: `SearchGatewayPort.search(query, principal)`를 호출한다. **직접 U2 호출 금지(INV-L2)** — 비용·근거화 훅이 재적용되도록 게이트웨이(U6→U2)를 경유한다.
5. **출력**: `SearchResultSetDTO`(§1 `SearchResultPageDTO` 카드 형상 재사용).

---

## 3. 라이브러리 오케스트레이션 (LibraryService)

US-L2 / FR-9. 사용자가 논문을 개인 라이브러리에 멱등 추가·열람·제거하는 하위 도메인이다. 핵심 불변식은 **메타 스냅샷의 가용성 격리**(D5)다.

### 3.1. 라이브러리 추가 (`add`) — 멱등 + 메타 스냅샷 검증 + 쿼터 (BR-L3/BR-L5/BR-L4)
1. **입력 수신**: `LibraryItemCreateDTO` (`arXivId`, `meta`) + `Principal`.
2. **arXiv ID 정규화/검증 (SEC-5, D3)**: `arxiv_id`는 NFC + strip(표시형, 버전 포함 가능). 패턴 검증: `^\d{4}\.\d{4,5}(v\d+)?$` OR 레거시 `^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$`. 위반 시 422.
3. **메타 스냅샷 검증 (BR-L5/D5)**: `meta`(wire `Any`)를 U4-내부 `LibraryItemMeta`로 검증한다.
   - `title`: 필수, ≤500. `authors`: list[str](각 ≤200, 최대 50개). `year`: int|None(1900..2100). `arxiv_id`: str. `abstract_snippet`: str|None(≤1000). `arxiv_url`: str|None.
   - 이 6개 카드 필드는 U2 `ResultCardVM`(dtos.md §1.1: title·authors·year·arxivId·abstractSnippet·arxivUrl)의 미러이며, **라이브 인덱스 없이 카드를 렌더**하기 위한 스냅샷이다(가용성 격리). 위반 시 422.
4. **멱등 조회 (BR-L3/D3, QT-4)**: `(owner_id, arxiv_id)` 유일 키로 기존 LibraryItem 조회.
   - **이미 존재**: 기존 LibraryItem을 **그대로** 반환(동형, 200). **저장된 메타 스냅샷을 덮어쓰지 않는다** — 최초 추가 시점의 스냅샷을 보존한다(BR-L5).
   - **미존재**: 신규 생성으로 진행.
5. **쿼터 검사 (BR-L4/D4)**: 소유자별 LibraryItem이 **1000건**에 도달했으면 `QuotaExceededError`(→ 409). 멱등 경로는 쿼터를 소모하지 않는다.
6. **엔티티 영속화**: `LibraryItem{id=uuid4, owner_id=principal.userId, arxiv_id, meta=LibraryItemMeta, added_at=datetime.now(UTC)}`를 소유자-스코프로 기록한다.
7. **감사 이벤트 (BR-L10/D12)**: `AuditSink`에 `library.added` 발행(내부 필드 비포함).
8. **출력**: `to_dto(LibraryItem)` → `LibraryItemDTO` (`id`, `arXivId`, `meta`(스냅샷), `addedAt`; owner userId 비노출).

> **가용성 격리(D5/BR-L5)**: 저장된 `meta`는 추가 시점에 캡처된 후 **U2/인덱스에서 재조회되지 않는다.** 목록/단건 응답은 항상 보존된 스냅샷을 반환한다. U2 검색이 저하/불가 상태여도 라이브러리 열람은 정상 동작한다(라이브러리의 가용성이 검색 가용성과 분리됨).

### 3.2. 라이브러리 목록 조회 (`list`) — 커서 페이지네이션
- §2.2와 동일한 keyset 알고리즘. 정렬 키는 `(added_at DESC, id DESC)`. 출력 `LibraryPageDTO{items: LibraryItemDTO[], nextCursor?}`. 반환 메타는 보존 스냅샷만(가용성 격리, D5).

### 3.3. 라이브러리 제거 (`remove`) — 소유자-스코프 + generalized-404
- §2.3과 동일 구조. `action = Action.DELETE`. 소유자-스코프 조회 실패/타 소유자 → 404. 감사 `library.removed` 발행. 멱등 제거도 404로 일관 처리.

---

## 4. 검색 이력 오케스트레이션 (SearchHistoryService)

US-L3 / FR-10. 검색 이력은 두 경로로 나뉜다 — **WRITE는 이벤트 소비(비동기·논블로킹)**, **READ/RERUN/CLEAR는 동기 CRUD**다. 공개 POST는 없다(이력 생성은 이벤트 구동).

### 4.1. 검색 이력 기록 (`recordSearch`) — 멱등 at-least-once 소비 (BR-L7/INV-L3/D7) → §6
- `SearchExecutedEvent`(🔒FROZEN) 소비 알고리즘. **동기 검색 경로 밖에서** 수행되며 검색 응답을 지연시키지 않는다(NFR-P1). 멱등 소비의 상세는 §6 참조. 요약:
  1. 이벤트(`userId`, `query`, `timestamp`, `resultCount`) 수신.
  2. `dedupe_key = sha256(owner_id | executed_at.isoformat() | query)` 산출(D7).
  3. `(owner_id, dedupe_key)` 존재 시 **무시(중복 행 생성 금지)** — at-least-once → exactly-once row(INV-L3).
  4. 미존재 시 `HistoryEntry` 기록 + 보존 한도(§4.4) 적용 + 감사.

### 4.2. 검색 이력 목록 조회 (`list`) — 커서 페이지네이션
- §2.2와 동일한 keyset 알고리즘. 정렬 키는 `(executed_at DESC, id DESC)`. 출력 `HistoryPageDTO{items: HistoryEntry[], nextCursor?}`. `HistoryEntry`는 `id`, `query`, `executedAt`, `resultCount`만 노출(owner userId·`dedupe_key` 비노출, SEC-9).

### 4.3. 검색 이력 재실행 (`rerun`) — 게이트웨이 경유 (BR-L9/INV-L2) → §5
- §2.4와 동일 구조. 대상 `HistoryEntry`를 소유자-스코프 조회(없으면 404) → `AuthorizationGuard.authorize(principal, Action.RERUN, AccountId(owner_id))`(DENY면 404) → 저장된 `query`로 `SearchGatewayPort.search(query, principal)` 호출(직접 U2 호출 금지, INV-L2) → `SearchResultSetDTO` 반환.

### 4.4. 검색 이력 정리 (`clearHistory`) — 소유자 전체 삭제 (BR-L6/D6)
1. **입력 수신**: `Principal` (대상 id 없음 — 소유자 전체 대상).
2. **인가**: owner는 `principal.userId` (자기 데이터). 소유자-스코프 전체 삭제이므로 타 소유자 영향 불가(INV-L1).
3. **삭제 실행**: `owner_id == principal.userId`인 모든 `HistoryEntry`를 삭제한다.
4. **감사 이벤트**: `AuditSink`에 `history.cleared` 발행(삭제 건수 등 비민감 메타만, 내부 필드 비포함).
5. **출력**: 성공(204/200).

### 4.5. 롤링 보존 한도 (BR-L6/D6)
- 소유자별 이력은 **최근 500건** 롤링 윈도다. `recordSearch`가 신규 행을 기록하여 한도를 초과하면 **가장 오래된 것부터 prune** 한다(`executed_at ASC` 우선 삭제). `clearHistory`는 소유자 전체를 삭제한다.

---

## 5. rerun — SearchGatewayPort 경유 흐름 (BR-L9 / INV-L2 / D9)

검색 저장 재실행(§2.4)과 검색 이력 재실행(§4.3)은 **동일한 게이트웨이 경유 알고리즘**을 공유한다. 핵심 불변식은 **rerun 백도어 금지(INV-L2)** — U4는 U2를 직접 import/호출하지 않는다.

### 5.1. 게이트웨이 재진입 알고리즘
1. **저장된 쿼리 해소**: rerun 대상(SavedSearch 또는 HistoryEntry)에서 저장된 `query`(표시 쿼리 원본)를 추출한다.
2. **포트 호출**: `SearchGatewayPort.search(query, principal) -> SearchResultSetDTO`를 호출한다.
   - `SearchGatewayPort`는 **게이트웨이-프런티드 검색 계약**(U6 `ApiGatewayMiddleware` → U2)이다. 이 경로를 강제함으로써 비용 가드·근거화(GroundingEnforcementHook) 훅이 일반 검색과 **동일하게 재적용**된다(백도어 없음).
3. **결과 표면화**: 게이트웨이가 반환한 결과를 §1 검색 카드 형상(`SearchResultPageDTO`)으로 재사용하는 `SearchResultSetDTO`로 표면화한다(dtos.md §3 rerun 주석, library.schema.json의 `SearchResultSetDTO`는 `search.schema.json#/$defs/SearchResultPageDTO`를 `$ref`).

### 5.2. 불변식 (INV-L2)
- rerun은 **반드시 `SearchGatewayPort`로 재진입**하며, 어떤 경우에도 U4가 U2 모듈을 직접 import 하거나 U2 서비스 메서드를 직접 호출해서는 안 된다. (application-design "rerun reconciliation" 미러)
- U4는 결정적 플레이스홀더 `StubSearchGateway`를 동봉한다(실 바인딩은 U6/Infra 가용 시 DI로 주입). 이 stub은 포트 시그니처를 만족하는 결정적 결과를 반환하여 라이브 인프라 없이 마운트/테스트가 그린이 되도록 한다(mock-first, discovery 패턴 답습).
- **실제 바인딩 검증(Real Binding Verification)**: U6/Infra에서 `StubSearchGateway`를 실제 게이트웨이 어댑터(`RealSearchGatewayAdapter`)로 교체하여 주입하는 시점에, 반드시 **통합 계약 테스트(Contract Test)**가 실행되어야 한다. 이 테스트는 `SearchGatewayPort`를 통한 rerun 요청이 최소 1회 이상 `CostGuardCircuitBreaker.getBudgetState()`를 호출하고, 응답 경로가 `GroundingEnforcementHook.enforce()`를 통과하는지(U6 게이트웨이 파이프라인의 횡단 관심사 정상 적용)를 검증해야 한다. `StubSearchGateway`는 프로덕션 환경(ENV=PROD) 구성에서 절대 사용될 수 없다.

---

## 6. 검색 이력 멱등 at-least-once 소비 (D7 / INV-L3 / BR-L7)

`SearchHistoryService.recordSearch`는 `SearchExecutedEvent`(🔒FROZEN, `shared/events/search-executed.schema.json`)를 구독한다. 이 이벤트는 **성공한 검색 응답 이후** U2 `SearchOrchestrationService.publishSearchExecuted(userId, query, timestamp, resultCount)`가 발행하며, **동기 검색 경로(NFR-P1 P50<3s) 밖에서** 발행/소비된다 — 검색 응답을 블로킹하지 않는다.

### 6.1. 멱등 기록 알고리즘
1. **이벤트 수신**: `SearchExecutedEvent{userId, requestId, query, timestamp, resultCount}`. `userId`를 `owner_id`로, `timestamp`를 `executed_at`(aware UTC)로 매핑한다.
2. **dedupe_key 산출 (D7)**: `dedupe_key = sha256(owner_id | requestId | query)`. 동일 시간대(초 단위 해상도)에 사용자가 의도적으로 동일 쿼리를 반복 실행하는 경우, `timestamp` 기반 식별 시 해시 충돌로 이력이 누락되는 한계가 있다. 이를 해결하기 위해 요청 당시 주입된 고유 `requestId`를 해시 키로 활용하여 재시도에 의한 이벤트 중복 전달만 정확히 차단한다.
3. **멱등 검사 (INV-L3)**: `(owner_id, dedupe_key)`가 이미 존재하면 **아무것도 하지 않고 종료**한다(중복 행 생성 금지). at-least-once 재전달이 exactly-once row로 수렴한다.
4. **신규 기록**: 미존재 시 `HistoryEntry{id=uuid4, owner_id, query, executed_at, result_count, dedupe_key}`를 소유자-스코프로 기록한다.
5. **보존 한도 적용 (§4.5/D6)**: 기록 후 소유자별 건수가 500을 초과하면 가장 오래된 것부터 prune.
6. **감사 이벤트 (선택, D12)**: `history.recorded`(비민감 메타만).

### 6.2. 비동기·논블로킹 보장 (NFR-P1)
- 소비는 동기 검색 요청-응답 경로와 **분리된** 실행 컨텍스트에서 수행된다. 이력 기록의 지연·일시 실패가 검색 사용자 경험(P50<3s)에 영향을 주지 않는다.
- 일시 실패 시 at-least-once 전달이 재시도를 보장하고, 멱등 키(§6.1.2)가 재시도로 인한 중복을 흡수한다(INV-L3).

### 6.3. 비노출 (SEC-9)
- `HistoryEntry`의 외부 노출 필드는 `id`·`query`·`executedAt`·`resultCount`만이다. `owner_id`·`dedupe_key`는 내부 필드로 **직렬화하지 않는다.** 이벤트 자체도 내부 점수/디버그 필드를 싣지 않는다(events 스키마 `additionalProperties:false`).

---

## 7. DTO 매핑·정규화·커서·검증 (UserDataDTOAndValidation)

### 7.1. 공유 SSOT 재사용 (DTO 포크 금지)
- wire DTO는 `docsuri_shared.dtos`에서 import: `PageParams, SavedSearchCreateDTO, SavedSearchDTO, SavedSearchPageDTO, LibraryItemCreateDTO, LibraryItemDTO, LibraryPageDTO, HistoryEntry, HistoryPageDTO, SearchResultSetDTO`. 이벤트는 `docsuri_shared.events`의 `SearchExecutedEvent`.
- U4는 이 DTO들을 **재정의하지 않는다**(SSOT 포크 = U3가 범한 결함의 회피 대상). `LibraryItemMeta`는 wire DTO의 재정의가 아니라 `meta: Any`를 검증하는 **U4-내부 pydantic 검증기**다.
- U4는 §3 정제(최대 limit=100, 타입드 meta, 문자열 id, 커서 의미)를 **자체 검증 계층**에서 강제한다 — 재생성 바인딩 설치 여부와 무관하게 U4가 정합하도록 한다(shared 바인딩은 `id`/`meta`=Any, `limit` ge=1 max 없음).

### 7.2. `to_dto` / `validate_and_map`
- `validate_and_map(create_dto, principal) -> 도메인 엔티티`: SEC-5 검증 + 정규화(쿼리 NFC/casefold, arXiv 패턴, meta 바운드) 후 owner_id를 `principal.userId`로 바인딩하여 도메인 엔티티를 생성한다(owner는 본문 미수용, SEC-8).
- `to_dto(entity) -> wire DTO`: 내부 필드(`owner_id`·`normalized_query`·`dedupe_key`·감사 메타)를 제외하고 공개 필드만 직렬화한다(SEC-9).

### 7.3. 커서 코덱 (BR-L8/D8)
- 인코딩: `nextCursor = urlsafe_b64({"ts": <sort-instant iso>, "id": <id>})`. 디코딩: base64 디코드 + JSON 파싱 + 스키마 검증. 첫 페이지는 cursor 생략, 마지막 페이지는 nextCursor 생략. 변조/가비지/스키마 불일치는 422.

### 7.4. PBT-09 (DTO 라운드트립) — U4 블로킹 PBT
- **속성**: 임의의 유효 도메인 엔티티에 대해 `to_dto(entity)`가 공유 DTO 검증에 안정적으로 통과하고, 유효 create DTO의 `validate_and_map`이 공개 필드를 라운드트립으로 보존한다. serialize→deserialize는 공개 필드를 보존하며 **내부 필드를 절대 누출하지 않는다.** Hypothesis 사용. (Partial 프로파일에서 advisory이나 U4 component-methods가 pin → 구현.)
- **커서 속성(advisory)**: 임의 리스트에 대해 limit L로 페이지네이션하면 모든 항목을 최근순으로 **중복/누락 없이 정확히 한 번씩** 수집한다(keyset 안정성).

---

## 8. 도메인 엔티티 및 값 객체 (내부 — wire DTO 아님)

| 엔티티/값 객체 | 속성 | 비고 | Trace |
|---|---|---|---|
| **SavedSearch** | `id: str(uuid4)`, `owner_id: str`, `query: str`, `label: str\|None`, `normalized_query: str`, `created_at: datetime(aware,UTC)` | `(owner_id, normalized_query)` 유일(BR-L1). `normalized_query`·`owner_id` 비노출(SEC-9) | FR-8, US-L1 |
| **LibraryItem** | `id: str(uuid4)`, `owner_id: str`, `arxiv_id: str`, `meta: LibraryItemMeta`, `added_at: datetime` | `(owner_id, arxiv_id)` 멱등(BR-L3). meta 스냅샷 가용성 격리(D5/BR-L5) | FR-9, US-L2 |
| **HistoryEntry** | `id: str(uuid4)`, `owner_id: str`, `query: str`, `executed_at: datetime`, `result_count: int`, `dedupe_key: str` | `dedupe_key`=sha256(owner_id\|executed_at_iso\|query)(D7). `dedupe_key`·`owner_id` 비노출(SEC-9) | FR-10, US-L3 |
| **LibraryItemMeta**(값 객체, 스냅샷) | `title: str(≤500, 필수)`, `authors: list[str](≤50개, 각 ≤200)`, `year: int\|None(1900..2100)`, `arxiv_id: str`, `abstract_snippet: str\|None(≤1000)`, `arxiv_url: str\|None` | U2 `ResultCardVM` 카드 필드 미러(dtos.md §1.1). `meta: Any` 정제(D5) | FR-9, US-L2, FR-4 |
| **Principal / Action / AccountId / Decision** | (U3 정의 REUSE) | `backend.modules.accounts.models`+`.guard`. SEC-8 단일 권위점, **재정의 금지** | SEC-8 |

### 8.1. 도메인 예외 (DomainException 하위)
| 예외 | 발생 조건 | HTTP 매핑(API Design) | Trace |
|---|---|---|---|
| `QuotaExceededError` | SavedSearch>200(D2) / LibraryItem>1000(D4) | 409 | BR-L2, BR-L4 |
| `ValidationError`(SEC-5) | query>500/label>200/arXiv 패턴/meta 바운드/limit>100/커서 변조 | 422 | SEC-5, BR-L8 |
| `NotFoundError`(일반화) | 미존재 OR 타 소유자(인가 DENY) | 404 | D11, SEC-9, INV-L4 |
| (세션 부재) | `principal` 없음 | 401 | D11, INV-L4 |
| (미상 예외) | 알 수 없는 내부 오류 | 500(fail-closed) | SEC-15 |

> **컨트롤러 매핑 규약(accounts 답습)**: `DomainException → 4xx`, 타 소유자/미존재 → **404로 일반화**(403 아님), 미상 예외 → 500 fail-closed. 본문에 스택/내부 식별자/존재 단서 비노출(SEC-9/SEC-15).

---

## 9. 영속 포트 및 마운트 (D10 / INV-L1)

- **포트 기반(D10)**: `UserDataRepository`(3 서브-리포 집합)·`SearchGatewayPort`·`AuditSink`는 모두 `typing.Protocol` 포트다.
- **기본 구현**: `InMemoryUserDataRepository` — app-shell이 라이브 인프라 없이 마운트하고 테스트가 그린이 되도록(mock-first, discovery 답습).
- **프로덕션 구현**: `SqlUserDataRepository`(SQLAlchemy scaffold) + `migrations/001_create_library_tables.sql` DDL. U3의 RDS PostgreSQL 상속(NFR/Infra).
- **소유자-스코핑 백스톱(INV-L1, SEC-8 데이터 계층, NFR-R1)**: 모든 쿼리는 구조적으로 `owner_id` 필터링. 어떤 쿼리도 타 소유자 row를 반환할 수 없다. 인가 판정(AuthorizationGuard)과 독립된 방어 심층화 계층이다.
- **app-shell 배선(backend/wiring.py)**: `_mount_library`가 기본 `InMemoryUserDataRepository` 싱글톤 + `StubSearchGateway` + `InMemoryAuditSink`를 빌드하여 컨트롤러 DI를 오버라이드하고 3개 라우터를 `include_router` 한다. 라이브 DB 불요(PostgreSQL 없이 마운트). `result.mounted`에 `"library"` append.

---

## 10. 추적성 매트릭스 (Traceability Matrix)

| 설계 요소 (서비스/규칙/불변식) | 결정 ID | 추적 요구사항 | 인수 스토리 | 설계 목적 및 불변식 |
|---|---|---|---|---|
| **SavedSearchService.save** | D1, D2 | FR-8, SEC-5 | US-L1 | 정규화 멱등 저장(BR-L1) + 200건 쿼터(BR-L2) |
| **SavedSearchService.list/delete** | D8, D11 | FR-8, SEC-8, SEC-9 | US-L1 | keyset 페이지네이션(BR-L8) + 소유자-스코프 + generalized-404 |
| **SavedSearchService.rerun** | D9 | FR-8, INV-L2 | US-L1 | SearchGatewayPort 경유 재실행(BR-L9), 직접 U2 호출 금지(INV-L2) |
| **LibraryService.add** | D3, D4, D5 | FR-9, SEC-5 | US-L2 | (owner,arxiv) 멱등(BR-L3) + 1000건 쿼터(BR-L4) + 메타 스냅샷 검증(BR-L5) |
| **LibraryService.list/remove** | D8, D11 | FR-9, SEC-8, SEC-9 | US-L2 | keyset 페이지네이션 + 소유자-스코프 + generalized-404. 보존 스냅샷만 반환(D5 가용성 격리) |
| **SearchHistoryService.recordSearch** | D6, D7 | FR-10, NFR-P1 | US-L3 | 멱등 at-least-once 소비(BR-L7/INV-L3) + 롤링 500 보존(BR-L6), 비동기·논블로킹(NFR-P1) |
| **SearchHistoryService.list/rerun/clear** | D6, D8, D9, D11 | FR-10, INV-L2 | US-L3 | keyset 조회 + 게이트웨이 경유 rerun(BR-L9) + 소유자 전체 정리(BR-L6) |
| **UserDataRepository** | D10 | SEC-8, NFR-R1 | US-L1..L3 | 소유자-스코핑 데이터 백스톱(INV-L1), 포트 기반(In-Memory/SQL) |
| **UserDataDTOAndValidation** | D8 | SEC-5, PBT-09 | US-L1..L3 | DTO 매핑/정규화/커서 코덱/SEC-5 검증 + PBT-09 라운드트립(내부 필드 비누출) |
| **SearchGatewayPort / StubSearchGateway** | D9 | FR-8, FR-10, INV-L2 | US-L1, US-L3 | 게이트웨이-프런티드 rerun 재진입, 비용·근거화 훅 재적용, 백도어 금지 |
| **AuditSink / InMemoryAuditSink** | D12 | SEC-13, SEC-9 | US-L1..L3 | 변이 연산 감사(BR-L10), 민감/내부 필드 비포함 |
| **AuthorizationGuard (U3 REUSE)** | D11 | SEC-8, SEC-9, SEC-15 | US-L1..L3 | 소유권 인가 단일 권위점 위임 + generalized-404(INV-L4 fail-closed) |
| **LibraryItemMeta** | D5 | FR-9, FR-4, SEC-5 | US-L2 | U2 카드 필드 미러 스냅샷, 가용성 격리(BR-L5) |
| **PBT-09 (DTO 라운드트립)** | — | PBT-09, SEC-9 | US-L1..L3 | serialize→deserialize 공개 필드 보존·내부 필드 비누출 보장(Hypothesis) |
