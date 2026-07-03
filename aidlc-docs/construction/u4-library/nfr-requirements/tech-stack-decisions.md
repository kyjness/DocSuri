# tech-stack-decisions.md — U4 Library 기술 스택 결정 (ADR, 프로덕션)

**단계**: CONSTRUCTION → NFR Requirements · **유닛**: U4 Library (검색 저장·라이브러리·이력) · **트랙**: Track 2(@revenantonthemission) · **일자**: 2026-06-17
**근거(SSOT)**: U4 설계 브리프(D1~D12·BR-L1..L10·INV-L1..L4) · FD 산출물 · U3 `tech-stack-decisions.md`(TD-U3-1/3/6 [상속]) · `construction/shared/dtos.md` §3·§1.1 · `shared/events/search-executed.schema.json` · `backend/pyproject.toml`(선언된 의존성) · `backend/wiring.py`(마운트 시임) · `backend/modules/accounts/`(코드 템플릿)
**스코프**: 단일 프로덕션 트랙(Track 2 최종 유닛). 태그 규약 —
- `[전역 계승]` = 시스템(§5) 또는 U1이 PIN한 결정 상속 (재결정 아님).
- `[U3 계승]` = U3 Accounts가 확정한 결정 상속 (Track 2 선행 유닛, 재결정 아님).
- `[backend-shared]` = backend app-shell 공유 결정 (소유자 합의 — CG-1 등).
- (무태그) = **U4 고유** 결정.

> 형식: 결정 · 근거 · 대안 · 전환 비용. 수치 임계(쿼터·보존·페이지 한도)·DDL·CI/CD·배포 타깃은 NFR Design/Infra에서 구체화한다. 본 문서는 "무엇을·왜"이고, 임계/스키마 SQL의 "정확한 값"은 nfr-design/infrastructure-design 산출물이 SSOT다.

---

## TD-U4-1 [전역 계승] — 언어 및 런타임: **Python 3.12+**
- **결정**: 모듈형 모놀리스 API 배포 단위(①)의 시스템 결정(§5)에 따라 backend 언어를 Python으로 상속한다. U4 코드는 `backend.modules.library` 패키지 네임스페이스에 위치한다 (accounts와 동일 규약).
- **근거**: U1/U2/U3/U6와 동일 단일 런타임 — 모듈 간 직접 호출(예: `backend.modules.accounts.guard` 재사용) unblocked. timezone-aware UTC datetime(`datetime.now(UTC)`) 규약 상속(`datetime.utcnow()` 폐기 회피).
- **전환 비용**: 시스템 전역 — 재논의 아님.

---

## TD-U4-2 [backend-shared] — API 웹 프레임워크: **FastAPI (CG-1)**
- **결정**: U4의 3개 컨트롤러(SavedSearchController · LibraryController · SearchHistoryController)는 모두 FastAPI `APIRouter`로 구현하며, app-shell이 `create_app`에서 라우터를 선택적으로 마운트한다. async 엔드포인트 + `Depends` 기반 DI.
- **근거**: **CG-1 = backend 웹 프레임워크 = FastAPI**는 app-shell 소유자(현 Track 2 @revenantonthemission)가 확정한 공유 결정으로, `backend/pyproject.toml`에 `fastapi>=0.110`이 이미 선언됨. shared/python 바인딩이 **pydantic v2** → 요청/응답 DTO 검증·직렬화 무드리프트; 자동 OpenAPI 스키마; U2/U3 모듈과 동형 라우터/DI 결선.
- **대안**: 없음 — backend 단일 런타임의 기확정 공유 결정이므로 U4가 재결정하지 않는다.
- **전환 비용**: backend 전 모듈 공유 — 변경 시 광범위(따라서 U4 단독 변경 대상 아님).

---

## TD-U4-3 [U3 계승] — 영속성 엔진: **Amazon RDS (PostgreSQL)**
- **결정**: U4의 프로덕션 영속화 백엔드는 U3가 확정한 **Amazon RDS (PostgreSQL)**를 상속한다 (TD-U3-3). U4는 RDS에 owner-scoped 테이블(saved_searches · library_items · search_history)을 추가하며, 인덱스명·샤드·인스턴스 클래스는 Infra에서 확정한다.
- **근거**:
  - 관계형 ACID 트랜잭션으로 쿼터 강제(BR-L2 200 / BR-L4 1000) 시의 count-then-insert 경합과 멱등 upsert(BR-L1·L3)를 정합성 있게 처리한다.
  - **Unique 제약**으로 도메인 멱등성을 데이터 계층에서 backstop한다: `(owner_id, normalized_query)` (D1/BR-L1), `(owner_id, arxiv_id)` (D3/BR-L3), `(owner_id, dedupe_key)` (D7/BR-L7·INV-L3 — at-least-once → exactly-once row).
  - 모든 쿼리가 owner_id로 구조적 필터링(INV-L1) → 관계형 인덱스 친화적.
