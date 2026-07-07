# Performance Test Instructions

**단계**: CONSTRUCTION → Build and Test · **유닛**: U1 Ingestion + U3 Accounts · **일자**: 2026-06-16
**문서 언어**: 영어/한국어 혼용 (유닛별 작성 언어 유지)

---

# U11 Evidence Formation Agent Performance Test Instructions — 2026-07-01

## NFR-P6: Streaming first + async job offload

The synchronous `EvidenceAgentOrchestrator.run()` is expected to complete within
**30 seconds** for a 5-paper corpus (Bedrock p50 target). For larger corpora, the
async SQS job path (BR-EV-6) is activated when `DOCSURI_EVIDENCE_ASYNC_ENABLED=true`.

Local performance validation (staging only — requires real Bedrock + OpenSearch):

```bash
time curl -X POST https://<staging-host>/api/evidence/turns \
  -H 'Authorization: Bearer <token>' \
  -H 'Content-Type: application/json' \
  -d '{"topic": "transformer attention mechanism", "scope": "auto"}'
```

Target: `state=ok` response under 30 s for a 5-paper auto-scope query.

## BR-EV-7: Cost gate (CostGuardCircuitBreaker)

If `CostGuardCircuitBreaker.check()` returns `False`, the orchestrator returns
`TurnAbstainResult(llm_unavailable)` without invoking Bedrock. No local load test
required; behavior is covered by the unit test stub path.

## Local overhead measurement

```bash
./backend/.venv/bin/pytest backend/tests/test_evidence.py -v --durations=5
```

Observed: all 12 tests complete in under 1.2 s (no I/O — InMemory + StubOrchestrator).

본 문서는 두 트랙의 성능 테스트 지침을 통합합니다.

- **U1 Ingestion**: 대규모 arXiv 슬라이스 처리 시 비용·쿼터·복원력 제약 준수 검증.
- **U3 Accounts**: 세션 검증 초저지연 성능 예산(P50 < 5ms, P99 < 20ms) 충족 여부 검증.

---

# Production API/Frontend Load Test — 2026-07-02

Use the checked-in k6 script for the public frontend and API gateway:

```bash
brew install k6
DOCSURI_APP_URL=https://docsuri.org \
DOCSURI_API_URL=https://d2bsni6xhpvbw1.cloudfront.net \
DOCSURI_VUS=20 \
DOCSURI_HOLD=2m \
k6 run tests/performance/api_frontend_load_test.js
```

Default thresholds:

| Target | Threshold |
|---|---|
| Frontend `/` | p95 < 1000 ms |
| API `/readyz` | p95 < 500 ms |
| API `/api/search` sampled at 20% | p95 < 3000 ms |
| Overall error rate | < 1% |

Set `DOCSURI_SKIP_SEARCH=1` for a frontend/readiness-only smoke run. If p95 breaks, inspect the matching ALB p95 alarm and ECS CPU/memory metrics, then tune `ops/cdk/stacks/compute_stack.py` or `ops/cdk/stacks/frontend_stack.py` task size/max capacity and rerun the same script.

Live smoke result before deploying this hardening change:

| Target | Requests / concurrency | p95 | Status |
|---|---:|---:|---|
| Frontend `/` | 40 / 8 | 394.7 ms | 40× 200 |
| API `/readyz` | 80 / 10 | 455.3 ms | 80× 200 |
| API `/api/search` | 12 / 3 | 9061.0 ms | 12× 200 |

Because API search p95 broke the 3000 ms threshold, the API service is raised to 1 vCPU / 2 GB, min 2, max 6 in `ops/cdk/stacks/compute_stack.py`. Re-run the k6 script after deployment; if search p95 remains high with low API CPU, investigate OpenSearch query latency and index/cache behavior before adding more API replicas.

---

# U11 Novelty Agent Performance Test Instructions — 2026-06-30

No standalone load test was executed for U11 in this local Build & Test pass.

Performance checks for staging:

- Job create/status/cancel endpoints should remain lightweight owner-scoped DB reads/writes.
- SSE progress reads should stream persisted progress events and fall back to polling.
- Worker concurrency should remain bounded by the novelty SQS queue and cost guard.
- External search adapters must stay bounded by timeout, allowlist, and degraded-result behavior.

