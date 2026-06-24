# Integration Test Instructions — 통합 테스트 지침서

**단계**: CONSTRUCTION → Build and Test · **일자**: 2026-06-16
**문서 언어**: 영문(공통 골격) + 한국어(U3 내용)

## Purpose

Validate interactions across generated module boundaries and, when infrastructure is
available, across AWS dependencies. This document covers both U1 (Ingestion) and U3
(Accounts) integration tests. U1 검증은 생성된 모듈 경계를 가로지르는 상호작용을, U3 검증은
Accounts 모듈 내 컴포넌트(Controller, Service, Repository) 간 결합과 외부 인프라스트럭처와의
통합 작용을 대상으로 합니다. develop 브랜치에는 모듈을 마운트하는 백엔드 app-shell(FastAPI)이
포함되어 있으며, App shell 결선 이후 통합 API 테스트는 app-shell HTTP 클라이언트를 활용할 수
있습니다.

---

## U1 — Ingestion Integration Tests

### Current Integration Status

Generated and executable now:

- U1 pipeline with fake arXiv, fake embedding, in-memory control plane, in-memory vector index
- OpenSearch partial bulk failure boundary through `InMemoryVectorIndex(fail_bulk=True)`
- DLQ boundary for permanent failures
- Rebuild lock deferral for schedule and new-arXiv event paths

Deferred until Infrastructure Design or other units exist:

- Real S3, Bedrock, OpenSearch, SQS, and Postgres integration tests
- U1 to U6 ObservabilityHub integration
- U1-produced index read by U2 HybridRetriever

### Test Scenarios

#### Scenario 1: U1 Pipeline Internal Integration

- Description: metadata fetch, full-text parse, OA validation, chunking, embedding, index write,
  `mark_ingested`, and watermark advancement.
- Setup: fake adapters from `ingestion/src/docsuri_ingestion/adapters/local.py`.
- Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_orchestration.py::test_successful_ingestion_end_to_end_with_fake_adapters
```

- Expected result: record exists in in-memory index, dedup state has fingerprint, watermark advances.

#### Scenario 2: Duplicate Event Redelivery

- Description: at-least-once event redelivery short-circuits after dedup detection.
- Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_orchestration.py::test_duplicate_redelivery_short_circuits
```

- Expected result: second ingest returns `DUPLICATE`, bulk upsert count remains one.

#### Scenario 3: OpenSearch Bulk Partial Failure Boundary

- Description: app-level verify-all-then-commit prevents `mark_ingested` after partial bulk failure.
- Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_orchestration.py::test_bulk_partial_failure_does_not_mark_ingested
```

- Expected result: raised retriable error, dedup fingerprint remains unset.

#### Scenario 4: Rebuild Lock Exclusion

- Description: schedule and event paths defer while rebuild lock is active.
- Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_orchestration.py::test_rebuild_lock_defers_incremental_and_event_paths
```

- Expected result: no incremental/event jobs enqueued while lock is active.

---

## U3 — Accounts Integration Tests

본 절은 U3 Accounts 모듈 내의 컴포넌트(Controller, Service, Repository) 간의 유기적인 결합과
외부 인프라스트럭처와의 통합 작용을 검증하기 위한 지침입니다. (단계: CONSTRUCTION → Build and Test ·
유닛: U3 Accounts)

### 테스트 목적 및 시나리오

#### 시나리오 1: 회원가입-인증-활성화 통합 워크플로우 (US-A1, BR-A5)
- **검증 내용**: 가입 시 `PENDING` 계정 생성 → 인증 토큰 메일 발송(Mock SES) → 활성화 엔드포인트 호출 → `ACTIVE` 전환 프로세스가 롤백 없이 안전하게 완결되는가.
- **수행 방식**: SQLAlchemy `sqlite:///:memory:` 인메모리 데이터베이스 및 `MockEmailClient` 기반 결선 수행.

