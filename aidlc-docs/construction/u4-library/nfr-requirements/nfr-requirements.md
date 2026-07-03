# nfr-requirements.md — U4 Library NFR 요구사항 정의서

**단계**: CONSTRUCTION → NFR Requirements (유닛별 루프, Track 2 두 번째이자 마지막 유닛) · **유닛**: U4 Library · **일자**: 2026-06-17
**근거(SSOT)**: `u4-design-brief.md`(D1~D12·BR-L1..L10·INV-L1..L4·PBT-09 반영) · `inception/requirements/requirements.md`(NFR-P1/QT-4 전역 상속) · `construction/u3-accounts/**`(템플릿·SEC-8 단일 권위 상속) · `construction/shared/{dtos.md §3, events.md §2}`(공용 계약)

> **유닛 성격**: U4는 **소유자 사설(owner-private) 동기 CRUD + 단일 이벤트 소비** 모듈입니다 (검색 저장·라이브러리·이력). U3가 확립한 인증/세션/인가(SEC-8 단일 권위) 위에 얹히며, **새로운 임베딩·LLM·인덱스 호출을 일절 추가하지 않습니다**(NFR-C1). 따라서 본 정의서의 핵심은 ① 동기 READ 경로의 가벼운 레이턴시 예산(NFR-P1), ② U2/인덱스로부터의 가용성 격리(NFR-R2), ③ 신규 비용 제로(NFR-C1), ④ U3 권위에 위임하는 보안 매핑(SEC), ⑤ 멱등성 보장(QT-4)입니다.

---

## 1. 성능 요구사항 (Performance Requirements)

### 1.1. 동기 CRUD 읽기 레이턴시 예산 (NFR-P1)
전역 NFR-P1은 사용자向 동기 디스커버리 READ에 대해 **종단 P50 < 3s, P95 < 8s**를 규정합니다 (`requirements.md` §NFR-P1, LLM 인-루프·콜드 스타트 영향 포함). U4의 소유자 범위 컬렉션 조회(list)와 단건 조회(get)는 **임베딩·LLM·인덱스 호출이 없는 순수 CRUD READ**이므로, 이 동기 예산을 **여유 있게 하회**해야 합니다 (Q-성격 반영).

- **대상 연산**: `GET /library/saved-searches`, `GET /library/items`, `GET /library/history` (페이지네이션 list) 및 향후 단건 조회 경로 — 모두 `UserDataRepository`의 **owner-scoped keyset 조회**(INV-L1, D8).
- **지표** (동기 READ, 게이트웨이·네트워크 제외 모듈 내부 처리):
  - **P50 Latency**: **30ms 미만**
  - **P99 Latency**: **150ms 미만**
- **제약**:
  - 한 페이지 조회는 단일 owner-scoped keyset 질의(`limit` 기본 20·최대 100, D8)로 완결하며, full-scan·N+1·교차 owner 조회를 발생시키지 않습니다.
  - 커서는 불투명 URL-safe base64(`{"ts", "id"}`, D8)로 서버 측 상태 없이 디코드/검증되어야 하며, 디코드 비용은 상수 시간입니다.
  - LLM/임베딩/외부 인덱스 호출이 없으므로(NFR-C1) 콜드 스타트·모델 워밍 가정이 적용되지 않습니다 — 본 예산은 콜드 스타트 **제외** 모듈 내부 처리 기준입니다.

### 1.2. 이력 WRITE 비차단 (off the sync path)
검색 이력 기록은 **공개 POST가 아니라 `SearchExecutedEvent` 소비**로 수행됩니다 (브리프 §6·§8, events.md §2 🔒FROZEN). 이 쓰기는 **동기 검색 READ 경로 밖**에서 일어나며, 검색 응답을 절대 블로킹하지 않습니다 (events.md §2 "P50<3s 동기 검색 경로 밖").

- **비차단 보장**: `U2.SearchOrchestrationService.publishSearchExecuted`는 성공 응답 **직후** 이벤트 백본에 fire-and-forget으로 발행하고, `U4.SearchHistoryService.recordSearch`는 이를 비동기 구독·기록합니다. 이력 기록 실패·지연은 검색 사용자 경험에 영향을 주지 않습니다.
- **전달 보장 → 멱등**: 백본은 **at-least-once** 전달을 전제하므로, 소비자는 **멱등 기록**해야 합니다 (`dedupe_key = sha256(owner_id|requestId|query)`, D7/BR-L7/INV-L3 — §5.4 참조). 재전달 시 중복 행을 생성하지 않습니다.
- **레이턴시 비목표(non-goal)**: 이력 기록은 동기 SLA 대상이 아니며, 백본 전달 지연(consumer lag)은 NFR-P1 예산에 산입하지 않습니다. 사용자가 새 이력을 조회 시점에 보지 못할 수 있는 결과적 일관성(eventual consistency)은 허용됩니다.

