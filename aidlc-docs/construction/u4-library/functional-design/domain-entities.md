# domain-entities.md — U4 Library 도메인 엔티티 및 값 객체 정의

**단계**: CONSTRUCTION → Functional Design (유닛별 루프, Track 2 두 번째·최종 유닛) · **유닛**: U4 Library · **일자**: 2026-06-17
**근거(SSOT)**: U4 Library 설계 브리프(orchestrator authored; unit-of-work.md, application-design components/methods/services, stories.md US-L1/L2/L3, `shared/dtos/library.schema.json`, `shared/events/search-executed.schema.json`, dtos.md §3·§1.1, U3 accounts 템플릿 반영)
**범위**: U4의 세 소유자-전용 하위 도메인(Saved Searches·Library·Search History)의 **내부** 도메인 엔티티·값 객체와, 공용 SSOT 와이어 DTO(`docsuri_shared.dtos`)에의 바인딩을 정의한다. 와이어 DTO는 §5에서 **재사용**하며 절대 포크하지 않는다(U3에서 발생한 SSOT 포크 결함을 피한다).

---

## 0. 위치 및 원칙 (Positioning & Principles)

- **내부 엔티티 ≠ 와이어 DTO**: 본 문서가 정의하는 `SavedSearch`·`LibraryItem`·`HistoryEntry`·`LibraryItemMeta`는 U4의 **도메인 내부 모델**(`backend/modules/library/models.py`)이다. 외부로 직렬화되는 형상은 공용 SSOT의 와이어 DTO(`docsuri_shared.dtos`)이며, 둘 사이의 변환은 `UserDataDTOAndValidation`(validation.py)이 담당한다. (브리프 §2, §5)
- **내부 식별자/경로는 영어, 산문은 한국어**: U3 문서 스타일을 그대로 따른다.
- **SEC-9 비공개 경계**: 내부 필드(`owner_id`·`normalized_query`·`dedupe_key`·점수·감사 메타)는 **절대** 외부 DTO로 직렬화되지 않는다. 본 문서는 모든 엔티티에서 내부 필드와 외부 노출 필드를 명시적으로 구분한다(§4, §6).
- **소유자 스코핑 백스톱(INV-L1)**: 모든 엔티티는 `owner_id`를 보유하며 저장소 계층에서 구조적으로 소유자 필터링된다. `owner_id`는 AuthorizationGuard 판정(SEC-8) 아래의 심층 방어이며 외부 비노출이다.
- **가용성 격리(availability isolation)**: `LibraryItemMeta`는 추가 시점의 스냅샷으로, 라이브 인덱스(U2)가 불가용해도 라이브러리 카드를 렌더할 수 있도록 검증·저장·반환된다(D5/BR-L5).

---

## 1. 도메인 엔티티 (Domain Entities)

### 1.1. SavedSearch (저장된 검색 엔티티)
사용자가 재실행을 위해 저장한 검색 질의를 나타내는 루트 엔티티입니다(US-L1). 정규화 질의(`normalized_query`)를 기준으로 소유자별 유일성을 보장합니다.
- **속성**:
  - `id`: `str` (UUID v4 문자열 형식 고유 식별자)
  - `owner_id`: `str` (소유 사용자 식별자 — **내부 전용**, SEC-9 비노출)
  - `query`: `str` (사용자가 입력한 표시용 질의; SEC-5 ≤500자)
  - `label`: `str | None` (선택 사용자 라벨; SEC-5 ≤200자)
  - `normalized_query`: `str` (중복 판정 키 — **내부 전용**, SEC-9 비노출)
  - `created_at`: `datetime` (생성 일시; timezone-aware UTC)
- **불변식**:
  - 동일 소유자 내에서 `(owner_id, normalized_query)`는 유일하다. 동일 정규화 질의의 재저장은 멱등이며 기존 `SavedSearch`를 반환한다(`label`이 새 비-null 값이면 갱신, `created_at`은 불변) — BR-L1/D1.
  - 소유자당 최대 200건을 초과하여 저장할 수 없다 — BR-L2/D2.
