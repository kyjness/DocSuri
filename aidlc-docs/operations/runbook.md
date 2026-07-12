# DocSuri 운영 런북 (Operations Runbook)

> AWS account `028317349537` · region `ap-northeast-2` (Seoul)
> CONSTRUCTION 종료·프로덕션 배포 2026-06-18. 본 문서는 OPERATIONS 단계 산출물.
> 모든 값은 코드에서 추출한 ground-truth. 코드가 바뀌면 이 문서도 갱신할 것.

## 1. 시스템 맵

CDK 스택 8개 (`ops/cdk/app.py`, account/region 하드코딩 `app.py:20`):

| 스택 | 배포단위 | 제공 | RemovalPolicy 트랩 |
|---|---|---|---|
| `Docsuri-Network` | — | VPC, 2 AZ, **NAT 0개**(비용절감), public/isolated subnet | 없음 |
| `Docsuri-Search` | — | OpenSearch alias `docsuri-corpus` (2.19, m6g.large ×2, kNN 1024 + BM25) | **RETAIN** (`search_stack.py:47`) |
| `Docsuri-Compute` | ① API | ECS Fargate `docsuri`, RDS PG16(Multi-AZ), Redis 7.1, ALB:443, CloudFront, SES | **RDS RETAIN** (`compute_stack.py:105`) |
| `Docsuri-Ingestion` | ② Worker | SQS+DLQ, S3 `docsuri-papers-fulltext-*`, EventBridge `docsuri-arxiv-daily`(15:00 KST), Fargate worker(desired 0) | **S3 RETAIN** (`ingestion_stack.py:81`) |
| `Docsuri-Frontend` | ④ FE | Next.js SSR Fargate, ALB, CloudFront @ docsuri.org | 없음 |
| `Docsuri-Summarization` | Worker | ECS Fargate 요약 워커 + SQS `docsuri-summary-job-queue`(+DLQ). 장문 map-reduce 요약을 비동기 처리, 결과는 papers 버킷 `summaries/`에 write-through | 없음 |
| `Docsuri-Novelty` | ⑪ Worker | novelty 형성 에이전트 Fargate 워커 (인셉션 유닛 **U12**; 코드/CDK는 구 U11 엄브렐러 네이밍 잔존) + SQS `docsuri-novelty-agent-job-queue`(+DLQ). `NOVELTY_AGENT_ENABLED=true`로 배포 시 활성 | 없음 |
| `Docsuri-Access` | — | 크로스계정 팀 접근 역할 `DocsuriCrossAccountDev` (PowerUser+MFA, §9) | 없음 |

> ③ Ops worker: 디텍터 코드는 `ops/src/docsuri_ops/`에 존재하나 **독립 배포 스택 없음** — 현재는 라이브러리 코드. 실배포 워커로 안 돌고 있음 (§4 갭).
> **summarization·novelty 스택은 원래 6-스택 인벤토리 작성 이후 추가됨** (`app.py:19` `SummarizationStack`, `app.py:17` `NoveltyStack`) — 둘 다 SQS 잡 큐 기반 Fargate 백그라운드 워커. 현재 라이브 스택은 8개.

## 2. 🔴 알려진 함정 (Footguns)

1. **RETAIN 3종 — `cdk destroy`로 안 지워짐.** RDS·S3 papers·OpenSearch는 스택 삭제 후에도 남아 과금 지속. 진짜 teardown 하려면 스택 destroy 후 콘솔/CLI로 수동 삭제. (의도된 데이터 보호장치 — 실수로 날리지 말라는 것.)
2. **ALB 헬스체크 경로 = `/healthz`** (`compute_stack.py:280`), **`/` 아님.** API엔 root 핸들러 없음. `/healthz` 제거하거나 경로 바꾸면 → **deployment circuit breaker(`compute_stack.py:234`, `rollback=True`)가 배포 자동 롤백.** Frontend ALB는 `/`(`frontend_stack.py:117`) 사용 — **두 스택 헬스체크 설정 복붙 금지.**
3. **CDK 배포 = SSO 자격증명 필요.** `aws configure export-credentials`로 export 후 `cdk deploy`. 안 하면 인증 실패.
4. **비용가드 강등이 조용함.** 검색 품질이 갑자기 lexical-only로 떨어지면 장애가 아니라 **예산 임박**일 수 있음 → §3 비용가드 표 확인.
5. **Novelty 워커 수동 재배포 = `cdk deploy Docsuri-Novelty` 먼저, force-new-deployment 나중.** novelty 잡은 Bedrock 호출 2회(query plan + draft, 각 `read_timeout` 기본 600s)라 단일 잡이 큐 `visibility_timeout`을 넘길 수 있음. 큐 timeout 상향(900→3600s, `novelty_stack.py:50`)이 신 워커 이미지보다 **나중**에 적용되면 잡 처리 중 SQS 재배달 → 중복 처리(Bedrock 중복 과금)·`maxReceiveCount`(3) 소진 시 DLQ+알람. 자동 태그 릴리스는 안전(`cd.yml` `needs:` 체인이 cdk-deploy → deploy-ecs 순서 강제). **수동 buildx + `aws ecs update-service --force-new-deployment`로 CDK를 건너뛰는 경로에서만** 이 순서를 지킬 것.

