# nfr-design-patterns.md — U4 Library NFR 디자인 패턴 정의서

**단계**: CONSTRUCTION → NFR Design (유닛별 루프, Track 2 두 번째 유닛) · **유닛**: U4 Library (검색 저장·라이브러리·이력) · **일자**: 2026-06-17
**근거(SSOT)**: `u4-design-brief.md` (D1~D12, BR-L1~BR-L10, INV-L1~INV-L4 반영) · 상속: `construction/u3-accounts/nfr-design/*`
**대상 컴포넌트**: SavedSearchService · LibraryService · SearchHistoryService · UserDataRepository · SearchGatewayPort · AuditSink
**언어 정책**: 본문 한국어 · 안정 식별자/경로/약어 영어 (U3 문서 스타일 일치)

> U4는 사이클 2(그린필드)의 모듈러 모놀리스 백엔드 배포 단위 ① 안에서 동작하는 **소유자 사설(owner-private)** API 모듈입니다. U3 Accounts가 SEC-8 인가 단일 권위(AuthorizationGuard)이며, U4는 그 결정을 위임하고 데이터 레이어에서 소유자 스코핑 백스톱(INV-L1)을 추가하는 방어심층(defense-in-depth) 구조를 따릅니다. 본 문서는 U4의 복원력(resilience)·보안(security)·성능(performance) NFR을 구체 디자인 결정으로 고정합니다. (FD = 추상, 본 NFR Design = 구체 결정)

---

## 1. 소유자 스코핑 데이터 백스톱 패턴 (INV-L1, SEC-8, NFR-R1)

인가 결정(AuthorizationGuard)이 어떤 이유로든 우회되거나 오결정되더라도, 어떤 쿼리도 타 소유자의 행(row)을 절대 반환하지 못하도록 **저장소 레이어에 구조적 소유자 스코핑을 강제**합니다. 이것은 가드 결정을 대체하는 것이 아니라, 그 아래에 두는 두 번째 방어선(defense-in-depth)입니다.

```
[Controller]
     | get_principal → request.state.principal (U6 게이트웨이가 주입)
     v
[Service]
     | AuthorizationGuard.authorize(principal, action, AccountId(owner_id))  ← 1차 방어 (SEC-8)
     | Decision.ALLOW 인 경우에만 진행
     v
[UserDataRepository / sub-repo]
     | 모든 read/write 가 owner_id 를 구조적 술어(predicate)로 포함  ← 2차 방어 백스톱 (INV-L1)
     | SELECT ... WHERE owner_id = :owner_id AND id = :id
     v
[InMemory ↔ SQL 어댑터]
```

### 1.1. 백스톱 강제 규칙
- **모든 read 경로**: `owner_id` 필터가 술어에 **구조적으로 포함**되어야 합니다. owner_id 없는 전역 조회 메서드는 포트(`UserDataRepository`)에 정의하지 않습니다. (INV-L1)
- **모든 write 경로**: insert/update/delete 시 `owner_id` 가 행에 기록되거나 술어로 매칭되어야 하며, 단건 조회 후 가드 통과 → 변경의 2단 패턴(get-then-act)에서도 변경 술어에 `owner_id` 를 재포함합니다 (TOCTOU 갭 방지).
- **교차 소유자 결과 불가능 보장**: 단건 조회가 다른 소유자의 id 를 가리키면 `WHERE owner_id = :owner_id` 술어에 의해 0행이 반환되며, 서비스는 이를 NotFound 로 일반화합니다 (§2 연계).
- **InMemory ↔ SQL 동등성**: 두 어댑터 모두 동일한 스코핑 의미를 구현합니다. InMemory 는 `(owner_id, id)` 복합 키 딕셔너리 또는 owner_id 1차 분할로, SQL 은 WHERE 술어 + 복합 인덱스로 구현합니다. (D10)