- **대안**: 전용 세션/캐시 스토어(ElastiCache Redis — U3가 세션용으로 채택)는 U4 도메인 데이터에는 불필요(영속·관계형 무결성 요구). DynamoDB(쿼터 카운트·NFC 정규화 키 유니크 강제가 관계형 대비 번거로움).
- **전환 비용**: 낮음 — 영속화는 포트(TD-U4-4) 뒤에 캡슐화되어 엔진 교체가 어댑터 교체로 국소화됨.

---

## TD-U4-4 — 영속성 접근 패턴: **포트 기반 리포지토리 — `InMemoryUserDataRepository`(기본) + `SqlUserDataRepository`(프로덕션 scaffold)**
- **결정** (D10·INV-L1): `UserDataRepository`를 `typing.Protocol` 포트로 정의하고(3개 서브-리포지토리 집약), **두 어댑터**를 제공한다.
  - **`InMemoryUserDataRepository` = 기본(mock-first)** — app-shell이 **라이브 DB 없이** 마운트되고 테스트가 그린으로 통과하도록 한다 (discovery의 mock-first 자세와 동형).
  - **`SqlUserDataRepository` = 프로덕션 scaffold** — SQLAlchemy 모델 + 구현. 실 결선은 Infra/배포 시.
  - **DDL 마이그레이션 SQL** — `migrations/001_create_library_tables.sql`로 동봉(3개 테이블 + 위 Unique 제약).
- **근거**:
  - **가용성 격리·CI unblock**: app-shell(`backend/wiring.py::_mount_library`)이 인메모리 싱글톤을 주입해 PostgreSQL 없이도 마운트 — "마운트되려면 라이브 인프라가 필요"한 결합을 끊는다.
  - **owner-scoping backstop(INV-L1·SEC-8)**: 두 어댑터 모두 read/write를 `owner_id`로 구조적 필터링 → AuthorizationGuard 결정 하위의 방어심층(defense-in-depth). 한 owner의 쿼리가 타 owner 행을 반환할 수 없다.
  - 동일 포트 뒤 두 구현으로 PBT-09(DTO 라운드트립)·쿼터·멱등 속성을 어댑터 무관하게 검증.
- **대안**: 단일 SQL 전용 구현(테스트/마운트에 라이브 DB 강제 → U2/U3 mock-first 규약 위반). Repository 추상 없는 직접 ORM 호출(교체·테스트성 저하).
- **전환 비용**: 낮음 — 포트 계약 고정 시 어댑터 추가/교체는 국소적.

---

## TD-U4-5 [U3 계승] — ORM / 데이터 매퍼: **SQLAlchemy 2.x**
- **결정**: `SqlUserDataRepository`의 관계형 매핑은 **SQLAlchemy 2.x**로 구현한다 (`backend/pyproject.toml`에 `sqlalchemy>=2.0,<3` 이미 선언 → **신규 서드파티 의존성 없음**).
- **근거**: U3가 RDS PostgreSQL 접근에 사용하는 동일 스택 상속 → backend 동형성. 2.x typed `Mapped[...]` 선언으로 도메인 엔티티(SavedSearch·LibraryItem·HistoryEntry)와 테이블 매핑. 트랜잭션 경계 안에서 쿼터 count + insert를 원자적으로 수행.
- **대안**: 원시 SQL(`asyncpg` 직접) — 멱등 upsert·Unique 충돌 처리는 가능하나 매핑/마이그레이션 일관성·타 모듈과의 패턴 정합 저하. 별도 ORM(SQLModel/Tortoise) — 신규 의존성 도입(거부, TD-U4-9).
- **전환 비용**: 낮음 — `SqlUserDataRepository` 내부에 한정(포트 외부 무영향).

---

