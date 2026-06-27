# infrastructure-design.md — 시스템 전역 AWS 인프라 명세서

**단계**: CONSTRUCTION → Infrastructure Design (시스템 전역, 크리티컬 패스 ⑦) · **일자**: 2026-06-17
**범위**: U3 배포 단위 ①이 커버하지 않는 **시스템 전역 인프라 — 벡터 검색 티어(OpenSearch) + 인제스천 워커(배포 단위 ②) + 이벤트 백본(SQS·EventBridge) + 오브젝트 스토어(S3) + ML 모델 액세스(Bedrock/Cohere)**를 정의한다.
**관계**: U3 `infrastructure-design/`(배포 단위 ① VPC·Fargate·RDS·Redis·SES)는 **부모** — 본 문서가 동일 VPC 내 추가 티어를 정의한다. U4는 U3을 상속(인프라 변경 없음).

---

## 0. 설계 원칙 및 제약

| 원칙 | 내용 |
|---|---|
| **비용 상한** | NFR-C1 = **$1,600/월 시스템 전역** (팀 AWS 크레딧 전액). 본 문서 §6에서 유닛별 배분. |
| **리전** | `ap-northeast-2` (서울) — U3에서 확정. 전 리소스 동일 리전. |
| **가용 영역** | **2 AZ** (AZ-A `apne2-az1` · AZ-B `apne2-az3`) — U3 VPC 계승. Multi-AZ 전 티어 적용. |
| **NAT Gateway 배제** | U3 확정. 퍼블릭 서브넷의 IGW 아웃바운드 직접 통신(Fargate·OpenSearch). |
| **IaC** | 본 문서는 **리소스 명세·토폴로지·보안·비용**만 정의. IaC 구현(Terraform/CDK)은 별도 후속 PR. |
| **SEC-10 이미지 핀** | 모든 컨테이너 이미지는 ECR 다이제스트 해시(sha256)로 버전 고정. |

---

## 1. Amazon OpenSearch Service — 벡터 검색 + BM25 티어

U1 Ingestion이 쓰고 U2 Discovery가 읽는 **공유 벡터 인덱스**(VectorSpec 🔒FROZEN: Cohere Embed Multilingual v3, 1024-dim, cosine)의 호스팅 계층이다.

### 1.1. 도메인 사양

| 항목 | 값 | 근거 |
|---|---|---|
| **도메인 이름** | `docsuri-papers` | |
| **엔진 버전** | OpenSearch `2.11+` (k-NN 플러그인 내장) | k-NN HNSW 1024-dim 지원 |
| **인스턴스 타입** | `m6g.large.search` (2 vCPU / 8 GB, Graviton3) | 수십만 1024-dim 벡터 + BM25 인덱스에 충분한 메모리 여유; $1600 상한 내 |
| **데이터 노드** | **2** (Multi-AZ, 각 AZ에 1개) | 가용성 + replica shard 분산 |
| **스토리지** | EBS gp3, 노드당 **50 GB** (총 100 GB) | 수십만 문서 × ~5KB/doc(논문당 1벡터, Q2=B) + k-NN 그래프; 초기 여유분 포함. ILM으로 관리 |
| **마스터 노드** | 없음 (2 데이터 노드 도메인은 전용 마스터 불요) | 비용 절감 |
| **레플리카** | index replica = 1 (2 노드 = 1 primary + 1 replica per shard) | AZ 장애 시 읽기 가용 |

### 1.2. k-NN 인덱스 설정

```json
{
  "settings": {
    "index.knn": true,
    "index.knn.algo_param.ef_search": 256,
    "number_of_shards": 2,
    "number_of_replicas": 1
  },
  "mappings": {
    "properties": {
      "vector": {
        "type": "knn_vector",
        "dimension": 1024,
        "method": {
          "name": "hnsw",
          "space_type": "cosinesimil",
          "engine": "nmslib",
          "parameters": { "ef_construction": 256, "m": 16 }
        }
      },
      "paperId": { "type": "keyword" },
      "arxivId": { "type": "keyword" },
      "title": { "type": "text", "analyzer": "standard" },
      "abstract": { "type": "text", "analyzer": "standard" },
      "authors": { "type": "keyword" },
      "year": { "type": "integer" },
      "categories": { "type": "keyword" },
      "chunkOrdinal": { "type": "integer" },
      "arxivUrl": { "type": "keyword" },
      "currentVersion": { "type": "integer" }
    }
  }
}
```