### 1.2. UserDataRepository 집합 포트
3개 하위 저장소(SavedSearchRepository · LibraryRepository · SearchHistoryRepository)를 **UserDataRepository** 단일 포트로 집약하여, 소유자 스코핑 정책을 한 곳에서 검증/감사할 수 있게 합니다. 하위 저장소는 각 sub-domain 의 행만 다루되 동일한 owner_id 술어 규약을 공유합니다.

---

## 2. Fail-Closed 인가 → 일반화 404 패턴 (INV-L4, SEC-9, SEC-15)

인가 또는 principal 처리 중 발생하는 모든 오류는 **항상 거부(DENY) 방향**으로 닫히며, 리소스의 존재 여부를 노출하지 않도록 일반화된 응답으로 변환됩니다. Fail-open 은 어떤 경로에서도 허용하지 않습니다.

```
                         ┌─────────────────────────────┐
[요청] → [get_principal] │ principal 부재/무효?         │── yes ──> HTTP 401 (세션 없음)
                         └──────────────┬──────────────┘
                                        | no
                                        v
                         ┌─────────────────────────────┐
                         │ AuthorizationGuard.authorize │
                         │  == Decision.ALLOW ?         │── no (DENY) ──┐
                         └──────────────┬──────────────┘               |
                                        | yes                          |
                                        v                              |
                         [owner-scoped repo 조회]                       |
                                        |                              |
                         ┌──────────────┴──────────────┐               |
                         │ 0행 (교차소유자/미존재)?     │── yes ────────┤
                         └──────────────┬──────────────┘               |
                                        | no                           v
                                        v                  HTTP 404 NotFound (일반화)
                                  [정상 응답]              (존재 비공개 — SEC-9)
                                        ^
                         [알 수 없는 예외] ── 500 (fail-closed, SEC-15)
```

### 2.1. 매핑 규칙 (controller HTTP 매핑)
- **principal 부재**: `get_principal` 의존성이 `request.state.principal` 부재 시 **HTTP 401** 을 발생시킵니다. (D11)
- **교차 소유자 OR 미존재**: 가드 DENY 또는 repo 0행 → **HTTP 404 NotFound** 로 일반화합니다. 403(Forbidden)을 반환하지 않습니다 — 403 은 "존재하지만 권한 없음"을 누설하기 때문입니다. (INV-L4, SEC-9)
- **검증 실패**: SEC-5 위반(길이 초과, arxiv_id 패턴 불일치, limit 범위 위반, 손상 cursor) → **HTTP 422** + 일반화 메시지. (§5, §6)
- **쿼터 초과**: `QuotaExceededError` → **HTTP 409**. (BR-L2, BR-L4)
- **알 수 없는 예외**: DomainException 계열이 아닌 모든 예외 → **HTTP 500** (fail-closed; 내부 상세 비노출). (SEC-15)

### 2.2. 비노출(non-disclosure) 직렬화 규칙 (SEC-9)
와이어 DTO 는 절대 다음 내부 필드를 직렬화하지 않습니다: `owner_id`, `dedupe_key`, `normalized_query`, 내부 점수/순위, audit 메타. `UserDataDTOAndValidation.to_dto` 가 도메인 엔티티 → 공개 DTO 변환 시 이 필드들을 구조적으로 제외하며, PBT-09 라운드트립 속성이 "어떤 내부 필드도 누설되지 않음"을 검증합니다. (PBT-09, SEC-9)

---

## 3. 멱등 업서트 패턴 — Saved Searches & Library (BR-L1, BR-L3, INV-L1)

쓰기 경로의 중복 호출이 중복 행이나 상태 변형을 만들지 않도록, 자연 키(natural key) 기반 멱등 업서트를 적용합니다.