### 1.3. rerun 경로의 레이턴시 귀속
저장 검색/이력 항목의 rerun(`POST /{id}/rerun`)은 **직접 U2 호출이 아니라 `SearchGatewayPort`(게이트웨이-프런티드 검색 계약, U6→U2)를 경유**합니다 (D9/BR-L9/INV-L2). 따라서 rerun의 종단 레이턴시는 **U4가 아니라 게이트웨이-프런티드 검색의 NFR-P1(P50<3s, P95<8s)에 귀속**됩니다. U4 자신의 기여분은 저장 query 해석 + 포트 호출의 상수 시간 오버헤드(§1.1 CRUD 예산 내)로 한정합니다. U4는 `StubSearchGateway`(결정적 플레이스홀더)를 기본 제공하며, 실제 바인딩은 U6/Infra를 기다립니다.

---

## 2. 확장성 및 부하 요구사항 (Scalability Requirements)

U4는 **무상태(stateless) 모듈**이며, 모든 질의는 **owner-scoped**이고, 사용자당 데이터는 **유한 보존·쿼터**로 경계가 잡힙니다. 따라서 확장성은 사용자 수에 선형이고, 단일 사용자의 데이터가 무한히 커지지 않습니다.

- **무상태성**: 컨트롤러·서비스는 요청 간 세션 상태를 보유하지 않습니다. 인증 컨텍스트(`Principal`)는 `request.state.principal`(U6 게이트웨이가 주입)에서 매 요청 획득합니다 (D11). 수평 확장 시 어떤 인스턴스로 라우팅되어도 동일하게 동작합니다 — U3 세션 스토어(ElastiCache)와 영속(RDS PostgreSQL, D10 상속)이 상태를 보유하고 모듈 자체는 stateless입니다.
- **owner-scoped 질의**: 모든 repository read/write는 `owner_id`로 구조적으로 필터링되어(INV-L1) 단일 사용자 파티션 내에서 keyset 페이지네이션(D8)으로 완결합니다 — 전역 스캔이 없으므로 사용자 수 증가가 단건 조회 비용을 키우지 않습니다.
- **유한 보존·쿼터로 경계화된 데이터량**(사용자당 상한):
  - **저장 검색**: 최대 **200건/owner** (D2/BR-L2, 초과 시 `QuotaExceededError` → HTTP 409).
  - **라이브러리**: 최대 **1000건/owner** (D4/BR-L4, 초과 시 409).
  - **검색 이력**: 롤링 **최근 500건/owner** (D6/BR-L6, 초과 기록 시 가장 오래된 항목 prune; `clearHistory`로 전체 삭제).
- **스토리지 용량 추정**: 위 상한과 `LibraryItemMeta` 스냅샷 바운드(title ≤500, authors ≤50×≤200, abstract_snippet ≤1000 — 브리프 §2)에 따라 사용자당 라이브러리 스냅샷이 지배적이며, 1차 프로덕션 타깃(최대 1,000명 활성 사용자, U3 §2 상속) 규모에서 RDS PostgreSQL 단일 인스턴스(D10, U3 RDS 상속)로 충분합니다.
- **처리량**: U4 CRUD는 U3 세션 검증(≥100 RPS, U3 §2)이 선통과한 인증된 요청만 처리하며, owner-scoped 인덱스 조회로 동일 처리량을 지연 없이 소화합니다.

---

## 3. 가용성 및 복원력 요구사항 (Availability & Resilience)

### 3.1. 메타 스냅샷 가용성 격리 (NFR-R2)
U4 라이브러리는 **U2/검색 인덱스의 가용성과 독립적으로 동작**해야 합니다. 라이브러리 항목은 추가 시점에 검증된 `LibraryItemMeta` **스냅샷을 보존**하며(D5/BR-L5), 조회 시 이를 **그대로 반환**할 뿐 **U2/인덱스에서 재페치하지 않습니다** (브리프 §2 "availability isolation"; dtos.md §3 "보존 메타 스냅샷만 반환(가용성 격리)").

