# u11-research-agent-infrastructure-design-plan.md — Infrastructure Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Infrastructure Design (유닛별 루프) · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `u11-research-agent/nfr-design/`(논리 컴포넌트·토폴로지) · `nfr-requirements/`(TD-RA-1~15) · `functional-design/` · 시스템 전역 `construction/infrastructure-design/infrastructure-design.md` · 아키텍처 게이트 `docmodel-fulltext-index-pivot-plan.md`.
**핵심 방향(선례 계승)**: U7처럼 **신규 관리형 서비스 최소화 — 기존 프로덕션 자산 재사용 + 자원 증분**. 리전 = **ap-northeast-2(서울)**. 단 U11은 **① SQS Agent 워커(비동기 잡)** 와 **② 전문 통합 인덱스 노드 증설(아키텍처 게이트)** 라는 신규/증설 요소가 있음.
**선례 비교(실제 정독 반영)**:
- **시스템 전역 `infrastructure-design.md`** ★ — OpenSearch 도메인 `docsuri-papers`(**VPC-내부·m6g.large.search×2 Multi-AZ·FGAC·~$220/월**), SQS 큐/DLQ 패턴(SSE-SQS·maxReceiveCount=3·14일 보존·요약잡 900s 가시성), S3 단일버킷 `docsuri-papers-fulltext-{env}` 프리픽스(`doc-model/`·`full-text/`·`summary/`), IAM 역할 4종, **비용 ~$370-400/$1,600(25% — 노드 업그레이드 여유 큼)**, Multi-AZ·NAT 배제 토폴로지.
- **U7** — 논리→AWS 매핑·S3 프리픽스·Redis 키스페이스·RDS 테이블·**요약 워커=`docsuri-api` 이미지 재사용(entrypoint)·신규 task role**·증분 비용.
- **U8** — 외부 API 시크릿(env)·Redis prefix·feature flag·쿼터(모드 B 참고, **신규 인프라 0**).
- **U3**(deployment-architecture) — VPC·서브넷·Multi-AZ·시크릿(시스템 전역에 흡수).

> 본 계획서는 **리뷰 게이트**다. `[Answer]:`가 모두 확정되기 전에 Infra 산출물(`infrastructure-design.md`·`deployment-architecture.md`)을 만들지 않는다. **본 게이트는 질문만 — 결정은 답변 후.**

---

## 1. 유닛 컨텍스트 (Infra 렌즈)

U11 = backend 모놀리스 모듈(동기) + **Agent 워커(비동기 잡)**. 대부분 기존 자산 재사용(ECS·RDS·Redis·S3·Bedrock·CloudWatch)이나, **신규/증설 2가지**: (1) **SQS 큐 + Agent 워커**(긴 다논문 분석), (2) **전문 통합 인덱스 → OpenSearch 노드 증설**(아키텍처 게이트·#120 추정 월 +$100~220). 후자는 **U1/U2/infra 조율 + 게이트 승인** 선결.

---

## 2. Infrastructure Design 실행 계획 (답변 확정 후, 체크박스)

`aidlc-docs/construction/u11-research-agent/infrastructure-design/`에 작성:
- [ ] **infrastructure-design.md** — 논리→AWS 매핑·스토리지(RDS 테이블·S3 프리픽스·Redis 키스페이스·OpenSearch 사이징)·Bedrock IAM·SQS·모니터링/비용·보안·CI 자격증명·증분 비용 요약.
- [ ] **deployment-architecture.md** — 컴퓨트/배포(모듈+워커)·네트워크 토폴로지·메시징·IaC 증분·배포 체크리스트.

---

## 3. 가정 (잘못이면 §4 또는 지적으로 정정)

- **AS-I1**: 리전 ap-northeast-2·기존 VPC/서브넷/ALB/CloudFront·Secrets Manager·CD(ECR/ECS) 패턴 계승.
- **AS-I2**: U6 게이트웨이·근거화·CostGuard·ObservabilityHub→CloudWatch는 기존 경로 재사용(신규 0).
- **AS-I3**: 전문 통합 인덱스·eager doc-model·OpenSearch 노드 증설은 **아키텍처 게이트 결정** + U1/U2/infra 조율(본 유닛 단독 확정 아님).
- **AS-I4**: 수치(인스턴스 사양·TTL·SQS 가시성 타임아웃·K·서킷 임계)는 본 단계에서 형태/등급까지, 정밀 튜닝은 Code-gen/Build&Test.
- **AS-I5**: 조율 존(`backend/wiring.py`·게이트웨이·CI/CD·IAM task role)은 app-shell/Infra(@ELSAPHABA) 사인오프.

---

## 4. 명확화 질문 (`[Answer]:` 태그; 권장안=A, 변경 시 B/C/X+사유)

### A. 컴퓨트 / 배포 (Compute / Deployment)

#### Q1 — 동기 모듈 배포 (U7 §1 패턴)
U11 동기 경로 컴퓨트는?

A) **ECS Fargate 기존 backend 모놀리스에 모듈 추가(권장)** — ALB 후면, 신규 컴퓨트 0. (U7과 동형)

