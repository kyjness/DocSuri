# U1 Corpus Code Generation Summary

**Stage**: CONSTRUCTION / U1 Corpus / Code Generation Part 2
**Branch**: `feature/u1-corpus-code-generation`
**Date**: 2026-06-26

## 구현 요약

U1 Corpus 구축 파이프라인의 코드 생성 범위를 구현했다. 핵심 변화는 DocModel을 AI 입력용 완성형 산출물로 승격하고, ingestion index 경로가 가능한 경우 DocModel을 먼저 만든 뒤 block-aware chunk를 생성하도록 바꾼 것이다.

## 주요 변경

- `shared/dtos/docmodel.schema.json`
  - `DocModel.fullText`를 required 필드로 추가했다.
  - `fullText`는 reading-order 텍스트 투영본이며 image bytes, base64, presigned URL, object ref를 포함하지 않는다.
  - Python generated DTO와 frontend curated type을 갱신했다.

- `ingestion/src/docsuri_ingestion/docmodel/parser.py`
  - section/block tree에서 paragraph, table, formula, figure caption, list, code 텍스트를 읽기 순서로 투영해 `fullText`를 생성한다.
  - abstract metadata를 `s0.p1` DocModel paragraph block으로도 모델링해 semantic embedding 대상에 포함한다.
  - asset internals와 raw binary는 projection에 포함하지 않는다.

- `ingestion/src/docsuri_ingestion/application.py`
  - full-text 저장 후 index write 전에 DocModel을 eager build한다.
  - arXiv HTML/ar5iv가 없으면 이미 확보된 PDF/full-text fallback 텍스트로 최소 DocModel을 생성한다.
  - lazy `BUILD_DOC_MODEL`도 arXiv HTML 미가용 시 동일한 PDF/full-text fallback DocModel 정책을 사용한다.
  - Semantic Scholar/OpenAlex `sourceRecord` job도 PDF -> GROBID -> FullText -> DocModel -> chunk/embed/index 공통 경로를 탄다.
  - arXiv와 외부 source 모두 canonical dedup state를 갱신하고, source priority(arXiv > Semantic Scholar > OpenAlex)를 적용한다.
  - 이미 상위 priority source가 이긴 canonical key는 PDF/GROBID fetch 전에 duplicate로 종료하고, 상위 source가 나중에 도착하면 기존 하위 source chunk를 tombstone 처리한다.
  - canonical dedup state는 DOI, arXiv, title/author/year alias row를 같은 winner에 묶는다. DOI-only 외부 record도 title alias로 이후 arXiv ingest와 매칭되며, arXiv가 lower-priority external winner를 대체할 때 기존 DOI alias도 새 arXiv winner로 이동한다.
  - withdrawal-detected paper는 tombstone 후 canonical winner로 기록하지 않아 정상 외부 복본을 삭제하지 않는다.
  - successful tombstone은 해당 `paperId`의 canonical winner rows를 삭제해 철회된 winner가 후속 외부 복본 ingest를 막지 않는다.
  - tombstone 시 DocModel cache invalidation을 수행한다.
  - canonical loser 제거 시에도 index tombstone, DocModel cache invalidation, asset cleanup을 대칭 수행한다.

- `ingestion/src/docsuri_ingestion/processors.py`
  - `Chunker.chunk_doc_model()`을 추가해 DocModel block 단위 chunk를 생성한다.
  - chunk에 section/block/type metadata를 보존하고, `IndexRecord.blockRefs[]`를 `{paperId, version, sectionId, blockId, blockType}` 구조화 필드로 저장한다.
  - DocModel 기반 chunking은 DocModel block만 사용하므로 모든 DocModel-derived index record가 실제 DocModel block을 참조한다.
  - text-bearing block이 없는 DocModel은 `fullText`를 첫 실제 block ref에 연결해 fallback chunk를 생성한다.
  - `blockRefs`는 provenance/QT-9 검증용이며 BM25 `lexicalTerms` 검색 토큰에는 섞지 않는다.
  - `doi`, `sourceArxivId`, `sourceProvenance`를 IndexRecord에 보존한다. 외부 source가 arXiv alias를 제공하면 `paperId`가 `src-*`여도 카드용 `arxivId`는 실제 alias를 사용한다.