- **격리 불변식**: U2(검색)·OpenSearch 인덱스·Cohere 임베딩 서비스가 전면 장애 상태여도, 사용자의 저장 검색 목록·라이브러리 카드·검색 이력 **조회와 삭제는 정상 동작**해야 합니다. 라이브러리 카드는 `LibraryItemMeta`(U2 ResultCardVM 카드 필드를 미러 — title·authors·year·arxivId·abstractSnippet·arxivUrl, 브리프 §2)만으로 라이브 인덱스 없이 렌더링됩니다.
- **부분 저하(graceful degradation)**: U2/게이트웨이 장애 시 **degrade되는 것은 rerun(신규 검색 실행)뿐**입니다 — rerun은 `SearchGatewayPort` 경유이므로(D9), 게이트웨이/U2 불가용 시 rerun만 일반화 에러로 실패하고, 나머지 CRUD READ/DELETE는 영향받지 않습니다.
- **가용성 목표**: 영속(RDS PostgreSQL, D10·U3 TD-U3-3 상속)의 멀티 AZ 고가용성 구성을 준수합니다 — **99.99%**.
- **백업/복구 목표** (U3 자격증명 데이터 가용성 정책 상속):
  - **RPO**: 24시간 이내 (매일 스냅샷 및 증분 백업).
  - **RTO**: 4시간 이내 (재해 복구 시나리오 준수).

### 3.2. 이력 소비의 복원력
이력 쓰기는 at-least-once 백본 위에서 동작하므로(events.md §2), 소비자 측 **멱등 기록(INV-L3)**과 **롤링 보존 prune(D6)**으로 복원력을 확보합니다.

- **중복 재전달 내성**: 동일 이벤트 재수신 시 `dedupe_key`로 정확히-한-번(exactly-once) 행을 보장합니다 (D7/BR-L7).
- **소비 실패 격리**: 이력 소비 경로의 일시 장애는 동기 검색·U4 CRUD READ에 영향을 주지 않습니다(§1.2 비차단). 백본 재전달로 복구되며, prune 정책이 무한 적재를 방지합니다.

### 3.3. fail-closed 복원력 (SEC-15 / INV-L4)
인가·principal 획득·repository 접근 등 어떤 예외도 **항상 거부 방향(fail-closed)**으로 귀결합니다 — 교차 소유/누락 리소스는 **404 NotFound로 일반화**(SEC-9, 존재 미노출), 세션 부재는 **401**, 알 수 없는 예외는 **500(일반화 메시지)**. 절대 fail-open하지 않습니다 (INV-L4/SEC-15, U3 SEC-15 정책 상속).

---

## 4. 비용 요구사항 (Cost Requirements)

### 4.1. 신규 비용 제로 (NFR-C1)
U4는 **순수 CRUD 모듈로서 임베딩·LLM·외부 추론 호출을 일절 수행하지 않으므로, 신규 가변 비용(per-call AI 비용)을 추가하지 않습니다** (브리프 D9·NFR-C1; 멱등 디덥은 인제스천 NFR-C1과 동궤).

- **무 AI 호출**: 저장/추가/이력 기록·조회·삭제·rerun 어디에서도 U4가 직접 임베딩/LLM을 호출하지 않습니다. rerun은 게이트웨이-프런티드 검색(U6→U2) 경유이므로, **검색 비용·근거화 후크는 U2/게이트웨이 경계에서 기존 정책대로 재적용**되며 U4가 우회(백도어)하지 않습니다 (INV-L2/D9) — 즉 rerun 비용은 U4 신규 비용이 아니라 U2 검색 비용에 귀속됩니다.
- **고정 비용 한도 내**: U4의 비용 기여는 RDS PostgreSQL(D10·U3 상속) 스토리지·IOPS의 한계 증분(사용자당 유한 쿼터·보존, §2)뿐이며, 전역 월 $1600 비용 상한(프로젝트 cap) 내 무시 가능한 증분으로 설계합니다.
- **멱등 디덥의 비용 효과**: 저장 검색 디덥(D1), 라이브러리 멱등 추가(D3), 이력 멱등 기록(D7)은 중복 행·중복 처리를 제거해 스토리지·쓰기 비용을 추가로 절감합니다(QT-4와 정렬).

