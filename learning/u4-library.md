# U4 Library — 파이프라인 상세 (저장·이력·재실행)

> 학습용 메모. **커밋하지 않는다.** 근거: `backend/modules/library/` 실제 코드.
> 형식: **[받음] → [함] → [내보냄]** + "어디서/어떻게". 먼저 `00-project-overview.md`·`u3-accounts.md` 가정.

---

## 0. 이 유닛이 하는 일 / 코드 구성

사용자의 **개인 데이터 3종**을 관리한다:
- **저장된 검색(saved searches)** — 자주 쓰는 검색어를 저장/재실행 (쿼터 200/인)
- **라이브러리(library)** — 논문을 내 서재에 담기 (쿼터 1000/인)
- **검색 이력(history)** — 내가 한 검색 기록 (최근 500개 유지)

세 갈래로 들어온다: **ⓐ CRUD(직접 요청)** · **ⓑ 이력 적재(U2 이벤트)** · **ⓒ 재실행(게이트웨이 재진입)**.

```
library/
├── controller.py        ← 라우터 3개 (/library/saved-searches · /items · /history)
├── services/
│   ├── saved_search.py  ← 저장된 검색 (쿼터 200)
│   ├── library.py       ← 라이브러리 (쿼터 1000)
│   └── history.py       ← 검색 이력 (적재·조회·재실행·삭제)
├── history_consumer.py  ← ⓑ U2 이벤트를 받는 구독자 입구
├── gateway.py           ← ⓒ 재실행용 게이트웨이 포트 (StubSearchGateway)
├── authz.py             ← ★U3 AuthorizationGuard에 인가 위임
├── validation.py        ← 입력검증·정규화·커서코덱·DTO매핑
├── repository/
│   ├── sql.py           ← PostgreSQL (운영)
│   └── memory.py        ← InMemory (mock-first 기본)
└── audit.py             ← 감사 로그
```

**핵심 불변식 한 줄**: 모든 데이터는 **owner_id로 스코프**(내 것만 보임), 소유권 판정은 **U3에 위임**, 재실행은 **U2 직접 호출 금지**.

---

## 진입: 컨트롤러 — `controller.py`

**[받음]** HTTP 요청.
**[함]** `get_principal(request)` 로 **U6 게이트웨이가 `request.state.principal`에 심어둔** 주인을 꺼낸다.
- **principal 없으면 → 401 (fail-closed, INV-L4).**
**[내보냄]** 서비스 호출 후, 도메인 예외를 HTTP로 매핑(`_to_http`):

| 도메인 예외 | HTTP | 의미 |
|---|---|---|
| `ValidationException` | 422 | 입력 형식 오류 |
| `QuotaExceededError` | 409 | 쿼터 초과 |
| `NotFoundError` | 404 | 없음 |
| `AuthorizationError` + 그 외 | **404** | ★타인 리소스도 404로 일반화 |

라우터 3개 = `routers = (saved_router, library_router, history_router)` → 앱셸이 마운트.

---

## ⓐ CRUD — 동기, owner 스코프

### 예시 1: 라이브러리에 논문 담기 — `services/library.py` `add()`

**[받음]** principal + `{ arXivId, meta }`.
**[함]**
1. `validate_arxiv_id` — arXiv ID 형식 검사(신형 `2401.12345`, 구형 `cs.LG/0701001`, ≤64자).
2. `validate_meta` — 담을 때의 **메타(제목·저자 등)를 검증해 스냅샷 저장**(BR-L5).
3. **멱등 검사**: `find_by_arxiv(owner, arxiv_id)` 이미 있으면 → 기존 것 반환(중복 안 만듦).
4. **쿼터**: `count(owner) >= 1000`(`MAX_LIBRARY_PER_OWNER`) → `QuotaExceededError`(409).
5. `insert` + 감사 로그.

**[내보냄]** `LibraryItemDTO`. 데이터는 **PostgreSQL**(운영) 또는 InMemory(mock).

**[왜 메타 스냅샷?]** *availability isolation* — 담을 때의 제목·저자를 **복사해 저장**하니, 원논문이 사라지거나 바뀌어도 내 서재 카드는 그대로 렌더된다. (검색은 실시간 코퍼스를 보지만, 서재는 내가 담은 순간을 박제.)

### 예시 2: 삭제 — `remove()` (소유권 위임이 보이는 곳)

```python
entity = self._repo.library.get(principal.user_id, item_id)   # owner 스코프로 조회
if entity is None:
    raise NotFoundError("library item not found")             # SEC-9
authorize_owned(principal, Action.DELETE, entity.owner_id)    # ★U3에 위임
self._repo.library.delete(principal.user_id, item_id)
```

`authz.py`의 `authorize_owned`:
```python
if AuthorizationGuard.authorize(principal, action, AccountId(owner_id)) is not Decision.ALLOW:
    raise NotFoundError("resource not found")   # DENY → 404로 일반화
```
**[핵심]** U4는 "이게 내 것인가"를 **스스로 판단하지 않는다.** U3의 `AuthorizationGuard`(인가 단일 권위)에 넘긴다. 거부(또는 잘못된 owner id)면 **403이 아니라 404** — "권한 없음"이 아니라 "없음"으로 일반화해서 **리소스 존재 여부조차 안 흘린다**(SEC-9).