- `ingestion/src/docsuri_ingestion/corpus_sources.py`
  - arXiv HTML/PDF 우선순위는 기존 adapter를 재사용한다.
  - Semantic Scholar/OpenAlex는 PDF bytes를 메모리에서만 GROBID로 넘기고, 반환 artifact에는 PDF bytes를 저장하지 않는다.
  - provider가 주입된 source는 incremental metadata와 PDF fetch 경로를 제공하며, 미주입 source는 refresh에서 metric으로 건너뛴다.
  - Semantic Scholar/OpenAlex 실 HTTP provider 구현과 credential/quota 운영 결정은 이 PR 범위 밖이며 Operations/follow-up에서 처리한다.

- `ingestion/src/docsuri_ingestion/domain/canonical.py`
  - canonical key 우선순위는 DOI -> arXiv id -> title/author/year hash다.
  - source별 dedup state 저장 포트를 in-memory/Postgres에 추가했고, canonical alias rows를 paperId 기준으로 조회/이동할 수 있게 했다.

- `ingestion/src/docsuri_ingestion/domain/models.py`, `worker.py`, queue adapters
  - retry/DLQ payload에 `sourceName`, `sourceRecord`, `failureStage`, `canonicalKey`, `paperId`, `version`을 포함한다.

- `ingestion/src/docsuri_ingestion/adapters/aws.py`
  - OpenSearch candidate generation validation과 alias cutover 메서드를 추가했다.
  - validation 실패 시 alias switch를 호출하지 않는 경계를 테스트했다.
  - OpenSearch mapping은 shared `papers_index_body()`를 SSOT로 사용하며, `blockRefs`/`sourceProvenance`는 검색하지 않는 provenance라 non-indexed object로 저장한다. DOI/arXiv source alias는 keyword로 저장한다.

- `ingestion/src/docsuri_ingestion/adapters/grobid.py`, `runtime.py`, `settings.py`
  - GROBID HTTP client와 runtime wiring을 추가했다.
  - 429/일시적 4xx는 retriable로 분류하고, malformed PDF 성격의 4xx만 permanent로 둔다.
  - `DOCSURI_OPENSEARCH_ALIAS`, `DOCSURI_CORPUS_SOURCES`, `DOCSURI_GROBID_URL` 설정을 추가했다.

- `ops/cdk/stacks/ingestion_stack.py`
  - 기존 ingestion worker service를 유지하면서 internal GROBID sidecar와 env만 추가했다.
  - 신규 queue, bucket, DB는 만들지 않았다.

- `backend/modules/summarization`
  - DocModel fixtures/tests에 required `fullText`를 반영했다.
  - 번역 DocModel은 LLM 로직 변경 없이 sections에서 root `fullText`를 재투영해 계약 일관성을 유지한다.

- `frontend`
  - DocModel fixtures/tests에 `fullText`를 추가했다.
  - `DocModelViewer` 렌더 구조는 변경하지 않고, 화면 중복 렌더도 추가하지 않았다.

## 신규 파일

- `ingestion/src/docsuri_ingestion/corpus_sources.py`
- `ingestion/src/docsuri_ingestion/domain/canonical.py`
- `ingestion/src/docsuri_ingestion/adapters/grobid.py`
- `ingestion/src/docsuri_ingestion/adapters/corpus_http.py`
- `ingestion/migrations/postgres/003_corpus_control_plane.sql`
- `ingestion/tests/test_canonical_dedup.py`
- `ingestion/tests/test_corpus_sources.py`
- `ingestion/tests/test_grobid_adapter.py`
- `ingestion/tests/test_runtime.py`
- `aidlc-docs/construction/u1-ingestion/code/u1-corpus-code-summary.md`

## 2026-06-27 코퍼스 빌드 전 리뷰 보정

