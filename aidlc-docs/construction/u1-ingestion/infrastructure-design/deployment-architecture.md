# deployment-architecture.md — U1 Ingestion 배포 아키텍처 (멀티모달 자산 범위)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거**: `infrastructure-design.md`(동일 디렉터리) · U1 NFR Design §5 · 계획 Q1~Q5=A
**스코프**: FR-17 자산 추출의 컴퓨트 co-location·전달 경로·기존 토폴로지 관계. **선결 상속**: 워커 런타임 타깃(ECS/Fargate vs Lambda)·리전·CD = 미결(TD-9), 본 기능 비결정.

---

## 1. 컴퓨트 co-location (Q4=A)
- 자산 추출(AssetExtractor·Image Normalizer)은 **기존 Ingestion Worker 태스크에 co-locate** — 별도 컴퓨트·큐 0(NFR Q4=A). 모듈형 모놀리스 워커 내 도메인 컴포넌트(NFR Design §2 매핑과 동형).
- **사이징**: PDF 페이지 렌더(PyMuPDF)·이미지 디코드/리사이즈는 **메모리 집약** → 워커 태스크에 이미지 처리 **메모리 헤드룸** 확보(픽셀 상한 ~30MP 가드와 정합, patterns §7.2). CPU만(ML/GPU 없음).
- **런타임 타깃**: ECS/Fargate vs Lambda는 **선결 상속**(미결). co-location은 타깃 무관(둘 다 워커 프로세스 내 컴포넌트).

## 2. 배포 토폴로지 (자산 분기)

```mermaid
graph LR
    subgraph Ingestion[Ingestion Worker (기존 태스크)]
      AX[AssetExtractor] --> NM[Image Normalizer]
    end
    NM -->|PutObject webp| S3[(S3 assets/ prefix<br/>private·SSE-KMS)]
    NM -->|upsert 매니페스트| RDS[(공유 RDS<br/>paper_asset)]
    AX -.->|index 경로(불변)| OS[(OpenSearch)]

    subgraph Read[U7 읽기 측]
      API[full-text/paper API]
    end
    API -->|SELECT paper_asset| RDS
    API -->|presign GET ~10m| S3
    API -->|서명 URL| Client[U5 상세/뷰어]
```

- 쓰기(인제스천 워커)와 읽기(U7)가 **공유 S3 prefix + 공유 RDS 테이블**을 매개. 인덱스 경로(OpenSearch)와 독립.

## 3. 자산 전달 경로 (Q2=A)
- **v1**: U7이 presigned S3 URL(만료 ~10분) 발급 → U5가 S3에서 직접 로드. 최소 인프라.
- **CloudFront CDN**: 후속(성능 트랙). 도입 시 OAC + 서명 URL/쿠키, 캐시 무효화 정책 추가.

## 4. 배포·마이그레이션
- **`paper_asset` 마이그레이션**: 공유 RDS 마이그레이션 파이프라인으로 적용(기존 패턴). 워커 배포 전 스키마 선적용.
- **워커 이미지**: 기존 인제스천 컨테이너에 추출 의존성(PyMuPDF·이미지 라이브러리) 추가, 다이제스트 핀(SEC-10, TD-9/10). SBOM/SCA에 신규 의존성 포함.
- **CD/롤백**: 기존 U1 CD(미결 상속). 자산 기능은 추출 실패 best-effort라 점진 롤아웃 안전(자산 없어도 텍스트 상세 정상).

## 5. 기존 U1 토폴로지와의 관계
- §1~5 기존 토폴로지(EventBridge·SQS·Worker·OpenSearch·Bedrock·전문 S3)·verify-all-then-commit **불변**.
- 추가분: 워커 내 자산 컴포넌트 + S3 `assets/` prefix + `paper_asset` RDS + (읽기) presign. 모두 인덱스 경로와 분리(best-effort).

---

> 비용·IAM·KMS·스키마 상세는 `infrastructure-design.md`. 다음 단계 = U1 Code Generation(추출·정규화·AssetStore 구현, `paper_asset` 마이그레이션).

---

## 6. U1 Corpus 배포 아키텍처 우선 적용 개정 (2026-06-26)

> **우선순위**: 본 섹션은 U1 Corpus 최신 배포 아키텍처다. 위 §1~§5의 멀티모달 자산 한정 설명과 충돌하면 본 섹션을 우선한다.

