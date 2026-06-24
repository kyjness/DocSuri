# U7 Summarization — Deployment Architecture (배포·네트워크·모니터링)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U7 Summarization · **일자**: 2026-06-19
**근거**: 계획서 9문 A · `infrastructure-design.md` · 시스템 전역 인프라(CDK 5 스택·배포됨).
**핵심**: U7 = 기존 ECS Fargate 모놀리스 모듈 — **신규 컴퓨트·네트워크·메시징 0**. IaC는 기존 스택 증분.

---

## 1. 컴퓨트 / 배포 (Q1)

- **U7 = 기존 ECS Fargate(배포 ① backend 모놀리스) 내 모듈** — 신규 서비스/태스크 0.
- `backend/modules/summarization/`(독립 pyproject) → app-shell 마운트(`backend/wiring.py`, **⚠️ 조율 존**), U6 게이트웨이 경유(`/api/summarize` · `/api/glossary`[개인 용어집 조회·저장, BR-S4]).
- 오토스케일·태스크 사양 = 기존 모놀리스 구성 계승(온디맨드 LLM 대기는 async I/O 흡수). 별도 스케일링 정책 불요(LLM 동시성은 Bedrock 쿼터·CostGuard로 경계).

```
[CloudFront/ACM] → [ALB] → [ECS Fargate: backend 모놀리스]
                                   ├─ U2 Discovery   ├─ U3 Accounts
                                   ├─ U4 Library     ├─ U6 미들웨어(게이트웨이)
                                   └─ U7 Summarization  ◀── 신규 모듈(컴퓨트 0)
                                         │
            ┌────────────────────────────┼───────────────────────┐
            ▼                ▼            ▼            ▼           ▼
          S3            ElastiCache     RDS         Bedrock    CloudWatch
       summaries/        sum: TTL    user_glossary  Sonnet/Haiku  메트릭/Budget
```

---

## 2. 네트워크 토폴로지 (Q5)

- **기존 VPC/ALB 재사용** — 신규 서브넷/ALB 0. 인그레스 = ALB(HTTPS, CloudFront 오리진).
- **Bedrock 아웃바운드** = 기존 퍼블릭 서브넷 경로(NAT 0, 시스템 패턴). VPC 엔드포인트는 선택 강화.
- 데이터 계층(RDS/Redis)은 기존 격리 서브넷·보안그룹(ECS만 인바운드) 계승.

---

## 3. 모니터링 (Q6)

- **CloudWatch**: U7 토큰·비용·지연·근거화 메트릭(ObservabilityHub→`/docsuri/ops` 네임스페이스, 기존 G3). 앱 로그 = 기존 로그그룹(retention 30일).
- **알람/Budget**: 기존 OpsAlerts 토픽·AWS Budget($1,280)에 U7 토큰 비용 반영. 앱 레벨 CostGuard(U6)는 인트라데이 게이트.
- **ALB 네이티브 메트릭**(5xx·p95)은 모놀리스 공통 — U7 경로 포함.

---

## 4. 메시징 (Q8)

- **v1 미프로비저닝** — 비동기 잡(SQS+워커) 없음. 동기 스트리밍 + 입력 토큰 캡(TD-S9).
- 후속(초장문 비동기) 도입 시 기존 EventBridge/Ops 워커(배포 ③) 패턴 재사용 — 본 v1 범위 밖.

---

## 5. IaC 증분 (Q9 — 조율 존)

기존 CDK 스택에 **증분 추가**(신규 스택 0):

| 스택 | U7 증분 |
|---|---|
| **Compute** | ECS task role에 Bedrock IAM(모델 ARN 스코프) + S3 `summaries/`·전문 read 정책 + CloudWatch PutMetric(기존) |
| **Search/Storage** | S3 `summaries/` 프리픽스 라이프사이클(선택) |
| **DB 마이그레이션** | `user_glossary` 테이블 — 기존 마이그레이션 러너 |
| **CI/CD** | 통합 테스트 게이트 레인 + 스코프 CI 역할(OIDC) |

- **⚠️ 전부 @ELSAPHABA/Infra 사인오프** — U7 제안, Infra 합의 후 반영.
- CD/무중단 배포·롤백 = 기존 ECR 빌드·ECS 롤링 계승(U7 모듈 포함).

---

## 6. 배포 체크리스트 (Code-gen/Build&Test 연계)

- [ ] ECS task role Bedrock/S3 IAM 증분(Compute 스택)
- [ ] `user_glossary` 마이그레이션 적용(RDS)
- [ ] Redis `sum:` 키스페이스 TTL(앱 구성)
- [ ] CloudWatch U7 메트릭 네임스페이스·Budget 반영
- [ ] CI 통합 게이트 레인 + 스코프 역할
- [ ] app-shell 마운트(`backend/wiring.py`) — 조율 존 사인오프

> 구체 수치(TTL·토큰 캡·오토스케일·라이프사이클 일수)는 Code-gen/튜닝.