- **Trace**: FR-8, US-L1, BR-L1, BR-L2, SEC-5, SEC-9, INV-L1

### 1.2. LibraryItem (라이브러리 항목 엔티티)
사용자가 라이브러리에 담은 논문 한 건을 나타내는 루트 엔티티입니다(US-L2). 추가 시점의 메타 스냅샷(`LibraryItemMeta`)을 보존하여 라이브 인덱스와 무관하게 카드를 렌더합니다.
- **속성**:
  - `id`: `str` (UUID v4 문자열 형식 고유 식별자)
  - `owner_id`: `str` (소유 사용자 식별자 — **내부 전용**, SEC-9 비노출)
  - `arxiv_id`: `str` (표시용 arXiv ID, 버전 포함 가능; SEC-5 패턴 검증)
  - `meta`: `LibraryItemMeta` (추가 시점 메타 스냅샷 값 객체 — §2.1)
  - `added_at`: `datetime` (추가 일시; timezone-aware UTC)
- **불변식**:
  - `(owner_id, arxiv_id)`에 대해 멱등하다(`arxiv_id`는 NFC+strip 정규화, 표시 형태·버전 유지). 재추가는 기존 `LibraryItem`을 동일 형상으로 반환하며 저장된 `meta` 스냅샷을 덮어쓰지 않는다 — BR-L3/D3, QT-4.
  - 소유자당 최대 1000건을 초과하여 추가할 수 없다 — BR-L4/D4.
  - `meta`는 추가 시 SEC-5 검증되며, 저장·반환 시 라이브 인덱스(U2)에서 재조회되지 않고 그대로(verbatim) 유지된다(가용성 격리) — BR-L5/D5.
- **Trace**: FR-9, US-L2, BR-L3, BR-L4, BR-L5, QT-4, SEC-5, SEC-9, INV-L1

### 1.3. HistoryEntry (검색 이력 엔티티)
검색 실행 후 비동기로 기록되는 검색 이력 한 건을 나타내는 엔티티입니다(US-L3). 공개 POST가 아니라 `SearchExecutedEvent` 소비를 통해 이벤트 구동으로 기록됩니다.
- **속성**:
  - `id`: `str` (UUID v4 문자열 형식 고유 식별자)
  - `owner_id`: `str` (소유 사용자 식별자 — **내부 전용**, SEC-9 비노출)
  - `query`: `str` (실행된 질의 문자열)
  - `executed_at`: `datetime` (검색 실행 일시; timezone-aware UTC. `SearchExecutedEvent.timestamp` 매핑)
  - `result_count`: `int` (해당 검색의 결과 수. `SearchExecutedEvent.resultCount` 매핑)
  - `dedupe_key`: `str` (`sha256(owner_id|requestId|query)` — 멱등 기록 키, **내부 전용**, SEC-9 비노출)
- **불변식**:
  - 소유자당 최신 500건의 롤링 보존. 상한 초과 기록 시 가장 오래된 항목을 정리(prune)한다. `clearHistory`는 소유자의 전체 이력을 삭제한다 — BR-L6/D6.
  - `SearchExecutedEvent`는 🔒FROZEN이며 at-least-once 전달이다. `dedupe_key`로 중복 제거하여, 재전달이 중복 행을 생성하지 않는다(exactly-once 행) — BR-L7/D7, INV-L3.
- **Trace**: FR-10, US-L3, BR-L6, BR-L7, INV-L3, NFR-P1, SEC-9, INV-L1

> **주의(엔티티명 vs DTO명)**: 본 내부 엔티티 `HistoryEntry`는 공용 와이어 DTO `docsuri_shared.dtos.HistoryEntry`와 **이름이 동일하나 다른 타입**이다. 내부 엔티티는 `owner_id`·`dedupe_key`를 포함(내부 전용)하고, 와이어 DTO는 `id`·`query`·`executedAt`·`resultCount`만 노출한다(SEC-9). 코드에서는 import 별칭 또는 모듈 한정으로 충돌을 피한다(브리프 §5·§7).

