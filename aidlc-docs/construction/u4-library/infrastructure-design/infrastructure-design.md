# infrastructure-design.md — U4 Library 인프라 명세서 (U3 인프라 상속)

**단계**: CONSTRUCTION → Infrastructure Design (유닛별 루프, Track 2 두 번째이자 마지막 유닛) · **유닛**: U4 Library · **일자**: 2026-06-17
**근거(SSOT)**: `tmp/u4-design-brief.md` (Identity §0, D1~D12, BR-L1~L10, INV-L1~L4) · **상위 문서(부모)**: `construction/u3-accounts/infrastructure-design/deployment-architecture.md` (배포 단위 ① VPC·Fargate·RDS 토폴로지)
**핵심 결론**: **U4는 신규 관리형 서비스·신규 비용이 없습니다.** U4는 U2/U3와 동일한 ECS Fargate 백엔드 모놀리스(배포 단위 ①) **안에서** 구동되며, U3가 이미 프로비저닝한 RDS PostgreSQL(Multi-AZ)에 테이블 3개를 추가할 뿐입니다(순수 CRUD).

---

## 0. 범위 선언 (인프라 변경 없음 — Inherited Infrastructure)

본 문서는 **간결(CONCISE)** 합니다. U4는 자체 인프라를 새로 정의하지 않고 U3가 확정한 인프라를 **그대로 상속**하기 때문입니다. 따라서 본 명세서는 다음 두 가지만 다룹니다.

1. U4가 어떤 기존 인프라 위에서 어떻게 배치되는가 (§1, §2)
2. U4가 유일하게 추가하는 인프라 변경분 — RDS 내 신규 테이블 3개 + 인덱스 (§3)

그 외 모든 컴퓨트·네트워크·보안 그룹·관측성 사양은 **U3 부모 문서를 정본으로 참조**하며 본 문서에서 재정의하지 않습니다.

| 인프라 차원 | U4의 변경 | 정본 위치 |
|---|---|---|
| 컴퓨트 (ECS Fargate, ALB, 태스크 정의) | **변경 없음** (동일 컨테이너에 코드 동봉) | U3 `deployment-architecture.md` §1 |
| 네트워크 (VPC, 서브넷, IGW, NAT 배제) | **변경 없음** | U3 `deployment-architecture.md` §2 |
| 보안 그룹 (ALB-SG/ECS-SG/RDS-SG/Redis-SG) | **변경 없음** (기존 TCP 5432 경로 재사용) | U3 `infrastructure-design.md` §3 |
| RDS PostgreSQL (인스턴스·Multi-AZ·백업) | **테이블 3개 + 인덱스만 추가** (스키마 마이그레이션, 인스턴스 사양 무변경) | 본 문서 §3 |
| ElastiCache Redis | **U4 미사용** (세션은 U3/U6 게이트웨이 관심사) | U3 `infrastructure-design.md` §1.2 |
| 신규 관리형 서비스 | **없음** | — |
| 신규 비용 | **없음** ($0 증분) | — |

---

## 1. 배포 위치 — 배포 단위 ① 내부 동봉 (No Separate Service)

U4 Library는 **별도 ECS 서비스가 아닙니다.** U2 Discovery·U3 Accounts·U6 미들웨어와 함께 단일 API 모듈형 모놀리스로 패키징되어 **배포 단위 ①의 동일한 ECS Fargate 태스크 안에서** 구동됩니다.

- **코드 위치**: `backend/modules/library/` (accounts와 동일 패키지 네임스페이스 `backend.modules.library`).
- **마운트 방식**: app-shell의 `backend/wiring.py`가 `_mount_library(app, settings, result)`를 통해 3개 라우터(`/library/saved-searches`, `/library/items`, `/library/history`)를 `create_app()`이 빚는 단일 FastAPI 애플리케이션에 `include_router`로 결합합니다. 별도 포트·별도 컨테이너·별도 로드밸런서 타깃 그룹이 **생기지 않습니다.**
- **컨테이너 이미지**: 기존 단일 `Dockerfile` 빌드 산출물에 U4 코드가 포함되어 동일한 ECR 이미지 다이제스트로 버전 고정됩니다(SEC-10). 즉 배포 파이프라인·태스크 정의·기동 태스크 수(최소 1 ~ 최대 2)는 U3 사양을 변경 없이 그대로 사용합니다.
- **컴퓨트 증분 영향**: U4는 동기 CRUD + 경량 이벤트 컨슈머이므로 추가 vCPU/메모리 가드레일(0.25 vCPU / 512 MB)을 초과하는 부하를 유발하지 않습니다. 별도 태스크 정의 재산정은 불요합니다.

