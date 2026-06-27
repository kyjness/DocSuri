# u1-corpus-code-generation-plan.md — U1 Corpus 코드 생성 계획

**단계**: CONSTRUCTION -> Code Generation Part 1 (Planning)
**유닛**: U1 Ingestion
**일자**: 2026-06-26
**상태**: Part 1 계획 완료 — 리뷰 게이트
**단일 진실 원천**: 본 계획은 승인 후 U1 Corpus Code Generation의 실행 순서와 범위를 결정한다. 코드 생성 중 완료된 단계는 같은 상호작용에서 즉시 `[x]`로 갱신한다.

> 앱 코드는 아직 생성하지 않았다. 승인 전 변경 범위는 본 계획, `aidlc-state.md`, `audit.md`뿐이다.

---

## 1. 계획 수립 체크리스트

- [x] Code Generation rule details를 읽었다.
- [x] Content validation rule을 확인했다.
- [x] Security / Resiliency / PBT extension rule을 현재 설정 기준으로 확인했다.
- [x] U1 Corpus Functional Design, NFR Requirements, NFR Design, Infrastructure Design 산출물을 확인했다.
- [x] 기존 코드의 DocModel, ingestion, U7, frontend 접점을 확인했다.
- [x] 실제 코드 위치를 `aidlc-state.md`와 현재 repo 구조 기준으로 확정했다.
- [x] 기존 구현 재사용 우선으로 생성 단계를 작성했다.
- [x] Code Generation 승인 프롬프트를 audit에 기록한다.

## 2. 유닛 컨텍스트

### 구현 대상

| 항목 | 결정 |
|---|---|
| 유닛 | U1 Ingestion |
| 주 구현 위치 | `ingestion/` |
| 공유 계약 | `shared/dtos/docmodel.schema.json`, `shared/python/src/docsuri_shared/_generated/` |
| 소비자 정합 위치 | `backend/modules/summarization/`, `frontend/` |
| 인프라 코드 | `ops/cdk/stacks/ingestion_stack.py` 중심, 필요 시 기존 stack만 수정 |
| 생성하지 않는 것 | 신규 microservice, 신규 public GROBID endpoint, 신규 S3 bucket, 신규 queue, 신규 DB |

### 설계 입력

- U1 Corpus는 arXiv, Semantic Scholar, OpenAlex를 source별로 수집한다.
- arXiv는 HTML 우선, 없으면 PDF fallback이다.
- Semantic Scholar/OpenAlex는 PDF를 GROBID 입력으로만 사용한다.
- raw PDF는 저장하지 않는다.
- DocModel은 `fullText` 전문 텍스트 투영본과 paragraph/table/formula/figure/list/code block을 포함한다.
- 이미지 바이트, base64, presigned URL, 내부 `object_ref`는 DocModel에 넣지 않는다. figure/table image는 `assetRef.assetId`로 private `assets/`를 참조한다.
- phase-1 Corpus 논문은 수집 시점 eager DocModel 생성이 기본이다. 기존 lazy build는 누락분, 재빌드, phase-1 밖 논문 보강 경로로 유지한다.

### 현재 코드에서 확인한 갭

- `shared/dtos/docmodel.schema.json`의 `DocModel`에 required `fullText`가 없다.
- generated Python DTO와 frontend curated type에도 `DocModel.fullText`가 없다.
- `ingestion/src/docsuri_ingestion/docmodel/parser.py`는 멀티모달 block은 만들지만 `fullText` 전문 투영본을 생성하지 않는다.
- `DocModelBuilder`와 `BUILD_DOC_MODEL` job은 lazy build 중심이다.
- `IngestionPipelineService.ingest_one` hot path는 아직 DocModel eager build와 DocModel block chunking을 수행하지 않는다.
- U7 `InputRefiner`는 DocModel block을 직접 투영하지만, root `fullText`가 없으므로 전문 계약을 소비자 수준에서 검증하지 못한다.

## 3. 코드 생성 실행 단계

### Step 1 — 공유 DocModel 계약 보정

- [x] `shared/dtos/docmodel.schema.json`에 required `fullText`를 추가한다.
- [x] `DocModel.fullText` 설명을 전문 텍스트 투영본으로 명확히 한다.
- [x] `DocModel`에는 image bytes, base64, presigned URL, `object_ref`가 들어가지 않도록 schema 설명과 negative validation을 유지한다.
- [x] `shared/python/tools/generate.py`로 Python DTO를 재생성한다.
- [x] `frontend/types/generated/docModel.ts`의 curated type에 `fullText: string`을 반영한다.

### Step 2 — DocModel parser fullText projection 구현

- [x] `ingestion/src/docsuri_ingestion/docmodel/parser.py`에서 생성된 section/block tree를 읽기 순서로 순회해 `fullText`를 만든다.
- [x] 포함 대상: section title, paragraph text, table caption/cells, formula LaTeX, figure caption, list item, code text.
- [x] 제외 대상: image bytes, URLs, internal object refs, LaTeXML note/footer noise.
- [x] 기존 paragraph/table/formula/figure/list/code parsing 로직은 재사용한다.

