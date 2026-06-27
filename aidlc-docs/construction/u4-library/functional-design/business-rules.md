# business-rules.md — U4 Library 비즈니스 규칙 및 검증 설계

**단계**: CONSTRUCTION → Functional Design (유닛별 루프, Track 2 두 번째·최종 유닛) · **유닛**: U4 Library · **일자**: 2026-06-17
**근거(SSOT)**: `tmp/u4-design-brief.md` (D1~D12 결정 + BR-L1..L10 + INV-L1..L4 + PBT-09)
**소유**: Track 2 (@revenantonthemission) · Track 2 흐름 = U3 Accounts → **U4 Library**
**대상 서브도메인**: Saved Searches (US-L1/FR-8) · Library (US-L2/FR-9) · Search History (US-L3/FR-10)

> U4는 **소유자 비공개(owner-private) CRUD + 이력 이벤트 소비** 유닛이다. 인가의 단일 권위점은 U3
> `AuthorizationGuard`이며(SEC-8), U4는 이를 재정의하지 않고 위임한다. 와이어 DTO는 `docsuri_shared`
> SSOT를 재사용하며(포크 금지 — U3가 범한 결함을 회피), U4는 §3 정제(최대 limit 100, 타입 meta,
> 문자열 id, 커서 시맨틱)를 **자체 검증 계층**(`UserDataDTOAndValidation`)에서 강제한다.

---

## 1. 비즈니스 결정 규칙 (Business Rules)

규칙 ID는 브리프 §4의 D1..D12 결정과 1:1로 매핑된다(BR-L1=D1 … BR-L10=D12).

### BR-L1: 저장 검색 정규화 및 멱등 중복 제거 (D1 반영)
- **유일성 키**: 저장 검색은 `(owner_id, normalized_query)` 단위로 유일하다.
- **정규화 파이프라인** (`normalized_query` 산출): Unicode **NFC** 정규화 → 양끝 공백 제거(strip) → 내부 연속 공백 단일 공백으로 축약(collapse) → **casefold**.
- **멱등 재저장**: 이미 존재하는 정규화 질의를 다시 저장하면 새 행을 만들지 않고 **기존 SavedSearch를 반환**한다.
  - 새 비-null `label`이 함께 제공되면 해당 `label`만 갱신한다.
  - `created_at`은 절대 변경되지 않는다(최초 저장 시각 보존).
- **노출 규칙**: `normalized_query`는 내부 필드로, 와이어 DTO(`SavedSearchDTO`)에 직렬화되지 않는다(SEC-9). 사용자에게는 원본 `query`만 노출된다.

### BR-L2: 저장 검색 쿼터 정책 (D2 반영)
- 소유자 1인당 저장 검색의 최대 보유 개수는 **200개**이다.
- 쿼터를 초과하는 신규 저장 시도(= 신규 행 생성에 한함; 멱등 재저장은 카운트하지 않음)는 `QuotaExceededError`를 발생시키며 컨트롤러에서 **HTTP 409**로 매핑된다.
- 쿼터 카운트는 owner-scoped 저장소 카운트에 기반한다(INV-L1).

### BR-L3: 라이브러리 추가 멱등성 (D3 반영, QT-4)
- 라이브러리 추가는 `(owner_id, arxiv_id)` 단위로 멱등이다(`arxiv_id`는 NFC + strip; 버전을 포함한 표시형 보존).
- **재추가 동작**: 이미 존재하는 항목을 다시 추가하면 **기존 LibraryItem을 동일 shape으로 반환**하며 응답 코드는 신규/기존 구분 없이 **200**이다.
- **메타 스냅샷 불변**: 재추가는 저장된 `meta` 스냅샷을 **덮어쓰지 않는다**(최초 추가 시점 스냅샷 보존 — 가용성 격리, BR-L5 참조).

### BR-L4: 라이브러리 쿼터 정책 (D4 반영)
- 소유자 1인당 라이브러리 항목의 최대 보유 개수는 **1000개**이다.
- 쿼터를 초과하는 신규 추가(멱등 재추가 제외)는 `QuotaExceededError`를 발생시키며 컨트롤러에서 **HTTP 409**로 매핑된다.