### 1.3. 인덱스 수명주기 관리 (ILM)

- **Hot tier**: 최근 2년 (활성 검색). k-NN 그래프 메모리 상주.
- **Warm tier 이전 없음** (현 규모에서는 2 데이터 노드로 전체 수용; 성장 시 UltraWarm 도입).
- **삭제 정책**: 없음 (arXiv 논문은 영구 보존 — 철회(tombstone) 시 `currentVersion` CAS로 소프트 삭제).

### 1.4. 접근 제어

- **Fine-Grained Access Control (FGAC)**: 활성화. IAM 역할 기반 인증.
- **접근 정책**: ECS 태스크 역할(`docsuri-api-task-role` + `docsuri-ingestion-task-role`)만 도메인 접근 허용.
- **전송 암호화**: 노드 간 TLS 1.2 필수.
- **저장 암호화**: AWS 관리형 키(SSE).

---

## 2. 인제스천 워커 — 배포 단위 ② (ECS Fargate + SQS)

arXiv 논문 수집·파싱·임베딩·벡터 인덱스 쓰기 파이프라인. 기존 `ingestion/Dockerfile` + `worker.py` (SQS 폴 루프).

### 2.1. ECS Fargate 태스크 정의

| 항목 | 값 | 근거 |
|---|---|---|
| **서비스 이름** | `docsuri-ingestion-worker` | |
| **CPU** | 0.5 vCPU (512 Units) | 임베딩 호출(네트워크) + OpenSearch bulk(직렬화) |
| **Memory** | 1024 MB | full-text 파싱 + 청크 어셈블리; t4g 최소보다 여유 |
| **이미지** | `ingestion/Dockerfile` → ECR (sha256 다이제스트 핀, SEC-10) | |
| **네트워킹** | 퍼블릭 서브넷 (IGW 아웃바운드 — arXiv API + Bedrock + OpenSearch) | NAT 배제 아키텍처 계승 |
| **환경변수** | SQS URL · OpenSearch endpoint · S3 bucket · Bedrock model ID → Secrets Manager/SSM Parameter Store에서 주입 | |

### 2.2. 오토스케일링

```
스케일링 트리거: SQS ApproximateNumberOfMessages
  min_tasks = 0       (유휴 시 $0 — scale-to-zero)
  max_tasks = 3       (arXiv rate limit ~0.33 req/s per worker; 3 워커 ≈ 1 req/s 총합)
  scale-out: Messages > 10 → +1 task (step, cooldown 120s)
  scale-in:  Messages = 0 for 5 min → −1 task (cooldown 300s)
```

**벌크 로드 시나리오**: phase-1 5 카테고리×최근 1년 슬라이스는 `trigger_full_rebuild` CLI → SQS 메시지 발행 → 3 워커 자동 기동, 큐 드레인. 5년 full-slice는 Phase 7 backfill에서 별도 실행한다.

### 2.3. SQS 큐 및 DLQ

| 큐 이름 | 용도 | 가시성 타임아웃 | 최대 수신 | DLQ |
|---|---|---|---|---|
| `docsuri-ingestion-queue` | 인제스천 작업 메시지(paperId/arXiv event) **+ doc-model lazy 빌드 잡(`BUILD_DOC_MODEL`, 피벗)** | 300s (5분 — 논문 1편 처리 상한) | 3회 | → `docsuri-ingestion-dlq` |
| `docsuri-ingestion-dlq` | 실패 메시지 격리 (redrive 또는 수동 조사) | — | — | — |
| `docsuri-summary-job-queue` | **긴 논문 요약 비동기 잡(BR-S6/BR-S12)** — API가 enqueue, 요약 워커가 소비 | 900s (15분 — map-reduce N+1 LLM 콜 상한) | 3회 | → `docsuri-summary-job-dlq` |
| `docsuri-summary-job-dlq` | 실패 요약 잡 격리 | — | — | — |

- **메시지 보존**: 큐 14일 / DLQ 14일. **암호화**: SSE-SQS (AWS 관리형 키). **Redrive**: `maxReceiveCount=3` → DLQ.
- **doc-model 빌드 잡은 신규 큐 없이 인제스천 큐 재사용** — 워커 `process_message`가 `kind=BUILD_DOC_MODEL` 분기로 `build_doc_model`을 호출(인제스천 워커가 이미 arXiv fetch·S3 쓰기·파서 보유). API(`docsuri-api-task-role`)는 인제스천 큐에 `SendMessage`만(빌드 트리거, 경계 B).

