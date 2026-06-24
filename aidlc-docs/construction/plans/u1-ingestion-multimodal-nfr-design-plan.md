# U1 Ingestion — 멀티모달 자산 추출 NFR Design 계획 (Multimodal Asset Extraction)

**단계**: CONSTRUCTION → NFR Design (기존 U1 NFR Design 확장) · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: U1 NFR Requirements 확장(`tech-stack-decisions` TD-11~15·`nfr-requirements` §11) · U1 FD §6/§7 · 기존 U1 NFR Design(`logical-components.md` 7-box·`nfr-design-patterns.md`)
**범위**: 추출 컴포넌트 경계(논리 토폴로지) · page-crop 검출/캡션 매칭 알고리즘(TD-11) · 이미지 정규화 수치(TD-13) · 자산 매니페스트 상태 설계(RDS) · 추출 복원력 패턴. **표시 전용** — §1~4 기존 토폴로지(EventBridge·SQS·Worker·OpenSearch·Bedrock)·제어평면 상태 **불변**.

## 1. NFR Requirements 분석 (설계 함의)

- **TD-11 PyMuPDF 휴리스틱**: 검출/캡션 매칭 알고리즘을 설계 수준에서 명시(임계·순서 결정성 P7).
- **TD-13 WebP 재인코딩 + 상한**: 정규화 파이프라인 수치(치수/픽셀/품질).
- **TD-14 S3 prefix + RDS 매니페스트**: 자산 메타 테이블 설계 + 매니페스트↔자산 정합(P8).
- **Q4=A 인라인·best-effort**: AssetExtractor/AssetStore를 Worker 내 컴포넌트로, 인덱스 커밋과 분리.

## 2. NFR Design 산출물 계획 (체크박스)

- [x] `logical-components.md` 확장: **AssetExtractor**·**AssetStore** 논리 컴포넌트 + 토폴로지 다이어그램 자산 분기 + 매니페스트 RDS 상태 설계. → §5 추가.
- [x] `nfr-design-patterns.md` 확장: page-crop 검출/캡션 매칭 알고리즘 · 이미지 정규화 파이프라인 · 추출 복원력(타임아웃/서킷/per-asset 격리) · 결정성/멱등 · 보안 패턴 · 패턴↔요구사항 행. → §7 추가.

**답변 상태**: ✅ 확정 (2026-06-22) — **Q1~Q5 전부 권장안 A** (사용자 "진행"). 모순 없음. NFR Design 산출물 생성 완료.

---

## 3. 명확화 질문 (NFR Design 게이트 — [Answer]에 AI 권장안 사전 기입)

> 특히 **Q2(검출 알고리즘)·Q3(정규화 수치·보안)·Q5(매니페스트 정합)** 가 실질 설계 결정.

### Q1. 추출 컴포넌트 경계·동시성 (Logical Components / Performance)

AssetExtractor/AssetStore를 토폴로지에 어떻게 두나?

A) **Ingestion Worker 내 stateless 컴포넌트(모듈형 모놀리스, 기존 FD 컴포넌트와 동형) + AssetStore(S3 자산 prefix + RDS 매니페스트)** (AI 권장): per-paper 흐름의 일부지만 **인덱스 경로(chunk/embed/upsert)와 독립**이라 워커 동시성(NFR Q11) 내 병행 가능, 커밋 비차단. 별도 서비스·큐 없음.

B) 자산 추출 전용 워커/큐 분리(독립 스케일).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — Worker 내 컴포넌트(AssetExtractor) + AssetStore(S3+RDS). 인덱스 경로와 독립·비차단. 분리 서비스는 처리량 문제 확인 시 차기.

### Q2. page-crop 검출·캡션 매칭 알고리즘 (TD-11) — **실질 설계**

PyMuPDF 휴리스틱으로 그림·표 영역·캡션을 어떻게 잡나?

A) **이미지 객체 + 캡션 정규식 근접 매칭** (AI 권장): ① 내장 이미지 객체(`get_image_rects`) 열거(그림 후보); ② 텍스트 블록에서 캡션 정규식(`^(Figure|Fig\.|Table)\s+\d+`) 탐지; ③ 캡션↔가장 가까운 이미지 rect(상/하 근접 임계) 연결; ④ **표는 내장 이미지가 없는 경우가 많아** 캡션~다음 블록/여백 경계 영역 크롭. 순서 결정성 = (page, y, x) 정렬 → ordinal(P7). 임계 수치는 본 설계에서 기본값 + Infra 튜닝.

B) 페이지 전체를 캡션 단위로 단순 분할(이미지 객체 비사용).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 이미지 객체 열거 + 캡션 정규식 근접 매칭, 표는 캡션~경계 크롭. (page,y,x) 결정적 순서. 임계 기본값 설계 + Infra 튜닝.

### Q3. 이미지 정규화 수치·보안 (TD-13/15) — **실질 설계**

재인코딩 파이프라인의 구체 정책은?

A) **WebP·최장변 상한·총 픽셀 상한·품질·메타 스트립(기본값 제시, Infra 튜닝)** (AI 권장): 안전 디코더 재디코드 → 최장변 ~2048px 다운스케일 → 총 픽셀 ~30MP 초과 거부(decompression bomb 가드) → WebP 품질 ~80 → EXIF/메타 제거. 원본 바이트 비저장. 수치는 권장 기본, Infra/Ops 최종 튜닝.

B) 정규화 수치를 전부 Infra로 위임(본 설계는 정책만).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — WebP·최장변 ~2048px·총 ~30MP 상한·품질 ~80·메타 스트립(기본값 제시). 안전 디코더 강제. 수치는 Infra 튜닝 여지.

### Q4. 추출 복원력 패턴 (Resilience)

추출/저장 실패를 어떻게 격리하나?

A) **AssetExtractor+AssetStore를 타임아웃+서킷으로 감싸고, per-asset 실패 격리** (AI 권장): 한 자산 실패가 같은 논문의 다른 자산·인덱스 커밋(INV-1)을 막지 않음(best-effort, BR-27). 실패 → `ASSET_*` 관측·재시도(BR-17 경로). 외부 fetch는 RES-9(타임아웃·서킷) 상속. 수치는 Infra.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 타임아웃+서킷, per-asset 격리, 인덱스 비차단, ASSET_* 관측. 수치 Infra.

### Q5. 매니페스트 RDS 설계·정합 (TD-14, P8) — **실질 설계**

자산 메타 영속·정합을 어떻게?

A) **`paper_asset` 테이블((paper_id,version,asset_id) 키: type·caption·section_ref·ordinal·source_mode·object_ref·page_ref·bbox) + write-order로 정합** (AI 권장): **S3 자산 put → RDS 매니페스트 행 upsert** 순서(고아 S3는 허용·GC, 매니페스트 행 without 객체는 회피 = P8). CHANGED=새 version 행/객체 교체(이전 정리), tombstone=행·객체 삭제. 매니페스트가 표시 진실원천. 스키마·마이그레이션 구체는 Infra.

B) 매니페스트 JSON을 S3에(RDS 미사용) — U7 조회·갱신 일관성 약화.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — paper_asset 테이블 + S3 put→RDS upsert 순서 정합(P8). CHANGED 교체·tombstone 삭제. 매니페스트=표시 진실원천. 스키마는 Infra.

---

> 답변 확정 후 모호성 점검 → `construction/u1-ingestion/nfr-design/`의 `logical-components.md`·`nfr-design-patterns.md`를 **확장**. 그 다음 게이트 = U1 Infrastructure Design. 앱 코드 미생성.
