# Solo/Local Migration — 팀 AWS 운영 종료 후 로컬 개발 환경 전환

> **Status**: ⛔ **SUPERSEDED (2026-08-16)** — 이 문서의 절차를 그대로 따르지 말 것.
> 아래 본문은 2026-07 "AWS 회수 → 로컬 + OpenAI" 전환의 **결정 기록**으로 보존한다.
>
> **무엇이 바뀌었나.** AWS가 복구되어 Bedrock이 다시 현행이고, 코퍼스는
> `cohere.embed-v4:0`으로 재색인됐다. OpenAI 경로(임베딩 어댑터 2개 · LLM 어댑터 3개 ·
> 프로바이더 스위치 5개)는 저장소에서 **제거**됐다. 따라서 §5의 `OPENAI_API_KEY` /
> `DOCSURI_EMBEDDING_PROVIDER=openai` / `DOCSURI_LLM_PROVIDER=openai` 설정은 더 이상
> 읽히지 않으며, 설정해도 무시된다.
>
> **왜 되돌렸나.** 이 문서 §2가 "차원 파라미터로 vector_spec 계약을 유지"한다고 적은 것이
> 정확히 위험 지점이었다 — OpenAI 1024차원과 Cohere 1024차원은 **차원 검사에 안 걸리는
> 다른 공간**이라, 색인과 리더가 갈리면 증상이 "검색 품질이 나쁘다"로만 나타난다.
> 코퍼스가 Bedrock으로 재색인된 이후 OpenAI 리더는 대체 경로가 아니라 공간 불일치였다.
>
> 현행 설정은 `.env.example`, 배포 형상은 `ops/cdk/`를 보라.

> **Status(당시)**: in progress (2026-07-14 시작)
> **Owner**: kyjness (solo fork)
> **위상**: 운영 문서. AI-DLC 동결 산출물이 아니며, 전환 작업의 결정 기록 + 실행 절차를 담는다.

## 1. 상황 변화

| | 이전 (팀, ~2026-07) | 이후 (솔로 포크) |
|---|---|---|
| 팀 | 4인, upstream `80-hours-a-week/DocSuri` | 1인, fork에서 로컬 커밋 위주 |
| 인프라 | AWS (C-5), 총예산 $1,600 | **예산 종료 — 모든 AWS 리소스 회수됨** |
| LLM/임베딩 | Bedrock (Claude Sonnet / Cohere Embed v4) | 개인 API 키 (OpenAI 결제분 활용) |
| 목표 | 서비스 운영 | 로컬에서 E2E 실동작 확인 + 에이전트 재설계 학습 |
| 배포 | https://docsuri.org (Route53) | **보류** — 도메인 갱신만 유지, 서버 비용은 공개 배포 재개 시점에 재결정 |

원칙: **도메인 코드는 건드리지 않는다.** 이 프로젝트는 헥사고날(포트/어댑터) + 조건부 마운팅
구조이므로, 전환은 (a) 어댑터 추가, (b) env 설정, (c) 데이터 재색인으로만 이뤄져야 한다.

## 2. 인프라 대체 맵

