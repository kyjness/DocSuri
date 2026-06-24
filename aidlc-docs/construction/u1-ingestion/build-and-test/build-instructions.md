# Build Instructions — U1 Ingestion 멀티모달 자산 (FR-17)

## Prerequisites
- **Build Tool**: `uv` (Python 3.11+; CI 검증은 3.12)
- **Dependencies**: 기본 = `pyproject.toml`; 멀티모달은 **`assets` extra**(pypdfium2·pdfplumber·Pillow — permissive).
- **Env (런타임)**: `DOCSURI_MULTIMODAL_ASSETS_ENABLED`(기본 false), `DOCSURI_S3_BUCKET`, `DOCSURI_ASSET_S3_PREFIX`(기본 `assets`), `DOCSURI_ASSET_KMS_KEY_ID`, `DOCSURI_CONTROL_PLANE_DSN`(공유 RDS), `DOCSURI_ASSET_*`(상한·품질·타임아웃). 빌드/테스트엔 불필요.

## Build Steps

### 1. 의존성 설치 (assets extra 포함)
```bash
cd ingestion
uv sync --extra assets        # 또는 uv run --extra assets <cmd>
```

### 2. 마이그레이션 (배포 시)
```bash
# 공유 RDS에 paper_asset 적용 (워커 배포 전 선적용)
psql "$DOCSURI_CONTROL_PLANE_DSN" -f migrations/postgres/002_paper_asset.sql
```

### 3. 빌드/컴파일 검증
```bash
uv run python -m compileall src/docsuri_ingestion
```

## Verify Build Success
- `uv sync --extra assets` → `Installed N packages` (pypdfium2·pdfplumber·pdfminer.six·pillow 포함).
- 빌드 산출물: 인제스천 워커 컨테이너(추출 의존성 포함, 다이제스트 핀 SEC-10).

## Troubleshooting
- **`multimodal assets extra not installed`**: `MULTIMODAL_ASSETS_ENABLED=true`인데 `--extra assets` 미설치. → extra 설치 또는 토글 off.
- **PDFium/Pillow 시스템 라이브러리**: pypdfium2/Pillow는 manylinux 휠에 네이티브 번들 — 추가 시스템 패키지 불필요.