Suggested staging validation:

```powershell
# Target endpoints:
# - POST /api/novelty/jobs
# - GET /api/novelty/jobs/{job_id}
# - GET /api/novelty/jobs/{job_id}/events
# - GET /api/novelty/jobs/{job_id}/result
```

Acceptance:

- API request path does not run long external searches inline.
- Worker failure lands in retry/DLQ paths with observable progress/degraded state.
- No Notion export proceeds without preview approval.

---

## 1. Purpose / 목적

### 1.1. U1 Ingestion

Validate that U1 ingestion respects cost, quota, and resiliency constraints while
processing large arXiv slices.

### 1.2. U3 Accounts

U3 Accounts 모듈의 핵심 비기능적 요구사항(NFR)인 **세션 검증 초저지연 성능 예산(P50 < 5ms, P99 < 20ms)** 충족 여부를 객체적으로 검증합니다.

---

## 2. Applicable Requirements / 성능 목표

### 2.1. U1 Ingestion — Applicable Requirements

- Corpus slice: `cs.LG`, `cs.AI`, `cs.CL`, `cs.CV`, `stat.ML` over five years.
- Writer role: Cohere Embed Multilingual v4 `search_document`, 1024 dimensions.
- Rate control: arXiv token bucket.
- Retry policy: maximum five attempts, base one second, exponential factor two, jitter.
- Atomicity: no `mark_ingested` unless all chunks are written and verified.

### 2.2. U3 Accounts — 성능 목표 (NFR Requirements)

| 성능 지표 | 목표 기준 | 대상 API 엔드포인트 | 비고 |
|---|---|---|---|
| **P50 레이턴시** | **< 5ms** | `GET /auth/session` | Redis 인메모리 lookup 보장 |
| **P99 레이턴시** | **< 20ms** | `GET /auth/session` | Redis 커넥션 풀 경합 제어 상태 |
| **동시 사용자 수** | 50 concurrent | `GET /auth/session` | 초당 트래픽(RPS) 500 이상 수용 |
| **에러율 (Error Rate)**| **< 0.1%** | 전체 인증 관련 API | 스레드 고갈/Redis 타임아웃 미발생 |

---

## 3. Local Performance Checks / 로컬 부하 테스트

### 3.1. U1 Ingestion — Local Performance Checks

Local checks use fake adapters and validate CPU-bound processing behavior only.

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests/test_properties.py
```

Expected result:

- PBT suite passes with deterministic chunking and idempotent upsert properties.

### 3.2. U3 Accounts — k6 기반 성능 테스트 구성 및 실행

본 가이드는 가볍고 고성능인 부하 테스트 도구인 **k6**를 기준으로 설명합니다.

#### 3.2.1. k6 스크립트 작성 (`tests/performance/session_load_test.js`)

테스트용 k6 스크립트를 작성하여 특정 가상 사용자(VU) 규모로 `/auth/session` API에 부하를 전송합니다.

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 50 }, // 30초 동안 가상 사용자 50명까지 램프업
    { duration: '1m', target: 50 },  // 1분간 50명 유지 (피크 부하)
    { duration: '10s', target: 0 },  // 10초간 램프다운
  ],
  thresholds: {
    // NFR 요구사항: P50 < 5ms, P99 < 20ms 강제 검증
    'http_req_duration{name:session_verify}': ['p(50)<5', 'p(99)<20'],
    'http_req_failed': ['rate<0.001'], // 에러율 < 0.1%
  },
};

export default function () {
  const url = 'http://localhost:8000/auth/session';
  const params = {
    headers: {
      'Cookie': 'session_id=dummysessiontokenmaterialforperformancetests',
    },
    tags: { name: 'session_verify' }
  };

  const res = http.get(url, params);
  
  check(res, {
    'is status 200': (r) => r.status === 200,
  });
  
  sleep(0.01); // 10ms 대기 후 재요청 (고빈도 호출)
}
```

#### 3.2.2. 로컬 부하 테스트 실행

실제 ECS Fargate 배포 전 로컬 또는 개발 컨테이너 환경에서 간이 확인을 수행합니다.

