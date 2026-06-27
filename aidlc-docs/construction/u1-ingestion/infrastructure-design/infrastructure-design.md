# infrastructure-design.md — U1 Ingestion 인프라 설계 (멀티모달 자산 범위)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거**: U1 NFR Design(`logical-components §5`·`nfr-design-patterns §7`)·TD-11~15·FD §6/§7·`requirements.md` FR-17·NFR-C1($1600) · 계획 Q1~Q5=A
**스코프**: **FR-17 멀티모달 자산 인프라만**. 기존 U1 인프라(EventBridge·SQS·OpenSearch·Bedrock·전문 S3)는 NFR 문서 상속(본 문서가 U1 최초 Infra 산출물이나 멀티모달 슬라이스로 한정). **선결 상속**: 워커 런타임 타깃(ECS/Fargate vs Lambda, TD-9)·리전·CD = 미결, 본 기능 비결정.

> 표시 전용 — 인덱스 경로(OpenSearch·임베딩) 인프라 불변. 자산은 독립.

---

## 0. U1 Corpus 인프라 우선 적용 개정 (2026-06-26)

> **우선순위**: 본 섹션은 재인셉션 페이즈 1 / U1 Corpus의 최신 Infrastructure Design이다. 아래 §1~§5의 멀티모달 자산 전용 범위와 lazy doc-model 설명이 본 섹션과 충돌하면 **본 섹션을 우선한다**. 기존 섹션은 FR-17 자산 인프라 추적 기록으로 보존한다.

### 0.1 AWS 리소스 매핑

| Corpus 논리 컴포넌트 | AWS 매핑 | 결정 |
|---|---|---|
| EventBridge Source Scheduler | 기존 EventBridge rule 패턴 확장 | source별 rule 3개 또는 하나의 daily fan-out rule을 같은 ingestion queue로 전송. 신규 event bus 불필요. |
| Corpus Work Queue | 기존 `docsuri-ingestion-queue` | message type으로 `source_tick`, `paper_ingest`, `BUILD_DOC_MODEL`, `REPROCESS_DLQ` 구분. 큐 추가 없음. |
| Corpus DLQ | 기존 `docsuri-ingestion-dlq` | payload에 `failureStage`, `sourceName`, `paperId`, `version`, `canonicalKey` 포함. stage별 별도 DLQ는 만들지 않음. |
| Ingestion Worker | 기존 ECS Fargate service `docsuri-ingestion` | max task count는 기존 3 유지. Corpus backfill은 budget/queue depth로 조절. |
| Internal GROBID | Ingestion task sidecar container | public endpoint 없음. worker container가 localhost/container network로 호출. GROBID 때문에 task memory/cpu는 Infra/code 단계에서 상향 가능. |
| Control Plane DB | 기존 RDS/Postgres | `source_watermark`, `canonical_dedup_state`, `corpus_generation`, `corpus_job_item` 테이블 추가. 신규 DB 없음. |
| Corpus artifacts | 기존 S3 bucket `docsuri-papers-fulltext-{account}` | prefixes: `full-text/`, `doc-model/`, `assets/`, `generation-manifests/`, `source-provenance/`. raw PDF prefix 없음. |
| Embedding | existing Bedrock profile `global.cohere.embed-v4:0` | `output_dimension=1024`, writer input_type=`search_document`. |
| OpenSearch generation | existing domain `docsuri-papers` | same domain, new generation index names, active alias cutover. 신규 domain 없음. |
| Observability | CloudWatch Logs/Metrics + U6 ObservabilityHub | DLQ depth, source watermark lag, GROBID failures, embedding spend, cutover status alarms. |
| Cost guard | existing AWS Budget `$1600/month` + U1 run budget | monthly account cap 유지. U1 worker stops new fetch/GROBID/embed work when run budget is exhausted. |

### 0.2 S3 layout

| Prefix | Content | Lifecycle |
|---|---|---|
| `full-text/{paperId}/v{version}.txt` | normalized FullText projection | retained, private |
| `doc-model/{paperId}/v{version}.json` | eager phase-1 DocModel: `fullText` projection + paragraph/table/formula/figure/list/code blocks + AssetRef ids | retained, private |
| `assets/{paperId}/{version}/{assetId}.webp` | figure/table image assets referenced by DocModel AssetRef | retained, private |
| `generation-manifests/{generationId}/{paperId}/v{version}.json` | artifact/index consistency manifest | retained until generation retired |
| `source-provenance/{paperId}/v{version}.json` | source lineage and sourceTier | retained with DocModel |

**Raw PDFs are not stored.** PDF bytes from arXiv/Semantic Scholar/OpenAlex are temporary GROBID/parser input only. DocModel JSON also does not store image bytes, base64 payloads, or presigned URLs; it stores only stable AssetRef identifiers that resolve to private `assets/` objects.

### 0.3 Control-plane tables