| AWS | 로컬 대체 | 코드 변경 | 근거 / 비고 |
|---|---|---|---|
| OpenSearch (관리형) | `backend/docker-compose.yml`의 단일 노드 (이미 존재) | 없음 | k-NN 번들, 보안 플러그인 OFF. `DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200` |
| RDS Postgres | compose의 postgres:16 (이미 존재) | 없음 | `DATABASE_URL=postgresql+psycopg://docsuri:docsuri@localhost:5432/docsuri` |
| ElastiCache Redis | compose의 redis:7 (이미 존재) | 없음 | accounts 세션 스토어 |
| S3 (doc-model / full-text / assets / summaries) | **s3proxy가 다운로드된 미러를 그대로 서빙** ✅ 검증됨 | 거의 없음* | boto3 ≥1.28은 `AWS_ENDPOINT_URL_S3` env를 자동 인식 → 클라이언트 코드 무수정. 미러: `~/data/docsuri-data/s3/` (24GB, 아래 §3) |
| SQS (ingestion job queue) | **당장 불필요** | 없음 | doc-model이 전부 사전 빌드돼 있어 BUILD_DOC_MODEL 경로가 콜드스타트에 필요 없음. 필요해지면 ElasticMQ 또는 인프로세스 큐로 재결정 |
| Bedrock 임베딩 (Cohere Embed v4, 1024-dim) | **OpenAI `text-embedding-3-small` + `dimensions=1024`** | 어댑터 2개 추가 | 차원 파라미터로 shared `vector_spec.DIMENSIONS=1024` 계약을 그대로 유지 → 인덱스 매핑/IndexRecord 무수정. Cohere의 reader/writer `input_type` 비대칭은 대칭 모델이라 삭제 |
| Bedrock LLM (Claude Sonnet/Haiku) | OpenAI API (추후 Anthropic API 선택 가능) | 어댑터 추가 | summarization의 forced-tool-call 구조화 출력 패턴을 OpenAI tool-choice로 동일 재현. novelty/evidence는 에이전트 재설계(별도 유닛)에서 함께 교체 |
| Bedrock rerank (cross-encoder) | **활성** *(2026-08-15)* | 도쿄 `cohere.rerank-v3-5:0` | `DOCSURI_RERANK_MODEL_ARN` 설정만으로 켜짐(코드 변경 없음). 모델 액세스 승인·`bedrock:Rerank` 별도 신청 **불필요**(2026-08-15 실측). 서울엔 모델이 없어 크로스리전이며 리전은 ARN에서 역산. 요청속도 쿼터가 실질 제약 — 스로틀 시 baseline fail-soft + WARNING |
| CloudWatch | stdout 구조화 로그 | 없음 | ObservabilityHub는 이미 주입식 |

*S3 예외 1건: `summarization/adapters/rds_assets.py:56`이 presign URL을 `https://s3.{region}.amazonaws.com`으로
하드코딩 — 로컬에서 figure 자산 표시가 필요해지는 시점에 endpoint 설정화 패치 필요 (그 전까지는 미표시로 무해).

### S3 대체 선정 기록 (2026-07-14 검증 완료)

**채택: `andrewgaul/s3proxy`** (jclouds filesystem 백엔드) — 미러 디렉토리를 무변환·무복제로
버킷 `docsuri`로 서빙. boto3로 list/get/put/delete 전부 검증됨 (요약 캐시 쓰기 포함).

기각된 대안:
- MinIO (구버전 fs-mode 핀 포함) — export 경로 아래의 서브마운트를 마운트 테이블 기준으로
  거부(`Cross-device mounts detected`)해서, 미러를 바인드하는 어떤 구성으로도 기동 불가.
  동일 디바이스 이중 바인드 트릭도 실패 (docker 바인드는 항상 별도 마운트 엔트리).
- 최신 MinIO + `mc mirror` 임포트 — 24GB 디스크 2배 소모라 기각.

## 3. 데이터 인벤토리와 재색인

### 보유 데이터 (`~/data/docsuri-data/`, S3 종료 전 다운로드, 24GB · 358,696 파일)

| prefix | 파일 수 | 내용 |
|---|---|---|
| `s3/doc-model/` | 30,065 | `<paper_id>/v<N>.json` — 파싱 완료된 DocModel (섹션/표/그림 구조) |
| `s3/full-text/` | 30,221 | 정규화 전문 |
| `s3/assets/` | 298,234 | figure/formula bbox 크롭 (WebP) |
| `s3/summaries/` | 173 | 캐시된 요약/번역 |
| `s3/novelty/` | 1 | novelty 아티팩트 |
| `docmodel-keys.txt`, `docmodel-manifest.tsv` | — | 키 목록, parser 버전 매니페스트 |

키가 상대경로(`doc-model/...`)이므로 **단일 버킷 + prefix 구조**. MinIO에서 버킷 `docsuri`로 마운트하고
`DOCSURI_S3_BUCKET` / `DOCSURI_DOCMODEL_BUCKET` 등을 `docsuri`로 지정한다.

### 무엇을 재생성해야 하나