---

## 2. 값 객체 (Value Objects)

### 2.1. LibraryItemMeta (라이브러리 메타 스냅샷)
`LibraryItem.meta`의 형상을 정제하는 값 객체로, 추가 시점에 캡처된 논문 카드 메타데이터의 스냅샷입니다. 와이어 DTO의 `meta: Any`를 검증하는 **U4-내부 pydantic 모델**이며, 공용 와이어 DTO의 재정의가 아닙니다(브리프 §5).
- **속성**:
  - `title`: `str` (필수, ≤500자)
  - `authors`: `list[str]` (각 항목 ≤200자, 최대 50개)
  - `year`: `int | None` (1900..2100)
  - `arxiv_id`: `str` (표시용 arXiv ID)
  - `abstract_snippet`: `str | None` (≤1000자; 전체 초록 비노출, 스니펫만)
  - `arxiv_url`: `str | None` (해소 가능 실재 링크)
- **불변식**:
  - 6개 카드 필드(`title`·`authors`·`year`·`arxivId`·`abstractSnippet`·`arxivUrl`)는 U2 `ResultCardVM` 카드 필드(dtos.md §1.1)를 미러링한다. 따라서 라이브러리는 라이브 인덱스 없이도 동일한 카드를 렌더할 수 있다(가용성 격리) — BR-L5/D5.
  - 추가 시 SEC-5 경계로 검증되며, 저장·반환 시 verbatim 유지된다(재조회 없음).
- **Trace**: FR-9, US-L2, BR-L5, SEC-5, SEC-9, dtos.md §1.1

### 2.2. 재사용 값 객체 — U3 단일 권위 (Reused from U3)
다음 타입은 U3 Accounts가 SEC-8 단일 권위(single authority)로 정의하며, U4는 **재정의하지 않고 import**합니다(`backend.modules.accounts.models` + `backend.modules.accounts.guard`). U3에서 재정의·포크하는 것은 금지됩니다(브리프 §2).

| 타입 | 출처 | U4에서의 역할 | Trace |
|---|---|---|---|
| `Principal` | `backend.modules.accounts.models` | 인증된 요청자 보안 컨텍스트(`userId`·`role`·`mfaVerified`). 컨트롤러가 `get_principal` 의존성으로 `request.state.principal`에서 획득 | SEC-8, SEC-12 |
| `Action` | `backend.modules.accounts.models` | 인가 액션 Enum(`READ`·`WRITE`·`DELETE`·`RERUN`). U4 소유권 판정 입력 | SEC-8 |
| `AccountId` | `backend.modules.accounts.models` | 소유자 식별자 값 객체. `AuthorizationGuard.authorize(principal, action, AccountId(owner_id))` 인자 | SEC-8 |
| `Decision` | `backend.modules.accounts.guard` | 인가 판정(`ALLOW`·`DENY`). DENY → SEC-9 비공개로 일반화된 404 | SEC-8, SEC-9, INV-L4 |

---

## 3. 보조 타입 및 식별자 (Identifiers & Auxiliary Types)

### 3.1. 식별자 규약 (Identifier Convention)
- 세 엔티티(`SavedSearch`·`LibraryItem`·`HistoryEntry`)의 `id`는 모두 **UUID v4 문자열**(`str(uuid4())`)이다. 와이어 DTO의 `id: Any`(공용 바인딩)는 U4 검증 계층에서 문자열로 정제된다(브리프 §5).
- `owner_id`는 U3 `AccountId`에 대응하는 문자열 키로, 모든 엔티티가 보유하나 **외부 비노출**이다(SEC-9). 저장소 계층은 이를 구조적 소유자 필터로 사용한다(INV-L1).