## 3. 비용가드 (Cost Guard) — `ops/src/docsuri_ops/cost_guard.py`

월 cap `$1600` (`:11`). 서킷 상태로 자동 강등:

| 구간 | 누적 | 상태 | 동작 |
|---|---|---|---|
| < 80% | < $1280 | normal | 풀 랭킹 |
| 80–95% | $1280–1520 | warning | `RERANK_OFF` (lexical+vector, 리랭크 끔) |
| 95–100% | $1520–1600 | critical | `LEXICAL_ONLY` (LLM 미사용) |
| ≥ 100% | ≥ $1600 | OPEN | **요청 거부** |

⚠️ 현재 강등/거부 시 **알림 없음** — §4 G1 닫기 전까지 사람이 모름.

## 4. 알림 마지막 1마일 — 처리 현황 (`feat/ops-hardening`)

| ID | 갭 | 처리 | 위치 |
|---|---|---|---|
| **G2** | SES 토픽 구독자 0 | ✅ ops 메일 구독 추가 | `compute_stack.py` `SesEventsTopic` |
| **G3** | CloudWatch 미활성 (어댑터는 있으나 env 미설정 → InMemory 폴백) | ✅ `CLOUDWATCH_NAMESPACE` env 추가 | `compute_stack.py` `container_env` |
| **G4** | CloudWatch 알람 0개 | ✅ 5xx·p95 알람 2개 → `OpsAlerts` 토픽 | `compute_stack.py` 말미 |
| **G1** | 비용 돌파 알림 없음 | ✅ AWS Budget 80%($1280) → ops 메일 (빌링 레벨) | `compute_stack.py` `MonthlyCostBudget` |

> ⚠️ **배포 시 `ops_alert_email` 미설정이면 토픽/알람/예산은 생성되나 사람에게 안 감.** 반드시 `cdk deploy -c ops_alert_email=<팀alias>` (§8).
> **ponytail 천장:** 앱 내부 cost guard의 per-incident SNS publisher(`AlertPublisher`→SNS)는 **의도적으로 안 함** — Budget가 빌링 레벨에서 모든 지출을 더 견고하게 잡고, cost guard는 이미 자체 강등/거부함. 세분화된 incident 페이징이 필요해질 때 올릴 것.

## 5. 장애 대응 (Incident Response)

> 디텍터(`ops/src/docsuri_ops/detectors.py`)는 3종 분류하지만 **자동 페이징은 안 함**(천장 §4). 사람을 깨우는 건 §7 CloudWatch 알람 + Budget. 디텍터 결과는 대시보드/감사 로그용.

- **COST_EXPLOSION** (USAGE, ≥$320 또는 ratio≥80% 또는 rate spike): 비용가드 ratio 확인 → 강등 정상인지 vs 비정상 호출 폭증인지. 후자면 ingestion/검색 트래픽 출처 추적.
- **HALLUCINATION** (GROUNDING, verdict=block→CRITICAL): grounding hook이 LLM 원문을 막은 것. 빈도 급증 시 프롬프트/모델 회귀 의심.
- **PARTIAL_RESULT** (failure→CRITICAL): OpenSearch/Bedrock 어댑터 부분 실패. 해당 의존성 헬스 확인.

## 6. 복구 절차 (Recovery)

- **RDS 복원/암호화 이전**: RETAIN이라 실수 삭제는 막히지만 **스냅샷 복원은 한 번도 테스트 안 됨**(하드닝 항목). 자동백업 보존 7일. 복원: 최신 스냅샷 → 새 인스턴스 → compute 스택 secret 갱신. 암호화 이전 절차는 [rds-encryption-migration.md](rds-encryption-migration.md)를 따른다. ⚠️ 검증 전엔 "백업 있음"을 신뢰하지 말 것.
- **비용가드 OPEN(요청거부)**: cap 일시 상향 또는 강등 모드로 운영하며 비용 원인 차단. 근본원인 전 cap만 올리지 말 것.
- **SES 바운스 급증**: `BOUNCES_AND_COMPLAINTS` 자동 suppression(`compute_stack.py:187`)이 계정 레벨에서 재발송 차단. suppression list 확인, 발신 도메인 평판 점검.
- **배포 롤백**: circuit breaker가 헬스체크 실패 시 자동 롤백. 수동은 직전 task definition으로 ECS 서비스 업데이트.

