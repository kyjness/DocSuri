# u1-ingestion-code-generation-plan.md — U1 Ingestion 코드 생성 계획

**단계**: CONSTRUCTION → Code Generation Part 1 (Planning)  
**유닛**: U1 Ingestion  
**일자**: 2026-06-16  
**상태**: Code Generation Part 2 완료 — 생성 코드 리뷰 대기  
**단일 진실 원천**: 본 계획은 승인 후 U1 Code Generation의 실행 순서와 범위를 결정하는 단일 기준이다. 코드 생성 중 완료된 단계는 같은 상호작용에서 즉시 `[x]`로 갱신한다.

---

## 1. 유닛 컨텍스트

### 구현 대상
- **유닛**: U1 Ingestion
- **배포 단위**: 독립 인제스천 워커
- **코드 위치**: `ingestion/`
- **언어/런타임**: Python 3.11+
- **공유 계약 의존성**: `shared/python`의 `docsuri_shared`
- **사용자 동기 API/프런트엔드**: 해당 없음

### 구현 스토리
- **US-I1**: arXiv 인제스천 및 인덱싱 시드 빌드
- **US-I2**: 최신성 스케줄 갱신
- **US-I3**: 복원력 있는 인제스천
- **백킹 기여**: US-H1, US-D2, US-D5에 필요한 공유 인덱스와 추적 메타 제공

### 핵심 설계 불변식
- `PaperId`는 버전 없는 arXiv ID다.
- `ContentFingerprint`는 `paperId + version` 파생 키다.
- U1은 공유 OpenSearch 인덱스의 단일 writer다.
- U2는 같은 인덱스의 단일 reader다.
- U1 writer는 `docsuri_shared.vector_spec.EMBEDDING_SPEC`의 `search_document` 역할을 사용한다.
- OpenSearch `_bulk`는 트랜잭션이 아니므로 `verify-all-then-commit`으로 논문 단위 원자성을 앱 계층에서 강제한다.
- 커밋 순서는 `index write durable -> markIngested -> advanceWatermark`다.
- `isNew`는 인서트 스킵 판정 전용이며 tombstone 삭제 가드가 아니다.
- tombstone/upsert 순서는 제어평면 `current_version` compare-and-set으로 `strictly-newer-vN-wins`를 강제한다.
- `indexStats`는 내부 전용이며 실시간 OpenSearch count 남용을 피하기 위해 TTL 캐시 또는 스냅샷을 사용한다.

### 구현 범위
- U1 애플리케이션 코드, 단위 테스트, PBT, 로컬 실행 진입점, 컨테이너 스캐폴드, 코드 요약 문서를 생성한다.
- 실제 AWS 리전/AZ 토폴로지, 사이징, IAM 정책 JSON, IaC는 Infrastructure Design에서 확정한다. 본 코드 생성에서는 설정 키와 어댑터 경계만 제공한다.

---

## 2. 코드 위치

### 애플리케이션 코드
- `ingestion/pyproject.toml`
- `ingestion/README.md`
- `ingestion/src/docsuri_ingestion/`
- `ingestion/tests/`
- `ingestion/migrations/postgres/`
- `ingestion/Dockerfile`

### 문서
- `aidlc-docs/construction/u1-ingestion/code/u1-ingestion-code-summary.md`

### 생성하지 않는 범위
- `backend/`
- `frontend/`
- `ops/`
- `aidlc-docs/` 내부 애플리케이션 코드
- 구체 AWS IaC 파일

---

## 3. 의존성과 인터페이스

### 내부 모듈
- `docsuri_ingestion.domain`: 도메인 값 타입, 엔티티, enum, 오류 타입
- `docsuri_ingestion.ports`: U1 포트 추상화
- `docsuri_ingestion.application`: 오케스트레이션 서비스
- `docsuri_ingestion.resilience`: retry, circuit breaker, token bucket, fault injection 지원
- `docsuri_ingestion.adapters`: arXiv, S3, Bedrock, OpenSearch, SQS, control plane 어댑터
- `docsuri_ingestion.observability`: 구조화 로그와 `ObservabilityHub` 포트 어댑터
- `docsuri_ingestion.cli`: 수동 rebuild와 단건 ingestion CLI
- `docsuri_ingestion.worker`: SQS/EventBridge 워커 진입점