### 3.2. PageCursor (페이지네이션 커서 — 불투명 토큰)
커서 기반 keyset 페이지네이션의 연속 토큰을 나타내는 내부 값입니다(D8/BR-L8).
- **형상**: `{"ts": <정렬 기준 instant ISO>, "id": <id>}`를 URL-safe base64로 인코딩한 불투명 문자열.
- **불변식**:
  - 최신순(most-recent-first) 정렬. `limit` 기본 20, 최대 100(초과 시 422로 **거부**). 첫 페이지는 `cursor` 생략. 마지막 페이지는 `nextCursor` 부재.
  - 변조/손상 커서 → 422(검증 실패). 임의 리스트에 대해 limit L로 페이지네이션 시 모든 항목을 중복·누락 없이 최신순으로 정확히 1회 수집(keyset 안정성, advisory 커서 속성).
- **Trace**: FR-8, FR-9, FR-10, BR-L8, SEC-5

### 3.3. 도메인 예외 (Domain Exceptions)
브리프 §9 규약에 따라 모든 도메인 예외는 `DomainException`을 상속하며 컨트롤러가 HTTP로 매핑합니다(DomainException→4xx, cross-owner→404 일반화, unknown→500 fail-closed).
- `QuotaExceededError` → HTTP 409 (저장 검색 200·라이브러리 1000 상한 초과; BR-L2/BR-L4)
- 검증 실패(SEC-5, 커서 변조) → HTTP 422
- cross-owner/누락 → HTTP 404 (SEC-9 비공개, 존재 미노출; INV-L4)
- principal 부재 → HTTP 401 (`get_principal` 의존성; D11)
- **Trace**: BR-L2, BR-L4, SEC-5, SEC-9, INV-L4, D11

---

## 4. 내부 필드 vs 외부 노출 필드 (SEC-9 비공개 경계)

각 엔티티에서 **외부 DTO로 직렬화되는 필드**와 **내부 전용 필드**를 명시합니다. 내부 전용 필드는 어떠한 와이어 DTO·감사 페이로드에도 노출되지 않습니다(SEC-9, D12/BR-L10).

| 엔티티 | 외부 노출 필드 (→ DTO) | 내부 전용 필드 (SEC-9 비노출) |
|---|---|---|
| `SavedSearch` | `id`, `query`, `label`, `created_at`(→`createdAt`) | `owner_id`, `normalized_query` |
| `LibraryItem` | `id`, `arxiv_id`(→`arXivId`), `meta`, `added_at`(→`addedAt`) | `owner_id` |
| `HistoryEntry` | `id`, `query`, `executed_at`(→`executedAt`), `result_count`(→`resultCount`) | `owner_id`, `dedupe_key` |
| `LibraryItemMeta` | `title`, `authors`, `year`, `arxiv_id`(→`arXivId`), `abstract_snippet`(→`abstractSnippet`), `arxiv_url`(→`arxivUrl`) | (없음 — 전 필드 카드 투영) |

- **불변식(SEC-9)**: DTO는 소유자 `userId`를 절대 운반하지 않는다. cross-owner 접근은 403이 아닌 404로 일반화된다. 내부 점수·감사 메타·`normalized_query`·`dedupe_key`는 직렬화되지 않는다.
- **PBT-09(차단 PBT)**: 임의 유효 도메인 엔티티에 대해 `to_dto(entity)` 후 공용 DTO 검증이 안정적이며, 직렬화→역직렬화가 공개 필드를 보존하고 **내부 필드를 절대 누출하지 않음**을 Hypothesis로 검증한다(브리프 §4).
- **Trace**: SEC-9, SEC-8, BR-L10, PBT-09

---

## 5. 와이어 DTO 바인딩 — 공용 SSOT 재사용 (Shared SSOT — REUSE, do NOT fork)