### BR-L5: 라이브러리 메타 스냅샷 형상 및 가용성 격리 (D5 반영)
- 라이브러리 항목의 `meta`는 값 객체 **`LibraryItemMeta`**로 정의된다:
  - `title: str` — 필수, ≤ 500자
  - `authors: list[str]` — 각 항목 ≤ 200자, 리스트 길이 ≤ 50
  - `year: int | None` — 1900 ~ 2100
  - `arxiv_id: str`
  - `abstract_snippet: str | None` — ≤ 1000자
  - `arxiv_url: str | None`
  - `retracted: bool` — 철회 논문 플래그 (기본 `false`)
- 추가 시점에 **SEC-5 검증**을 거쳐 그대로 저장되고, 조회 시 **저장된 값을 verbatim 반환**한다.
- **가용성 격리(availability isolation)**: 라이브러리 렌더링은 라이브 인덱스(U2)나 게이트웨이를 재조회하지 않는다. 이 스냅샷은 U2 `ResultCardVM` 카드 필드(dtos.md §1.1: title·authors·year·arxivId·abstractSnippet·arxivUrl)를 미러링하므로, 라이브 인덱스 없이도 카드를 완전히 렌더링할 수 있다.
- **논문 철회 상태 전파(PaperRetractedEvent 소비)**: U1 인제스천 측에서 원문 철회가 감지되어 `PaperRetractedEvent`가 발행되면, `LibraryService`가 이를 비동기적으로 구독하여 보유한 항목 중 해당 논문의 `retracted` 속성을 `true`로 갱신한다. 사용자의 라이브러리 데이터는 강제 삭제하지 않고 보존하되 신뢰할 수 없는 항목임을 UI에 명시적으로 알리도록 한다.

### BR-L6: 검색 이력 롤링 보존 정책 (D6 반영)
- 검색 이력은 소유자별 **최근 500건** 롤링 보존이다.
- 보존 한도를 초과하는 기록(record) 시점에 가장 오래된 항목부터 **프루닝(prune)**한다.
- `clearHistory`는 해당 소유자의 이력 전체를 삭제한다.

### BR-L7: 검색 이력 기록 멱등성 (D7 반영, INV-L3)
- 이력 기록은 `SearchExecutedEvent`(🔒FROZEN) **at-least-once** 전달을 전제로 한다.
- **디덥 키**: `dedupe_key = sha256(owner_id | requestId | query)`.
- 기존 `timestamp` 기반 디덥 키는 의도적인 빠른 반복 쿼리에서 해시 충돌(데이터 누락)이 발생할 위험이 있으므로, 요청 생성 시의 고유 `requestId`를 사용하여 시스템 재시도로 인한 중복 전달만 멱등하게 차단한다.
- 동일 이벤트의 **재전달은 중복 행을 생성하지 않는다**(exactly-once 행, INV-L3).
- 이력 WRITE는 이벤트 구동(consumer)이며 공개 POST 엔드포인트로 노출되지 않는다.
- `dedupe_key`는 내부 필드로 와이어 DTO에 직렬화되지 않는다(SEC-9).

### BR-L8: 커서 기반 키셋 페이지네이션 (D8 반영)
- 모든 컬렉션 조회는 **커서 기반 키셋(keyset)** 페이지네이션이며, 정렬은 **최신순(most-recent-first)**이다.
- `limit`: 기본값 **20**, 최대 **100**.
  - `limit > 100`은 명시성을 위해 **REJECT**(클램프 아님)하여 **HTTP 422**로 거절한다.
  - `limit < 1`도 422(SSOT `ge=1` + U4 상한 강제).
- `cursor`: `{"ts": <정렬 기준 instant ISO>, "id": <id>}`의 **URL-safe base64** 불투명 토큰.
  - 첫 페이지 요청은 `cursor`를 생략한다.
  - 마지막 페이지의 응답에는 `nextCursor`가 **부재(absent)**한다.
  - 변조/손상(garbage) 커서는 **HTTP 422**로 거절한다(디코드/검증 실패 → 일반화 메시지).
- 키셋 안정성(중복·누락 없는 전수 순회)은 advisory 커서 PBT 속성으로 검증한다(§3 참조).