## TD-U4-6 — 페이지네이션 커서 코덱: **표준 라이브러리 `base64`(URL-safe) + JSON keyset 커서**
- **결정** (D8·BR-L8): 커서 기반 keyset 페이지네이션(most-recent-first). `cursor`는 `{"ts": <정렬 인스턴트 iso>, "id": <id>}`를 JSON 직렬화 후 **URL-safe base64**로 인코딩한 불투명 토큰. 인코딩/디코딩은 Python **표준 라이브러리 `base64`**(+ `json`)만 사용한다. `limit` 기본 **20** · **최대 100**(>100 → 422 REJECT, 명시성 우선) · 첫 페이지는 `cursor` 생략 · 마지막 페이지는 `nextCursor` 부재 · 변조/깨진 커서 → **422**.
- **근거**: 커서는 **불투명 페이로드 인코딩**일 뿐 보안 토큰이 아니므로(서명/암호화 불요 — 변조는 keyset 디코드 실패로 422 처리) 표준 라이브러리로 충분 → **신규 의존성 0**. keyset(오프셋 아님)으로 most-recent-first 안정 순회(advisory cursor property: limit L로 전 항목을 정확히 1회·누락/중복 없이 수집).
- **대안**: 오프셋 페이지네이션(대형 목록에서 일관성·성능 저하). 서명 커서(JWT/HMAC — 보안 토큰 아니므로 과설계). 외부 페이지네이션 라이브러리(신규 의존성, 거부).
- **전환 비용**: 낮음 — 커서 코덱은 `UserDataDTOAndValidation`(`validation.py`)에 캡슐화.

---

## TD-U4-7 [U3 계승] — 인가(Authorization): **`backend.modules.accounts.AuthorizationGuard`에 위임 (U3 단일 권위, SEC-8)**
- **결정** (D11·INV-L4·SEC-8·SEC-9): U4는 자체 인가 로직을 정의하지 않는다. 소유권 결정은 전적으로 `AuthorizationGuard.authorize(principal, action, AccountId(owner_id))`에 위임한다. `Principal / Action / AccountId / Decision`은 `backend.modules.accounts.models` + `...guard`에서 **재사용**(재정의 금지).
  - 컨트롤러는 `get_principal` 의존성으로 `request.state.principal`(U6 게이트웨이 미들웨어가 세팅)을 읽고, 부재 시 **401**. 테스트/standalone은 의존성 오버라이드.
  - cross-owner OR principal 부재 → DENY → **HTTP 404 NotFound**로 일반화(SEC-9 존재 비노출). 알 수 없는 오류 → fail-closed(500).
- **근거**: **SEC-8 단일 인가 권위** — U3가 시스템 인가 SSOT이므로 U4가 별도 가드를 만들면 권위 분기(U3가 회피하려던 결함의 재현). INV-L4 fail-closed: 어떤 authz/principal 오류도 DENY → 404(리소스)/401(세션 없음), 절대 fail-open 아님(SEC-15).
- **대안**: U4 자체 ownership 체크(거부 — 권위 분기·SEC-8 위반). 게이트웨이 단독 인가(데이터 계층 backstop INV-L1 상실).
- **전환 비용**: 낮음 — accounts 모듈 import. 단 accounts 가드 API 변경 시 동반 영향(동일 backend라 결선 가능).

---

## TD-U4-8 — 재실행(rerun) 경로: **`SearchGatewayPort` 경유 (게이트웨이-fronted) + `StubSearchGateway`**
- **결정** (D9·INV-L2·BR-L9): saved-search/history rerun은 **U2를 직접 호출하지 않는다**. `SearchGatewayPort`(`search(query, principal) -> SearchResultSetDTO`)를 통해 게이트웨이-fronted 검색 계약(U6 ApiGatewayMiddleware → U2)으로 재진입한다 → 비용·근거화 hook 재적용(백도어 없음). U4는 `StubSearchGateway`(결정적 placeholder)를 동봉하고, 실 바인딩은 U6/Infra에서 주입.
- **근거**: **INV-L2 no-rerun-backdoor** — rerun이 저장된 query를 해석한 뒤 포트로 호출하므로, 신규 검색과 동일한 비용 게이트/근거화 hook을 통과한다. U2 직접 import는 격리·비용 통제·근거화를 우회(금지).
- **대안**: U2 서비스 직접 호출(거부 — INV-L2 위반, 비용/근거화 우회). 클라이언트가 query만 받아 별도 검색 호출(서버 계약 일관성·감사성 저하).
- **전환 비용**: 낮음 — 포트 뒤 추상. 실 게이트웨이 결선은 U6 통합 시점.

---

