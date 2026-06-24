# U1 멀티모달 자산 추출 — Code 요약 (FR-17)

**단계**: CONSTRUCTION → Code Generation · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**범위**: 표시 전용 그림·도표 자산 추출·저장(생산자 U1). **인덱스 경로(chunk/embed/upsert) 코드 불변.** 자산 best-effort(BR-27).

## 생성/수정 파일 (브라운필드 `ingestion/`)

| 파일 | 구분 | 내용 |
|---|---|---|
| `pyproject.toml` | 수정 | `[project.optional-dependencies] assets` = pypdfium2(Apache/BSD)·pdfplumber(MIT)·Pillow(HPND) — permissive only(PyMuPDF/AGPL 회피, TD-11/13 정정). 토글 off 기본이라 extra. |
| `src/docsuri_ingestion/domain/enums.py` | 수정 | `AssetType`·`AssetSourceMode` enum, `FailureReason.ASSET_EXTRACT_FAILURE`/`ASSET_STORE_FAILURE`. |
| `src/docsuri_ingestion/domain/assets.py` | 신규 | `asset_id()` 결정적 헬퍼, `RawAssetCandidate`·`FigureTableAsset`·`ExtractedAsset`·`AssetManifest`. |
| `src/docsuri_ingestion/asset_extraction.py` | 신규 | `caption_kind`(정규식)·`finalize_assets`(순서·ordinal·id, **P7 순수**)·`ImageNormalizer`(Pillow: bomb 가드·다운스케일·WebP·메타스트립)·`AssetExtractor`(혼합: e-print 그래픽/PDF page-crop 폴백, import-guarded). |
| `src/docsuri_ingestion/ports.py` | 수정 | `AssetSourcePort`(fetch_pdf/eprint)·`AssetStorePort`(store_assets/remove_assets). |
| `src/docsuri_ingestion/adapters/assets.py` | 신규 | `ArxivAssetSource`(httpx pdf/eprint)·`S3RdsAssetStore`(S3 바이너리 + RDS `paper_asset`, **write-order S3→RDS** P8, CHANGED 교체·tombstone 삭제). |
| `src/docsuri_ingestion/application.py` | 수정 | `IngestionPipelineService`에 자산 포트 주입(미주입=비활성, 안전 기본). `_store_assets_best_effort`(인덱스 커밋 후 호출, try/except 비차단), `_remove_assets_best_effort`(tombstone). |
| `src/docsuri_ingestion/settings.py` | 수정 | `MULTIMODAL_ASSETS_ENABLED`(기본 false)·prefix·치수/픽셀 상한·WebP 품질·KMS·fetch 타임아웃 env. |
| `migrations/postgres/002_paper_asset.sql` | 신규 | `paper_asset` 테이블((paper_id,version,asset_id) PK·조회 인덱스). |
| `tests/test_assets.py` | 신규 | caption_kind·finalize(순서/ordinal/id)·**PBT P7**(결정성·연속 ordinal)·ImageNormalizer(WebP·bomb·undecodable, importorskip PIL). |
| `tests/test_asset_wiring.py` | 신규 | 기본 off·성공 시 store 호출·**추출 실패가 인덱싱 비차단(BR-27)**. |

## 핵심 설계 반영

- **혼합 추출(Q2=C/BR-23)**: e-print(LaTeX) 그래픽 직접(structured) → 없/실패 시 PDF page-crop(캡션 정규식 근접). 표는 항상 page-crop(TD-12).
- **결정성(P7)**: `finalize_assets` (page,y,x) 정렬·type별 ordinal·결정적 `asset_id`. 순수 함수 → PBT.
- **이미지 보안(TD-13/15/BR-24)**: 안전 디코더 재인코딩(WebP), 픽셀 상한(bomb 가드), 메타 스트립, 원본 바이트 비저장.
- **정합(P8)**: S3 put → RDS upsert 순서. CHANGED=버전 행/객체 교체, tombstone=삭제.
- **best-effort(Q4=A/BR-27)**: 자산 단계는 **인덱스 커밋 후** 호출·전체 try/except → `mark_ingested`/워터마크 전진 비차단. 실패는 `ASSET_*` 메트릭/로그.
- **DUPLICATE 비용 0(BR-22)**: 자산 단계는 NEW|CHANGED 경로에서만 실행(dedup 단락 이후), PDF/e-print fetch도 그때만.
- **토글 안전 기본**: `MULTIMODAL_ASSETS_ENABLED=false` + 포트 미주입 시 기존 동작 동일(점진 롤아웃).

## 검증 상태 (이 단계)
- `python3 -m compileall` 통과(변경 파일). 순수 모듈 import + `finalize_assets`/`caption_kind` 로직 스모크 통과.
- **전체 테스트 실행은 다음 Build & Test 단계**(assets extra 설치 후 PIL/pdfplumber 경로 포함).

## 범위 밖(후속)
- 읽기 측 계약(공유계약 `paper_asset` 노출·서명 URL)·U7·U5 렌더는 별도 유닛.
- 구조화 추출의 캡션·section 매칭 enrich, CloudFront, 워커 런타임 타깃(선결 상속).