```
[ALB] ──> [ECS Fargate 태스크 — 배포 단위 ① (단일 컨테이너)]
              ├── U2 Discovery 라우터
              ├── U3 Accounts 라우터
              ├── U4 Library 라우터  ← 본 유닛 (코드만 동봉, 신규 인프라 없음)
              └── U6 ApiGateway 미들웨어 (조립 시)
                         │ (TCP 5432, 기존 RDS-SG 경로)
                         v
                   [RDS PostgreSQL (Multi-AZ)] ← U3 프로비저닝, U4 테이블 3개 추가
```

---

## 2. 데이터 스토어 — U3 RDS PostgreSQL 재사용 (No New Managed Service)

U4는 U3가 격리 사설 서브넷에 배치한 **Amazon RDS PostgreSQL(`db.t4g.small`, PostgreSQL 16.x, Multi-AZ 활성화)** 인스턴스를 **그대로 재사용**합니다. 신규 데이터베이스 인스턴스를 프로비저닝하지 않습니다.

- **인스턴스 사양**: U3 정본(`infrastructure-design.md` §1.1) 그대로 — `db.t4g.small` (2 vCPU, 2 GB RAM, Graviton3), gp3 20 GB, Multi-AZ Enabled, 자동 백업 7일(RPO < 24h).
- **연결 경로**: 기존 `ECS-SG → RDS-SG` TCP 5432 인바운드 규칙을 재사용합니다. U4를 위한 신규 보안 그룹 규칙·신규 포트 개방이 **없습니다**.
- **자격증명**: 기존 DB 연결 자격증명(AWS Secrets Manager/Parameter Store에서 컨테이너 환경변수로 투과 주입)을 공유합니다. U4 전용 시크릿을 추가하지 않습니다.
- **운영 기본값(비-프로덕션·테스트)**: U4의 영속화는 포트 기반(D10)이며 기본 구현은 **InMemoryUserDataRepository**입니다. app-shell은 라이브 DB 없이도(목 우선, mock-first) U4를 마운트하므로(브리프 §8) PostgreSQL이 없는 CI/로컬에서도 8 라우터가 그린으로 기동합니다. 프로덕션 바인딩만 **SqlUserDataRepository**(SQLAlchemy)를 통해 위 RDS에 접속합니다(D10).
- **소유자 스코핑 백스톱(INV-L1, SEC-8)**: 모든 리포지토리 읽기/쓰기는 `owner_id`로 구조적으로 필터링됩니다. 이는 인프라 차원의 추가 격리가 아니라 데이터 계층 방어 심층화이며, RDS 인스턴스 자체에는 추가 격리 인프라가 필요하지 않습니다.

> 비용 영향: 테이블 3개는 동일 인스턴스·동일 gp3 스토리지(20 GB 여유 내)에서 수용되므로 **인스턴스 업그레이드·스토리지 증설·신규 RDS 비용이 발생하지 않습니다.** U4 데이터는 소유자별 상한(저장 검색 200·라이브러리 1000·이력 500, D2/D4/D6)이 걸려 무제한 증가하지 않습니다.

---

## 3. 인프라 변경분 — RDS 신규 테이블 3개 + 인덱스 (유일한 추가)

U4가 인프라에 가하는 **유일한** 변경은 기존 RDS PostgreSQL에 테이블 3개와 인덱스를 추가하는 스키마 마이그레이션입니다(`backend/modules/library/migrations/001_create_library_tables.sql`). 신규 관리형 서비스·신규 비용은 없습니다.

### 3.1. 테이블 목록 (도메인 엔티티 ↔ 테이블 매핑)

| 테이블 | 도메인 엔티티 | 스토리 | 소유자 상한 |
|---|---|---|---|
| `saved_searches` | SavedSearch (US-L1) | FR-8 | 200 / owner (D2/BR-L2) |
| `library_items` | LibraryItem (US-L2) | FR-9 | 1000 / owner (D4/BR-L4) |
| `search_history` | HistoryEntry (US-L3) | FR-10 | rolling 500 / owner (D6/BR-L6) |

### 3.2. 스키마 및 인덱스 사양

모든 테이블은 `owner_id` 컬럼에 인덱스를 두어 소유자 스코핑 조회(INV-L1)와 키셋 페이지네이션(D8) 정렬 키 조회를 인덱스로 충족합니다. 타임스탬프는 timezone-aware UTC(`timestamptz`)로 저장합니다(브리프 §9).