- DocModel 계약을 FROZEN으로 전환하고, footnote/references/page 제외 및 PDF/GROBID 단일 paragraph degrade를 명시했다.
- `lexicalTerms`는 본문 청크 전용 analyzed 필드로 줄이고, `title`/`abstract`는 기존 analyzed 표시 필드를 lexical 검색에도 재사용한다. 현재 U2 reader는 세 필드를 equal-weight `multi_match`로 조회하고, boost 튜닝은 재색인 없이 query 변경으로 적용한다.
- Semantic Scholar/OpenAlex 실 HTTP provider를 추가했다. production runtime은 GROBID 설정이 있을 때만 외부 provider를 배선해 PDF fetch 후 기존 GROBID/DocModel/index 경로로 보낸다.
- `migrate.py backfill`은 legacy `chunk()` 직접 재색인을 제거하고, OAI metadata를 기존 ingestion pipeline에 넣어 DocModel blockRefs 기반으로 재임베딩한다.
- local runtime에 in-memory DocModelBuilder를 주입해 local/prod indexing path를 맞췄다.
- HTML 본문에 `meta.abstract`와 동일한 abstract section이 있으면 첫 abstract section을 제거해 semantic embedding 이중계상을 막는다.
- `DocModelBuilder` cache hit는 cached provenance `parserVersion`/`schemaVersion`이 현재 shared doc-model contract와 일치할 때만 재사용한다. U7 `S3DocModelReader`도 같은 contract를 검사하고 mismatch를 cache miss로 처리해 오래된 lazy-build S3 artifact를 노출하지 않는다.
- `trigger-full-rebuild` preflight가 production corpus build 전에 multimodal assets ON, external source용 GROBID URL, `DOCSURI_BEDROCK_MODEL_ID_V2` unset, worker rollout 완료 및 harvest redeploy freeze 확인(`DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED=true`)을 강제한다.

## 검증 결과

- `shared/python`: `uv run python tools/generate.py --check` -> passed
- `shared/python`: `uv run pytest` -> 66 passed
- `ingestion`: `uv run pytest` -> 129 passed, 1 skipped
- `ingestion`: `uv run ruff check .` -> passed
- `ops`: `uv run pytest` -> 42 passed
- `backend/modules/discovery`: `uv run pytest` -> 53 passed, 3 skipped
- `backend/modules/summarization`: `uv run pytest` -> 116 passed, 3 skipped
- `frontend`: targeted `pnpm exec vitest ...` -> 5 files, 19 tests passed
- `frontend`: `pnpm exec tsc --noEmit` -> passed
- repo root: `git diff --check` -> passed
- 2026-06-27 review follow-up: `uv run --directory ingestion pytest tests/test_orchestration.py tests/test_docmodel_build_job.py tests/test_corpus_sources.py tests/test_canonical_dedup.py -q` -> 39 passed
- 2026-06-27 review follow-up: `uv run --directory ingestion ruff check src tests/test_orchestration.py tests/test_docmodel_build_job.py` -> passed
- 2026-06-27 review follow-up: `uv run --directory ingestion pytest -q -rA` -> 132 passed, 1 skipped
- 2026-06-27 review follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 re-review follow-up: `uv run --directory ingestion pytest tests/test_orchestration.py tests/test_docmodel_build_job.py tests/test_canonical_dedup.py -q` -> 34 passed
- 2026-06-27 re-review follow-up: `uv run --directory ingestion ruff check src tests/test_orchestration.py tests/test_docmodel_build_job.py tests/test_canonical_dedup.py` -> passed
- 2026-06-27 re-review follow-up: `uv run --directory ingestion pytest -q -rA` -> 133 passed, 1 skipped
- 2026-06-27 re-review follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 re-review follow-up: `git diff --check` -> passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory shared/python pytest tests/test_vector_spec.py -q` -> 8 passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory ingestion pytest tests/test_docmodel_build_job.py tests/test_domain_units.py tests/test_orchestration.py -q` -> 39 passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory shared/python python tools/generate.py --check` -> passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory shared/python pytest -q` -> 67 passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory shared/python ruff check .` -> passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory ingestion pytest -q -rA` -> 133 passed, 1 skipped
- 2026-06-27 blockRef re-review follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory ops pytest -q` -> 42 passed
- 2026-06-27 blockRef re-review follow-up: `uv run --directory backend/modules/discovery pytest -q` -> 53 passed, 3 skipped
- 2026-06-27 blockRef re-review follow-up: `git diff --check` -> passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory ingestion pytest tests/test_docmodel_parser.py tests/test_docmodel_build_job.py tests/test_domain_units.py tests/test_orchestration.py -q` -> 54 passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory shared/python pytest tests/test_vector_spec.py -q` -> 9 passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory shared/python ruff check .` -> passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory shared/python python tools/generate.py --check` -> passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory shared/python pytest -q` -> 68 passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory ingestion pytest -q -rA` -> 133 passed, 1 skipped
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory ops pytest -q` -> 42 passed
- 2026-06-27 abstract/mapping re-review follow-up: `uv run --directory backend/modules/discovery pytest -q` -> 53 passed, 3 skipped
- 2026-06-27 fullText/canonical cleanup follow-up: `uv run --directory ingestion pytest tests/test_domain_units.py tests/test_canonical_dedup.py tests/test_orchestration.py -q` -> 39 passed
- 2026-06-27 fullText/canonical cleanup follow-up: `uv run --directory ingestion ruff check src tests/test_domain_units.py tests/test_canonical_dedup.py tests/test_orchestration.py` -> passed
- 2026-06-27 fullText/canonical cleanup follow-up: `uv run --directory ingestion pytest -q -rA` -> 135 passed, 1 skipped
- 2026-06-27 fullText/canonical cleanup follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 fullText/canonical cleanup follow-up: `uv run --directory shared/python python tools/generate.py --check` -> passed
- 2026-06-27 fullText/canonical cleanup follow-up: `git diff --check` -> passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory ingestion pytest tests/test_grobid_adapter.py tests/test_corpus_sources.py tests/test_docmodel_parser.py tests/test_runtime.py tests/test_orchestration.py tests/test_migrate_dispatch.py -q` -> 58 passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory ingestion ruff check src tests/test_grobid_adapter.py tests/test_corpus_sources.py tests/test_docmodel_parser.py tests/test_runtime.py tests/test_orchestration.py tests/test_migrate_dispatch.py` -> passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory shared/python python tools/generate.py --check` -> passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory ingestion pytest -q -rA` -> 141 passed, 1 skipped
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory shared/python pytest -q` -> 68 passed
- 2026-06-27 pre-corpus-build review follow-up: `uv run --directory shared/python ruff check .` -> passed
- 2026-06-27 pre-corpus-build review follow-up: `git diff --check` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory shared/python pytest tests/test_vector_spec.py -q` -> 11 passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory ingestion pytest tests/test_domain_units.py tests/test_canonical_dedup.py tests/test_orchestration.py -q` -> 46 passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory ingestion ruff check src tests/test_domain_units.py tests/test_canonical_dedup.py tests/test_orchestration.py` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory shared/python python tools/generate.py --check` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory ingestion pytest -q -rA` -> 152 passed, 1 skipped
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory ingestion ruff check .` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory shared/python pytest -q` -> 70 passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory shared/python ruff check .` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory backend/modules/discovery pytest -q` -> 53 passed, 3 skipped
- 2026-06-27 sourceProvenance/alias follow-up: `uv run --directory backend/modules/discovery ruff check .` -> passed
- 2026-06-27 sourceProvenance/alias follow-up: `git diff --check` -> passed