### BR-L9: 재실행은 게이트웨이 경유 (D9 반영, INV-L2)
- 저장 검색/이력 항목의 재실행(rerun)은 **U2 직접 호출이 아니다**.
- 재실행은 **`SearchGatewayPort`** (`search(query, principal) -> SearchResultSetDTO`)를 통해 게이트웨이-프론트된 검색 계약(U6 `ApiGatewayMiddleware` → U2)으로 재진입하여, **비용·근거화 훅이 재적용**되도록 한다(백도어 금지).
- `rerunSavedSearch` / `rerunHistoryEntry`는 저장된 질의를 해석(resolve)한 뒤 포트를 호출한다.
- U4는 `StubSearchGateway`(결정론적 placeholder)를 기본 탑재하며, 실제 바인딩은 U6/Infra에서 주입된다. **주의: 프로덕션 환경 구성에서는 `StubSearchGateway` 사용이 엄격히 금지된다.**
- **게이트웨이 컨트랙트 테스트 강제**: 실제 게이트웨이 바인딩이 U6의 비용(`CostGuardCircuitBreaker.getBudgetState()`) 및 근거화(`GroundingEnforcementHook.enforce()`) 훅을 정상적으로 통과하는지 검증하는 CI 차원의 블로킹 통합 테스트(`ContractTestHarness`)를 반드시 통과해야만 배포를 허용한다.

### BR-L10: 핵심 데이터 변경 감사 (D12 반영, SEC-13)
- 변이 연산(저장/삭제, 추가/제거, clear)에서 서비스는 **`AuditSink`** 포트를 통해 감사 이벤트를 발행한다.
- 기본 구현은 in-memory / no-op이며, 실제 와이어링은 U6/ops에서 주입된다.
- 감사 페이로드에는 민감/내부 필드(`owner_id`, `dedupe_key`, `normalized_query`, scores, 내부 audit meta)를 포함하지 않는다(SEC-9).

---

## 2. 보안 및 개인정보 보호 불변식 (SEC Rules · Invariants)

### SEC-BR-1: 자원 존재 비노출 — 교차 소유자 404 일반화 (SEC-9)
- 와이어 DTO는 소유자 `userId`를 절대 외부로 노출하지 않는다(SavedSearchDTO·LibraryItemDTO·HistoryEntry 모두 owner 미포함).
- 내부 필드(`owner_id`, `dedupe_key`, `normalized_query`, scores, audit meta)는 어떤 응답에도 직렬화되지 않는다.
- 타 소유자 자원에 대한 접근(또는 존재하지 않는 자원 접근)은 **403이 아닌 HTTP 404**로 일반화하여 자원의 존재 여부 자체를 알리지 않는다.

### SEC-BR-2: 입력 검증 및 일반화된 거절 (SEC-5)
- 모든 외부 입력은 컨트롤러 진입 직후 `UserDataDTOAndValidation`에서 검증된다.
- **검증 규칙**:
  - `query` ≤ 500자
  - `label` ≤ 200자
  - `arxiv_id`: 정규형 `^\d{4}\.\d{4,5}(v\d+)?$` **또는** 레거시 `^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$`
  - page `limit`: 1 ~ 100 (BR-L8)
  - `meta`: §1 BR-L5 경계(`LibraryItemMeta`)
- 검증 실패는 **HTTP 422 + 일반화된 메시지**로 거절한다(구체적 위반 위치를 과도하게 노출하지 않음).

### SEC-BR-3: 예외 발생 시 안전 거부 — Fail-Closed (SEC-15)
- 인가/주체(principal) 해석 중 발생하는 모든 오류는 **DENY로 종결**된다(절대 fail-open 금지).
  - 자원 관련 인가 실패 → **404**(SEC-9 일반화)
  - 세션/주체 부재(미인증) → **401**
- 미지의 예외는 전역 핸들러에서 **500 fail-closed**로 종결되며 내부 상태를 노출하지 않는다.
- 컨트롤러는 주체를 `get_principal` 의존성(= `request.state.principal`, U6 게이트웨이 미들웨어가 설정)으로 획득하며, 부재 시 401을 발생시킨다. 테스트/스탠드얼론은 의존성을 오버라이드한다.

### 불변식 요약 (Invariants INV-L1..INV-L4)