U4는 와이어 DTO를 **재정의하지 않고** `docsuri_shared`에서 import합니다(브리프 §5). `meta` 타입 모델(`LibraryItemMeta`)은 U4-내부 검증자이지 와이어 DTO의 재정의가 아닙니다. §3 정제(max limit 100·typed meta·string id·커서 의미)는 U4 자체 검증 계층(`UserDataDTOAndValidation`)에서 강제하므로, 재생성된 바인딩 설치 여부와 무관하게 U4는 정확합니다.

```python
from docsuri_shared.dtos import (
    PageParams,
    SavedSearchCreateDTO, SavedSearchDTO, SavedSearchPageDTO,
    LibraryItemCreateDTO, LibraryItemDTO, LibraryPageDTO,
    HistoryEntry, HistoryPageDTO,        # 내부 엔티티 HistoryEntry와 동명·별개 타입
    SearchResultSetDTO,
)
from docsuri_shared.events import SearchExecutedEvent
```

- 공용 DTO는 생성된 pydantic 모델(camelCase: `createdAt`·`addedAt`·`executedAt`·`arXivId`·`nextCursor`·`resultCount`; `extra='forbid'`)이다. 공용 바인딩에서 `id`/`meta`=`Any`, `limit` ge=1(상한 없음)이며, U4가 §3 정제를 자체 적용한다.
- **금지**: 이 DTO들의 U4-로컬 재정의. 공용 SSOT 포크는 U3에서 피해야 할 결함이다.

---

## 6. 엔티티 ↔ DTO 매핑 (Entity ↔ Wire DTO Mapping)

`UserDataDTOAndValidation`(validation.py)이 수행하는 변환 매핑입니다. 입력(Create DTO)→엔티티는 `validate_and_map`, 엔티티→출력 DTO는 `to_dto`로 라운드트립합니다(PBT-09).

| 내부 엔티티/값 객체 | 입력 DTO (생성) | 출력 DTO (단건) | 출력 DTO (페이지) |
|---|---|---|---|
| `SavedSearch` | `SavedSearchCreateDTO`{`query`, `label?`} | `SavedSearchDTO`{`id`, `query`, `label?`, `createdAt`} | `SavedSearchPageDTO`{`items[]`, `nextCursor?`} |
| `LibraryItem` | `LibraryItemCreateDTO`{`arXivId`, `meta`} | `LibraryItemDTO`{`id`, `arXivId`, `meta`, `addedAt`} | `LibraryPageDTO`{`items[]`, `nextCursor?`} |
| `HistoryEntry`(내부) | (공개 입력 없음 — 이벤트 구동) | `HistoryEntry`(와이어){`id`, `query`, `executedAt`, `resultCount`} | `HistoryPageDTO`{`items[]`, `nextCursor?`} |
| `LibraryItemMeta` | `LibraryItemCreateDTO.meta`(`Any`→검증) | `LibraryItemDTO.meta`(verbatim) | — |
| `PageCursor` | `PageParams`{`limit`, `cursor?`} | (각 페이지 DTO의 `nextCursor`) | — |
| rerun 결과 | (질의 해소 후 `SearchGatewayPort.search`) | `SearchResultSetDTO`(게이트웨이-프론티드 검색 카드) | — |

**필드명 변환(snake_case 내부 ↔ camelCase 와이어)**: `created_at`↔`createdAt`, `added_at`↔`addedAt`, `executed_at`↔`executedAt`, `arxiv_id`↔`arXivId`, `result_count`↔`resultCount`, `abstract_snippet`↔`abstractSnippet`, `arxiv_url`↔`arxivUrl`. 내부 필드(`owner_id`·`normalized_query`·`dedupe_key`)는 어떤 DTO에도 매핑되지 않는다(SEC-9).

---

## 7. 엔티티 ↔ 공용 계약 추적 (Entity ↔ Shared Contract Table)

내부 엔티티가 의존·바인딩하는 공용 계약(`docsuri_shared`)과 이벤트 출처입니다.