### 3.1. Saved Search 멱등 — `(owner_id, normalized_query)` (D1, BR-L1)
- **정규화(normalized_query)**: Unicode **NFC** → 양끝 strip → 내부 연속 공백 1칸으로 collapse → **casefold**. 이 순서로 결정론적 정규형을 산출합니다.
- **멱등 의미**: 동일 정규형 재저장 시 기존 SavedSearch 를 반환(HTTP 200). 새 non-null `label` 이 제공되면 label 만 갱신하고, `created_at` 은 변경하지 않습니다. (BR-L1)
- **유니크 제약**: `UNIQUE(owner_id, normalized_query)` — SQL 어댑터는 부분/복합 유니크 인덱스로, InMemory 는 `(owner_id, normalized_query) → id` 인덱스 맵으로 강제합니다.
- **경합(concurrency) 처리**: 동시 동일 저장 시 SQL 은 유니크 위반을 잡아 기존 행 재조회(insert-or-select)로 멱등성을 복원합니다.

### 3.2. Library 멱등 — `(owner_id, arxiv_id)` (D3, BR-L3, QT-4)
- **arxiv_id 정규화**: NFC + strip, **표시형(display form, 버전 vN 포함) 보존**. 버전 접미사를 제거하지 않습니다.
- **멱등 의미**: 재추가 시 기존 LibraryItem 을 동일 shape 로 반환(HTTP 200). **저장된 meta 스냅샷을 덮어쓰지 않습니다** (최초 캡처 보존 — 가용성 격리, §7 연계). (BR-L3, QT-4)
- **유니크 제약**: `UNIQUE(owner_id, arxiv_id)`.

```
[POST /library/items {arXivId, meta}]
        |
        v
[정규화: arxiv_id = NFC+strip(표시형 보존)]
        |
        v
[repo.find_by(owner_id, arxiv_id)]
        |
  ┌─────┴─────┐
  | 존재?     |── yes ──> 기존 LibraryItem 반환 (200, meta 스냅샷 보존, 덮어쓰기 없음)
  └─────┬─────┘
        | no
        v
[쿼터 가드 (§4)] → [insert] → 신규 LibraryItem 반환 (200/201)
```

---

## 4. 소유자별 쿼터 가드 패턴 (BR-L2, BR-L4)

소유자당 저장 리소스 폭증을 막기 위해 추가/저장 직전에 카운트 기반 쿼터를 강제합니다.

### 4.1. 쿼터 수치
- **Saved Searches**: 소유자당 최대 **200** 건. (D2, BR-L2)
- **Library**: 소유자당 최대 **1000** 건. (D4, BR-L4)
- **초과 처리**: 상한 도달 후 신규 생성(멱등 재저장 제외) 시 `QuotaExceededError` → **HTTP 409 Conflict**. (BR-L2, BR-L4)

### 4.2. 쿼터 평가 순서 (멱등성과의 상호작용)
쿼터 가드는 **멱등 분기 이후, 신규 insert 직전**에만 평가합니다. 즉 이미 존재하는 자연 키의 재저장/재추가는 카운트를 증가시키지 않으므로 상한에 걸린 소유자도 기존 항목을 멱등하게 갱신/재조회할 수 있습니다.

```
[create]
   |
   v
[멱등 조회] ─ 존재 ─> [기존 반환 (쿼터 평가 건너뜀, 200)]
   | 미존재
   v
[count(owner_id) >= 상한?] ─ yes ─> QuotaExceededError → 409
   | no
   v
[insert]
```

- **카운트 비용**: owner_id 술어의 `COUNT(*)` 는 §1 의 복합 인덱스를 사용해 O(인덱스 범위)로 평가합니다. InMemory 는 owner 분할 리스트 길이로 O(1) 평가합니다.

---

## 5. 경계 롤링 보존 가지치기 패턴 — Search History (D6, BR-L6, INV-L1)

이력은 무한 증가하지 않도록 소유자당 **최근 500건 롤링 윈도우**로 제한합니다.

### 5.1. 보존 정책
- **상한**: 소유자당 **500** 건. (D6, BR-L6)
- **가지치기(prune)**: 상한 초과 기록 시 가장 오래된 항목부터 삭제하여 윈도우를 유지합니다. 가지치기는 `executed_at` (동률 시 `id`) 오름차순으로 선택합니다.
- **clearHistory**: 소유자의 모든 이력을 삭제합니다 (DELETE `/library/history`, 소유자 스코프). (D6)