B) 별도 서비스.  X) 기타.

[Answer]: 

#### Q2 — Agent 워커(비동기 잡) 배포 (U7 SQS 워커 / U8 런타임 패턴)
긴 다논문 분석 워커는?

A) **별도 ECS 서비스(SQS 소비)로 분리·`docsuri-api` 이미지 재사용(권장)** — 요약 워커(`docsuri-summary-worker`) 선례 그대로: 별도 이미지 없이 `docsuri-api` ECR 이미지에 entrypoint(`python -m research_agent.worker`), scale-to-zero(min 0), 신규 `docsuri-agent-worker-task-role`. 게이트웨이 타임아웃 무관·독립 스케일. env 게이트 미설정 시 대규모는 abstain(안전 저하).

B) 동기 모듈 내 백그라운드 스레드.  C) 별도 이미지/Lambda.  X) 기타.

[Answer]: 

### B. 스토리지 (Storage)

#### Q3 — 세션·결과 RDS (U7 §2.3 테이블 패턴)
세션·턴·결과 영속은?

A) **기존 RDS PostgreSQL + 신규 테이블(권장)** — `research_session`·`research_turn`·`research_result`(owner FK·인덱스). 마이그레이션 러너 재사용. 큰 근거표 본문은 JSONB 또는 S3 참조.

B) 신규 DB.  X) 기타.

[Answer]: 

#### Q4 — 첨부·결과 S3 (U7 §2.1 프리픽스 패턴)
첨부 원본·대용량 결과는?

A) **기존 S3 버킷 + 프리픽스(권장)** — `research-agent/attachments/{ownerId}/...`·(옵션)`research-agent/results/...`. SSE-KMS·owner 스코프·IAM 프리픽스 스코프. 라이프사이클은 운영 옵션.

B) 신규 버킷.  X) 기타.

[Answer]: 

#### Q5 — 결과 캐시 Redis (U7 §2.2 키스페이스 패턴)
`AgentCacheKey` 핫캐시는?

A) **기존 ElastiCache + 키스페이스 `agent:`(권장)** — 세션 캐시와 분리·TTL. 신규 노드 0(메모리 모니터). 영구는 S3/RDS.

B) 신규 캐시.  X) 기타.

[Answer]: 

#### Q6 — 전문 통합 인덱스 사이징 (아키텍처 게이트 · #120 · GQ1)
전문 색인 OpenSearch는?

A) **게이트·실험 종속 — 사이징 확정 안 함(권장)**. 구체 사실만 기록: 현재 단일 공유 도메인 **`docsuri-papers` m6g.large.search×2 Multi-AZ(~$220)**, 전문 색인 도입 시 **벡터 ~12~18배 → 노드 업그레이드(r6g.large/m6g.xlarge) 또는 3노드**(시스템 전역 §6: 상한 내 가능, 현재 ~$370-400/$1,600). **eager doc-model은 인제스천 워커 변경**(현재 lazy `BUILD_DOC_MODEL` 잡 → eager). granularity(GQ1) 미정. 확정 = 게이트 승인 + U1/U2/infra 조율.

B) 지금 노드 등급·granularity 확정.  X) 기타.

[Answer]: 

### C. 통합 / 네트워크 (Bedrock / Networking)

#### Q7 — Bedrock IAM (U7 §3 ARN 스코프 패턴)
LLM 액세스 권한은?

A) **기존 권한 재사용 + 워커 role 추가(권장)** — **`docsuri-api-task-role`엔 이미 Sonnet/Haiku `InvokeModel`이 부여됨(U7)** → U11 동기 모듈은 IAM 증분 0. 신규 `docsuri-agent-worker-task-role`에만 동일 모델 ARN 스코프 부여. ⚠️ task role 변경=조율 존.

B) 광범위 권한.  X) 기타.

[Answer]: 

#### Q8 — 검색/doc-model/OpenSearch 액세스 경로
U11이 검색·doc-model에 어떻게 접근?