## 7. SLO (3개) — G4로 CloudWatch 알람화

| SLO | 지표 | 임계(초안, 튜닝) | 구현 |
|---|---|---|---|
| API 가용성 | ALB target 5xx (5분) | > 10건 | ✅ `Api5xxAlarm` → `OpsAlerts` |
| 검색 지연 | ALB target p95 | > 2s × 3창(15분) | ✅ `ApiLatencyP95Alarm` → `OpsAlerts` |
| 비용 번레이트 | 월 누적 / cap | 80%($1280) — `warning_ratio`와 일치 | ✅ `MonthlyCostBudget` → ops 메일 |

> 30개 만들지 말 것. 이 3개가 3am 호출 막는 최소셋. 유저가 SLA 요구할 때 확장.
> 임계값은 전부 초안 — 실트래픽 며칠 관찰(§8 번인) 후 튜닝.

## 8. 배포 & 검증 절차

```bash
# 1. ops 알림 수신자와 함께 배포 (팀 alias 권장 — 개인 메일 X)
cd ops/cdk
aws configure export-credentials --profile <sso> >/dev/null  # SSO 자격증명 (함정 §2.3)
cdk deploy Docsuri-Compute -c ops_alert_email=ops@docsuri.org

# 2. SNS/Budget 이메일 구독 확인 메일 → 반드시 "Confirm" 클릭 (미확인 시 알림 0)
```

**검증 (배포 후, 라이브 — 같이 돌릴 것):**
- ☐ **알림→사람**: CloudWatch 콘솔에서 `Api5xxAlarm`을 임시로 `Set alarm state → ALARM` → ops 메일 수신 확인. 끝나면 원복.
- ☐ **RDS 복원/암호화 이전**: 최신 자동 스냅샷 → 새 인스턴스로 복원 테스트 1회 → 접속 확인 후 폐기. 암호화 이전은 [rds-encryption-migration.md](rds-encryption-migration.md) 기준으로 암호화 스냅샷 복사 → 병렬 복원 → 명시적 컷오버로 처리한다. (RETAIN이라 원본은 안전.) **검증 전엔 "백업 있음"을 신뢰하지 말 것.**
- ☐ **번인**: 며칠 실트래픽 관찰 후 §7 임계값 튜닝.

## 9. 팀원 크로스계정 접근 (Cross-account onboarding) — `Docsuri-Access`

Option B: 팀원의 **자체 AWS 계정**이 prod 계정(`028317349537`)으로 assume. 역할 `DocsuriCrossAccountDev` (`access_stack.py`) — 신뢰 계정은 `app.py:48` `TEAM_ACCOUNT_IDS` (버전관리 = 부여/회수가 PR diff). 권한 `PowerUserAccess`(IAM·결제 제외), **MFA 필수**, 세션 4h.

> 이 역할 = **콘솔/CLI/디버그용**. 배포 권한 아님 — 실배포는 여전히 CI OIDC(`CD_ROLE_ARN`).

**접근 관리자 (Access admins) — 부여/회수 권한 보유:**
- corpseonthemission@icloud.com (계정 `028317349537` 소유자, SSO 프로필 `AdministratorAccess-028317349537`)

**부여/회수 절차:**
1. `app.py` `TEAM_ACCOUNT_IDS`에 팀원 12자리 계정 ID 추가(회수 = 제거) → PR → 머지.
2. `cd ops/cdk && cdk deploy Docsuri-Access` (SSO 자격증명, 함정 §2.3). 출력 `CrossAccountDevRoleArn` 확인 후 팀원에게 전달.
3. 회수: 목록에서 빼고 재배포 → 다음 assume부터 거부.

**팀원 (각자 자기 계정에서 1회):**
1. 자신의 IAM 사용자/역할에 인라인 정책 부여:
   `{ "Effect":"Allow", "Action":"sts:AssumeRole", "Resource":"arn:aws:iam::028317349537:role/DocsuriCrossAccountDev" }`
2. 자기 계정에 MFA 디바이스 등록 (없으면 assume 거부됨).
3. `~/.aws/config`에 프로필 추가:
   ```ini
   [profile docsuri]
   role_arn       = arn:aws:iam::028317349537:role/DocsuriCrossAccountDev
   source_profile = <본인 프로필>
   mfa_serial     = arn:aws:iam::<본인계정>:mfa/<본인사용자>
   region         = ap-northeast-2
   ```

**검증:** `aws sts get-caller-identity --profile docsuri` → ARN이 `.../DocsuriCrossAccountDev/...` 면 성공 (MFA 토큰 프롬프트 뜸). 콘솔은 Switch Role로 동일 역할 진입.

> **함정:** MFA 없는 세션은 trust 조건(`aws:MultiFactorAuthPresent`)에서 거부 — assume 시 "access denied"는 대개 권한이 아니라 **MFA 미사용**.