### 5.2. 가지치기 실행 모델 (record 경로)
이력 기록은 동기 검색 경로 밖에서 일어나는 이벤트 소비(consumer)이므로(§8, NFR-P1), 가지치기는 record 트랜잭션의 일부로 수행하되 검색 응답을 절대 블로킹하지 않습니다.

```
[recordSearch(event)]
   |
   v
[멱등 dedup (§8, dedupe_key)] ─ 중복 ─> [no-op (행 생성 없음)]
   | 신규
   v
[insert HistoryEntry (owner_id 스코프)]
   |
   v
[count(owner_id) > 500?] ─ yes ─> [delete oldest (count-500) rows by (executed_at, id) asc]
   | no
   v
[commit]
```

- **경계 보장**: insert + prune 가 단일 단위로 수행되어 윈도우 크기가 항상 ≤ 500 으로 수렴합니다 (eventual, 재전송에도 안정).

---

## 6. 키셋 커서 페이지네이션 패턴 (D8, BR-L8)

모든 컬렉션 조회는 오프셋이 아닌 **키셋(keyset) 커서** 기반으로 최신순(most-recent-first) 페이징하여, 대용량/동시 삽입 상황에서도 안정적(중복·누락 없음)인 순회를 보장합니다.

### 6.1. 커서 의미
- **limit**: 기본 **20**, 최대 **100**. 100 초과는 **REJECT → HTTP 422** (명시성 우선; 클램프 아님). (D8)
- **cursor**: `{"ts": <정렬 기준 instant ISO>, "id": <id>}` 의 **URL-safe base64** 불투명 토큰. 첫 페이지는 cursor 를 생략합니다.
- **nextCursor**: 마지막 페이지에서는 **부재**(absent). 페이지 DTO 의 `nextCursor` 와 PageParams 의 `cursor` 가 대칭입니다.
- **정렬 키**: SavedSearch=`(created_at, id)`, Library=`(added_at, id)`, History=`(executed_at, id)`. id 를 타이브레이커로 두어 동일 instant 충돌을 결정론적으로 해소합니다 (cursor 안정성 속성).

### 6.2. 키셋 술어
```
WHERE owner_id = :owner_id                       -- INV-L1 백스톱 (항상 동반)
  AND (sort_ts, id) < (:cursor_ts, :cursor_id)   -- 최신순 키셋 (커서 이후)
ORDER BY sort_ts DESC, id DESC
LIMIT :limit + 1                                  -- +1 로 다음 페이지 존재 여부 판정
```
- `limit + 1` 행을 조회하여 초과분이 있으면 마지막 항목을 잘라내고 그 경계로 `nextCursor` 를 생성합니다. 초과분이 없으면 nextCursor 를 생략합니다.

### 6.3. 커서 변조(tamper) 처리 (보안)
- **불투명성**: cursor 내부 구조(ts/id)는 클라이언트 계약이 아닌 불투명 토큰으로 취급합니다.
- **변조/손상 → 422**: base64 디코드 실패, JSON 파싱 실패, 필수 키(ts/id) 부재, 타입 불일치 → **HTTP 422** 로 거부합니다. cursor 는 owner_id 를 담지 않으므로(§1 백스톱이 별도 강제), 위조 cursor 로 타 소유자 데이터에 접근할 수 없습니다. (D8, INV-L1)
- **codec 위치**: 인코딩/디코딩은 `UserDataDTOAndValidation` (validation.py) 의 cursor codec 에 집약하여 3개 컨트롤러가 공유합니다.

---

## 7. 가용성 격리 패턴 — 저장 meta 스냅샷 (D5, BR-L5)

라이브러리 항목은 라이브 인덱스(U2/index)나 외부 카탈로그의 가용성에 의존하지 않고 렌더링되어야 합니다. 추가 시점에 캡처한 **meta 스냅샷**을 검증·저장·반환하여, 다운스트림 장애로부터 U4 를 격리합니다.