### 외부 패키지
- `docsuri-shared` 로컬 path 의존성: `../shared/python`
- `pydantic`
- `pydantic-settings`
- `httpx`
- `boto3`
- `opensearch-py`
- `psycopg`
- `structlog`
- `pytest`
- `hypothesis`
- `ruff`

### 주요 포트
- `ArxivSourcePort`
- `FullTextStorePort`
- `EmbeddingPort`
- `VectorIndexPort`
- `ControlPlaneStorePort`
- `QueuePort`
- `ObservabilityPort`
- `ClockPort`

---

## 4. 실행 단계

### Step 1 — 프로젝트 구조 설정
- [x] `ingestion/` 패키지 디렉터리와 기본 Python 패키지 구조를 생성한다.
- [x] `pyproject.toml`에 런타임/개발 의존성, pytest, ruff 설정을 추가한다.
- [x] `docsuri-shared`를 로컬 path 의존성으로 연결한다.
- [x] `README.md`에 로컬 실행, 테스트, 환경 변수 개요를 작성한다.

### Step 2 — 도메인 모델 생성
- [x] `domain/ids.py`에 `paper_id` 정규화와 arXiv version 파싱을 구현한다.
- [x] `domain/models.py`에 `CategoryFilter`, `MetadataRecord`, `RawDocument`, `ParsedPaper`, `Chunk`, `ChunkSet`, `EmbeddingBatch`, `IndexRecordBatch`, `IngestionJob`, `Watermark`, `DedupState`, `Tombstone`를 구현한다.
- [x] `domain/enums.py`에 `DedupDecision`, `JobKind`, `FailureClass`, `FailureReason`, `DedupStateKind`를 구현한다.
- [x] `domain/errors.py`에 fail-closed용 typed exception을 구현한다.
- [x] `docsuri_shared.ids.chunk_id`와 `docsuri_shared.vector_spec.IndexRecord`를 도메인 조립에서 사용한다.

### Step 3 — 포트와 설정 생성
- [x] `ports.py`에 U1 내부 포트 Protocol을 정의한다.
- [x] `settings.py`에 환경 변수 기반 설정을 정의하되, 시크릿 값은 로깅하지 않도록 표현을 제한한다.
- [x] `config.py`에 corpus slice 기본값 `cs.LG`, `cs.AI`, `cs.CL`, `cs.CV`, `stat.ML`와 phase-1 최근 1년 범위를 둔다.

### Step 4 — 순수 도메인 컴포넌트 구현
- [x] `FetchParseProcessor`를 구현한다.
- [x] 엄격 OA 라이선스 검증 정책을 구현한다.
- [x] withdrawal 신호 탐지를 메타데이터와 전문 텍스트 기준으로 구현한다.
- [x] `Chunker`를 섹션 인지 결정적 청킹으로 구현한다.
- [x] `DeduplicationGuard`의 지문 산출, `is_new`, `mark_ingested` 조율 로직을 구현한다.
- [x] `IndexRecordAssembler`를 구현해 `ChunkSet + EmbeddingBatch + ParsedPaper`를 `IndexRecordBatch`로 변환한다.

### Step 5 — 제어평면 저장소 구현
- [x] `migrations/postgres/001_control_plane.sql`에 `dedup_state`, `watermark`, `ingestion_job`, `rebuild_lock` 스키마를 작성한다.
- [x] `PostgresControlPlaneStore`를 구현한다.
- [x] `current_version` compare-and-set으로 upsert/tombstone 적용 가능성을 원자적으로 결정한다.
- [x] `REBUILD_LOCK` 획득/해제를 구현한다.
- [x] `advance_watermark`는 max-clamp를 적용하고, rebuild reset은 명시 경로로만 허용한다.

### Step 6 — 복원력 유틸리티 구현
- [x] 명시 timeout wrapper를 구현한다.
- [x] 최대 5회, base 1s, factor 2, jitter 기반 retry policy를 구현한다.
- [x] 의존성별 circuit breaker를 구현한다.
- [x] arXiv 전역 token bucket rate limiter를 구현한다.
- [x] `IngestFailureHandler`와 `IngestionResilienceService`를 구현한다.
- [x] 실패 신호는 `docsuri_shared.events.IngestionFailureSignal` 형상으로 일반화해 발행한다.