---

## 5. 보안 및 위협 모델링 요구사항 (Security Requirements)

U4는 **자체 인증/인가 권위를 두지 않고 U3에 위임**합니다 — U3가 SEC-8의 단일 권위(`AuthorizationGuard`)입니다. U4의 보안은 ① 위임(SEC-8), ② 비노출(SEC-9), ③ 입력 검증(SEC-5), ④ 감사(SEC-13)의 매핑으로 구성됩니다.

### 5.1. 인가 위임 (SEC-8)
- 모든 소유권 결정은 `AuthorizationGuard.authorize(principal, action, AccountId(owner_id))`로 **U3 단일 권위에 위임**합니다 (D11, `backend.modules.accounts.guard` 재사용 — U4는 `Principal/Action/AccountId/Decision`을 재정의하지 않음, 브리프 §2).
- **데이터 계층 백스톱(INV-L1)**: 인가 결정과 별개로, 모든 repository read/write는 `owner_id`로 구조적 필터링되어 다른 owner의 행을 절대 반환하지 않습니다 — 심층 방어(defense-in-depth).
- `Principal`은 `get_principal` 의존성이 `request.state.principal`(U6 게이트웨이 미들웨어 주입)에서 획득하며, 부재 시 **401**을 발생시킵니다 (D11). 테스트/standalone은 이 의존성을 override합니다.

### 5.2. 비노출 / 존재 미노출 (SEC-9)
- 와이어 DTO는 **owner `userId`를 절대 싣지 않으며**, 교차 소유 또는 누락 리소스 접근은 **403이 아니라 404 NotFound로 일반화**합니다 (D11/INV-L4 — 존재 미노출).
- **내부 필드 비직렬화**: `owner_id`, `dedupe_key`, `normalized_query`, 내부 점수, 감사 메타는 어떤 응답에도 직렬화되지 않습니다 (dtos.md §4 비노출 규약 준수).

### 5.3. 입력 검증 (SEC-5)
모든 쓰기 입력은 `UserDataDTOAndValidation`에서 검증 후 매핑되며, 위반은 **422 + 일반화 메시지**로 거부합니다 (브리프 §SEC-5).
- `query` ≤ 500자, `label` ≤ 200자.
- `arxiv_id`: `^\d{4}\.\d{4,5}(v\d+)?$` 또는 레거시 `^[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?$`.
- `limit`: 1..100 (>100 → **REJECT 422**, 명시성 위해 clamp 아닌 reject 선택, D8).
- `cursor`: 변조/garbage 커서 → **422** (D8).
- `meta`(`LibraryItemMeta`): title 필수·≤500, authors ≤50개·각 ≤200, year 1900..2100, abstract_snippet ≤1000 (브리프 §2 바운드).
- **공용 SSOT 비포크**: 와이어 DTO는 `docsuri_shared.dtos`에서 import하며 재정의하지 않습니다 (브리프 §5 — U3가 범한 SSOT 포크 결함 회피). §3 정제(최대 limit 100·typed meta·string id·cursor 의미)는 U4 **자체 검증 계층**에서 강제해, 재생성 바인딩 설치 여부와 무관하게 정확합니다.

### 5.4. 멱등성 (QT-4)
전역 QT-4(PBT 멱등 불변식)를 U4의 3개 멱등 표면에 매핑합니다:
- **저장 검색 디덥(D1/BR-L1)**: `(owner_id, normalized_query)` 유일. `normalized_query` = NFC → strip → 내부 공백 축약 → casefold. 재저장은 멱등(기존 SavedSearch 반환, 새 non-null label 시 갱신, `created_at` 불변).
- **라이브러리 멱등 추가(D3/BR-L3)**: `(owner_id, arxiv_id)` 멱등. 재추가는 기존 LibraryItem 동형 반환(200), 저장된 meta 스냅샷을 덮어쓰지 않음.
- **이력 멱등 소비(D7/BR-L7/INV-L3)**: `dedupe_key`로 at-least-once → exactly-once 행. 재전달이 중복 행을 만들지 않음.
- **PBT-09(차단성, U4 컴포넌트-메서드 고정)**: 임의의 유효 도메인 엔티티에 대해 `to_dto(entity)` 후 공용 DTO 검증이 안정적이고, 유효 create DTO의 `validate_and_map`이 공개 필드를 라운드트립하며 **내부 필드를 절대 누출하지 않음**(serialize→deserialize 공개 필드 보존). Hypothesis로 구현 (브리프 §4).