### 7.1. LibraryItemMeta 스냅샷
- **필드**: `title`(필수, ≤500), `authors`(list[str], 각 ≤200, ≤50개), `year`(int|None, 1900..2100), `arxiv_id`, `abstract_snippet`(≤1000|None), `arxiv_url`(None 허용). U2 ResultCardVM 카드 필드(dtos.md §1.1: title·authors·year·arxivId·abstractSnippet·arxivUrl)를 미러링합니다.
- **검증 시점**: 추가 시(SEC-5) `LibraryItemMeta` (U4 내부 pydantic 모델)가 `meta: Any` 를 검증합니다. 이는 와이어 DTO 의 재정의가 아닌 내부 검증기입니다 (§9, SSOT 포크 금지).
- **저장·반환**: 캡처된 그대로 verbatim 저장하고 반환합니다. **U2/index 에서 절대 재조회하지 않습니다.** 멱등 재추가도 스냅샷을 덮어쓰지 않습니다 (§3.2). (BR-L5, BR-L3)

### 7.2. 격리 경계
```
[추가 시점]  U2 결과 카드 ──(스냅샷 캡처 + SEC-5 검증)──> [LibraryItemMeta 저장]
                                                              |
[조회 시점]  GET /library/items ──(저장된 스냅샷 verbatim)──> [응답]
                                                              ^
                          U2/index 다운 ───X (재조회 안 함, 영향 없음)
```
이 경계로 U4 GET 가용성은 U2 인덱스 가용성과 **독립**입니다 (NFR-R2 가용성 격리).

---

## 8. 멱등 이벤트 소비 패턴 — SearchExecutedEvent (D7, BR-L7, INV-L3)

이력 쓰기는 공개 POST 가 아니라 `SearchExecutedEvent` (🔒FROZEN) 소비로 수행됩니다. 이벤트 백본은 **at-least-once** 전달이므로, 재전송이 중복 행을 만들지 않도록 멱등 소비를 강제합니다.

### 8.1. dedupe_key 기반 멱등성
- **키**: `dedupe_key = sha256(owner_id|requestId|query)`. 동일 (userId, requestId, query) 재전송은 동일 키를 산출합니다. (D7)
- **exactly-once 행**: dedupe_key 당 정확히 1행. insert 전 dedup 조회(또는 `UNIQUE(owner_id, dedupe_key)` 위반 무시)로 재전송을 흡수합니다. (INV-L3)
- **비블로킹 보장**: 이 소비 경로는 동기 검색 P50<3s 경로 밖에서 실행되며 검색 응답을 블로킹하지 않습니다. (NFR-P1, search-executed 이벤트 계약 명시)

```
[event bus] ──(at-least-once)──> [history_consumer.recordSearch(event)]
                                          |
                                          v
                          [compute dedupe_key = sha256(owner_id|requestId|query)]
                                          |
                          ┌───────────────┴───────────────┐
                          │ dedupe_key 존재? (UNIQUE)      │── yes ──> [no-op, 중복 무시]
                          └───────────────┬───────────────┘
                                          | no
                                          v
                          [insert HistoryEntry] → [보존 가지치기 (§5)] → [commit]
```

### 8.2. 매핑
- 이벤트의 `userId` → 내부 `owner_id`, `timestamp` → `executed_at`(aware UTC), `query`/`resultCount` 그대로. 이벤트는 내부 필드를 노출하지 않습니다 (SEC-9).

---

## 9. 게이트웨이-프론트 재실행 패턴 — Rerun (D9, BR-L9, INV-L2)

저장된 검색/이력 항목의 재실행(rerun)은 **U2 를 직접 호출하지 않습니다.** 비용·근거화 훅이 재적용되도록 게이트웨이를 경유합니다 (백도어 금지).

### 9.1. SearchGatewayPort 경유
- **포트**: `SearchGatewayPort.search(query, principal) -> SearchResultSetDTO`. 이는 게이트웨이-프론트 검색 계약(U6 ApiGatewayMiddleware → U2)입니다. (D9, INV-L2)
- **흐름**: `rerunSavedSearch`/`rerunHistoryEntry` 는 저장된 query 를 해소(소유자 스코프 조회)한 뒤 포트를 호출합니다. U2 를 직접 import/call 하지 않습니다 (INV-L2 백도어 없음).
- **U4 출하 구현**: `StubSearchGateway` (결정론적 placeholder). 실제 바인딩은 U6/Infra 통합을 대기합니다. (D9)