| ID | 불변식 | 강제 지점 | 관련 SEC |
|---|---|---|---|
| **INV-L1** | **소유자 범위 백스톱**: 모든 저장소 read/write가 구조적으로 `owner_id`로 필터링된다. 어떤 질의도 타 소유자의 행을 반환할 수 없다(Guard 결정 하위의 방어심층). | `UserDataRepository` 및 3개 서브-리포 | SEC-8, NFR-R1 |
| **INV-L2** | **재실행 백도어 부재**: 재실행은 `SearchGatewayPort`(게이트웨이-프론트)로만 재진입하며, U2를 직접 import/호출하지 않는다. | `rerun*` 서비스 메서드 | SEC-8 |
| **INV-L3** | **이력 멱등성**: at-least-once 전달 → `dedupe_key`당 exactly-once 행. | `SearchHistoryService.recordSearch` / consumer | SEC-13 |
| **INV-L4** | **Fail-closed 인가**: 모든 인가/주체 오류 → DENY → 404(자원) / 401(세션 부재). 절대 fail-open 금지. | 컨트롤러 + `AuthorizationGuard` 위임 | SEC-15 |

---

## 3. PBT 속성 정의 (Property-Based Testing Properties)

> Partial 프로파일에서 PBT-09는 **차단성(blocking)**이며, U4 component-methods가 이를 핀(pin)한다 — 반드시 구현한다.
> 커서 속성은 advisory(권고)이나 키셋 안정성 보장을 위해 함께 구현한다. 프레임워크는 **Hypothesis**(Python).

### PBT-09: DTO 라운드트립 무결성 (차단성)
- **속성 1 (엔티티 → DTO 안정성)**: 임의의 유효 도메인 엔티티 `e`에 대해 `to_dto(e)`를 산출하고 이를 공유 DTO(`docsuri_shared`)로 검증하면 항상 안정적으로 성공한다. `to_dto`는 결정론적이다(동일 입력 → 동일 출력).
- **속성 2 (생성 DTO 라운드트립)**: 임의의 유효 생성 DTO(`SavedSearchCreateDTO` / `LibraryItemCreateDTO`)에 대해 `validate_and_map`을 적용한 뒤 다시 `to_dto`로 직렬화하면 **공개 필드가 보존**된다(serialize → deserialize 가역).
- **속성 3 (내부 필드 비누출)**: 위 두 경로의 어떤 출력에서도 내부 필드(`owner_id`, `dedupe_key`, `normalized_query`, scores, audit meta)가 **절대 누출되지 않는다**(SEC-9).
- **제너레이터**: 도메인 제너레이터(query/label/arxiv_id/meta 경계 포함), shrinking, 시드 재현성 적용.

### PBT-Cursor: 키셋 페이지네이션 전수 순회 (advisory)
- **속성**: 임의의 항목 리스트에 대해 `limit = L`로 페이지네이션을 반복하면, 모든 항목을 **정확히 한 번씩** **최신순**으로 수집하며 **중복·누락이 없다**(keyset 안정성).
- **부속 속성**: 마지막 페이지에는 `nextCursor`가 부재하고, 변조/손상 커서는 422로 거절된다(BR-L8).

---

## 4. 추적성 매트릭스 (Traceability Matrix)