### 2.4. 요약 워커 — 배포 단위 ④ (ECS Fargate, 신규 — 피벗 BR-S12)

긴 논문 요약(map-reduce, LLM 3~5콜·15~75s)은 게이트웨이 동기 한계(~29s)를 넘으므로 **비동기 잡**으로 처리한다. API가 `docsuri-summary-job-queue`에 잡을 enqueue→`PendingDTO` 반환, **요약 워커**가 소비해 map-reduce를 inline 실행(`orchestrator.run(allow_enqueue=False)`)하고 결과를 `summary/` 캐시에 write-through → 클라이언트 폴링이 캐시 히트.

| 항목 | 값 | 비고 |
|---|---|---|
| **서비스 이름** | `docsuri-summary-worker` | |
| **이미지** | `docsuri-api` ECR 재사용(엔트리 `python -m summarization.worker`) | U7 코드가 API 이미지에 포함 — 별도 이미지 불필요 |
| **크기/스케일** | 0.5 vCPU / 1 GB · min 0 — max 2 | SQS depth 기반 step scaling, scale-to-zero |
| **환경변수** | `DOCSURI_SUMMARY_BUCKET`(papers 버킷) · `DOCSURI_SUMMARY_JOB_QUEUE_URL` · **`DOCSURI_MAP_REDUCE_ENABLED=true`**(워커는 맵리듀스 보유 필수) · Bedrock 모델 id · Redis(요약 store) · RDS DSN(용어집) · `CLOUDWATCH_NAMESPACE` | SSM/Secrets 주입 |
| **의존 서비스** | Bedrock(InvokeModel) · S3(doc-model read·summary write) · Redis(store) · RDS(용어집) | API와 동일 백킹(워커 = HTTP 서버 없는 동일 파이프라인) |

- **게이트**: `DOCSURI_MAP_REDUCE_ENABLED`/`DOCSURI_SUMMARY_JOB_QUEUE_URL` 미설정 시 API는 MAP_REDUCE를 inline 또는 abstain(BR-S6) — 워커 없이도 안전 저하. **배포는 팀 담당**(본 설계는 코드·synth까지).

---

## 3. 이벤트 백본 (Amazon EventBridge)

### 3.1. 스케줄 규칙 — arXiv 정기 수집

| 규칙 이름 | 스케줄 | 대상 | 근거 |
|---|---|---|---|
| `docsuri-arxiv-daily` | `cron(0 6 * * ? *)` (매일 06:00 UTC = 15:00 KST) | SQS `docsuri-ingestion-queue` JSON `{"type":"schedule_tick"}` | Worker dispatches `schedule_tick` to `on_schedule_tick()`; `ingest_paper` messages continue to `ingest_one()`/doc-model handling. Invalid message types are not acked as success and go to DLQ. |

### 3.2. 이벤트 규칙 — new-arXiv 이벤트 (향후)

arXiv Atom 피드 기반 near-real-time 트리거는 EventBridge Pipes(SQS→step)로 확장 가능. 현재는 스케줄 + CLI `on_new_arxiv_event` 매핑으로 충분.

---

## 4. Amazon S3 — 전문(Full-Text) 원본 저장소

| 버킷 이름 | 용도 | 암호화 | 수명주기 |
|---|---|---|---|
| `docsuri-papers-fulltext-{env}` | **단일 버킷·프리픽스 분리**(피벗 §1.1): `full-text/`(평문 .txt) · `assets/`(그림 webp) · **`doc-model/`(구조화 JSON)** · `summary/`(요약 캐시 영구본) | SSE-S3 (AES-256) | Intelligent-Tiering (90일→IA, 180일→Archive) |

- **접근(피벗 갱신)**:
  - `docsuri-ingestion-task-role`: 버킷 **read/write**(full-text·assets·**doc-model** 쓰기 — 빌더 PutObject).
  - `docsuri-api-task-role`(요약/리치뷰): **`doc-model/*` GetObject**(U7 리치뷰·요약 입력 reader) + `summary/*` read/write(요약 캐시 store). 그림은 RDS `paper_asset`의 object_ref를 **presign**(버킷 GetObject).
  - `docsuri-summary-worker-task-role`: `doc-model/*` GetObject(요약 입력) + `summary/*` read/write(결과 write-through).
- **버저닝**: 활성화. doc-model 캐시 키 = `(paperId, version)`, version 변경 시 무효화(BR-30).

---

## 5. Amazon Bedrock — ML 모델 액세스

