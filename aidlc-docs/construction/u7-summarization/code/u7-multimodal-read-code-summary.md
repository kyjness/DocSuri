# U7 멀티모달 읽기 측 + 정합 갭 — Code 요약 (FR-17)

**단계**: CONSTRUCTION → Code Generation + Build & Test · **유닛**: U7 Summarization · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**범위**: 자산 읽기 노출(`GET /api/papers/{id}/assets`) + 갭 3건 해소(SSOT·상태 매핑). 요약/번역 생성·근거화·캐시 **불변**.

## 생성/수정 파일

### 공유 (갭 #1 SSOT)
| 파일 | 구분 | 내용 |
|---|---|---|
| `shared/dtos/summarization.schema.json` | 신규 | **계약 SSOT 수립**(FD §8 예고 이행): SummarizeRequest/Response·AnchorVM·SummaryVM/TranslationVM + 신규 `AssetRef`/`PaperAssetsResponse` + `unauthorized`/`validation_error`. SEC-9 비노출 명시. |

### 백엔드 (`backend/modules/summarization`)
| 파일 | 구분 | 내용 |
|---|---|---|
| `domain/models.py` | 수정 | `StoredAsset`(내부·object_ref)·`AssetRef`(공개·서명 URL만, `to_dict` SEC-9). |
| `ports/ports.py` | 수정 | `AssetReadPort`(`list_assets`·`presign`). |
| `service/orchestrator.py` | 수정 | `asset_reader` 주입(미주입=None) + `list_assets`(매니페스트→AssetRef, presign, object_ref 미노출). |
| `api/router.py` | 수정 | **`GET /api/papers/{id}/assets`**(인증·OA 게이트·서명 URL) + **갭 #2**: `validation_error`에 `message` 추가. |
| `adapters/rds_assets.py` | 신규 | `RdsS3AssetReader`: `paper_asset` 읽기(psycopg) + S3 presign(boto3), `object_ref` 비노출. |
| `tests/test_assets_endpoint.py` | 신규 | 엔드포인트(401·license·ok 서명 URL·SEC-9 비노출·reader 미설정) + 갭#2 message + 어댑터(list/presign·s3 ref 파싱). |

### 프론트엔드 (`frontend`)
| 파일 | 구분 | 내용 |
|---|---|---|
| `types/generated/summarize.ts` | 수정 | SSOT 헤더 갱신 + `AssetRef`·`PaperAssetsResponseDTO`·`UnauthorizedDTO`·`SummarizeValidationErrorDTO`(search와 이름 충돌 회피) union 반영. |
| `lib/api/classifySummarize.ts` | 수정 | `classifyAssetsResponse` 신설 + **갭 #2/#3**: `validation_error`→invalid(입력 확인)·`unauthorized`→인증 메시지(일반 error 뭉개기 제거). |
| `lib/api/apiClient.ts` | 수정 | `getAssets(paperId, version)` 메서드. |
| `test/classifyAssets.test.ts` | 신규 | assets 분류 + 갭#2/#3 매핑 단위 테스트. |

## 설계 반영
- **D1**: 독립 `GET /api/papers/{id}/assets`(전문 뷰어와 분리, OA 게이트 재사용).
- **D2**: `AssetRef` = 서명 URL만(SEC-9, `object_ref` 비노출 — 테스트로 단언).
- **D3**: 앵커는 백엔드 불변(프론트 매칭은 U5 렌더).
- **D4(갭#1)**: `summarization.schema.json` SSOT.
- **D5(갭#2/#3)**: `validation_error`(message)·`unauthorized` 상태를 계약·분류기에 반영.
- **NFR/Infra(경량·폴드)**: 읽기 포트·presign TTL(기본 600s, 어댑터 인자)·`assets_enabled` 게이트는 코드 레벨로 흡수(별도 무거운 인프라 없음 — 자산 저장 인프라는 U1에서 확정).

## 검증 (Build & Test)
- 백엔드: `uv run pytest` (summarization) **48 passed/1 skip**, 자산 신규 **7 passed**, `ruff` **clean**.
- 프론트: `tsc --noEmit` **0**, `next lint` **clean**, `vitest` **75 passed**(+5 신규).

## 범위 밖(다음 = U5)
- 상세 페이지/뷰어 **자산 렌더 컴포넌트**(이미지 표시·lazy-load·앵커↔자산 연결·빈/실패 UX) = U5.
- 실 RDS/S3 통합(env-gated)·서명 만료 운영 수치 = Infra/Ops.