- **재파싱 불필요** — DocModel은 완성 산출물.
- **재색인 필요** — OpenSearch 인덱스(`docsuri-corpus-v1`)는 백업이 없으므로:
  `doc-model JSON → Chunker.chunk_doc_model → OpenAI 임베딩(1024-dim) → bulk_upsert`.
  인덱스 매핑은 `docsuri_shared.index_spec.papers_index_body()` 재사용 (U1 writer와 동일 SSOT).
- **재임베딩 = 임베딩 공간 교체** — Cohere 벡터와 OpenAI 벡터는 호환되지 않으므로 전량 재임베딩이며,
  reader(query embed)도 반드시 같은 모델로 교체돼야 한다 (기존 dimension-mismatch fail-loud 가드가 그대로 지켜줌).

### 비용 추정 (OpenAI text-embedding-3-small, $0.02/1M tok)

실측 보정 (2026-07-15, 첫 20편 = 1,956청크 → **논문당 평균 ~98청크 ≈ 59K 토큰**):

| 범위 | 대략 토큰 | 비용 |
|---|---|---|
| 1,000편 | ~59M | ~$1.2 |
| 서브셋 3,000편 | ~176M | **~$3.5** |
| 전체 30,065편 | ~1.8B | ~$35 |

→ **서브셋으로 시작**해 E2E를 살리고, 전체 재색인은 검색 품질 확인이 필요할 때 1회 실행.
스크립트는 `--limit`(서브셋)과 이어하기(이미 색인된 paper_id 스킵)를 지원해야 한다.

## 4. 로컬 환경 변수 프로파일

레포 루트 `.env`가 단일 소스다 (gitignore 대상; 템플릿은 `.env.example` 커밋).
셸에서 쓸 때는 `set -a; source .env; set +a`.

```bash
# --- stores ---
DATABASE_URL=postgresql://docsuri:docsuri@localhost:5432/docsuri
# 주의: SQLAlchemy식 postgresql+psycopg:// 를 쓰면 raw-psycopg 소비자(용어집 repo)가
# DSN 파싱에 실패한다. 평문 postgresql:// 로 두면 db.py가 알아서 +psycopg를 붙인다.
DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200
DOCSURI_OPENSEARCH_USE_SSL=0
DOCSURI_OPENSEARCH_VERIFY_CERTS=0

# --- S3 substitute (s3proxy가 미러를 버킷 docsuri로 서빙) ---
AWS_ENDPOINT_URL_S3=http://localhost:9000
AWS_ACCESS_KEY_ID=docsuri
AWS_SECRET_ACCESS_KEY=docsuri-local
AWS_DEFAULT_REGION=ap-northeast-2        # 클라이언트 생성용 더미
DOCSURI_S3_BUCKET=docsuri
DOCSURI_DOCMODEL_BUCKET=docsuri
DOCSURI_SUMMARY_BUCKET=docsuri           # U7 마운트 게이트

# --- LLM / embeddings (개인 키) ---
OPENAI_API_KEY=sk-...
DOCSURI_EMBEDDING_PROVIDER=openai        # U2 쿼리 임베더 스위치
DOCSURI_LLM_PROVIDER=openai              # U7 LLM 게이트웨이 스위치 (기본 모델 gpt-4o-mini)
DOCSURI_DOCMODEL_VIEWER_ENABLED=1        # U7 소스를 DocModel 경로로 (미러에 전부 있음)
```

## 5. 실행 절차 (목표 상태)

```bash
docker compose -f backend/docker-compose.yml up -d       # postgres+redis+opensearch+minio
python tools/local/reindex_docmodels.py --limit 3000     # 서브셋 재색인 (작성 예정)
uvicorn backend.main:app --reload                        # 앱셸 (설정된 모듈만 마운트)
cd frontend && pnpm run dev                              # http://localhost:3000
```

## 6. 전환 중 발견/수리한 사항 (2026-07-15 검증 로그)

- **검증 완료 E2E**: `POST /api/search` (OpenAI 쿼리 임베딩 → 로컬 OpenSearch 하이브리드 →
  RRF → U6 grounding enforce → 카드), `GET /api/papers/{id}`, 요약 전체 경로
  (DocModel 소스 → gpt-4o-mini 강제 tool-call → U7 결정론 grounding 게이트 → s3proxy 캐시
  기록/히트). HTTP `/api/summarize`는 세션 인증(Redis+로그인) 뒤라 인프로세스로 검증.
