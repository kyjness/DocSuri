# U11 Evidence Formation Agent — Infrastructure Design (AWS 리소스 매핑)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**근거**: NFR Design(logical-components.md · nfr-design-patterns.md) · NFR Requirements(TD-E1~E11) · 시스템 전역 `construction/infrastructure-design/infrastructure-design.md`.
**핵심**: 기존 자산 최대 재사용. **신규 관리형 서비스 2**(SQS 큐 1개 + AgentWorker ECS 태스크 1종). 리전 = **ap-northeast-2(서울)**.

---

## 1. 논리 컴포넌트 → AWS 리소스 매핑

| 논리 컴포넌트 | AWS 리소스 | 신규/재사용 |
|---|---|---|
| U11 Router · EvidenceChatService · EvidenceSessionManagementService | **ECS Fargate**(배포 ① backend 모놀리스, ALB 후면) | 재사용(모듈 추가) |
| EvidenceAgentOrchestrator (동기 경로) | backend 모놀리스 내 실행 | 재사용 |
| AgentWorker(비동기 경로) | **ECS Fargate** — **신규 태스크 정의**(배포 ③ 워커 계열) | **신규**(SQS 폴링·Agent 실행) |
| EvidenceSessionRepository | **RDS PostgreSQL** — 신규 테이블 `evidence_sessions`·`evidence_turns` | 재사용(테이블 추가·마이그레이션) |
| EvidencePaperSearchTool | **OpenSearch**(U2 소유 클러스터) — read-only 소비 | 재사용(IAM read 권한) |
| EvidenceDocModelTool | **S3**(U1 소유 DocModel 버킷) — read-only 소비 | 재사용(기존 IAM GetObject) |
| AttachmentDocModelAdapter | **S3** — `evidence-attachments/tmp/` 프리픽스 (업로드→추출→즉시 삭제) | 재사용(프리픽스 추가) |
| EvidenceAgentOrchestrator (LLM) | **Bedrock** — Sonnet 4.6(`claude-sonnet-4-6`) | 재사용(IAM 권한 추가) |
| SQS 잡 큐 | **SQS** — `evidence-agent-job-queue` | **신규** |
| CostGate/Telemetry | **Ports → U6**(CloudWatch 경유) | 재사용 |

---

## 2. 스토리지 (RDS · S3)

### 2.1 RDS PostgreSQL — 세션·턴 테이블 (신규 마이그레이션)

예시 DDL (정제는 Code-gen):

```sql
CREATE TABLE evidence_sessions (
  id          BIGSERIAL     PRIMARY KEY,
  session_id  UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  owner_id    BIGINT        NOT NULL REFERENCES accounts(id),
  title       TEXT,
  status      TEXT          NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'deleted')),
  created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_ev_sessions_owner ON evidence_sessions (owner_id, updated_at DESC);
CREATE INDEX idx_ev_sessions_sid   ON evidence_sessions (session_id);

CREATE TABLE evidence_turns (
  id          BIGSERIAL     PRIMARY KEY,
  turn_id     UUID          NOT NULL UNIQUE DEFAULT gen_random_uuid(),
  session_id  UUID          NOT NULL REFERENCES evidence_sessions(session_id),
  request     JSONB         NOT NULL,
  result      JSONB,
  created_at  TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_ev_turns_session ON evidence_turns (session_id, created_at ASC);
CREATE INDEX idx_ev_turns_job     ON evidence_turns ((result->>'jobId'))
    WHERE result->>'jobId' IS NOT NULL;
```

- **owner 격리**: 앱 레벨 `WHERE owner_id = :principal` + FK. (RLS 선택 강화.)
- **소프트 삭제**: `status='deleted'` (INV-EV-1 · BR-EV-8).
- **마이그레이션**: 기존 U3/U4/U7 마이그레이션 러너 재사용(`backend/modules/evidence_agent/migrations/001_*`).

### 2.2 S3 첨부 임시 처리
- **기존 버킷 + `evidence-attachments/tmp/{jobId}/{attachmentId}` 프리픽스**.
- 수명: 추출 완료 즉시 **삭제**(INV-EV-4 · C-1). S3 라이프사이클 정책으로 미삭제 잔여분 자동 만료(예: 1일).
- IAM: U11 task role에 `s3:PutObject`·`s3:GetObject`·`s3:DeleteObject` — 해당 프리픽스 스코프만.

### 2.3 S3 DocModel (U1 소유 — read-only 소비)
- U1이 write한 DocModel 버킷 — U11은 `GetObject`만. 신규 버킷 0.
- **키 정규화**: `paperId`를 bare id로 정규화(`vN` 제거) 후 조회 — U1 키 계약 일치(U7 패턴 계승).

### 2.4 OpenSearch (U2 소유 — read-only 소비)
- U2 소유 클러스터 — U11은 쿼리만(색인 금지). IAM: `es:ESHttpGet`·`es:ESHttpPost` — 해당 도메인 스코프.

---

## 3. Bedrock 액세스 (Agent 추론)

- **모델**: `claude-sonnet-4-6` — **inference profile** 경유(`global.anthropic.claude-sonnet-4-6`). bare foundation-model id 사용 시 ValidationException(U7 교훈 계승).
- **IAM(최소권한)**: 기존 ECS task role에 추가
  - `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`
  - Resource: `...:inference-profile/global.anthropic.claude-sonnet-4-6*` + `...:foundation-model/anthropic.claude-sonnet-4-6*`