```
[POST /library/saved-searches/{id}/rerun]
        |
        v
[가드 + owner-scoped 조회로 stored query 해소]
        |
        v
[SearchGatewayPort.search(query, principal)]   ← U6 게이트웨이가 비용·근거화 훅 재적용
        |  (U4 기본 구현 = StubSearchGateway, 실바인딩은 U6/Infra)
        v
[SearchResultSetDTO 반환]   (U2 직접 호출 절대 없음 — INV-L2)
```

---

## 10. 포트 기반 영속성 & Mock-First 스왑 패턴 (D10, INV-L1)

저장소는 포트(typing.Protocol) 뒤에 두어, 라이브 인프라 없이도 앱-셸이 마운트되고 테스트가 그린으로 통과하도록(mock-first, discovery 와 동일 철학) 설계합니다.

### 10.1. 어댑터 구성
- **InMemoryUserDataRepository** (기본): 앱-셸 마운트 + 테스트 기본값. 라이브 DB 불필요. (D10)
- **SqlUserDataRepository** (프로덕션): SQLAlchemy 스캐폴드 + DDL 마이그레이션 SQL(`migrations/001_create_library_tables.sql`). U3 의 RDS PostgreSQL(NFR/Infra) 상속.
- **동등성 계약**: 두 어댑터는 동일한 포트 의미(소유자 스코핑 §1, 멱등 유니크 §3, 키셋 정렬 §6, dedup §8, 보존 §5)를 구현하며, 동일한 계약 테스트 스위트로 검증합니다.

```
        UserDataRepository (Protocol, ports.py)
                  /                    \
   InMemoryUserDataRepository    SqlUserDataRepository
   (default, mock-first)         (SQLAlchemy + DDL, prod)
   - 라이브 DB 불필요             - RDS PostgreSQL (U3 상속)
   - 테스트/앱-셸 그린            - owner-scoped 복합 인덱스
```

### 10.2. DI 스왑 (app-shell)
- `backend/wiring.py` 의 `_mount_library(app, settings, result)` 가 기본 InMemory 싱글톤 + `StubSearchGateway` + `InMemoryAuditSink` 를 빌드하고 컨트롤러의 repo/gateway/audit DI 프로바이더를 오버라이드합니다. 3개 라우터를 `include_router` 하고 `result.mounted` 에 `"library"` 를 추가합니다.
- **마운트 무전제(no live DB)**: 라이브러리는 PostgreSQL 없이 in-memory 로 마운트됩니다 (accounts 의 DB 엔진 재사용 패턴은 가용하게 유지하되 강제하지 않음). (브리프 §8)

### 10.3. 인덱싱 (SQL 어댑터)
소유자 스코핑 + 키셋 + 멱등을 동시에 만족하는 복합 인덱스를 정의합니다.
- saved_searches: `UNIQUE(owner_id, normalized_query)`, `INDEX(owner_id, created_at DESC, id DESC)`
- library_items: `UNIQUE(owner_id, arxiv_id)`, `INDEX(owner_id, added_at DESC, id DESC)`
- search_history: `UNIQUE(owner_id, dedupe_key)`, `INDEX(owner_id, executed_at DESC, id DESC)`

---

## 11. 감사 싱크 포트 패턴 (D12, BR-L10, SEC-13)

변경 연산(save/delete, add/remove, clear)은 `AuditSink` 포트로 감사 이벤트를 방출합니다. 기본 구현은 in-memory/no-op 이며, 실제 라우팅은 U6/ops 로 위임합니다.