- **수리**: ingestion `OpenSearchVectorIndex`가 `use_ssl`을 전달하지 않아 로컬 http 클러스터
  접속 불가 → 전달하도록 수정. backend가 `docsuri-discovery`를 `[real]` extra 없이 선언해
  opensearch-py 부재로 discovery가 조용히 스킵 → `[real]` 추가. 스타트업 마이그레이션
  러너에 summarization(용어집) 마이그레이션 누락 → 추가.
- **알려진 이슈 (③ 유닛 리뷰로 이관)**:
  - refiner legacy `.txt` 경로: U1 정규화 전문은 개행이 없어 한 줄인데, 라인 단위 노이즈
    제거가 저작권 패턴(`(c)` 등)이 아무 데나 있으면 문서 전체를 삭제 → body가 빈다.
    (DocModel 경로가 기본이라 실경로 영향 없음; legacy 폴백만 침묵 실패)
  - summarization `tests/test_pbt.py::test_pbt_response_to_dict_sec9_all_states` — 마이그레이션
    이전부터 실패하는 hypothesis 케이스 (변경분과 무관 확인).
  - gpt-4o-mini가 요약을 영어로 출력하는 사례 → 프롬프트 한국어 강제 보강 또는 summary
    모델 상향(`DOCSURI_SUMMARY_MODEL_ID=gpt-4o`)으로 해결 가능.

## 6.1 로컬 피처 플래그 & 본질적 제한 (2026-07-24 진단)

전환 검증(§6)은 search·papers·summary 경로만 다뤘다. 나머지 유닛은 **롤아웃 게이트가 기본 off**라 로컬
`.env`에서 명시적으로 켜야 동작한다. 안 켜면 라우터 전체가 **404**(인증 앞단 dependency가 먼저 raise) —
"AWS→로컬 전환으로 깨졌다"로 오인하기 쉬우나 회귀가 아니라 미활성이다.

**로컬에서 켜야 하는 플래그(`.env`):**

| 플래그 | 유닛 | 안 켜면 | 비고 |
|---|---|---|---|
| `PERSONALIZATION_ENABLED=1` | u9 | `/api/personalization/*` 전체 404 (events·settings·recently-viewed) | 프론트는 events를 best-effort로 삼켜 화면 비치명적 |
| `CITATION_GRAPH_ENABLED=1` | u8 | `/api/papers/{id}/citation-tree` 404 | 아래 참조 |
| `DOCSURI_SUMMARY_MODEL_ID=gpt-4o` | u7 | 기본 gpt-4o-mini — 요약 영어 출력·앵커 빈약 | 품질 레버(선택) |

**로컬에서 본질적으로 제한되는 것:**

- **citation-tree**: 로컬 코퍼스가 아니라 **Semantic Scholar 라이브 API**(`/paper/{id}/references`) 호출 +
  Redis 캐시. 로컬 엣지 인제스트 불필요하나, S2 **익명 rate-limit**이 간헐 실패 요인(키 없으면 429).
- **요약 출처앵커**: OpenAI 어댑터도 Bedrock과 동일 forced-tool 스키마로 앵커를 방출한다(구조적 문제 아님).
  앵커가 안 보이면 하류 SOFT-drop — gpt-4o-mini 품질 또는 구 파서 세대 저장분의 라벨 resolve 실패. **번역은
  설계상 grounding-free = 앵커 없음이 정상**(`TranslationView.tsx`).
- **evidence(u11) 모듈**: 로컬 마운트 실패(`TypeError: NoneType not iterable`). `evidence/real_wiring.py`가
  Bedrock Cohere 임베더를 `model_id=None`으로 생성(`bedrock_embedding.py "-v3" in model_id`). discovery는
  OpenAI 임베더로 전환됐으나 evidence real_wiring은 Bedrock 전용 → **u11 별도 수리 대상**(로컬 미대응).