#### 시나리오 2: 실패 누적 브루트포스 백오프 및 reCAPTCHA (US-A2, BR-A4)
- **검증 내용**: 로그인 3회 이상 실패 시 비동기 지연(`asyncio.sleep`)이 워커 리소스를 점유하지 않고 정확히 지연되는가, 10회 이상 실패 시 reCAPTCHA 검증 게이트가 Fail-Closed로 올바르게 차단하는가.
- **수행 방식**: `unittest.mock`을 활용한 `asyncio.sleep` 호출 감지 및 `RecaptchaClient.verify_token` 모킹 분기 검증.

#### 시나리오 3: Redis 연결 유실 시 Fail-Closed 차단 (US-R1, BR-A3)
- **검증 내용**: Redis 장애(ConnectionError 등) 발생 시 데이터베이스 등으로 비정상 폴백하지 않고, 안전하게 예외를 격리 래핑하여 인증 요청을 차단하는가.
- **수행 방식**: `redis.asyncio` 세션 레포지토리에 임의의 커넥션 예외를 강제 주입하여 가드의 차단 동작 확인.

### 통합 테스트 실행 방법

통합 테스트는 `tests/accounts/test_services.py` 및 `tests/accounts/test_session.py`, `tests/accounts/test_guard.py`에 수록되어 있습니다.

```bash
# 1. 서비스 비즈니스 흐름 통합 테스트 실행
pytest tests/accounts/test_services.py -v

# 2. Redis 세션 장애 및 만료 통합 테스트 실행
pytest tests/accounts/test_session.py -v

# 3. Stateless 인가 가드 통합 테스트 실행
pytest tests/accounts/test_guard.py -v
```

### 로컬 독립 서버 연동 통합 테스트 (Optional)
로컬에 실제 PostgreSQL 및 Redis 컨테이너를 가동하여 테스트하고 싶은 경우의 절차입니다.

```bash
# 1. 로컬 개발용 인프라 기동 (Docker Compose 활용 예시)
docker run -d --name docsuri-db -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
docker run -d --name docsuri-redis -p 6379:6379 redis:7

# 2. 로컬 모킹 비활성화 및 환경변수 주입 실행
export ENV=production
export SES_MOCK=false
export RECAPTCHA_SECRET_KEY=real_recaptcha_key

# 3. DDL 마이그레이션 적용
psql -h localhost -U postgres -d postgres -f backend/modules/accounts/migrations/001_create_accounts_table.sql

# 4. 통합 API 테스트 수행
# (App shell 결선 이후 HTTP API 클라이언트 테스트 도구 활용 가능)
```

---

## AWS Integration Environment (U1)

Run only after Infrastructure Design defines concrete endpoints, IAM, KMS, and network access:

1. Provision isolated test resources for S3, Bedrock, OpenSearch, SQS, DLQ, and Postgres.
2. Apply `ingestion/migrations/postgres/001_control_plane.sql`.
3. Export production-like `DOCSURI_*` variables.
4. Run a controlled single-paper ingest.

Command shape:

```powershell
$env:DOCSURI_ENV="integration"
python -m docsuri_ingestion.cli ingest-one --arxiv-ref <known-oa-paper-vN>
```

Cleanup:

- Delete test S3 object prefix.
- Delete test OpenSearch records by `paperId`.
- Purge test SQS messages.
- Reset control-plane rows for the test `paperId`.
# U9 Personalization Integration Test Instructions — 2026-06-23

Run backend integration/app-shell checks with local path packages:

```powershell
$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'
python -m pytest backend/tests/test_personalization.py backend/tests/test_app_shell.py -q
python -m pytest backend/tests -q
```

Observed results:

- U9 + app-shell: 25 passed
- backend tests: 57 passed, 1 skipped

Key scenarios:

- U9 module appears in app-shell registry.
- U9 endpoints are feature-flag gated by default.
- U9 routes work when `PERSONALIZATION_ENABLED=true`.
- Existing backend app-shell routes continue to mount with local source packages present.

---