### 6.1 배포 단위

| 배포 단위 | 매핑 | 결정 |
|---|---|---|
| Ingestion worker | existing ECS Fargate service `docsuri-ingestion` | 유지. SQS depth 기반 scale-to-zero/min 0/max 3 패턴 유지. |
| GROBID | worker task sidecar | 별도 ALB/service discovery 없음. worker와 같은 task network에서만 호출. |
| Queue/DLQ | existing `docsuri-ingestion-queue` / `docsuri-ingestion-dlq` | message type으로 Corpus job 종류 구분. |
| Scheduler | EventBridge rules | source별 daily tick 또는 fan-out payload. 같은 queue target. |
| OpenSearch | existing `docsuri-papers` domain | new generation index + alias cutover. |
| Storage | existing papers bucket + RDS | prefixes/table additions only. |

### 6.2 Runtime environment

Existing ingestion task env remains the base:

- `DOCSURI_S3_BUCKET=docsuri-papers-fulltext-{account}`
- `DOCSURI_BEDROCK_MODEL_ID=global.cohere.embed-v4:0`
- `DOCSURI_OPENSEARCH_ENDPOINT=https://...`
- `DOCSURI_CONTROL_PLANE_DSN=...`
- `DOCSURI_SQS_QUEUE_URL=...`
- `DOCSURI_SQS_DLQ_URL=...`

Corpus additions:

- `DOCSURI_CORPUS_PHASE1_ENABLED=true`
- `DOCSURI_CORPUS_SOURCES=ARXIV,SEMANTIC_SCHOLAR,OPENALEX`
- `DOCSURI_GROBID_URL=http://localhost:8070`
- `DOCSURI_MULTIMODAL_ASSETS_ENABLED=true`
- `DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED=true` only after the new worker deployment is fully stable and worker redeploys are frozen for the harvest window.
- `DOCSURI_CORPUS_RUN_BUDGET_USD=<per-run cap>`
- optional `SEMANTIC_SCHOLAR_API_KEY` from Secrets Manager only if quota requires it.

### 6.3 Rollout sequence

1. Apply RDS migrations for `source_watermark`, `canonical_dedup_state`, `paper_version_state`, `corpus_generation`, `corpus_job_item`.
2. Deploy ingestion image with Corpus code and GROBID sidecar, but keep harvest triggers disabled.
3. Wait for the ECS service deployment to fully stabilize: every running task must be on the new task definition. Old and new workers must not consume SQS jobs concurrently during corpus build.
4. Freeze ingestion worker redeploys for the full harvest window.
5. Set `DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED=true`. Production `trigger-full-rebuild` refuses to queue the build until this is set.
6. Provision the new OpenSearch candidate generation index with on-disk vector mapping in the existing domain.
7. Enable one source at a time: arXiv first, then Semantic Scholar, then OpenAlex.
8. Run phase-1 budgeted backfill/harvest only after steps 3-6 are complete.
9. Run QT-9 gates and U2/U7 smoke checks against candidate generation, including DocModel `fullText`, multimodal block coverage, blockRef integrity, and AssetRef object resolution.
10. Switch active alias.
11. Keep previous generation until burn-in completes, then retire.

### 6.4 Rollback

- Disable `DOCSURI_CORPUS_PHASE1_ENABLED`.
- Stop EventBridge Corpus rules.
- Keep current active OpenSearch alias on previous generation.
- Leave candidate S3 artifacts and RDS state for inspection; do not delete during incident response.
- Reprocess DLQ only after root cause is known.

### 6.5 Network and capacity

- Worker remains outbound-only. Public ingress is not added.
- GROBID sidecar has no public route.
- OpenSearch remains VPC-only with worker/API security group access.
- Existing worker size `512 CPU / 1024 MiB` may be too small with GROBID. Infrastructure Design sets the trigger to raise task size when sidecar is enabled; Code/Infra implementation should start with a conservative GROBID-enabled task size rather than failing at runtime.

### 6.6 Operations handoff

- Required dashboards: source watermark lag, queue depth, DLQ depth, GROBID failures, embedding spend, generation validation status, alias active generation.
- Required runbooks: source circuit open, GROBID degraded, budget hard stop, generation cutover failure, DLQ reprocess.