### Step 7 — 애플리케이션 오케스트레이션 구현
- [x] `IngestionPipelineService.ingest_one`을 구현한다.
- [x] `RefreshOrchestrationService.trigger_full_rebuild`를 구현한다.
- [x] `RefreshOrchestrationService.on_schedule_tick`을 구현한다.
- [x] `RefreshOrchestrationService.on_new_arxiv_event`를 구현한다.
- [x] rebuild 중 incremental/event 보류 또는 거부 정책을 구현한다.
- [x] 처리 성공 후 event ack 경계를 구현한다.

### Step 8 — arXiv 어댑터 구현
- [x] OAI-PMH seed harvest 어댑터를 구현한다.
- [x] Atom API incremental fetch 어댑터를 구현한다.
- [x] full-text fetch 어댑터를 구현한다.
- [x] 네트워크 오류, 429, 5xx, timeout을 retriable로 분류한다.
- [x] 404, 비-OA, validation violation을 permanent로 분류한다.

### Step 9 — AWS 어댑터 구현
- [x] S3 full-text storage 어댑터를 구현한다.
- [x] Bedrock Cohere Embed Multilingual v3 어댑터를 구현한다.
- [x] `search_document` input type과 1024차원 검증을 강제한다.
- [x] OpenSearch `_bulk` upsert 어댑터를 구현한다.
- [x] OpenSearch per-paper tombstone/delete 어댑터를 구현한다.
- [x] `_bulk` per-item 실패를 전수 검사하고 실패 시 커밋하지 않는다.
- [x] stale chunk 삭제 처리를 구현한다.
- [x] `indexStats` TTL 캐시를 구현한다.
- [x] SQS queue/DLQ 어댑터를 구현한다.

### Step 10 — 로컬/테스트 어댑터 구현
- [x] `FakeArxivSource`
- [x] `InMemoryControlPlaneStore`
- [x] `FakeEmbeddingPort`
- [x] `InMemoryVectorIndex`
- [x] `InMemoryQueue`
- [x] `CapturingObservabilityHub`
- [x] fault injection용 실패 어댑터

### Step 11 — CLI와 워커 진입점 구현
- [x] `python -m docsuri_ingestion.cli trigger-full-rebuild` 진입점을 구현한다.
- [x] `python -m docsuri_ingestion.cli ingest-one` 진입점을 구현한다.
- [x] `python -m docsuri_ingestion.worker` SQS polling 진입점을 구현한다.
- [x] 환경 변수 누락 시 fail closed로 종료한다.
- [x] 구조화 로그에 request/job/correlation ID를 포함한다.

### Step 12 — 비즈니스 로직 단위 테스트
- [x] arXiv ID 정규화와 version 파싱 테스트를 작성한다.
- [x] OA 라이선스 검증 테스트를 작성한다.
- [x] Chunker 예시 기반 테스트를 작성한다.
- [x] DeduplicationGuard 예시 기반 테스트를 작성한다.
- [x] Watermark max-clamp 테스트를 작성한다.
- [x] tombstone strictly-newer-vN-wins 테스트를 작성한다.

### Step 13 — PBT 테스트
- [x] 도메인 generator를 `tests/strategies.py`에 중앙화한다.
- [x] P2 청크 결정성 PBT를 작성한다.
- [x] P3 upsert 멱등성 PBT를 작성한다.
- [x] P4 무손실/무중복 PBT를 작성한다.
- [x] P5 vector-to-chunk 정렬 보존 PBT를 작성한다.
- [x] P6 watermark 단조성 PBT를 작성한다.
- [x] Hypothesis seed 재현성 설정을 테스트 설정에 포함한다.

### Step 14 — 오케스트레이션 및 폴트 인젝션 테스트
- [x] 성공 ingestion end-to-end 테스트를 fake adapter로 작성한다.
- [x] duplicate 재전송 단락 테스트를 작성한다.
- [x] OpenSearch `_bulk` 부분 실패 시 `markIngested` 미호출 테스트를 작성한다.
- [x] Bedrock 429/timeout retry 테스트를 작성한다.
- [x] arXiv 5xx retry와 404 permanent DLQ 테스트를 작성한다.
- [x] poison event DLQ 테스트를 작성한다.
- [x] rebuild lock 중 incremental/event 보류 테스트를 작성한다.

### Step 15 — 배포/빌드 아티팩트 생성
- [x] `Dockerfile`을 생성하고 `latest` 태그 없이 고정 가능한 베이스 이미지 형식을 사용한다.
- [x] 런타임 환경 변수 목록을 README에 문서화한다.
- [x] SBOM/SCA 실행 명령을 README와 pyproject dev dependency 기준으로 문서화한다.

