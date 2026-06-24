# U1 Ingestion — 멀티모달 자산 추출 Code Generation 계획 (Multimodal Asset Extraction)

**단계**: CONSTRUCTION → Code Generation (PART 1: 계획) · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: U1 FD §6/§7 · NFR Design §5/§7 · Infra Design(S3 `assets/` prefix·`paper_asset` RDS·presigned) · TD-11~15
**코드 위치(브라운필드)**: `ingestion/src/docsuri_ingestion/`(기존 수정 우선, 복제 금지) · 테스트 `ingestion/tests/` · 문서 `aidlc-docs/construction/u1-ingestion/code/`
**스토리/추적**: FR-17(표시 전용 자산 추출·저장) · US-I1/I2(인제스천 파이프라인) · BR-22~28 · P7/P8.
**범위 경계**: 생산자(U1)만 — 읽기 측 계약(공유계약)·U7·U5는 별도 유닛. **인덱스 경로(chunk/embed/upsert) 코드 불변.** 자산은 best-effort.

> **본 계획서가 Code Generation의 단일 진실 원천**. 승인 후 PART 2에서 단계별 [x] 생성.

---

## 0. 결정 필요 — 추출 라이브러리 라이선스 (선행 질문)

> NFR TD-11은 **PyMuPDF(fitz)** 를 권장했으나, **PyMuPDF는 AGPL-3.0**(상용 라이선스 별도)이다. 본 프로젝트는 "프로덕션 수준·공개 이용 모바일 웹"이라 AGPL 전파 위험이 실질적이다. → 라이선스-안전 대안 확인.

### Q1. PDF 추출/렌더 라이브러리 (라이선스)

A) **permissive 스택: `pypdfium2`(Apache-2.0/BSD-3, PDFium 렌더) + `pdfplumber`/`pdfminer.six`(MIT, 텍스트·rect·캡션 레이아웃) + `Pillow`(HPND, WebP 정규화)** (AI 권장): TD-11 휴리스틱(이미지 객체·캡션 근접 매칭·page-crop)을 AGPL 없이 동등 구현. **TD-11/TD-13 "PyMuPDF"를 본 스택으로 정정.**

B) **PyMuPDF(fitz) 유지**: 단일 라이브러리로 간결하나 **AGPL-3.0** — 배포 시 소스 공개 의무 위험(또는 상용 라이선스 비용).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — permissive 스택(pypdfium2 + pdfplumber + Pillow). NFR TD-11/TD-13의 "PyMuPDF"를 본 스택으로 정정(라이선스 안전). 알고리즘(이미지 객체+캡션 근접·page-crop·WebP)은 동일.

---

## 1. 유닛 컨텍스트·의존성

- **기존 흐름**(`application.py:ingest_one`): fetch_metadata → fetch_full_text → parse → (철회 tombstone) → dedup → begin_upsert → **put_full_text** → chunk → embed → assemble → bulk_upsert → delete_stale → mark_ingested → advance_watermark.
- **삽입 지점(FD §6.1, Q1=A)**: `begin_upsert` 성공 후(NEW|CHANGED), `put_full_text` 인근에 **자산 추출·저장(best-effort, try/except — 실패는 인덱싱 비차단)**. 철회 경로(`_tombstone`)에 `remove_assets` 추가. CHANGED는 `replace_assets`.
- **신규 의존성**: `RawDocument`는 텍스트만 보유 → 자산은 **PDF/e-print 원천 바이트**가 필요. 신규 `AssetSourcePort`(`fetch_pdf`/`fetch_eprint`)로 분리(기존 `fetch_full_text` 텍스트 경로 불변).

## 2. 생성 단계 (번호·체크박스)

- [x] **Step 1 — 의존성**: `pyproject.toml` `[optional-dependencies] assets`(pypdfium2·pdfplumber·Pillow, permissive — Q1=A). 토글 off 기본이라 extra.
- [x] **Step 2 — 도메인 모델**: `enums.py`(AssetType·AssetSourceMode·ASSET_* FailureReason), `domain/assets.py`(asset_id·RawAssetCandidate·FigureTableAsset·ExtractedAsset·AssetManifest). (ParsedPaper.assets는 불필요 — 추출이 dedup 후 app 단계에서 source fetch와 함께 수행, DUPLICATE fetch 0.)
- [x] **Step 3 — 포트**: `ports.py` AssetSourcePort·AssetStorePort.
- [x] **Step 4 — AssetExtractor**: `asset_extraction.py` 혼합 추출·캡션 매칭·finalize(P7).
- [x] **Step 5 — ImageNormalizer**: `asset_extraction.py` bomb 가드·다운스케일·WebP·메타스트립.
- [x] **Step 6 — AssetStore 어댑터**: `adapters/assets.py` S3RdsAssetStore(write-order P8·CHANGED 교체·tombstone 삭제) + ArxivAssetSource.
- [x] **Step 7 — application 와이어링**: `application.py` 자산 포트 주입(미주입=비활성)·`_store_assets_best_effort`(인덱스 커밋 후·비차단)·`_remove_assets_best_effort`(tombstone).
- [x] **Step 8 — 마이그레이션**: `migrations/postgres/002_paper_asset.sql`.
- [x] **Step 9 — 설정**: `settings.py` MULTIMODAL_ASSETS_ENABLED(off 기본)·prefix·상한·품질·KMS·타임아웃.
- [x] **Step 10 — 테스트**: `tests/test_assets.py`(PBT P7·caption·finalize·normalizer)·`tests/test_asset_wiring.py`(기본 off·성공·실패 비차단). (P8 정합은 store write-order 구현 + Build&Test env-gated.)
- [x] **Step 11 — 코드 요약**: `construction/u1-ingestion/code/u1-multimodal-asset-code-summary.md`.
- [x] **Step 12 — 배포 산출물**: pyproject extra 반영(런타임 타깃 선결 상속).

**검증**: `compileall` 통과·순수 모듈 import+로직 스모크 통과. **전체 테스트 실행=Build & Test 단계.**

## 3. 안전·불변 (생성 시 강제)

- **인덱스 경로 불변**: chunk/embed/upsert/INV-1·VectorSpec 코드 미변경(자산은 분리 경로).
- **best-effort**: 자산 전체 실패도 `mark_ingested`/워터마크 전진과 무관(BR-27). per-asset 격리.
- **토글 안전 기본**: `MULTIMODAL_ASSETS_ENABLED=false` 기본 — 자산 미주입 시 기존 동작 동일(점진 롤아웃).
- **검증은 Build&Test 단계**: 본 단계는 코드+테스트 생성, 실행은 다음 단계.

---

> 승인 후 PART 2(Step 1→12 순차 생성). 그 다음 게이트 = U1 Build & Test. **Q1(라이브러리 라이선스) 답을 확정해야** Step 1 진행.