### 목록 조회 — keyset 커서 페이지네이션 (`validation.py` `build_page`)

**[함]**
- `limit + 1` 개를 가져와서, `limit`보다 많으면 "다음 페이지 있음"으로 판단.
- 마지막 행의 `(시각, id)`를 **불투명 커서**(base64로 인코딩)로 만들어 `nextCursor` 반환.
- 정렬은 **최신순**.

**[왜 offset 안 쓰나]** "20개 건너뛰고 다음 20개"(offset) 방식은 데이터가 추가되면 **밀려서 중복/누락**이 생기고, 전체 건수 세는 게 비싸다. keyset = "마지막으로 본 레코드 **다음부터**" → 안정적·빠름. 커서는 base64라 변조하면 422.

---

## ⓑ 검색 이력 적재 — 비동기, 검색 응답 경로 밖

**[받음]** U2가 검색 후 발행한 `SearchExecutedEvent` (`{userId, query, timestamp, resultCount}`).
**[경로]** `U2 → EventBridge → history_consumer.consume → SearchHistoryService.record_search`.

`record_search()` (`services/history.py`):
```python
key = dedupe_key(owner, event.timestamp, event.query)   # sha256(owner|시각|query)
if repo.find_by_dedupe_key(owner, key) is not None:
    return None                                          # ★중복 재배달 → no-op
entity = HistoryEntry(..., dedupe_key=key)
repo.insert(entity)
repo.prune_to(owner, RETENTION_LIMIT)                    # 최근 500개만 유지
```

**[왜 dedupe_key?]** 이벤트 버스는 **at-least-once**(최소 한 번 — 같은 이벤트가 두 번 올 수 있음). `owner|시각|query`의 sha256 해시를 키로 써서, 같은 검색이 두 번 배달돼도 **딱 한 번만** 기록(exactly-once 효과, INV-L3).

**[왜 비동기?]** 이력 저장이 **검색 응답을 막으면 안 된다**(P50<3s). 그래서 U2의 동기 응답 경로 **밖**에서 이벤트로 처리. (U2 ⑨ "fire-and-forget"의 받는 쪽이 여기.)

---

## ⓒ 재실행 — 게이트웨이 재진입 (백도어 금지, INV-L2)

저장된 검색이나 이력을 다시 돌릴 때 (`saved_search.rerun` / `history.rerun`):

```python
authorize_owned(principal, Action.RERUN, entity.owner_id)   # 소유권 확인
return await self._gateway.search(entity.query, principal)  # ★게이트웨이로 재진입
```

**[핵심]** 재실행은 **U2를 직접 부르지 않는다.** `SearchGatewayPort`를 통해 **U6 게이트웨이 → U2** 로 다시 들어간다.

**[왜?]** 그래야 매 재실행마다 **비용 가드(U6)와 근거화 enforce(U6)가 다시 적용**된다. U2를 직접 부르면 그 검문을 **우회하는 백도어**가 되니까. — 지금은 `StubSearchGateway`(빈 결과 반환하는 자리표시)이고, 실제 U6 결선은 **같은 포트 뒤에서** 교체되어 U4 코드는 안 바뀐다.

---

## 정리: 멱등·쿼터·정규화 한눈에

| | 멱등 기준 | 쿼터/유지 | 정규화 |
|---|---|---|---|
| **저장된 검색** | (owner, **정규화 쿼리**) | 200/인 | NFC+공백정리+casefold |
| **라이브러리** | (owner, **arxiv_id**) | 1000/인 | NFC+strip(버전 보존) |
| **검색 이력** | **dedupe_key**(sha256) | 최근 500 | — |

---

## 한 장 요약

```
ⓐ CRUD (동기, owner 스코프)
  U5 → U6(principal 주입) → controller.get_principal (없으면 401)
     → Service.add/list/remove/save/delete
        · 멱등 검사 → 쿼터 검사 → insert + 감사로그
        · mutate 시 authorize_owned → U3 AuthorizationGuard (타인/부재 → 404)
        · list = keyset 커서(limit+1, 불투명 base64, 최신순, offset 없음)
     → PostgreSQL (운영) / InMemory (mock)

ⓑ 이력 적재 (비동기, 검색 응답 밖)
  U2 → EventBridge → history_consumer → record_search
     · dedupe_key(sha256) 멱등 → insert → prune_to(500)

ⓒ 재실행 (백도어 금지, INV-L2)
  controller → SearchGatewayPort.search(query, principal)
     · U2 직접호출 금지 → U6 게이트웨이 재진입 → U2 (비용·근거화 재적용)
     · 현재 StubSearchGateway 자리표시
```

**연결고리**: ⓑ의 입력은 **U2 ⑨**가 발행한 이벤트, 인가는 **U3 AuthorizationGuard**, ⓒ는 **U6 게이트웨이**로 재진입 → 지금까지 배운 U2·U3·U6가 여기서 다 만난다.
```