A) **U2 검색 재사용 + doc-model 읽기(권장)** — **`docsuri-api-task-role`엔 이미 `doc-model/* GetObject`가 부여됨(U7 리치뷰/요약)** → U11 doc-model 읽기 IAM 증분 0. OpenSearch는 **VPC-내부 도메인**(공유)·U2 경유(직접 질의 시 OpenSearch read 권한·SG 인바운드 추가 — U2 API 재사용 vs 직접 질의는 FD Q2 미정). 아웃바운드 Bedrock/SQS/S3는 기존 IGW 경로(NAT 0).

B) U11이 OpenSearch 직접 접근.  X) 기타.

[Answer]: 

### D. 메시징 (Messaging — 비동기 잡)

#### Q9 — SQS 큐 (U7 요약 큐 / U8 패턴)
비동기 잡 큐는?

A) **신규 SQS 큐 `docsuri-agent-job-queue` + DLQ(권장 — 요약잡 큐 패턴)** — SSE-SQS·maxReceiveCount=3·14일 보존·가시성 ~900s(다논문 fan-out·요약잡과 동급)·멱등(캐시 히트). 워커 소비, EventBridge 무관(API가 enqueue). 게이트 env(`DOCSURI_AGENT_JOB_QUEUE_URL`)로 on/off. 수치는 Code-gen.

B) 기존 인제스천/요약 큐 공유.  C) 큐 없이 동기만.  X) 기타.

[Answer]: 

### E. 모니터링 / 비용 (Monitoring / Cost)

#### Q10 — CloudWatch·비용 라인 (U7 §4 패턴)
관측·비용은?

A) **ObservabilityHub→CloudWatch(기존 G3 경로) + 시스템 비용표에 U11 라인 추가(권장)** — 모드별 토큰·지연·기권/저하·외부 오류율. 비용 = Bedrock 토큰(가변) + (게이트 시)인덱스 노드 증분. AWS Budget·OpsAlerts 반영. 앱 게이트=U6 CostGuard(RES-11a).

B) 비용만.  X) 기타.

[Answer]: 

### F. CI 자격증명 (Shared / Deployment)

#### Q11 — CI 레인 자격증명 (U7 §6 패턴)
통합 테스트 자격증명은?

A) **스코프된 CI IAM 역할(OIDC, 기존 CD 패턴)(권장)** — Bedrock 모델·S3 `research-agent/*`·테스트 RDS/Redis/SQS·U2 검색 한정. 단위 레인은 자격증명 불필요. ⚠️ CI 파이프라인=조율 존.

B) 광범위 자격증명.  X) 기타.

[Answer]: 

### G. 공유 인프라 (Shared Infrastructure)

#### Q12 — IaC 증분 + 공유 전략 (시스템 전역 / U7 §5 패턴)
IaC는 어떻게?

A) **시스템 CDK에 U11 증분(권장)** — RDS 테이블·S3 프리픽스·Redis 키스페이스·SQS 큐+DLQ·Agent 워커 서비스·IAM. 전문 인덱스 노드 증설은 게이트 승인 후 별도(U1/U2/infra). 신규 스택 최소화. ⚠️ 조율 존.

B) U11 전용 스택 신설.  X) 기타.

[Answer]: 

#### Q13 — 증분 비용 요약 (U7 §7 패턴)
비용 요약 방식은?

A) **증분 표(권장)** — 기준선 현재 **~$370-400/$1,600(25%·여유 큼)**. 증분: 컴퓨트(동기 모듈 0·워커 scale-to-zero 소액)·RDS/Redis/S3 프리픽스(무시~소액)·**Bedrock 토큰(가변·다논문 fan-out=단건의 K배·K 상한·캐시 bound)**·**(게이트 시)OpenSearch 노드 업그레이드(r6g/3노드, 시스템 §6 상한 내·실측 배포 후)**·SQS(소액). NFR-C1 상한 내.

B) 단일 총액.  X) 기타.

[Answer]: 

---

## 5. 다음 절차
1. **Q1~Q13 답변 확정**(애매 시 후속 질문) — 본 게이트는 질문만.
2. 답변 후 `u11-research-agent/infrastructure-design/`에 `infrastructure-design.md`·`deployment-architecture.md` 생성.
3. 승인 후 **Code Generation**(코드·테스트·배포 스캐폴드).
4. **전문 인덱스 사이징·granularity(GQ1)·랭킹(GQ2)** 은 아키텍처 게이트 승인 + U1/U2/infra 조율 + 실험으로 확정(본 유닛 단독 아님).
5. 커밋·푸시·PR(#183)은 사용자 승인 후.