### Step 3 — DocModel parser 테스트 보강

- [x] `ingestion/tests/test_docmodel_parser.py`에 `fullText`가 모든 block type을 읽기 순서로 포함하는 예시 테스트를 추가한다.
- [x] `fullText`가 figure asset bytes/URL을 포함하지 않는 테스트를 추가한다.
- [x] 기존 결정성 테스트가 `fullText`까지 포함해 통과하도록 유지한다.

### Step 4 — U1 eager DocModel build 경로 추가

- [x] `DocModelBuilder`를 lazy 전용 문구에서 eager+lazy 공용 builder로 정리한다.
- [x] `IngestionPipelineService.ingest_one` NEW/CHANGED 경로에서 DocModel을 build/store한다.
- [x] source unavailable 또는 validation failure는 index write 전에 failure handler로 보낸다.
- [x] 기존 `BUILD_DOC_MODEL` lazy job은 cache miss/rebuild/backfill 호환 경로로 유지한다.
- [x] tombstone/version change 시 기존 `DocModelBuilder.invalidate` 경로를 호출한다.

### Step 5 — DocModel 기반 chunk 최소 전환

- [x] 기존 `Chunker`를 보존하되, DocModel이 있으면 block-aware text를 chunk 입력으로 사용한다.
- [x] chunk metadata에 DocModel block id 참조를 추가할 수 있는 최소 구조를 만든다.
- [x] 모든 chunk의 block ref가 DocModel 내 실제 id를 가리키는 assertion을 둔다.
- [x] 기존 OpenSearch record shape와 U2 호환성을 깨지 않는 범위에서 block ref를 lexical/metadata 필드에 반영한다.

### Step 6 — Corpus source adapter 경계 확장

- [x] 기존 `ArxivSourcePort`를 바로 대체하지 않고 `CorpusSourceAdapterSet` 또는 동등한 얇은 wrapper를 추가한다.
- [x] arXiv adapter는 기존 `adapters/arxiv.py`를 재사용하고 HTML 우선, PDF fallback 정책을 명시한다.
- [x] Semantic Scholar/OpenAlex adapter는 PDF metadata/fetch boundary만 추가한다.
- [x] GROBID 호출은 내부 port/adapter로 감싸고, raw PDF bytes는 함수 스코프에서만 사용한다.
- [x] source별 permanent/retriable failure classification을 기존 `IngestFailureHandler`에 맞춘다.

### Step 7 — source별 watermark와 canonical dedup 저장

- [x] `ingestion/migrations/postgres/`에 source watermark, canonical dedup, paper version state, corpus generation/job item 스키마를 추가한다.
- [x] 기존 `PostgresControlPlaneStore`와 in-memory fake store에 최소 메서드를 추가한다.
- [x] DOI -> arXiv id -> normalized title/first author/year 순서의 canonical key를 구현한다.
- [x] losing duplicate는 index/embed 없이 provenance만 남긴다.

### Step 8 — retry/DLQ payload 보강

- [x] `IngestionJob` 또는 message body에 `sourceName`, `failureStage`, `canonicalKey`, `paperId`, `version`을 싣는다.
- [x] 기존 SQS queue/DLQ adapter를 재사용한다.
- [x] reprocess는 원 pipeline을 다시 타고 dedup/upsert idempotency로 중복을 방지한다.

### Step 9 — OpenSearch generation/alias 코드 경계

- [x] 기존 vector index adapter를 generation index name과 active alias를 받을 수 있게 확장한다.
- [x] candidate generation write와 active alias cutover를 분리한다.
- [x] validation 실패 시 alias cutover를 막고 기존 active alias를 유지한다.
- [x] rollback은 이전 alias target 유지/복귀로 처리한다.

### Step 10 — runtime/settings/CDK wiring

- [x] `ingestion/src/docsuri_ingestion/settings.py`에 Corpus 관련 env를 추가한다.
- [x] `ingestion/src/docsuri_ingestion/runtime.py`에서 source adapters, GROBID, DocModel store, generation writer를 wiring한다.
- [x] `ops/cdk/stacks/ingestion_stack.py`는 기존 worker service를 재사용하고 GROBID sidecar/env/IAM만 필요한 만큼 추가한다.
- [x] 신규 queue/bucket/db는 만들지 않는다.

### Step 11 — U7 소비자 정합

- [x] `backend/modules/summarization`의 DocModel fixture/tests에 required `fullText`를 반영한다.
- [x] `InputRefiner.refine_doc_model`이 `sections` 기반 투영을 유지하되, root `fullText`와 크게 불일치하지 않는 smoke assertion을 둔다.
- [x] `S3DocModelReader`는 기존 bare paper id key normalization을 유지한다.
- [x] summary/translation 로직은 바꾸지 않는다. 입력 계약만 보강한다.

