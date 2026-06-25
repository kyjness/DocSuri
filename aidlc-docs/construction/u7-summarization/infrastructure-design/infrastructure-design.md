# U7 Summarization — Infrastructure Design (AWS 리소스 매핑)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U7 Summarization · **일자**: 2026-06-19
**근거**: 계획서 `u7-summarization-infrastructure-design-plan.md`(9문 전수 A) · NFR Design(논리 컴포넌트) · 시스템 전역 `construction/infrastructure-design/infrastructure-design.md`.
**핵심**: **신규 관리형 서비스 0** — 전부 기존 프로덕션 자산 재사용. U7은 기존 인프라에 **자원 증분 추가**(프리픽스·키스페이스·테이블·IAM·비용 라인). 리전 = **ap-northeast-2(서울)**.

---

## 1. 논리 컴포넌트 → AWS 리소스 매핑

| 논리 컴포넌트 | AWS 리소스 | 신규/재사용 |
|---|---|---|
| U7 Router·Orchestration | **ECS Fargate**(배포 ① backend 모놀리스, ALB 후면) | 재사용(모듈 추가) |
| SummaryStoreAdapter(영구) | **S3** — 기존 버킷 `summaries/` 프리픽스 | 재사용(프리픽스 추가) |
| SummaryStoreAdapter(핫) | **ElastiCache Redis** — `sum:` 키스페이스 + TTL | 재사용(키스페이스 추가) |
| FullTextSourceAdapter | **S3** — 기존 전문(`stored_full_text_ref`) read | 재사용 |
| GlossaryRepository | **RDS PostgreSQL** — 신규 테이블 `user_glossary` | 재사용(테이블 추가·마이그레이션) |
| BedrockLlmGatewayAdapter | **Bedrock** — Sonnet 4.6·Haiku 4.5(InvokeModel/Stream) | 재사용(IAM 권한 추가) |
| CostGate/Telemetry | **Ports → U6**(CloudWatch 경유) | 재사용 |

---

## 2. 스토리지 (Q2·Q3·Q4)

### 2.1 S3 요약 객체 (Q2)
- **기존 버킷 + `summaries/` 프리픽스**. 경로: `summaries/{paperId}/v{version}/{task}_{lang}_{scope}_{persona}_g{glossaryVer}[_u{ownerId}]_{modelVer}_{promptVer}.json`. 신원 차원은 BR-S1과 일치(`glossaryVer` 포함 → 용어 변경 시 키 변경으로 무효화; translate는 `scope`=abstract|full로 산출물 분기). `_u{ownerId}` 세그먼트는 **개인화 산출물(`glossaryVer > 0`)에만** 붙어 사용자 간 충돌을 막고, 베이스라인(`glossaryVer == 0`)은 owner 무관·공유.
- **라이프사이클**: 현행 키 **영구 보존**(immutable·INV-5). glossaryVer/modelVer/promptVer 변경 시 옛 객체 미참조 방치 → 선택적 라이프사이클 만료(예 미참조 90일)는 운영 옵션.
- **IAM**: U7 task role은 `s3:GetObject`/`PutObject` **프리픽스 스코프**(`arn:.../summaries/*`) + 전문 read(`GetObject` 전문 프리픽스).
- 용량: ~2KB×30만 ≈ 600MB(무시 수준).

### 2.2 ElastiCache Redis 핫캐시 (Q3)
- **기존 클러스터 + 키스페이스 프리픽스 `sum:`**(세션 캐시와 분리). 값 = 요약/번역 JSON. **TTL**(구체값 Code-gen).
- 메모리: 요약 ~2KB·핫셋 한정 → CloudWatch `DatabaseMemoryUsagePercentage` 모니터. 신규 노드 0.

