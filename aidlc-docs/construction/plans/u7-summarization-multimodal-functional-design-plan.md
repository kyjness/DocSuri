# U7 Summarization — 멀티모달 읽기 측 + 정합 갭 FD 계획 (Multimodal Read + Contract Gaps)

**단계**: CONSTRUCTION → Functional Design (기존 U7 FD 확장) · **유닛**: U7 Summarization · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: `requirements.md` FR-17·FR-12(앵커 자산 연결) · U1 FD/Infra(`paper_asset` RDS·S3 `assets/`) · 기존 U7 FD(domain-entities §8 "summarization.schema.json 신설 예고") · 멀티모달 인셉션 Q5/Q6
**범위**: U7은 **자산 읽기·노출 측**(생산은 U1). ① 자산 읽기 계약·엔드포인트(매니페스트 조회 + 서명 URL) ② **갭 #1**: `shared/dtos/summarization.schema.json` SSOT 수립 ③ **갭 #2/#3**: `validation_error`/`unauthorized` 상태 계약 반영. **요약/번역 LLM·근거화·캐시 로직 불변.**
**방식 메모**: 사용자 위임("알아서 진행")으로 게이트 답변은 권장안으로 확정(아래 §3 결정 반영). 모순 없음.

## 1. 기존 자산 재사용

- U7 라우터(`backend/modules/summarization/.../api/router.py`): `GET /api/papers/{id}/full-text`(OA 게이트·presign 패턴 존재), `POST /api/summarize`.
- U1 산출: `paper_asset`(공유 RDS) + S3 `assets/{paper}/v{n}/{assetId}.webp`.
- 기존 계약(수기 `frontend/types/generated/summarize.ts`) — 갭 #1 대상.

## 2. FD 산출물 계획 (체크박스)

- [x] `domain-entities.md` §9: **`AssetRef`**(읽기 DTO)·**`PaperAssetsResponse`** union·자산 읽기 포트(매니페스트 조회+presign)·앵커↔자산 연결.
- [x] `business-rules.md`: **BR-S15**(자산 읽기·라이선스 게이트·presign SEC-9)·**BR-S16**(계약 SSOT 수립, 갭#1)·**BR-S17**(상태 매핑, 갭#2/#3)·PBT-S6.

## 3. 결정 (게이트 — 위임 확정)

### D1. 자산 노출 지점 — **신규 `GET /api/papers/{id}/assets`**
독립 엔드포인트(전문 뷰어 미오픈에도 상세 그림·도표 표시 가능). full-text 응답에 끼우지 않음(관심사 분리). 인증 필수, OA 라이선스 게이트(BR-SF-11 재사용) — 비-OA → `license_unavailable`. **확정.**

### D2. 자산 DTO 형상 — `AssetRef`
`{ assetId, type(figure|table), ordinal, caption, sourceMode, url(presigned 단기), pageRef?, bbox? }`. **SEC-9**: `object_ref`·내부 메타 비노출, **서명 URL만**. 정렬=ordinal(표시 순서). **확정.**

### D3. 앵커 연동 — 프론트 매칭(백엔드 앵커 불변)
요약 `Anchor{target:figure|table, label}`은 그대로. 프론트가 `label`/순서를 `AssetRef`(caption·ordinal)에 매칭해 "출처 보기→해당 도표"(인셉션 Q5). 백엔드 추가 변경 없음. **확정.**

### D4. 갭 #1 SSOT — `shared/dtos/summarization.schema.json` 신설
기존 수기 `summarize.ts`를 스키마 SSOT로 승격(SummarizeRequest/Response·AnchorVM·FullText + 신규 AssetRef/PaperAssetsResponse). 프론트 `pnpm gen:types` 재생성. **확정(U7 FD §8 예고 이행).**

### D5. 갭 #2/#3 상태 매핑 — union에 `unauthorized`/`validation_error` 명시
백엔드 `validation_error`에 `message` 포함(프론트 'invalid' 분기 동작), `unauthorized` 상태 타입 추가. summarize·full-text·assets 응답 union 일관. 프론트 `classifySummarizeResponse`/`classifyFullText`/신규 assets 분류가 상태로 판정. **확정.**

---

> FD 확장 생성 후 다음(위임 진행): U7 NFR/Infra(자산 읽기 포트·presign 정책·서명 만료) 경량 확장 → Code(shared schema·backend `/assets` 엔드포인트·갭 수정·frontend types/classify) → Build & Test. 그 다음 U5(렌더).
