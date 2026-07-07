# U11 Evidence Formation Agent — Deployment Architecture (배포·네트워크·모니터링)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**근거**: `infrastructure-design.md` · NFR Design(logical-components.md) · 시스템 전역 인프라(CDK 5 스택·배포됨).
**핵심**: 기존 컴퓨트·네트워크 최대 재사용. **신규 컴포넌트**: SQS 큐 1 + AgentWorker ECS 태스크 1.

---

## 1. 컴퓨트 / 배포

- **U11 Router·Service(동기 경로)** = 기존 ECS Fargate(배포 ① backend 모놀리스) 내 모듈. 신규 서비스/태스크 0.
- **AgentWorker(비동기 경로)** = **신규 ECS Fargate 태스크 정의**(배포 ③ 워커 계열 — U7 비동기 잡 패턴 계승).
  - SQS long-polling 루프 → 메시지 수신 → EvidenceAgentOrchestrator 실행 → RDS write.
  - 스케일링: `ApproximateNumberOfMessagesVisible` 기반 Auto Scaling(min=0·수치=Infra CDK).
  - 실행 시간 제약: ECS(무제한) 선택 — Lambda 15분 한계 초과 가능.

```
[CloudFront/ACM] → [ALB] → [ECS Fargate: backend 모놀리스]
                                  ├─ U2 Discovery    ├─ U3 Accounts
                                  ├─ U4 Library      ├─ U6 미들웨어(게이트웨이)
                                  ├─ U7 Summarization
                                  └─ U11 Evidence Agent  ◀── 신규 모듈(컴퓨트 0)
                                         │ 복잡 요청
                                         ▼
                                  [SQS: evidence-agent-job-queue]  ◀── 신규
                                         │
                                         ▼
                      [ECS Fargate: AgentWorker]  ◀── 신규 태스크
                                  │     │     │     │      │
                                  ▼     ▼     ▼     ▼      ▼
                               RDS    S3   OpenSearch Bedrock CloudWatch
                            sessions DocModel U2 클러스터 Sonnet 4.6 메트릭
```

---

## 2. 네트워크 토폴로지

- **기존 VPC/ALB 재사용** — 신규 서브넷/ALB 0. 인그레스 = ALB(HTTPS, CloudFront 오리진).
- **Bedrock 아웃바운드**: 기존 퍼블릭 서브넷 경로(NAT 0, 시스템 패턴). VPC 엔드포인트는 선택 강화.
- **OpenSearch 접근**: U2 OpenSearch 클러스터 VPC 내부 접근 — 기존 보안그룹(U11 태스크 sg → OpenSearch sg inbound) 증분 허용.
- **SQS 접근**: VPC 엔드포인트(기존) 또는 퍼블릭 경로.
- **AgentWorker 네트워크**: 동일 VPC — RDS·S3·OpenSearch·Bedrock·SQS 접근 동일 패턴.
- 데이터 계층(RDS)은 기존 격리 서브넷·보안그룹(ECS만 인바운드) 계승.

---

## 3. 모니터링

- **CloudWatch**: U11 턴 지연·LLM 호출 횟수·토큰·비용·기권 사유·스트리밍 건강도(ObservabilityHub → `/docsuri/ops` 네임스페이스, 기존 G3). 앱 로그 = 기존 로그그룹(retention 30일).
- **SQS 메트릭**: `ApproximateNumberOfMessagesVisible`·`ApproximateAgeOfOldestMessage` — 큐 깊이·지연 알람.
- **DLQ 알람**: `evidence-agent-job-dlq` 메시지 수 > 0 → OpsAlerts 토픽.
- **알람/Budget**: 기존 OpsAlerts 토픽·AWS Budget($1,280)에 U11 Bedrock 비용 반영.
- **ALB 네이티브 메트릭**(5xx·p95)은 모놀리스 공통 — U11 경로 포함.

---

## 4. IaC 증분 (조율 존)

기존 CDK 스택에 **증분 추가**(신규 스택 최소):

| 스택 | U11 증분 |
|---|---|
| **Compute** | backend task role: Bedrock IAM(Sonnet ARN 스코프) + S3 evidence-attachments/tmp 정책 + OpenSearch read 정책 · SQS SendMessage 정책 |
| **Compute(Worker)** | AgentWorker ECS 태스크 정의 + Auto Scaling(SQS 기반) + task role(Bedrock·S3·OpenSearch·SQS ReceiveMessage·RDS) |
| **Messaging** | SQS `evidence-agent-job-queue` + `evidence-agent-job-dlq` |
| **Storage** | S3 `evidence-attachments/tmp/` 라이프사이클(1일 자동 만료) |
| **DB 마이그레이션** | `evidence_sessions`·`evidence_turns` 테이블 + 인덱스 — 기존 마이그레이션 러너 |
| **CI/CD** | 통합 테스트 게이트 레인 + 스코프 CI 역할(OIDC) |

- **⚠️ 전부 Infra 담당자 사인오프** — U11 제안, Infra 합의 후 반영.
- **게이트**: `DOCSURI_EVIDENCE_ASYNC_ENABLED`=false(기본) — 비동기 인프라 선배포 후 점진 활성화.
- CD/무중단 배포·롤백 = 기존 ECR 빌드·ECS 롤링 계승(U11 모듈·AgentWorker 포함).

---

## 5. 배포 체크리스트 (Code-gen/Build&Test 연계)

- [ ] ECS backend task role: Bedrock Sonnet ARN · S3 첨부 프리픽스 · OpenSearch read · SQS SendMessage IAM 증분
- [ ] AgentWorker ECS 태스크 정의 + Auto Scaling CDK
- [ ] AgentWorker task role: Bedrock · S3 · OpenSearch · SQS ReceiveMessage/DeleteMessage · RDS
- [ ] SQS `evidence-agent-job-queue` + `evidence-agent-job-dlq` 생성(CDK)
- [ ] S3 `evidence-attachments/tmp/` 라이프사이클(1일 만료) 적용
- [ ] RDS 마이그레이션: `evidence_sessions`·`evidence_turns` + 인덱스
- [ ] CloudWatch U11 메트릭 네임스페이스·DLQ 알람·Budget 반영
- [ ] CI 통합 게이트 레인 + 스코프 IAM 역할(OIDC)
- [ ] app-shell 마운트(`backend/wiring.py`) — 조율 존 사인오프
- [ ] `DOCSURI_EVIDENCE_ASYNC_ENABLED` 환경변수 구성

> 구체 수치(SQS 가시성 타임아웃·AgentWorker 스케일 임계·Auto Scaling 목표·라이프사이클 일수)는 Code-gen/튜닝.