| 내부 엔티티/값 객체 | 공용 와이어 계약 (`docsuri_shared.dtos`) | 이벤트/포트 계약 | 출처 스키마 | Trace |
|---|---|---|---|---|
| `SavedSearch` | `SavedSearchCreateDTO`·`SavedSearchDTO`·`SavedSearchPageDTO` | rerun → `SearchGatewayPort.search` → `SearchResultSetDTO` | `library.schema.json` | FR-8, US-L1, BR-L9 |
| `LibraryItem` | `LibraryItemCreateDTO`·`LibraryItemDTO`·`LibraryPageDTO` | — | `library.schema.json` | FR-9, US-L2 |
| `HistoryEntry`(내부) | `HistoryEntry`(와이어)·`HistoryPageDTO` | 입력: `SearchExecutedEvent`(🔒FROZEN, `docsuri_shared.events`); rerun → `SearchResultSetDTO` | `library.schema.json`, `search-executed.schema.json` | FR-10, US-L3, BR-L7, BR-L9, NFR-P1 |
| `LibraryItemMeta` | `LibraryItemDTO.meta`(`Any` 검증) ↔ U2 `ResultCardVM` 카드 필드(미러) | — | `library.schema.json`, dtos.md §1.1 | FR-9, US-L2, BR-L5 |
| 공통(페이지네이션) | `PageParams`(`limit`·`cursor?`) | `PageCursor` 내부 코덱(§3.2) | `library.schema.json` | FR-8/9/10, BR-L8 |
| rerun(저장검색·이력) | `SearchResultSetDTO`(= search.schema.json `SearchResultPageDTO` 재사용) | `SearchGatewayPort`(U6 ApiGatewayMiddleware → U2; `StubSearchGateway` 기본) | `library.schema.json` → `search.schema.json` | BR-L9, INV-L2 |

- **rerun 비백도어(INV-L2)**: rerun은 U2 직접 호출이 아니라 `SearchGatewayPort`(게이트웨이-프론티드)로 재진입하여 비용·근거화 훅이 재적용된다. U4는 결정적 `StubSearchGateway`를 제공하고 실제 바인딩은 U6/Infra를 기다린다(D9).
- **이력 멱등(INV-L3)**: `SearchExecutedEvent`는 at-least-once → `dedupe_key`로 exactly-once 행 보장(D7).

---

## 8. 추적성 요약 (Traceability Summary)

| ID | 정의 위치 | 대응 BR/INV | 본 문서 항목 |
|---|---|---|---|
| FR-8 | 저장된 검색(US-L1) | BR-L1·L2·L8·L9 | §1.1, §6, §7 |
| FR-9 | 라이브러리(US-L2) | BR-L3·L4·L5·L8 | §1.2, §2.1, §6, §7 |
| FR-10 | 검색 이력(US-L3) | BR-L6·L7·L8·L9 | §1.3, §6, §7 |
| INV-L1 | 소유자-스코핑 백스톱 | — | §0, §1, §3.1 |
| INV-L2 | rerun 비백도어 | BR-L9 | §7 |
| INV-L3 | 이력 멱등(exactly-once) | BR-L7 | §1.3, §7 |
| INV-L4 | fail-closed 인가(DENY→404/401) | — | §2.2, §3.3 |
| SEC-5 | 입력 검증 | — | §1, §2.1, §3.2, §3.3 |
| SEC-8 | 인가 단일 권위(U3) | — | §0, §2.2 |
| SEC-9 | 비공개(내부 필드·userId 비노출) | BR-L10 | §0, §4, §6 |
| PBT-09 | DTO 라운드트립(차단 PBT) | — | §4, §6 |

> **상태**: 🟡 PROVISIONAL — 본 문서는 U4 FD의 도메인 모델 SSOT이다. business-logic-model.md(서비스 흐름)·business-rules.md(BR-L1..L10 전문)·NFR/Design 문서가 본 엔티티 정의를 참조한다. 공용 와이어 DTO 형상은 `library.schema.json`(🟡 PROVISIONAL, U4 FD에서 정제)에 묶인다.