### 11.1. 감사 규칙
- **포트**: `AuditSink` (typing.Protocol), 기본 `InMemoryAuditSink`. (D12)
- **방출 시점**: 변경 성공 시 서비스 레이어에서 방출 (save/delete, add/remove, clear).
- **민감/내부 필드 금지**: 감사 페이로드에 owner_id 외 식별 가능한 민감 필드나 내부 필드(normalized_query, dedupe_key, 점수)를 담지 않습니다 (SEC-9). 행위·리소스 종류·결과 등 비민감 메타만 기록합니다.
- **비블로킹**: 감사 방출 실패가 주 연산을 롤백하거나 블로킹하지 않습니다 (best-effort, no-op 기본).

---

## 12. 의존성 격리 — 타임아웃/재시도 위임 패턴 (RES-9)

U4 는 외부 호출(SearchGatewayPort 경유 검색, 이벤트 버스, SQL/DB)에 대한 명시적 타임아웃·재시도·서킷 브레이커를 **자체 재구현하지 않고**, 공유 복원력 어댑터(RES-9, U1/U2 의 EmbeddingGatewayAdapter·ArxivSource/게이트웨이 미들웨어와 동일 정책)에 위임합니다.

### 12.1. 위임 경계
- **SearchGatewayPort**: 타임아웃/서킷/저하 모드는 U6 게이트웨이 미들웨어 + 공유 어댑터가 적용합니다 (RES-9). U4 `StubSearchGateway` 는 결정론적이므로 외부 지연이 없습니다.
- **DB 커넥션 풀/타임아웃**: U3 의 SQLAlchemy 풀 정책(`pool_size=10`, `max_overflow=20`, `pool_timeout=3.0s`, `pool_recycle=1800s`)을 상속합니다 (logical-components §1.1). U4 는 신규 풀 정책을 도입하지 않습니다.
- **저하 모드**: 게이트웨이 검색 장애 시 정의된 저하 동작은 게이트웨이/U2 책임이며, U4 는 포트 예외를 도메인 예외로 변환해 fail-closed(§2) 매핑합니다 (RES-9).

> 본 위임은 "U4 의 침묵 시 전역/상속 결정을 명시"하는 원칙에 따른 것입니다 — U4 브리프는 자체 타임아웃 수치를 정의하지 않으며, RES-9 공유 어댑터 정책을 상속합니다.

---

## 13. 성능 — 이력 쓰기 비블로킹 (NFR-P1)

- **검색 동기 경로 무영향**: 이력 쓰기는 `SearchExecutedEvent` 소비(§8)로 비동기 수행되며, 검색 동기 응답 경로(P50<3s, NFR-P1) 밖에서 실행됩니다. 이벤트 발행/소비는 검색 응답을 블로킹하지 않습니다 (search-executed 계약 명시).
- **읽기 경로 비용**: 모든 컬렉션 조회는 키셋(§6) + 복합 인덱스(§10.3)로 O(limit) 비용을 가집니다 (오프셋 스캔 없음).
- **쿼터 카운트**: 멱등 분기 이후에만 평가하며(§4.2), 인덱스 범위 COUNT 로 평가합니다.

---

## 14. PBT 및 CI 파이프라인 통합 명세 (PBT-09, CI=GHA)

### 14.1. 속성 기반 테스트 (Property-Based Testing)
- **PBT-09 (DTO 라운드트립, blocking)**: 임의의 유효 도메인 엔티티에 대해 `to_dto(entity)` 후 공유 DTO 검증이 안정적이며, 유효 create DTO 의 `validate_and_map` 가 공개 필드를 라운드트립합니다. 속성: serialize→deserialize 가 공개 필드를 보존하고 **어떤 내부 필드도 누설하지 않음**. Hypothesis 사용. (PBT-09; Partial 프로파일에서 advisory 이나 U4 component-methods 가 핀하므로 구현)
- **커서 속성 (advisory)**: 임의의 리스트를 limit L 로 페이징하면 모든 항목이 정확히 한 번씩 최신순으로 수집되며 중복/누락이 없음 (키셋 안정성, §6).