## 추적성

- FR-6 U1 Corpus 구축: eager DocModel build, chunk/embed/index path, retry/DLQ metadata, OpenSearch generation validation.
- FR-18 DocModel 리치뷰/AI 입력: required `fullText`, multimodal blocks, U7/frontend consumer 정합.
- US-I1 Corpus seed/indexing: fake adapter NEW/CHANGED smoke test로 FullText -> DocModel -> chunk -> embed -> index path 확인.
- US-I2 source별 incremental update: source enum, source adapter boundary, source별 watermark PBT.
- US-I3 retry/DLQ/reprocess: DLQ payload metadata 보존 테스트.
- QT-9 DocModel/index invariant: parser fullText projection, structured `blockRefs[]`, block_refs validation, schema drift check.

## Extension Compliance

- Security Baseline: Compliant. Raw PDF bytes는 transient in-memory 처리이며 DocModel과 candidate artifact에 저장하지 않는다. GROBID는 worker sidecar로만 노출한다. DocModel은 signed URL/image bytes를 포함하지 않고 asset id만 참조한다.
- Resiliency Baseline: Compliant. Source별 watermark, retry/DLQ stage metadata, OpenSearch validation-before-alias-cutover, rollback boundary를 추가했다.
- Property-Based Testing: Compliant for enabled partial rules. Canonical key determinism, arXiv suffix normalization, source watermark monotonicity/independence, existing chunk/index idempotency PBT를 유지·보강했다.
- N/A: Browser CSP/auth/password rules는 U1 ingestion worker code generation 범위가 아니다.