### 2.3 RDS PostgreSQL 개인 용어집 (Q4)
- **기존 DB + 신규 테이블** (예시 DDL — 정제는 Code-gen):
```sql
CREATE TABLE user_glossary (
  id           BIGSERIAL PRIMARY KEY,
  user_id      BIGINT NOT NULL REFERENCES accounts(id),
  term_from    TEXT   NOT NULL,
  term_to      TEXT   NOT NULL,
  glossary_ver INT    NOT NULL DEFAULT 1,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, term_from)
);
CREATE INDEX idx_user_glossary_owner ON user_glossary (user_id);
```
- **owner 격리**: 앱 레벨 owner 스코프(쿼리 `WHERE user_id = :principal`) + FK. (RLS는 선택 강화.)
- **마이그레이션**: 기존 U3/U4 마이그레이션 러너 재사용(`backend/modules/summarization/migrations/001_*`).
- 시드 도메인 용어집(P1 공유·고정)은 **코드/구성 자산**(DB 아님).

---

## 3. Bedrock 액세스 + 네트워크 (Q5)

- **IAM(최소권한)**: 기존 ECS task role에 추가
  - `bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`
  - **Resource = 모델 ARN 스코프**: `...:foundation-model/anthropic.claude-sonnet-4-6*`, `...claude-haiku-4-5*`(리전 inference profile ARN 포함).
- **아웃바운드**: 기존 **퍼블릭 서브넷 경로**(NAT 0, U3/시스템 패턴) 재사용. Bedrock VPC 엔드포인트는 보안 강화 선택 옵션(Infra trade-off).
- **⚠️ task role 변경 = 조율 존**(@ELSAPHABA/Infra).

---

## 4. 모니터링 / 비용 (Q6)

- **CloudWatch 메트릭**: U7 토큰·비용(모델별)·지연·근거화 결과 → ObservabilityHub→CloudWatch(`CLOUDWATCH_NAMESPACE`, 기존 G3 경로).
- **비용 라인**: 시스템 비용표에 **U7 라인 추가**(Bedrock Sonnet/Haiku 토큰, 가변). distinct×1 영구저장으로 bounded.
- **알람**: 기존 **AWS Budget($1,280 임계)·OpsAlerts** 토픽에 U7 반영. 앱 레벨 CostGuard(U6)는 인트라데이 게이트(RES-11a).
- 신규 스택/대시보드 0.

---

## 5. 보안 매개변수

- **IAM 최소권한**: Bedrock 모델 ARN 스코프 · S3 `summaries/`·전문 프리픽스 스코프 · RDS = 기존 시크릿(Secrets Manager) 자격증명.
- **RDS owner 격리**: 앱 레벨 owner 스코프(개인 용어집 cross-user 차단, SEC-8).
- **시크릿**: 기존 ECS 환경변수/Secrets Manager 패턴 계승(신규 시크릿 = 없음; Bedrock는 task role IAM).

---

## 6. CI 자격증명 (Q7)

- **단위 레인**(Fixture/Stub): 자격증명 불필요·항상 실행.
- **통합 게이트 레인**: 스코프된 **CI IAM 역할**(OIDC, 기존 CD 패턴) — Bedrock 모델·S3 `summaries/`·테스트 RDS/Redis 한정. PR 게이트 또는 주기 실행.
- **⚠️ CI 파이프라인 = 조율 존**.

---

## 7. 증분 비용 요약 (NFR-C1 $1,600/월 내)

| 항목 | 증분 |
|---|---|
| 컴퓨트(ECS) | **0**(기존 모놀리스 모듈) |
| S3 저장 | ~무시(600MB) |
| Redis/RDS | **0**(기존 노드/인스턴스 공존) |
| **Bedrock 토큰** | **가변**(요약 Sonnet ≈$0.1~0.2/건·번역 Haiku ≈$0.01~0.02/건, distinct×1 bounded) |
| 신규 관리형 서비스 | **0** |

> 증분 인프라 비용 ≈ **Bedrock 토큰(가변)** 중심. NFR-C1 상한 여유(현재 ~$370-400 사용). 비동기 잡 인프라 v1 미프로비저닝(Q8).
