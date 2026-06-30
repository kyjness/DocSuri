# Novelty Agent — Infrastructure Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> Infrastructure Design  
**유닛**: Novelty Agent  
**일자**: 2026-06-29  
**상태**: 확정 — `infradesign-answer.md` 답변 반영, Infrastructure Design 산출물 생성 완료
**근거**: `construction/novelty-agent/functional-design/`, `construction/novelty-agent/nfr-requirements/`, `construction/novelty-agent/nfr-design/`

## 1. Infrastructure Design 렌즈

- **Compute**: backend API + ECS/Fargate worker.
- **Messaging**: SQS queue + DLQ.
- **Storage**: RDS metadata/events/export state + S3 stage artifacts.
- **Streaming**: API service SSE endpoint over existing ALB/CloudFront path.
- **Secrets**: Notion token encryption/revocation.
- **Observability**: CloudWatch/U6 ObservabilityHub metrics and logs.

## 2. Infrastructure Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/novelty-agent/infrastructure-design/`에 작성한다.

- [x] `infrastructure-design.md`
  - AWS service mapping
  - storage and encryption mapping
  - queue/DLQ mapping
  - observability and alarms
  - security controls
- [x] `deployment-architecture.md`
  - API/worker deployment topology
  - network/data flow
  - scaling and rollback notes
  - environment variables/secrets

---

## 3. 명확화 질문

아래 `[Answer]:`를 모두 채운 뒤 Infrastructure Design 산출물 생성을 진행한다.

### Q1 — Deployment environment
novelty Agent 인프라는 어떤 환경에 붙일까요?

A) 기존 AWS CDK 스택과 develop/prod 배포 패턴에 추가한다. (권장)

B) 별도 AWS 계정/스택으로 분리한다.

C) 로컬/PoC 전용으로만 둔다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q2 — Worker infrastructure
novelty worker는 어떤 compute로 배치할까요?

A) 기존 Fargate worker 패턴을 재사용해 SQS consumer task/service로 배치한다. (권장)

B) Lambda 함수 여러 개로 분해한다.

C) backend API task 안의 background thread로 실행한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q3 — Queue and DLQ
job queue는 어떻게 둘까요?

A) novelty 전용 SQS queue + DLQ를 만들고 visibility timeout은 최장 stage 실행 시간을 기준으로 둔다. (권장)

B) 기존 ingestion queue를 공유한다.

C) queue 없이 RDS polling만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 단, 마이그레이션은 기존 커스텀 SQL 러너(`backend/migrations`, 번호 `.sql` + `_migrations` 테이블) 사용. Alembic 도입 금지.

### Q4 — RDS schema
RDS에는 어떤 테이블을 둘까요?

A) `novelty_jobs`, `novelty_progress_events`, `novelty_artifacts`, `novelty_exports`를 owner-scoped로 둔다. (권장)

B) 단일 JSON 테이블 하나만 둔다.

C) RDS 없이 S3만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q5 — S3 artifact storage
stage artifact 저장은 어떤 bucket/prefix를 쓸까요?

A) 기존 private papers/artifact bucket 패턴을 재사용하고 `novelty/{ownerHash}/{jobId}/...` prefix로 분리한다. (권장)

B) public bucket에 저장한다.

C) artifact를 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 보정: 기존 버킷 prefix는 paper-scoped이고 owner 격리는 앱 레이어에서 강제됨. 전용 `novelty/` prefix(또는 별도 버킷)로 lifecycle 분리 권장.

### Q6 — SSE infrastructure
SSE는 기존 ALB/CloudFront 경로에서 어떻게 다룰까요?

A) 기존 API service에 SSE endpoint를 추가하고 idle timeout/keepalive만 Infra/Code에서 명시한다. (권장)

B) 별도 WebSocket API Gateway를 도입한다.

C) SSE를 포기하고 polling만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 보정: 현재 repo에 SSE 없음(기존 비동기 작업은 S3 폴링). 신규 컴포넌트로 다루고 polling fallback을 저위험 앵커로 유지.

### Q7 — Notion secrets
Notion OAuth/token 저장은 어떤 인프라를 쓸까요?

A) RDS에는 연결 metadata만 두고 token secret은 KMS/Secrets Manager 또는 기존 암호화 secret 패턴으로 저장한다. (권장)

B) token을 RDS 평문 컬럼에 저장한다.

C) token을 job payload에 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 보정: 사용자별 token이므로 사용자당 Secrets Manager 항목은 비확장적. 암호화 RDS 컬럼(KMS envelope encryption)으로 token 저장 + Secrets Manager에는 KMS/OAuth 앱 자격 증명.

### Q8 — Network egress
Agent-Browser/GitHub/dataset/Notion 외부 호출 egress는 어떻게 제한할까요?

A) worker outbound allowlist/config와 request-level SSRF guard를 두고, raw manuscript/Evidence는 외부 query로 보내지 않는다. (권장)

B) worker에서 모든 outbound를 unrestricted로 허용한다.

C) 외부 호출은 사용자 브라우저에서 수행한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 주의: 재사용 가능한 SSRF guard/outbound allowlist가 현재 부재(per-call httpx timeout만 존재). novelty가 플랫폼 최초의 비신뢰 egress이므로 신규 보안 통제로 명시 필요.

### Q9 — Scaling
worker scaling은 어떤 기준으로 둘까요?

A) queue depth, age of oldest message, CPU/memory, CostGuard budget state를 기준으로 min/max를 제한한다. (권장)

B) 항상 max worker로 실행한다.

C) 수동으로만 스케일한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 보정: CostGuard는 budget circuit-breaker(지출 게이트/`degraded` 강제)이며 autoscaling 지표 아님. 스케일은 queue depth + age of oldest message + CPU/mem 기준, CostGuard는 지출 게이트로 분리.

### Q10 — Observability and alarms
알람은 어디에 둘까요?

A) 기존 CloudWatch/U6 경로에 queue age, DLQ count, stage failure, Notion failure, budget exceeded, half-baked completion alarm을 추가한다. (권장)

B) 로그만 남기고 알람은 만들지 않는다.

C) novelty 전용 별도 관측 스택을 만든다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## 4. 답변 후 생성할 산출물 요약

답변 확정 후 다음 문서를 생성한다.

- `infrastructure-design.md`: AWS 서비스 매핑, 저장소/암호화, queue/DLQ, observability, security controls
- `deployment-architecture.md`: API/worker topology, network/data flow, scaling, secrets/env