### 14.2. CI (GitHub Actions)
- **CI=GHA**: 단위·PBT·계약(InMemory↔SQL 동등성) 테스트를 GitHub Actions 파이프라인에서 커밋마다 자동 검증합니다. **CD(배포)는 Infra 단계** 책임입니다 (본 NFR Design 범위 밖).
- **ruff**: `backend/modules/*` 는 self-lint (backend ruff 가 modules/ 제외)이나 clean 유지 (line-length 100, select E/F/I/UP/B).
- **신규 서드파티 의존성 금지**: sqlalchemy·pydantic 은 기존 backend/pyproject 에 존재. hypothesis 는 PBT 용 dev 의존성.
- **datetime**: timezone-aware UTC (`datetime.now(UTC)`; `datetime.utcnow()` 비사용).

---

## 15. 패턴 → 트레이스 매핑 요약

| # | 패턴 | 결정/규칙 | 트레이스 |
|---|---|---|---|
| 1 | 소유자 스코핑 데이터 백스톱 | 모든 repo read/write owner_id 술어 | INV-L1, D10, SEC-8, NFR-R1 |
| 2 | Fail-Closed 인가 → 일반화 404 | DENY/0행→404, 부재→401, 알수없음→500 | INV-L4, D11, SEC-9, SEC-15 |
| 3 | 멱등 업서트 (saved/library) | `(owner,normalized_query)` / `(owner,arxiv_id)` | BR-L1, BR-L3, D1, D3, QT-4 |
| 4 | 소유자별 쿼터 가드 | saved 200 / library 1000 → 409 | BR-L2, BR-L4, D2, D4 |
| 5 | 경계 롤링 보존 가지치기 | history 500, oldest prune, clear | BR-L6, D6, INV-L1 |
| 6 | 키셋 커서 페이지네이션 | limit 20/max100→422, base64 cursor, tamper→422 | BR-L8, D8 |
| 7 | 가용성 격리 meta 스냅샷 | verbatim 저장, 재조회 없음 | BR-L5, D5, NFR-R2 |
| 8 | 멱등 이벤트 소비 | dedupe_key sha256, exactly-once 행 | BR-L7, D7, INV-L3, NFR-P1 |
| 9 | 게이트웨이-프론트 재실행 | SearchGatewayPort, StubSearchGateway | BR-L9, D9, INV-L2 |
| 10 | 포트 기반 영속성 mock-first | InMemory(기본)↔SQL 스왑 | D10, INV-L1 |
| 11 | 감사 싱크 포트 | AuditSink, no-op 기본, 민감필드 금지 | BR-L10, D12, SEC-13, SEC-9 |
| 12 | 의존성 격리 타임아웃/재시도 위임 | RES-9 공유 어댑터 위임 | RES-9 |
| 13 | 이력 쓰기 비블로킹 | 동기 검색 경로 무영향 | NFR-P1 |
| 14 | PBT + CI(GHA) | PBT-09 라운드트립, GHA CI | PBT-09, SEC-9 |

---

## 16. 참조한 공유 계약 (REUSE — 포크 금지)

- **DTO (docsuri_shared.dtos)**: `PageParams, SavedSearchCreateDTO, SavedSearchDTO, SavedSearchPageDTO, LibraryItemCreateDTO, LibraryItemDTO, LibraryPageDTO, HistoryEntry, HistoryPageDTO, SearchResultSetDTO` — `shared/dtos/library.schema.json` 생성 바인딩. U4 는 §3 정제(max limit 100, typed meta, string id, cursor 의미)를 **자체 검증 레이어**(`UserDataDTOAndValidation`)에서 강제하며 와이어 DTO 를 재정의하지 않습니다.
- **이벤트 (docsuri_shared.events)**: `SearchExecutedEvent` (🔒FROZEN) — `shared/events/search-executed.schema.json`.
- **인가 (backend.modules.accounts)**: `Principal, Action, AccountId, Decision, AuthorizationGuard.authorize(...)` (U3 SEC-8 단일 권위, 재정의 금지).
- **앱-셸**: `backend/wiring.py` `_mount_library` 마운트 시임, `backend/app.py`/`config.py`.