### 5.1. 임베딩 (Cohere Embed Multilingual v3)

| 항목 | 값 |
|---|---|
| **모델 ID** | `cohere.embed-multilingual-v3` (Bedrock On-Demand) |
| **input_type** | writer=`search_document` (U1 인제스천) / reader=`search_query` (U2 검색) |
| **차원** | 1024 (VectorSpec FROZEN) |
| **호출 주체** | `docsuri-ingestion-task-role` (벌크 임베딩) · `docsuri-api-task-role` (검색 질의 임베딩) |
| **비용 추정** | ~$0.0001/1K tokens; 초기 벌크(수십만×~300 tokens avg, **제목+초록만 — issue #120 Q2=B**) ≈ $2-5 일회성; 이후 일일 수십 건 ≈ 무시 |

### 5.2. 모델 접근 권한

- **Bedrock Model Access**: 계정 028317349537에서 `cohere.embed-multilingual-v3` On-Demand 활성화 필요 (사이클 1에서 use-case gate 해소 완료 — [[project-aws-integration-spike]]).
- **IAM 정책**: 태스크 역할에 `bedrock:InvokeModel` 허용 (Resource: 해당 모델 ARN만).

---

## 6. 비용 배분 (NFR-C1 $1,600/월)

| 티어 | 리소스 | 예상 월비용 | 비고 |
|---|---|---|---|
| **OpenSearch** | m6g.large.search ×2 (Multi-AZ) + 100GB EBS gp3 | ~$220 | 데이터 노드 $97×2 + 스토리지 $24 |
| **API 컴퓨트** | ECS Fargate 0.25vCPU/512MB ×1-2 (배포 단위 ①) | ~$15-30 | U3 확정 사양 |
| **인제스천 워커** | ECS Fargate 0.5vCPU/1GB ×0-3 (배포 단위 ②) | ~$0-25 | scale-to-zero; 벌크 시만 비용 |
| **RDS PostgreSQL** | db.t4g.small Multi-AZ | ~$50 | U3 확정 |
| **ElastiCache Redis** | cache.t4g.micro ×2 (Multi-AZ) | ~$20 | U3 확정 |
| **SQS** | 인제스천 큐 + DLQ | ~$1 | 무시 수준 |
| **S3** | 전문 원본 + Intelligent-Tiering | ~$5-10 | 수십만 논문 ~50GB |
| **Bedrock (Cohere)** | 임베딩 호출 (벌크 일회 + 일일 질의) | ~$5-10 | 토큰 기반 과금 |
| **EventBridge** | 스케줄 규칙 1개 | ~$0 | |
| **ALB** | Application Load Balancer | ~$20 | U3 계승 |
| **기타** | CloudWatch, ECR, Secrets Manager | ~$10-15 | |
| **합계** | | **~$370-400** | **$1,600 상한 대비 ~25% 사용** |

> ✅ $1,600 상한에 **충분한 여유**. 성장 시 OpenSearch 노드 업그레이드(r6g) 또는 3노드 확장이 상한 내에서 가능.

---

## 7. IAM 역할 및 최소 권한

| 역할 이름 | 바인딩 | 허용 액션 |
|---|---|---|
| `docsuri-api-task-role` | 배포 단위 ① (ECS) | OpenSearch(읽기) · Bedrock `InvokeModel`(search_query **+ 요약/번역 모델 — U7**) · SES(SendEmail) · CloudWatch(PutMetricData/PutLogEvents) · **S3 `doc-model/*` GetObject + `summary/*` read/write** · **SQS `SendMessage`(`docsuri-ingestion-queue` doc-model 빌드 + `docsuri-summary-job-queue` 요약 잡)** |
| `docsuri-ingestion-task-role` | 배포 단위 ② (ECS) | OpenSearch(쓰기/삭제) · Bedrock `InvokeModel`(search_document) · S3(PutObject/GetObject — **doc-model 빌더 PutObject 포함**) · SQS(ReceiveMessage/DeleteMessage/SendMessage[DLQ]) · CloudWatch |
| `docsuri-summary-worker-task-role` | **배포 단위 ④ (ECS — 요약 워커, 신규)** | Bedrock `InvokeModel`(요약/번역 모델) · S3 `doc-model/*` GetObject + `summary/*` read/write · SQS(Receive/DeleteMessage `docsuri-summary-job-queue` · SendMessage[DLQ]) · RDS(용어집) · CloudWatch |
| `docsuri-eventbridge-rule-role` | EventBridge 규칙 | SQS(SendMessage) 대상 `docsuri-ingestion-queue`만 |

---

## 8. 보안 그룹 확장 (U3 토폴로지 위 추가분)

U3 `infrastructure-design.md` §3의 기존 SG(ALB-SG·ECS-SG·RDS-SG·Redis-SG) 위에 추가:

### 8.1. OpenSearch-SG

- **인바운드**: `ECS-SG`(배포 단위 ①)·`Ingestion-SG`(배포 단위 ②)로부터 TCP `443` (HTTPS) 허용.
- **아웃바운드**: 없음 (VPC 내부 통신만).

### 8.2. Ingestion-SG (배포 단위 ② 전용)

- **인바운드**: 없음 (워커는 아웃바운드 전용; SQS 폴링 = 아웃바운드 HTTPS).
- **아웃바운드**:
  - `OpenSearch-SG` 방향 TCP `443` (벡터 인덱스 쓰기).
  - 인터넷(`0.0.0.0/0`) TCP `443` (arXiv API · Bedrock · SQS · S3 · CloudWatch).

### 8.3. ECS-SG 확장 (배포 단위 ①)

기존 U3 규칙에 추가:
- **아웃바운드**: `OpenSearch-SG` 방향 TCP `443` (U2 벡터 검색 읽기 + Bedrock 질의 임베딩).

---

## 9. 네트워크 토폴로지 통합 다이어그램

```
VPC 10.0.0.0/16 (ap-northeast-2, 2 AZ)
├── Public Subnets (10.0.1.0/24 [AZ-A] · 10.0.2.0/24 [AZ-B])
│   ├── Internet Gateway (IGW)
│   ├── ALB → ECS Fargate 배포 단위 ① (U2/U3/U4/U6-mw API 모놀리스)
│   └── ECS Fargate 배포 단위 ② (인제스천 워커, SQS 폴링)
│
├── Isolated Private Subnets (10.0.3.0/24 [AZ-A] · 10.0.4.0/24 [AZ-B])
│   ├── RDS PostgreSQL (db.t4g.small, Multi-AZ)
│   └── ElastiCache Redis (cache.t4g.micro, Multi-AZ)
│
└── VPC-내부 OpenSearch 도메인 (docsuri-papers, VPC endpoint, 2 AZ 분산)
    └── m6g.large.search ×2 (AZ-A + AZ-B)

외부 서비스 (아웃바운드 HTTPS via IGW):
  · arXiv API (OAI-PMH + Atom + e-print)
  · Amazon Bedrock (Cohere Embed Multilingual v3)
  · Amazon SQS / S3 / EventBridge / SES
  · Google reCAPTCHA v3
```

---

## 10. 추적성 매트릭스

| 설계 요소 | 추적 요구사항 |
|---|---|
| OpenSearch 도메인 (k-NN + BM25) | NFR-P1(P50<3s 검색), FR-1(벡터 검색), FR-2(BM25 전문 검색), VectorSpec |
| 인제스천 워커 (ECS + SQS) | FR-3(arXiv 수집), BR-1(OA 라이선스), INV-1(커밋순서), RES-1(의존성맵), RES-9(재시도/서킷) |
| S3 전문 저장소 | FR-4(전문 보존), SEC-3(암호화) |
| Bedrock/Cohere | FR-1/FR-3(임베딩), TD-3(cross-lingual), VectorSpec(1024/cosine/asymmetric) |
| EventBridge 스케줄 | Q12=B(이벤트 경로), FR-3(정기 수집) |
| SQS + DLQ | RES-9(재시도), RES-1(DLQ 격리), INV-1(멱등 재처리) |
| IAM 최소 권한 | SEC-8(단일 결정점 아님 — 인프라 레벨 격리), SEC-10 |
| Multi-AZ 전 티어 | RES-2(리전 토폴로지), NFR-A1(가용성) |
| NFR-C1 비용 배분 | NFR-C1($1600/월 상한, 유닛별 배분) |

---

## 11. 범위 외 (후속)

- **IaC 구현** (Terraform/CDK): 본 문서의 명세를 코드로 구현하는 별도 PR.
- **CD 파이프라인**: ECR build-push + ECS deploy + 롤백 자동화.
- **DNS + 인증서**: Route 53 + ACM (도메인 미확정).
- **WAF**: ALB 앞단 웹 방화벽 (프로덕션 트래픽 개시 전 추가).
- **Operations 런북**: 장애 대응·DLQ redrive·인덱스 재구축 절차.