### Step 16 — 코드 요약 문서 생성
- [x] `aidlc-docs/construction/u1-ingestion/code/u1-ingestion-code-summary.md`를 생성한다.
- [x] 생성된 파일 목록, 스토리 매핑, 테스트 매핑, 보안/복원력/PBT 준수 요약을 기록한다.

### Step 17 — 검증 실행
- [x] `python -m pytest` 또는 `uv run pytest`를 실행한다.
- [x] `ruff check`를 실행한다.
- [x] 가능한 경우 lockfile 생성 또는 갱신을 수행한다.
- [x] 실패가 있으면 같은 계획 단계 내에서 수정하고 다시 검증한다.

---

## 5. 스토리 추적성

| 스토리 | 계획 단계 |
|---|---|
| US-I1 arXiv 인제스천 및 인덱싱 | Step 2, Step 4, Step 7, Step 8, Step 9, Step 14 |
| US-I2 스케줄 갱신 | Step 5, Step 7, Step 9, Step 11, Step 14 |
| US-I3 복원력 인제스천 | Step 6, Step 9, Step 10, Step 13, Step 14 |
| US-H1 백킹 인덱스 | Step 4, Step 8, Step 9 |
| US-D2 공유 시맨틱 검색 백킹 | Step 4, Step 9 |
| US-D5 근거화 추적 메타 | Step 2, Step 4, Step 9 |

---

## 6. 확장 규칙 준수 계획

### Security Baseline
- **SECURITY-01**: S3/OpenSearch/control-plane TLS와 at-rest 암호화 설정 키를 제공한다. 구체 KMS/IAM은 Infra Design.
- **SECURITY-03**: 구조화 로그를 사용하고 PII/시크릿을 로그에 싣지 않는다.
- **SECURITY-05**: arXiv 입력, 이벤트 payload, 환경 설정을 검증한다.
- **SECURITY-06**: 코드에는 최소 권한 IAM에 필요한 리소스 경계를 설정값으로 분리한다. 와일드카드 정책은 생성하지 않는다.
- **SECURITY-09**: 공개 S3 접근을 전제하지 않고 내부 오류를 일반화한다.
- **SECURITY-10**: lockfile, SCA, SBOM, 이미지 핀 정책을 준비한다.
- **SECURITY-15**: 모든 외부 호출은 fail closed와 명시 오류 처리를 갖는다.
- 그 외 사용자 API/웹/인증 관련 규칙은 U1 코드 생성에는 N/A 또는 후속 유닛 소관이다.

### Resiliency Baseline
- **RESILIENCY-01**: arXiv, Bedrock, OpenSearch, S3, SQS, control-plane dependency를 코드와 요약 문서에 매핑한다.
- **RESILIENCY-05**: 구조화 로그와 메트릭 emit 경계를 만든다.
- **RESILIENCY-06**: `indexStats` 내부 헬스 소비 계약을 구현한다.
- **RESILIENCY-07**: DLQ, 실패율, lastWrite, retry exhaustion 메트릭을 제공한다.
- **RESILIENCY-09**: scaling limit과 token bucket을 코드 정책으로 둔다.
- **RESILIENCY-10**: timeout, retry, circuit breaker, graceful pause를 구현한다.
- **RESILIENCY-12/14**: fault injection 테스트 스위트를 만든다.
- 리전/AZ, autoscaling target, backup/restore, failover runbook은 Infrastructure/Operations 단계 소관이다.

### PBT Partial
- 차단 적용: PBT-02, PBT-03, PBT-07, PBT-08, PBT-09.
- U1 직접 적용: PBT-03, PBT-07, PBT-08.
- PBT-02/PBT-09는 shared/event serialization과 U1 이벤트 payload 검증으로 보조 적용한다.

---

## 7. 완료 기준

- `ingestion/` 애플리케이션 코드가 생성된다.
- U1 순수 도메인, 오케스트레이션, fake adapter, AWS adapter 경계가 구현된다.
- U1 스토리 US-I1, US-I2, US-I3가 테스트 가능한 코드로 매핑된다.
- 모든 계획 단계가 `[x]`로 갱신된다.
- 테스트와 린트 실행 결과가 보고된다.
- `aidlc-docs/construction/u1-ingestion/code/`에 코드 요약 문서가 생성된다.