| Table | Purpose | Notes |
|---|---|---|
| `source_watermark` | source별 cursor/timestamp and last success | PK `source_name`; monotonic update only. |
| `canonical_dedup_state` | DOI/arXiv/title-key -> canonical paper/version | stores winning source tier and seen source refs. |
| `paper_version_state` | `(paper_id, version)` consistency state | stores docModelRef, generationId, status. |
| `corpus_generation` | OpenSearch generation lifecycle | `BUILDING`, `VALIDATED`, `ACTIVE`, `RETIRED`, `ROLLED_BACK`. |
| `corpus_job_item` | retry/DLQ/reprocess metadata | stage, attempts, failureReason, sourceName. |

Existing RDS migration runner applies these schema changes. No separate database.

### 0.4 IAM and network

- Worker task role:
  - SQS consume on `docsuri-ingestion-queue`, DLQ send/reprocess permissions on `docsuri-ingestion-dlq`.
  - S3 read/write only for the Corpus prefixes above.
  - Bedrock `InvokeModel` only for Cohere Embed v4 profile/foundation model.
  - OpenSearch write only for Corpus indices/generation aliases.
  - RDS secret read and DB network access as existing ingestion stack pattern.
- API/U7 read role:
  - S3 read for `doc-model/`, `full-text/`, `assets/`; no write to Corpus generation.
  - SQS `SendMessage` only for doc-model build/backfill trigger when still needed.
- GROBID:
  - no IAM, no public ingress, no load balancer.
  - worker sidecar call only.

### 0.5 Alarms and budget stops

| Signal | Action |
|---|---|
| DLQ visible messages > 0 | alert OP; reprocess runbook. |
| source watermark lag over threshold | alert OP; source-specific circuit opens. |
| GROBID failure rate over threshold | alert OP; PDF sources slow/stop, arXiv HTML continues. |
| embedding spend/run budget over threshold | stop new fetch/GROBID/embed work; keep active alias. |
| generation validation failure | block alias cutover. |
| OpenSearch write failures | stop generation writes; keep active alias. |

---

## 1. 스토리지

### 1.1 S3 자산 (Q1=A)
- **버킷**: 기존 전문(StoredFullText) S3 버킷 재사용. 신규 버킷 0.
- **prefix**: `assets/{paperId}/{version}/{assetId}.webp` (결정적 키, AssetId 기반 — FD §10).
- **접근**: **공개 차단**(Block Public Access, deny-by-default, SEC-9). 노출은 presigned URL만(§2).
- **암호화**: **SSE-KMS** — 기존 U1 S3 CMK 재사용(SEC-1). 전송 TLS.
- **라이프사이클(Q5=A)**: **만료 없음**(표시 영구 소스). 자산은 재생성 가능하나 표시 진실원천이므로 자동 삭제 안 함. 정리는 CHANGED 교체·tombstone 삭제(애플리케이션 주도, §3.4).

### 1.1b doc-model S3 (피벗 2026-06-23, D1/D6 — SSOT=`construction/plans/docmodel-foundation-pivot-plan.md`)
- **버킷**: 동일 단일 버킷 재사용(신규 버킷 0). 신규 **prefix `doc-model/{paperId}/v{version}.json`**(결정적 키). 이미지 바이트는 미포함 — `assets/` webp를 `assetId`로 참조.
- **접근/암호화**: `assets/`와 동일 — **공개 차단(SEC-9)** · **SSE-KMS**(동일 CMK) · 전송 TLS. 노출은 서비스 역할 GetObject(리치뷰/요약 입력).
- **생성**: **lazy on-demand**(첫 요약/열람/에이전트 사용 시 빌더가 `PutObject`) + `(paperId, version)` 캐시(U1 BR-30·BLM §7). `ingestOne` eager 아님.
- **라이프사이클**: doc-model = **파생 캐시**. version 변경·tombstone 시 **애플리케이션 주도 무효화**(`doc-model/{paperId}/*` 삭제, §3.4 write-order에 편입). 선택적 TTL은 NFR(재생성 가능하므로 비용 관점 허용); 기본은 만료 없음(재생성 콜드스타트 회피).
- **키 계약 — `{paperId}`는 bare arXiv id**: `assets/`·`doc-model/` prefix와 `paper_asset.paper_id` 컬럼의 `{paperId}`는 **버전 없는 bare id**다(버전은 별도 `v{version}` 경로 세그먼트/컬럼). 빌더는 `rsplit('v',1)`로 bare id를 유도해 기록한다. 애플리케이션은 버전 포함 id(`2304.10557v1`)를 들고 다니므로, **읽기 측(U7 어댑터)은 키 생성 전 트레일링 `vN`을 제거**해야 한다 — 누락 시 빌드 산출물을 영영 못 찾음(영구 미스 → 본문/요약 "근거 없음"). 회귀: `backend/modules/summarization/tests/test_paper_ref_normalization.py`.