- **`saved_searches`**
  - 컬럼: `id` (uuid4 텍스트, PK), `owner_id` (텍스트), `query` (텍스트), `label` (텍스트, nullable), `normalized_query` (텍스트), `created_at` (`timestamptz`).
  - **고유 제약**: `UNIQUE (owner_id, normalized_query)` — 정규화 질의 멱등성(D1/BR-L1)을 데이터 계층에서 강제.
  - **인덱스**: `idx_saved_searches_owner_created (owner_id, created_at DESC, id DESC)` — 소유자 스코핑 + 최신순 키셋 페이지네이션(D8).
- **`library_items`**
  - 컬럼: `id` (uuid4 텍스트, PK), `owner_id` (텍스트), `arxiv_id` (텍스트), `meta` (jsonb — `LibraryItemMeta` 스냅샷, 가용성 격리; 인덱스에서 재조회하지 않음, D5/BR-L5), `added_at` (`timestamptz`).
  - **고유 제약**: `UNIQUE (owner_id, arxiv_id)` — 추가 멱등성(D3/BR-L3, QT-4); 재추가는 기존 행을 반환하며 스냅샷을 덮어쓰지 않음.
  - **인덱스**: `idx_library_items_owner_added (owner_id, added_at DESC, id DESC)` — 소유자 스코핑 + 최신순 키셋 페이지네이션(D8).
- **`search_history`**
  - 컬럼: `id` (uuid4 텍스트, PK), `owner_id` (텍스트), `query` (텍스트), `executed_at` (`timestamptz`), `result_count` (정수), `dedupe_key` (텍스트).
  - **고유 제약**: `UNIQUE (owner_id, dedupe_key)` — at-least-once 전달을 exactly-once 행으로 수렴(D7/BR-L7, INV-L3). `dedupe_key = sha256(owner_id|requestId|query)`.
  - **인덱스**: `idx_search_history_owner_executed (owner_id, executed_at DESC, id DESC)` — 소유자 스코핑 + 최신순 키셋 페이지네이션(D8) 및 상한 초과 시 가장 오래된 행 프루닝(D6).

> 모든 고유 제약·인덱스는 SEC-9(비공개) 위반 없이 내부 컬럼(`owner_id`, `normalized_query`, `dedupe_key`)을 인덱스 키로만 사용합니다. 이들 컬럼은 와이어 DTO로 직렬화되지 않습니다.

---

## 4. 이력 컨슈머 — 공유 이벤트 버스 구독 (Future U6/EventBridge 배선)

검색 이력(`search_history`) 쓰기는 공개 POST 엔드포인트가 아니라 **이벤트 구동 컨슈머**입니다(브리프 §6). U2의 `SearchOrchestrationService`가 발행한 **SearchExecutedEvent(🔒FROZEN 계약)** 를 **공유 이벤트 버스로 구독**하여 `UserDataRepository`(SearchHistory 포트)에 비동기 기록합니다(NFR-P1 검색 응답 비차단).

- **인프라 의존성**: 프로덕션에서 공유 이벤트 버스는 **향후 U6 게이트웨이/EventBridge 배선**을 통해 연결됩니다. 본 유닛은 해당 배선을 정의하거나 EventBridge 리소스를 프로비저닝하지 **않습니다** — 이는 공유 인프라/U6 통합 작업의 관심사입니다.
- **비-프로덕션 구현**: U4는 라이브 메시지 버스 없이도 동작하도록 **인메모리 컨슈머**(`history_consumer.py`)를 기본 제공합니다. 따라서 EventBridge/SQS 같은 신규 관리형 서비스가 U4 마운트의 전제가 아니며, U4 단독으로도 테스트가 그린으로 통과합니다.
- **멱등성 보장(INV-L3)**: at-least-once 재전달이 발생해도 `dedupe_key` 고유 제약(§3.2)이 중복 행을 차단하므로, 메시지 버스의 전달 보증 수준과 무관하게 정확히 한 번의 행만 남습니다.
- **재실행 경로(INV-L2)**: rerunSavedSearch / rerunHistoryEntry는 U2를 직접 호출하지 않고 **SearchGatewayPort**(게이트웨이 전면 검색 계약, U6 ApiGatewayMiddleware → U2)를 경유합니다. 비용·근거화 훅이 재적용되며 백도어가 없습니다. U4는 인프라 미연결 단계에서 `StubSearchGateway`(결정론적 플레이스홀더)를 사용하므로 별도 인프라가 필요하지 않습니다.

---