| 설계 요소 (컴포넌트/규칙) | 추적 대상 요구사항 ID | 인수 기준 스토리 ID | 설계 목적 및 불변식 |
|---|---|---|---|
| **SavedSearchController** | FR-8, SEC-5, SEC-9, SEC-15 | US-L1 | 저장 검색 CRUD + rerun API 노출, 입력 검증(SEC-5), 교차 소유자 404 일반화(SEC-9), 예외 Fail-Closed(SEC-15) |
| **LibraryController** | FR-9, SEC-5, SEC-9, SEC-15 | US-L2 | 라이브러리 멱등 add/list/delete API 노출, 메타 스냅샷 검증, 404 일반화·Fail-Closed |
| **SearchHistoryController** | FR-10, SEC-9, SEC-15 | US-L3 | 이력 list/rerun/clear API 노출(WRITE는 이벤트 구동), 404 일반화·Fail-Closed |
| **SavedSearchService** | FR-8, SEC-8, SEC-13 | US-L1 | 정규화·멱등 중복제거(BR-L1)·쿼터(BR-L2)·게이트웨이 재실행(BR-L9), 변경 감사(BR-L10) |
| **LibraryService** | FR-9, SEC-8, SEC-13 | US-L2 | 멱등 추가(BR-L3)·쿼터(BR-L4)·메타 스냅샷 verbatim(BR-L5), add/remove 감사(BR-L10) |
| **SearchHistoryService** | FR-10, SEC-8, SEC-13 | US-L3 | 롤링 500 보존(BR-L6)·디덥 멱등 기록(BR-L7)·게이트웨이 재실행(BR-L9), clear 감사(BR-L10) |
| **UserDataRepository** (+ 3 서브-리포) | FR-8, FR-9, FR-10, SEC-8 | US-L1, US-L2, US-L3 | owner-scoped read/write 데이터 백스톱(INV-L1), 모든 질의 `owner_id` 구조적 필터링 |
| **UserDataDTOAndValidation** | SEC-5, SEC-9, PBT-09, QT-4 | US-L1, US-L2, US-L3 | DTO 매핑·SEC-5 검증·정규화·커서 코덱·PBT-09 라운드트립·내부 필드 비누출 |
| **SearchGatewayPort** (StubSearchGateway) | FR-8, FR-10, SEC-8 | US-L1, US-L3 | 게이트웨이-프론트 재실행 단일 경로(INV-L2), 비용·근거화 훅 재적용(백도어 부재) |
| **AuditSink** (InMemoryAuditSink) | SEC-13, SEC-9 | US-L1, US-L2, US-L3 | 핵심 데이터 변경 감사 발행(BR-L10), 민감/내부 필드 비포함 |
| **history_consumer** (SearchExecutedEvent) | FR-10, SEC-13 | US-L3 | 🔒FROZEN 이벤트 at-least-once 소비 → 디덥 멱등 기록(INV-L3) |
| **AuthorizationGuard** (U3 재사용) | SEC-8, SEC-9, SEC-15 | US-L1, US-L2, US-L3 | Stateless 소유권 인가 단일 권위점 위임, DENY → 404 일반화(INV-L4) |
| **BR-L1 / BR-L3 (멱등성)** | FR-8, FR-9, QT-4 | US-L1, US-L2 | 정규화 중복제거·`(owner,arxiv_id)` 멱등 — 디덥 멱등성 불변식(QT-4) |
| **BR-L2 / BR-L4 (쿼터)** | FR-8, FR-9 | US-L1, US-L2 | 200 / 1000 상한 → `QuotaExceededError` → 409 |
| **BR-L5 (메타 스냅샷)** | FR-9, SEC-5 | US-L2 | `LibraryItemMeta` verbatim 보존 — 가용성 격리(라이브 인덱스 비의존) |
| **BR-L6 (이력 보존)** | FR-10 | US-L3 | 최근 500건 롤링 프루닝 + clear |
| **BR-L7 (이력 멱등)** | FR-10, SEC-13 | US-L3 | `dedupe_key` 기반 exactly-once 행(INV-L3) |
| **BR-L8 (페이지네이션)** | FR-8, FR-9, FR-10, SEC-5 | US-L1, US-L2, US-L3 | 키셋 최신순 커서, limit 1..100 REJECT, 변조 커서 422 |
| **BR-L9 (게이트웨이 재실행)** | FR-8, FR-10, SEC-8 | US-L1, US-L3 | 게이트웨이 경유 재진입 — 백도어 부재 불변식(INV-L2) |
| **BR-L10 (감사)** | SEC-13, SEC-9 | US-L1, US-L2, US-L3 | 변이 연산 감사, 민감정보 비노출 |
| **PBT-09 (DTO 라운드트립)** | QT-4, SEC-9 | US-L1, US-L2, US-L3 | serialize↔deserialize 공개 필드 보존 + 내부 필드 비누출(차단성 PBT) |
| **PBT-Cursor (키셋 순회)** | QT-4 | US-L1, US-L2, US-L3 | limit L 페이지네이션 전수·무중복·무누락 순회(advisory) |

---

### 부록 A. HTTP 상태 코드 매핑 (컨트롤러 일반화 규칙)

| 상황 | 도메인 신호 | HTTP | 근거 |
|---|---|---|---|
| 입력 검증 실패 (필드 경계·커서 변조·limit 범위) | `ValidationError` | **422** | SEC-5, BR-L8 |
| 쿼터 초과 (저장 검색 200 / 라이브러리 1000) | `QuotaExceededError` | **409** | BR-L2, BR-L4 |
| 교차 소유자 / 미존재 자원 접근 | Guard `DENY` (일반화) | **404** | SEC-9, INV-L4 |
| 세션/주체 부재 (미인증) | principal 부재 | **401** | INV-L4, SEC-15 |
| 멱등 재저장 / 재추가 (정상) | 기존 엔티티 반환 | **200** | BR-L1, BR-L3 |
| 미지 예외 | unknown | **500 (fail-closed)** | SEC-15 |