### 1.2 `paper_asset` RDS 테이블 (Q3=A, NFR Design §5.2)
- **위치**: 기존 **공유 RDS PostgreSQL**(U3 계정·U4 라이브러리·U7 용어집). 신규 DB 0.
- **스키마(개념)**:

```sql
CREATE TABLE paper_asset (
  paper_id     TEXT     NOT NULL,
  version      INTEGER  NOT NULL,
  asset_id     TEXT     NOT NULL,
  type         TEXT     NOT NULL,          -- 'figure' | 'table'
  caption      TEXT,
  section_ref  TEXT,                       -- 앵커 매칭 좌표
  ordinal      INTEGER  NOT NULL,
  source_mode  TEXT     NOT NULL,          -- 'structured' | 'page-crop'
  object_ref   TEXT     NOT NULL,          -- S3 키
  page_ref     INTEGER,                    -- page-crop 위치
  bbox         JSONB,                      -- page-crop 위치
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (paper_id, version, asset_id)
);
CREATE INDEX idx_paper_asset_lookup ON paper_asset (paper_id, version, ordinal);
```

- **마이그레이션**: 기존 버전관리 마이그레이션 패턴(예: `backend/.../migrations/00X` 또는 인제스천 `postgres` 어댑터 마이그레이션)으로 추가. 직접 수정 금지(스키마 변경=마이그레이션).
- **조회**: U7 full-text/paper API가 `(paper_id, version)`로 매니페스트 조회 → ordinal 정렬.

---

## 2. 자산 전달 (Q2=A — presigned S3, CDN 후속)
- **경로(v1)**: U7(읽기 측)이 자산 표시 시 `paper_asset` 조회 → 각 `object_ref`에 **presigned S3 GET URL** 발급(만료 **~10분**) → 클라이언트가 S3에서 직접 로드.
- **토큰 비노출(SEC-9/12)**: 서명 URL만 노출, 내부 키·자격증명 비노출.
- **CloudFront CDN**: **후속 트랙**(캐시 적중·전 세계 지연 개선 필요 시 OAC + 서명). v1 미도입.
- **만료 수치**: ~10분(권장). Ops 조정 가능.

---

## 3. IAM·정합·비용

### 3.1 최소권한 IAM (Q5=A, SEC-6 — patterns §4.1 확장)
| 역할 | 권한 |
|---|---|
| **Ingestion Worker** | S3 `assets/` prefix `PutObject`/`DeleteObject` · `paper_asset` INSERT/UPDATE/DELETE · KMS Encrypt |
| **doc-model 빌더(역할)** | S3 `doc-model/` prefix `PutObject`/`DeleteObject`(lazy 생성·무효화) · `assets/`·`paper_asset` 읽기(참조 연결) · KMS Encrypt/Decrypt |
| **U7 읽기(서비스 역할)** | S3 `assets/` prefix `GetObject` + presign · **`doc-model/` prefix `GetObject`**(요약 입력·리치뷰) · `paper_asset` SELECT · KMS Decrypt |

- 와일드카드 금지. 자산·doc-model prefix·테이블로 스코프 한정.

### 3.2 write-order 정합 (P8 — patterns §7.4)
- S3 `PutObject`(바이너리) → RDS `paper_asset` upsert(메타) 순서. "행 있는데 객체 없음" 회피.

### 3.3 CHANGED·tombstone 정리
- **CHANGED(vN↑)**: 새 version 객체·행 기록 후 이전 version 객체·행 삭제. **tombstone**: `paper_asset` 행 + S3 객체 삭제(애플리케이션 주도, best-effort).

### 3.4 비용 (NFR-C1, Q5=A)
- **추출 컴퓨트**: 워커 CPU(PyMuPDF 렌더·이미지 처리), ML/GPU 없음 → 기존 워커 비용에 흡수.
- **S3 스토리지**: distinct 논문×버전 1회 자산(WebP·치수상한 → 건당 소용량). bounded.
- **$1600 시스템 전역 상한 내 흡수**, U6.CostGuard 강제. 텔레메트리에 **자산 추출/스토리지 라인 별도 계상**.

---

## 4. 관측 (Monitoring)
- 메트릭: 자산 추출 성공/실패 수(`ASSET_*`), 논문당 자산 수, source_mode 분포(structured/page-crop), S3 자산 스토리지 크기 → CloudWatch/U6.ObservabilityHub.
- 알림: 추출 실패율 임계(BR-17 잡 실패율 신호 보조). 인덱싱과 분리(best-effort라 자산 실패는 갱신 실패 경보와 별개 라인).

---

## 5. 추적성
- FR-17 → S3 `assets/` prefix(Q1)·`paper_asset` RDS(Q3)·presigned 전달(Q2)·IAM/KMS(Q5) · TD-13/14/15 · BR-22~28 · P7/P8. 배포·컴퓨트는 `deployment-architecture.md`.
