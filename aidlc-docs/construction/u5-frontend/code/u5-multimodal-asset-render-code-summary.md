# U5 멀티모달 자산 렌더 — Code 요약 (FR-17)

**단계**: CONSTRUCTION → Code Generation + Build & Test · **유닛**: U5 Frontend · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**범위**: 상세 페이지에 그림·도표 **렌더** + 요약 앵커(figure/table)↔자산 연결. 멀티모달 트랙의 마지막 유닛.

## 생성/수정 파일 (`frontend/`)

| 파일 | 구분 | 내용 |
|---|---|---|
| `lib/assetAnchor.ts` | 신규 | `captionNumber`·`matchAssetForAnchor`(순수): figure/table 앵커를 type+캡션번호(또는 ordinal)로 자산에 매칭(인셉션 Q5·FR-12). |
| `lib/useAssets.ts` | 신규 | 자산 매니페스트 페치 훅(useFullText 패턴, (paper,version) 디덥). |
| `components/AssetGallery.tsx` (+`.module.css`) | 신규 | 그림·도표 렌더: **컴팩트 썸네일 그리드(모바일 3·데스크톱 4, `cover`)** + 탭하면 라이트박스. lazy-load·치수 예약 프레임(레이아웃 시프트 회피)·캡션(React 이스케이프 BR-SF-9)·서명 URL `img`(SEC-9)·로딩/에러(재시도)/빈·라이선스 미허용=미표시. 활성 앵커=썸네일 스크롤+라이트박스 자동 오픈. |
| `components/AssetLightbox.tsx` (+`.module.css`) | 신규 | 전체화면 자산 뷰어: 원본 비율(`contain`)·‹이전/다음›·`1/N` 카운터·ESC/배경/✕ 닫기·←→ 키보드·바디 스크롤 락·포커스(`role=dialog` `aria-modal`). 서명 URL만(SEC-9). 모바일에서 큰 인라인 이미지가 본문을 가리는 문제 + 수십 장 세로 열거 문제 해소. |
| `components/PaperDetailIsland.tsx` | 수정 | `<AssetGallery>` 섹션 추가(전문 위), `anchor` 전달 → figure/table 앵커가 자산으로 스크롤. |
| `lib/api/index.ts` | 수정 | `AssetsOutcome` 배럴 export. |
| `lib/api/mockTransport.ts` · `mocks/summarizeFixtures.ts` | 수정 | `/api/papers/{id}/assets` mock + `assetsResponse` 픽스처(인라인 SVG data URL — 네트워크 없이 dev 미리보기). |
| `test/assetAnchor.test.ts` · `test/assetGallery.test.tsx` | 신규 | 매처 단위 + 갤러리 썸네일 렌더(2 자산·lazy) + 라이트박스 오픈·경계 prev/next·닫기. |

## 설계 반영
- **D3 앵커 연동**: 순수 `matchAssetForAnchor`(테스트) + 갤러리가 활성 앵커 자산을 썸네일 스크롤 후 라이트박스 자동 오픈. 백엔드 앵커 불변.
- **보안(BR-SF-9/SEC-9)**: 캡션 React 이스케이프, `img src`=백엔드 서명 URL만(원본 S3 키 비노출은 U7에서 보장).
- **모바일 우선**: 썸네일 그리드(폰 3·≥640px 4)로 본문 점유 최소화 + 탭→라이트박스 확대(모바일 실제 열람 방식). lazy-load·치수 예약. 큰 인라인 이미지/긴 세로 열거 회피.
- **접근성**: 썸네일=단일 탭 버튼(`aria-label`), 라이트박스 `role=dialog`·`aria-modal`·ESC·←→·포커스·44px 터치 타깃.
- **상태 UX**: 로딩/에러(재시도)/빈/라이선스 미허용·미인증=미표시(과한 노출 회피).

## 검증 (Build & Test)
- `tsc --noEmit` **0** · `next lint` **clean** · `vitest` **83 passed** · `next build` **OK**.
- 자산 점등 코드 배선(옵션 B): 읽기측 `assets_enabled`+`RdsS3AssetReader` 주입, 쓰기측 `build_production_runtime` 자산 어댑터 주입 — **기본 OFF 유지**(인프라만 깔면 점등). 실 인프라 배포 절차는 `aidlc-state.md` 자산 점등 체크리스트.

## 트랙 종결
멀티모달 표시(FR-17) 트랙 **완결**: U1(추출·저장) → 공유계약/U7(노출·갭) → U5(렌더). 비전 LLM 추론은 차기 사이클(범위 밖).