```bash
# 1. k6 설치 (macOS)
brew install k6

# 2. 로컬 API 서버 기동 (Uvicorn으로 백엔드 구동)
uvicorn backend.app:app --host 0.0.0.0 --port 8000 --workers 4

# 3. k6 부하 테스트 실행
k6 run tests/performance/session_load_test.js
```

---

## 4. AWS Load Test Setup (U1 Ingestion)

Run only after Infrastructure Design defines quotas and isolated test resources.

Recommended initial parameters:

- Test duration: 30 minutes
- Seed size: 100 known OA papers
- Concurrency: one worker process initially
- Ramp-up: increase worker count only after arXiv and Bedrock quotas are confirmed
- Error budget: zero silent partial indexing; retriable failures may enter retry/DLQ paths

---

## 5. Load Test Execution (U1 Ingestion)

1. Prepare a known OA arXiv ID list.
2. Enqueue U1 `EVENT` jobs into the test SQS queue.
3. Run one or more worker containers.
4. Observe:
   - ingestion throughput
   - retry count by stage
   - DLQ count
   - OpenSearch document count
   - Bedrock throttling
   - arXiv request rate

Command shape:

```powershell
docker run --rm --env-file .env.integration docsuri-ingestion:<git-sha>
```

---

## 6. Pass Criteria (U1 Ingestion)

- No partial paper commit.
- Duplicate replay does not increase OpenSearch record count.
- Bedrock 429/timeout recovers within retry policy or reaches DLQ with failure signal.
- `indexStats` calls use cached count behavior, not per-request expensive count loops.
- arXiv request rate remains within configured token bucket policy.

---

## 7. Optimization Loop / 모니터링 및 병목 지점 해소

### 7.1. U1 Ingestion — Optimization Loop

If performance is below target:

1. Identify bottleneck by dependency stage.
2. Tune chunk bounds and worker concurrency within cost budget.
3. Confirm Bedrock and OpenSearch quotas before raising concurrency.
4. Repeat load test and compare metrics.

### 7.2. U3 Accounts — 모니터링 및 병목 지점 해소

성능 예산 미달 시 점검사항:

- **Redis ConnectionPool 모니터링**: 커넥션 풀 크기(50개)를 초과하여 대기 스레드/태스크 지연이 발생하지 않는지 로그 확인.
- **Garbage Collection**: Python 런타임의 GC 스파이크로 인해 일시적으로 P99 레이턴시가 튀지 않는지 확인.
- **비동기 이벤트 루프 차단**: 비즈니스 로직 중 비동기(async/await) 처리가 누락되어 동기식 디스크 I/O나 암호학적 해싱 연산이 메인 이벤트 루프를 블로킹하고 있는지 파악. (특히 password hashing은 CPU bound 작업이므로 로그인 API 호출 빈도를 적절히 격리 통제해야 함).
# U9 Personalization Performance Test Instructions — 2026-06-23

No standalone load test was executed for U9 in this local Build & Test pass.

Performance checks for staging:

- Search and summary decision reads should remain bounded profile reads.
- U9 timeout/failure must return non-personalized defaults.
- Retention cleanup should run as a short scheduled task, not an always-on worker.

Suggested staging validation:

```powershell
# Run backend smoke/load command used by the deployment environment once U9 is enabled.
# Target endpoints:
# - GET /api/personalization/decision/search
# - GET /api/personalization/decision/summary-defaults
```

Acceptance:

- U9 decision read does not dominate U2/U7 latency.
- U9 failure produces degraded/default behavior, not primary feature failure.

---

# Agent Chat Frontend Performance Test Instructions — 2026-07-01

No standalone load test was executed for Agent Chat Frontend in this local Build & Test pass.

Observed build budget:

- `/agent` route size: `6.18 kB`.
- `/agent` first-load JS: `131 kB`.

Suggested staging validation:

```powershell
corepack pnpm@9.15.9 --dir frontend build
corepack pnpm@9.15.9 --dir frontend exec -- playwright test e2e/agent-chat.spec.ts --reporter=line
```

Acceptance:

- `/agent` remains within the same first-load JS class as adjacent authenticated screens.
- Chat message send keeps visible loading/progress state during adapter latency.
- Attachment chips remain compact and do not push the composer off-screen on mobile.

---