### Step 12 — frontend 소비자 정합

- [x] `frontend/types/generated/docModel.ts`와 fixtures/tests에 `fullText`를 추가한다.
- [x] `DocModelViewer` 렌더 구조는 유지한다.
- [x] `fullText`는 검색/접근성 fallback 또는 테스트 검증용 데이터로만 사용하고 화면 중복 렌더는 추가하지 않는다.

### Step 13 — 단위 테스트와 PBT

- [x] shared schema validity/drift check를 통과시킨다.
- [x] ingestion DocModel parser/builder/eager build tests를 추가하거나 갱신한다.
- [x] canonical dedup/idempotency/source watermark에 property-based tests를 추가한다.
- [x] source adapter/GROBID는 network-free fake tests로 먼저 검증한다.
- [x] raw PDF 미저장 negative test를 둔다.

### Step 14 — 통합 smoke

- [x] fake adapters로 NEW/CHANGED paper가 FullText -> DocModel -> chunk -> embed -> index generation manifest까지 진행되는 smoke test를 추가한다.
- [x] DLQ/retry path가 stage/source metadata를 보존하는 테스트를 추가한다.
- [x] U7 `GET /api/papers/{id}/doc-model`과 summary input tests를 갱신한다.
- [x] frontend `classifyDocModel` / `useDocModel` / viewer targeted tests를 갱신한다.

### Step 15 — 검증 명령

- [x] `uv run python tools/generate.py --check`를 `shared/python/` 기준으로 실행한다.
- [x] `uv run pytest`를 `ingestion/` 기준으로 실행한다.
- [x] `uv run ruff check .`를 `ingestion/` 기준으로 실행한다.
- [x] `uv run pytest`를 `backend/modules/summarization/` 기준으로 실행한다.
- [x] frontend targeted vitest와 typecheck를 실행한다.
- [x] 변경 후 `git diff --check`를 실행한다.

### Step 16 — 코드 요약 문서 생성

- [x] `aidlc-docs/construction/u1-ingestion/code/u1-corpus-code-summary.md`를 생성한다.
- [x] 수정/생성 파일, 설계 추적성, 테스트 결과, extension compliance를 기록한다.
- [x] 계획 체크박스를 모두 `[x]`로 갱신한다.
- [x] `aidlc-state.md`를 Code Generation 완료 리뷰 게이트로 갱신한다.

## 4. 스토리/요구사항 추적성

| 요구사항/스토리 | 계획 단계 |
|---|---|
| FR-6 U1 Corpus 구축 | Step 4-10, Step 13-16 |
| FR-18 DocModel 리치뷰/AI 입력 | Step 1-5, Step 11-12 |
| US-I1 Corpus seed/indexing | Step 4-10, Step 14 |
| US-I2 source별 incremental update | Step 6-8, Step 13 |
| US-I3 retry/DLQ/reprocess | Step 8, Step 14 |
| NFR-C1 비용 제어 | Step 6, Step 8, Step 10 |
| QT-9 DocModel/index 불변식 | Step 1-5, Step 13-14 |

## 5. Extension Compliance 계획

### Security Baseline

- **Compliant / Applicable**: SEC-01, SEC-03, SEC-05, SEC-06, SEC-09, SEC-10, SEC-15.
- 계획 반영: private S3, raw PDF transient, no public GROBID endpoint, schema validation, no secret logging, least-privilege IAM, generated DTO drift check.
- **N/A**: browser security headers, auth/password rules 등은 U1 worker code generation의 직접 범위가 아니다.

### Resiliency Baseline

- **Compliant / Applicable**: RESILIENCY-01, RESILIENCY-05, RESILIENCY-06, RESILIENCY-07, RESILIENCY-08, RESILIENCY-09, RESILIENCY-12, RESILIENCY-13, RESILIENCY-14.
- 계획 반영: source별 watermark, stage-aware retry/DLQ, source circuit behavior, generation alias cutover/rollback, smoke tests, budget stop.
- **N/A**: 새 DR topology나 별도 deployment process 결정은 이번 코드 계획에서 새로 만들지 않는다. 기존 AWS/GitHub Actions/CDK 정책을 재사용한다.

### Property-Based Testing

- **Partial mode blocking**: PBT-02, PBT-03, PBT-07, PBT-08, PBT-09.
- 계획 반영: DocModel schema roundtrip, `fullText` projection invariants, canonical dedup idempotency, watermark monotonicity, generator reuse.
- **Advisory**: PBT-01/04/05/06/10은 설계 문서의 기존 PBT 항목을 유지하고 필요한 경우 regression example test를 추가한다.

## 6. Content Validation

- Mermaid diagram: 없음.
- ASCII diagram: 없음.
- Markdown tables: simple pipe table only.
- Code fences: 없음.
- 특수 문자는 Markdown inline code로 제한했다.