## TD-U4-9 [전역 계승] — 빌드/의존성: **신규 서드파티 의존성 0 (모노레포 `backend/`)**
- **결정**: U4는 **신규 런타임 서드파티 의존성을 도입하지 않는다.** 사용 라이브러리(`fastapi`·`sqlalchemy`·`pydantic`)는 `backend/pyproject.toml`에 **이미 선언**되어 있고, 커서 코덱·SEC-5 검증은 표준 라이브러리(`base64`·`json`·`hashlib`·`unicodedata`·`re`)로 충족한다. `hashlib.sha256`으로 `dedupe_key`(D7) 생성.
- **근거**: U1(`ingestion/`)·U2(`discovery/`)·U3(`accounts/`)와 동형 공급망 자세(SEC-10) — 추가 의존성 0으로 SCA/SBOM 표면 무증가. backend 모노레포 단일 락파일 정합.
- **대안**: 페이지네이션/커서/검증 전용 라이브러리 도입(거부 — 표준 라이브러리로 충분, 공급망 표면 증가).
- **전환 비용**: 해당 없음(추가 없음).

---

## TD-U4-10 [U3 계승] — PBT 프레임워크: **Hypothesis** (dev 의존성)
- **결정** (PBT-09): DTO 라운드트립 속성 검증을 위해 Python **Hypothesis**를 상속하여 테스트를 작성한다. Hypothesis는 backend dev 의존성으로, 신규 런타임 의존성이 아니다.
- **근거**: U1/U2/U3와 일관. **PBT-09(U4 핀)**: 임의의 유효 도메인 엔티티에 대해 `to_dto(entity)` → shared DTO 검증이 안정적이고, 유효 create DTO의 `validate_and_map`이 public 필드를 라운드트립하며, **직렬화→역직렬화가 public 필드를 보존하고 내부 필드(owner_id·dedupe_key·normalized_query·scores·audit meta)를 절대 누출하지 않는다**(SEC-9). 강력한 shrinking으로 반례 최소화. cursor property(advisory)도 Hypothesis로 검증 가능.
- **대안**: 예제 기반 단위 테스트 단독(엣지 케이스 커버리지 약함, 라운드트립 불변식 보장 약함).
- **전환 비용**: 없음 — 기채택 dev 도구.

---

## TD-U4-11 — 와이어 DTO: **`docsuri_shared` SSOT 재사용 (포크 금지)**
- **결정** (브리프 §5): 와이어 DTO는 `docsuri_shared.dtos`에서 import한다 — `PageParams, SavedSearchCreateDTO, SavedSearchDTO, SavedSearchPageDTO, LibraryItemCreateDTO, LibraryItemDTO, LibraryPageDTO, HistoryEntry, HistoryPageDTO, SearchResultSetDTO`. 이벤트는 `docsuri_shared.events.SearchExecutedEvent`(🔒 FROZEN — U2 producer ↔ U4 consumer). **U4는 이 DTO/이벤트를 재정의하지 않는다.**
- **근거**:
  - shared/는 언어중립 JSON Schema SSOT의 생성 pydantic 바인딩(camelCase: `createdAt`·`addedAt`·`executedAt`·`arXivId`·`nextCursor`·`resultCount`; `extra='forbid'`)이다. **SSOT 포크는 U3가 범한 결함**(BR-A4 위반+SSOT 포크)으로 명시적으로 회피한다.
  - shared 바인딩이 느슨한 부분(`id`/`meta`=Any, `limit` ge=1·max 없음)을 **U4 자체 검증 계층(`UserDataDTOAndValidation`)이 §3 정련으로 강화**한다: limit 최대 100, string id, 커서 시맨틱, 그리고 **`LibraryItemMeta`(U4 내부 pydantic 모델)가 `meta: Any`를 타입 검증**. 따라서 재생성 바인딩 설치 여부와 무관하게 U4가 정확하다.
  - `LibraryItemMeta`는 U2 ResultCardVM 카드 필드(dtos.md §1.1: title·authors·year·arXivId·abstractSnippet·arxivUrl)를 미러 → 라이브 인덱스 없이 카드 렌더(가용성 격리, D5/BR-L5). 이는 **와이어 DTO 재정의가 아니라 내부 검증기**다.
- **대안**: U4 로컬 DTO 정의(거부 — SSOT 포크, U3 결함 재현). shared 바인딩 직접 신뢰만 하고 검증 생략(거부 — limit/meta 미강화로 SEC-5 갭).
- **전환 비용**: 낮음 — shared 재생성 시 자동 정합(드리프트 CI 가드 존재). U4 검증 계층은 상위호환.

---

