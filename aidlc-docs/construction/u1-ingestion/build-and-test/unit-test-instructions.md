# Unit Test Execution — U1 Ingestion 멀티모달 자산 (FR-17)

## Run Unit Tests
```bash
cd ingestion
uv run --extra assets pytest          # 전체 (자산 정규화 PIL 경로 포함)
uv run --extra assets pytest tests/test_assets.py tests/test_asset_wiring.py   # 자산만
uv run ruff check src tests
```

## Expected
- **42 passed, 0 failed** (자산 신규 + 기존 회귀). ruff **All checks passed**.
- `--extra assets` 없이 실행 시 ImageNormalizer 테스트는 `importorskip("PIL")`로 skip(나머지 통과).

## Coverage (자산 신규)
| 테스트 | 검증 |
|---|---|
| `test_assets::test_caption_kind` | 캡션 정규식(Figure/Fig./Table, 숫자 필수) |
| `test_assets::test_finalize_orders_*` | (page,y,x) 정렬·type별 ordinal·결정적 asset_id |
| `test_assets::test_pbt_p7_*` (Hypothesis) | **P7** 추출 결정성·연속 ordinal·id 유일 |
| `test_assets::test_normalizer_*` | **TD-13/15**: WebP 재인코딩·다운스케일·**decompression bomb 가드**·undecodable/빈 입력 거부 |
| `test_asset_wiring::test_assets_disabled_by_default` | 토글/포트 미주입 시 자산 경로 미동작·인덱싱 정상 |
| `test_asset_wiring::test_assets_stored_on_success` | 성공 시 store 호출, 논문 인덱싱 유지 |
| `test_asset_wiring::test_asset_failure_never_blocks_indexing` | **BR-27**: 추출 실패가 인덱싱 비차단 |

## 미커버(다음 단계 / env-gated)
- 실 PDF/e-print 추출(`_page_crop`/`_structured`)·S3/RDS 저장(`S3RdsAssetStore`)은 **통합/계약 테스트(env-gated)** — 실 의존성 필요. P8(매니페스트↔자산 정합)은 store write-order 구현으로 보장하며 통합에서 검증.