**로컬 준비성 점검 도구 (`tools/local/smoke.py`)**: 비-에이전트 표면을 in-process ASGI로 로컬 인프라에 태워
전수 점검(실 세션 인증, 모듈별 대표 플로우, ok/degraded/fail/skip 분류). 리팩토링마다 재실행하는 회귀 방지.
```bash
set -a; source .env; set +a
backend/.venv/bin/python tools/local/smoke.py             # 무료 표면
backend/.venv/bin/python tools/local/smoke.py --with-llm  # + 유료 소수(OpenAI·S2)
```
**2026-07-24 실행 결과: 20/20 ok** (degraded·fail 0) — search 20건(실경로)·doc-model 10섹션·요약 앵커 3개
(@10 논문)·번역 200·citation 30 edges. "앵커 안뜸"은 파이프라인 결함이 아니라 **구세대(`version=1`) 저장분**에서
라벨 resolve 실패로 드롭된 것 확인. `ops` 403은 USER authz 정상, `orcid-profile` 404는 미연동 정상.

## 7. 미룬 결정 (deferred)

| 결정 | 보류 사유 | 재검토 시점 |
|---|---|---|
| 배포 (docsuri.org 재연결) | 서버 비용. 도메인 갱신(연 ~$13 + 호스팅존 $0.5/월)만 유지 | 비용 확보 시. **AWS 재배포**(이관 이전 구성 복귀)가 전제 — 대체 호스팅은 검토 대상 아님 |
| SQS 대체 | 사전 빌드된 DocModel로 큐 없이 동작 | 신규 논문 인제스트가 필요해질 때 |
| rerank 로컬 대체 | 불필요 — 도쿄 Bedrock 직접 호출(2026-08-15 활성) | — |
| 전체 30k 재색인 | 서브셋으로 개발 충분 | 검색 품질 평가 필요 시 ($6–9) |
| Anthropic API 병행 | OpenAI 키로 시작 | 에이전트 재설계에서 모델 비교가 필요할 때 |
| GROBID 표 구조 복원 교체 | 노출 범위가 fallback 티어뿐 (아래) | 비-arXiv 소스 비중이 커지거나 표 숫자 정확도가 요구될 때 |

### GROBID 표 셀 복원의 한계와 업그레이드 경로

GROBID 0.8.0은 다중행 헤더가 있는 표에서 셀을 병합·절단해 내보낸다. 픽스처 논문 `2210.12090`의
Table 2에서 `Dimensionality Reduction`이 `'Dimensionality Fast ICA '`로 합쳐지고 `PCA (1)`이
이웃 셀에 먹힌다. **TEI 원본이 이미 그 상태**이므로 파서에서 고칠 수 있는 문제가 아니다.
셀을 재분할하는 휴리스틱은 원본에 없는 정보를 추정하는 것이고, 그렇게 만든 숫자를 U7 grounding의
numeric-match가 그대로 신뢰하므로 **틀린 숫자가 빈칸보다 나쁘다**. 넣지 않는다.

노출 범위는 제한적이다 — `application.py`가 arXiv 논문에 ar5iv HTML을 먼저 쓰고 PDF/GROBID는
`status="pdf_fallback"`이다. 같은 논문의 ar5iv 경로는 표 6개를 셀 손상 없이 만든다. 즉 이 손상은
ar5iv가 없는 비-arXiv 소스(S2/OpenAlex)에서 주로 드러난다.

품질을 올려야 할 때의 선택지와 **라이선스 함정**(이 저장소는 TD-11/13에서 이미 AGPL 때문에
PyMuPDF를 회피했다):

| 후보 | 라이선스 | 비고 |
|---|---|---|
| Docling / TableFormer (IBM) | MIT | 로컬 CPU 구동 가능. 현재 오픈 기본값으로 가장 무난 |
| Table Transformer (MS) | MIT | PubTables-1M 학습, 검출+구조 인식 분리 |
| PP-StructureV2 (PaddleOCR) | Apache-2.0 | 표 구조를 HTML로 |
| Nougat (Meta) | **CC BY-NC** | 상업 이용 불가 — 채택 불가 |
| Marker | **상용 제한** | 채택 불가 |

가장 싼 경로는 새 엔진 도입이 아니라 **이미 저장돼 있는 표 크롭 이미지를 필요한 시점에 vision
모델로 재판독**하는 것이다. 설계가 애초에 그 용도로 크롭을 남겨두고 있다(D8 / TD-11,
`docmodel/tei.py`의 table 크롭 주석).