- **AgentWorker task role**: 동일 Bedrock 권한(별도 task role — 최소권한 원칙).
- **아웃바운드**: 기존 퍼블릭 서브넷 경로 재사용(NAT 0). VPC 엔드포인트는 선택 강화.

---

## 4. SQS — Evidence Agent Job Queue (신규)

- **큐 이름**: `evidence-agent-job-queue`(표준 큐). FIFO 불필요(jobId 기반 독립).
- **메시지**: `{ jobId, sessionId, turnId, request(EvidenceRequest), principalId }`.
- **가시성 타임아웃**: Agent 최대 예상 실행 시간보다 크게 설정 — 수치는 Code-gen/튜닝.
- **DLQ**: `evidence-agent-job-dlq`(재처리 실패 격리). DLQ 메시지 → TurnErrorResult{ errorCode: "job_failed" } 기록 + ObservabilityHub emit.
- **게이트**: `DOCSURI_EVIDENCE_ASYNC_ENABLED`=false(기본) · `DOCSURI_EVIDENCE_JOB_QUEUE_URL`. 미설정 시 async path 비활성(동기 전용 모드).
- **IAM**: backend task role `sqs:SendMessage` + AgentWorker task role `sqs:ReceiveMessage`·`sqs:DeleteMessage`·`sqs:ChangeMessageVisibility` — 해당 큐 ARN 스코프.

---

## 5. AgentWorker — 비동기 잡 실행 (신규 ECS 태스크)

- **배포 단위**: `backend/workers/evidence_agent_worker/` → **별도 ECS Fargate 태스크 정의**(배포 ③ 워커 계열).
- **스케일링**: SQS `ApproximateNumberOfMessagesVisible` 기반 Auto Scaling(최소 0·수치는 Infra CDK).
- **실행 시간**: Lambda 15분 제한 초과 가능(Agent 장기 실행) → ECS 선택.
- **파이프라인**: 동일 `EvidenceAgentOrchestrator` 재사용 — 비동기 경로 전용 로직 없음.
- **완료 후**: `EvidenceSessionRepository.saveTurnResult(turnId, result)` → 클라이언트 폴링 응답.

---

## 6. 모니터링 / 비용 (NFR-O1 · NFR-C1)

- **CloudWatch 메트릭**: U11 턴 지연·LLM 호출 횟수·토큰·비용 추정·기권 사유·스트리밍 건강도 → ObservabilityHub → `/docsuri/ops` 네임스페이스(기존 G3 경로).
- **비용 라인**: 시스템 비용표에 **U11 라인 추가**(Bedrock Sonnet 4.6 Agent 턴별 토큰).
  - 특성: Agent 1턴 = 복수 LLM 호출 → U7 요약 대비 **단가 높음**. 페이퍼 수에 비례.
  - [추측] 단순 분석(2~3논문) ≈ $0.3~0.5/턴 · 복잡 분석(10논문+) ≈ $1~3/턴 (Sonnet 기준 추정, 실측은 Build&Test).
- **알람**: 기존 AWS Budget($1,280 = $1,600 × 0.80) + OpsAlerts 토픽에 U11 반영. 앱 레벨 CostGuard(U6 `warning_ratio=0.80`)가 인트라데이 게이트(RES-11a · BR-EV-7).
- **SQS 메트릭**: `ApproximateNumberOfMessagesVisible`(큐 깊이)·`ApproximateAgeOfOldestMessage`(지연) — 알람 임계 = Infra.

---

## 7. 보안 매개변수

- **IAM 최소권한**: Bedrock 모델 ARN 스코프 · S3 프리픽스 스코프 · OpenSearch 도메인 스코프 · SQS 큐 ARN 스코프.
- **RDS owner 격리**: 앱 레벨 owner 스코프(INV-EV-1 · SEC-8). 기존 Secrets Manager 자격증명 재사용.
- **첨부 임시 키**: 처리 완료 즉시 S3 삭제 + 라이프사이클 안전망(INV-EV-4 · C-1).
- **시크릿**: 기존 ECS 환경변수/Secrets Manager 패턴 계승. 신규 시크릿 = SQS URL(환경변수).

---

## 8. CI 자격증명

- **단위 레인**(Fixture/Stub + Hypothesis PBT-EV-1~5): 자격증명 불필요·항상 실행.
- **통합 게이트 레인**: 스코프된 **CI IAM 역할**(OIDC, 기존 CD 패턴) — Bedrock Sonnet·S3·OpenSearch·테스트 RDS·SQS 테스트 큐 한정.
- **⚠️ CI 파이프라인 = 조율 존**.

---

## 9. 증분 비용 요약 (NFR-C1 $1,600/월 내)

| 항목 | 증분 | 비고 |
|---|---|---|
| 컴퓨트(backend 모놀리스 ECS) | **0**(모듈 추가) | |
| 컴퓨트(AgentWorker ECS) | **가변**(큐 깊이 기반 0→N) | idle 시 0(min=0 스케일) |
| S3 첨부 임시 저장 | **≈0**(추출 즉시 삭제) | 라이프사이클 안전망 |
| RDS | **≈0**(기존 인스턴스 공존) | 테이블 마이그레이션 |
| SQS | **≈0**(메시지 수 기반·수백만 건/월 무료 포함) | |
| OpenSearch / S3 DocModel | **0**(기존 U2/U1 자산 read-only) | |
| **Bedrock Sonnet 4.6 토큰** | **가변**(Agent 다중 LLM 호출 — 단가 높음) | CostGuard가 상한 방어 |
| 신규 관리형 서비스 | SQS 큐 1개 + AgentWorker 태스크 정의 1종 | |