## TD-U4-12 — 감사(Audit, SEC-13): **`AuditSink` 포트 + `InMemoryAuditSink`(no-op 기본)**
- **결정** (D12·BR-L10): 서비스는 변경 연산(save/delete · add/remove · clear)에서 `AuditSink` 포트로 감사 이벤트를 발행한다. 기본 구현은 인메모리/no-op(`InMemoryAuditSink`)이며 실 결선은 U6/ops. 감사 페이로드에 **민감/내부 필드 미포함**(SEC-9).
- **근거**: 변경 추적성(SEC-13)을 포트로 추상화 → mock-first 마운트(라이브 감사 인프라 불요)·테스트 결정성. no-op 기본으로 app-shell이 의존성 없이 마운트.
- **대안**: 직접 로깅 호출(교체성·테스트성 저하). 감사 생략(SEC-13 미충족).
- **전환 비용**: 낮음 — 포트 뒤 추상, 실 sink 주입은 U6.

---

## TD-U4-13 — 이벤트 소비(History write): **`SearchExecutedEvent` 멱등 소비자 (consumer, 비-공개 POST)**
- **결정** (D7·INV-L3·BR-L7): Search History의 **쓰기는 이벤트 구동**이다. `history_consumer.py`가 `SearchExecutedEvent`(🔒 FROZEN, at-least-once 전달)를 소비해 `HistoryEntry`를 기록하며, **공개 POST 엔드포인트가 아니다**. 멱등성은 `dedupe_key = sha256(owner_id|requestId|query)`(표준 `hashlib`)로 강제 — 재전달이 중복 행을 생성하지 않는다(exactly-once row, TD-U4-3의 `(owner_id, dedupe_key)` Unique와 함께).
- **근거**: at-least-once 전달 의미론 하에서 exactly-once 영속(INV-L3)을 데이터 계층 Unique + 애플리케이션 dedupe로 이중 보장. 이벤트 계약은 FROZEN이므로 U4는 소비 측만 구현.
- **대안**: 공개 history POST(클라이언트 위조·중복·인가 표면 증가 — 거부). 애플리케이션 dedupe만(Unique 백스톱 없으면 경합 시 중복 가능 — 거부).
- **전환 비용**: 낮음 — 소비자/Unique 모두 U4 내부.

---

## 비용 주석 (NFR-C1) — U4 슬라이스
- **NFR-C1 = $1600/월(시스템 전역, U1 확정).** U4 직접 LLM/임베딩 비용 동인은 **없다** — 저장/라이브러리/이력은 CRUD + 영속화이며 외부 모델 호출이 없다.
- **rerun**만이 비용 유발 경로이나, **`SearchGatewayPort` 경유**(TD-U4-8·INV-L2)로 U2/U6 비용 게이트(U6.CostGuardCircuitBreaker)와 근거화 hook을 그대로 통과 → U4가 별도 비용 상한을 두지 않고 시스템 게이트에 위임한다(백도어 부재). 따라서 rerun 비용은 일반 검색 1회와 동일하게 계상된다.
- 가용성 격리(D5/BR-L5): 라이브러리 카드는 저장된 `LibraryItemMeta` 스냅샷으로 렌더 → 목록 조회 시 U2/인덱스 재호출 0(레이턴시·비용 동인 없음).

## 결정 요약 & 후속
- ✅ **[전역 계승]**: Python(TD-U4-1) · 신규 의존성 0 / 모노레포 backend(TD-U4-9).
- ✅ **[backend-shared]**: FastAPI / CG-1(TD-U4-2).
- ✅ **[U3 계승]**: RDS PostgreSQL(TD-U4-3) · SQLAlchemy(TD-U4-5) · AuthorizationGuard 위임(TD-U4-7) · Hypothesis(TD-U4-10).
- ✅ **U4 고유**: 포트 기반 리포지토리(InMemory 기본 + Sql scaffold + DDL, TD-U4-4) · base64 keyset 커서 코덱(TD-U4-6) · SearchGatewayPort+StubSearchGateway rerun(TD-U4-8) · shared DTO/이벤트 SSOT 재사용·LibraryItemMeta 내부 검증기(TD-U4-11) · AuditSink no-op(TD-U4-12) · SearchExecutedEvent 멱등 소비자(TD-U4-13).
- 후속(NFR Design/Infra로 이관): 쿼터/보존 임계 수치 강제 지점(BR-L2 200·L4 1000·L6 500) 구현 세부 · `001_create_library_tables.sql` DDL 확정(테이블+Unique 인덱스) · 페이지 한도 422 메시지 일반화 · `SqlUserDataRepository` 트랜잭션/격리 수준 · 실 `SearchGateway`/`AuditSink` 결선(U6) · CI 드리프트 가드 통과 확인 · NFR-P1 레이턴시 실측(Build & Test).