### 5.5. 감사 (SEC-13)
- 서비스는 변경 연산(save/delete, add/remove, clear)에서 **`AuditSink` 포트로 감사 이벤트를 발행**합니다 (D12/BR-L10). 기본 구현은 in-memory/no-op이며 실제 결선은 U6/ops로 연기됩니다.
- 감사 페이로드에는 민감·내부 필드를 포함하지 않습니다 (SEC-9 — owner 점수·디버그·자격증명 절대 미포함).

### 5.6. 전송 보안 (SEC-1, 상속)
모든 U4 API 호출은 U3와 동일하게 **TLS 1.2+ (HTTPS)** 상에서만 수행됩니다 (U3 SEC-1 상속, 게이트웨이 경계 종단).

---

## 6. 트레이스 요약 (Traceability)

| NFR ID | 요구사항 | 근거 결정/규칙 | 공용 계약 |
|---|---|---|---|
| **NFR-P1** | 동기 CRUD READ 예산(P50<30ms·P99<150ms, 전역 P50<3s 하회); 이력 WRITE 비차단·off sync path | D8, BR-L7/INV-L3, events.md §2 | `PageParams`, `SearchExecutedEvent` |
| **NFR-R2** | 메타 스냅샷 가용성 격리(U2/인덱스 독립); rerun만 degrade | D5/BR-L5, D9/INV-L2 | `LibraryItemDTO.meta`, `SearchResultSetDTO` |
| **NFR-C1** | 신규 비용 제로(임베딩/LLM 미호출, CRUD only); rerun 비용은 U2 귀속 | D9/INV-L2, D1/D3/D7(디덥 절감) | `SearchGatewayPort`(게이트웨이-프런티드) |
| **SEC-8** | 인가 위임(U3 `AuthorizationGuard` 단일 권위) + owner-scoping 백스톱 | D11, INV-L1 | `Principal`/`Action`/`AccountId`(U3 재사용) |
| **SEC-9** | 비노출(owner userId·내부 필드 미직렬화) + 교차 소유 404 일반화 | D11, INV-L4 | `SavedSearchDTO`/`LibraryItemDTO`/`HistoryEntry` (dtos.md §3/§4) |
| **SEC-5** | 입력 검증(query/label/arxiv_id/limit/cursor/meta 바운드, 422 일반화) | D8, §2 meta 바운드 | `SavedSearchCreateDTO`/`LibraryItemCreateDTO`, `LibraryItemMeta`(U4 내부) |
| **SEC-13** | 감사(`AuditSink` 변경 연산 발행, 민감/내부 비노출) | D12/BR-L10 | (U6/ops 결선 예정) |
| **QT-4** | 멱등(저장 디덥·라이브러리 추가·이력 소비) + PBT-09 라운드트립 | D1/D3/D7, BR-L1/L3/L7, INV-L3, PBT-09 | `docsuri_shared.dtos`(SSOT 비포크) |
| 확장성 | 무상태 모듈·owner-scoped 질의·유한 보존/쿼터 | D2/D4/D6, INV-L1, D10 | `PageParams`(keyset D8) |

---

## 7. 비목표 및 가정 (Non-goals & Assumptions)

- **비목표**: U4는 자체 인증/세션/CAPTCHA/이메일 인프라를 두지 않습니다(U3 소관). 검색 실행 자체(랭킹·근거화·임베딩)는 U2 소관이며 U4는 rerun을 게이트웨이로 위임만 합니다.
- **가정(상속 결정)**:
  - 언어/런타임 **Python 3.12+**, PBT 프레임워크 **Hypothesis** (U3 TD-U3-1/TD-U3-6 상속).
  - 영속 **RDS PostgreSQL** (U3 TD-U3-3 상속); U4는 포트 기반으로 기본 `InMemoryUserDataRepository`(앱-셸 무-DB 마운트·테스트 그린) + `SqlUserDataRepository`(프로덕션) 제공 (D10).
  - `SearchExecutedEvent` 형상은 🔒FROZEN(events.md §2) — U4는 소비자로서 멱등 기록만.
  - `SearchGatewayPort` 실 바인딩은 U6/Infra 대기; U4는 `StubSearchGateway` 결정적 플레이스홀더 제공 (D9).