## 5. 관측성 및 감사 (기존 구성 재사용)

- **로그/경보**: U4는 배포 단위 ①의 동일 컨테이너에 동봉되므로 기존 CloudWatch Logs 로그 그룹(`/aws/ecs/docsuri-api-service`, 보존 30일)과 CPU/Memory 경보를 그대로 공유합니다(U3 `deployment-architecture.md` §3). U4 전용 신규 로그 그룹·신규 경보를 추가하지 않습니다. 로깅은 SEC-3 비민감 정보 필터링을 따릅니다.
- **감사(SEC-13, D12/BR-L10)**: 변경 연산(save/delete, add/remove, clear)은 `AuditSink` 포트로 감사 이벤트를 방출합니다. 기본 구현은 인메모리/무동작(no-op)이며 실제 배선은 U6/ops로 위임됩니다. 감사 페이로드에는 민감/내부 필드를 담지 않습니다(SEC-9). 이 또한 신규 인프라 리소스를 요구하지 않습니다.

---

## 6. 공유 인프라 설계로 이연(Deferred)되는 항목

다음 결정은 단일 유닛이 아닌 **시스템 전역 관심사**이므로 본 U4 유닛 인프라 문서에서 확정하지 않고 **공유(전역) Infrastructure Design으로 이연**합니다. U4는 이연 항목에 대해 별도의 상충 결정을 내리지 않으며, 전역 결정을 그대로 상속합니다.

| 이연 항목 | 전역 요구 ID | 현재 상속 상태 | 정본(예정) |
|---|---|---|---|
| 리전/AZ 토폴로지·RTO/RPO·DR | **RES-2** | 단일 리전(`ap-northeast-2`)·Multi-AZ·교차 리전 DR 없음; 저장 메타데이터 RPO ~24h, RTO는 IaC 재배포+복원으로 수 시간. U4 테이블은 U3 RDS 자동 백업에 포함되어 별도 백업 불요. | 공유 Infrastructure Design |
| 오토스케일링 / 동시성 한도 / 클라우드 쿼터 | **RES-8** | 배포 단위 ① 기동 태스크 수 최소 1 ~ 최대 2 가드레일을 상속(U3 `deployment-architecture.md` §1). U4 CRUD는 추가 오토스케일링 정책을 요구하지 않음. | 공유 Infrastructure Design |

> U4의 DR 입장: `search_history`는 rolling 500 상한의 재생 가능 성격(이벤트 재전달 시 멱등 재기록)을 가지나, `saved_searches`/`library_items`는 사용자 생성 자산이므로 RES-2의 RDS 자동 백업(RPO ~24h)에 의존합니다. 별도 백업 스토어를 두지 않습니다.

---

## 7. 추적성 요약 (Traceability)

| 인프라 결정 | 근거 ID |
|---|---|
| 배포 단위 ① 내부 동봉 (별도 서비스 없음) | Identity §0(deploy unit ①), 브리프 §8 (app-shell wiring) |
| U3 RDS PostgreSQL(Multi-AZ) 재사용 | D10, U3 `infrastructure-design.md` §1.1 |
| `saved_searches` 고유 제약 `(owner_id, normalized_query)` | D1/BR-L1 |
| `saved_searches` 소유자 상한 200 | D2/BR-L2 |
| `library_items` 고유 제약 `(owner_id, arxiv_id)` | D3/BR-L3, QT-4 |
| `library_items` 소유자 상한 1000 | D4/BR-L4 |
| `library_items.meta` jsonb 스냅샷(가용성 격리) | D5/BR-L5 |
| `search_history` 상한 rolling 500 + 프루닝 | D6/BR-L6 |
| `search_history` 고유 제약 `(owner_id, dedupe_key)` | D7/BR-L7, INV-L3 |
| 인덱스 `(owner_id, <sort> DESC, id DESC)` 키셋 페이지네이션 | D8/BR-L8 |
| 이력 컨슈머 = 공유 이벤트 버스 구독(향후 U6/EventBridge) | 브리프 §6, INV-L3 |
| 재실행 = SearchGatewayPort 경유(백도어 없음) | D9/BR-L9, INV-L2 |
| 소유자 스코핑 데이터 백스톱 | INV-L1, SEC-8 |
| 감사 = AuditSink 포트(no-op 기본, U6/ops 배선) | D12/BR-L10, SEC-13 |
| 리전/AZ/DR 이연 | RES-2 (공유 Infrastructure Design) |
| 오토스케일링 이연 | RES-8 (공유 Infrastructure Design) |
