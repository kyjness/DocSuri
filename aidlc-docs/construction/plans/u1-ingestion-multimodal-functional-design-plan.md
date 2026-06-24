# U1 Ingestion — 멀티모달 자산 추출 Functional Design 계획 (Multimodal Asset Extraction FD)

**단계**: CONSTRUCTION → Functional Design (기존 U1 FD 확장) · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: `requirements.md` **FR-17**(그림·도표 자산 추출·저장·표시 — 표시 전용; Q2=C 혼합 추출) · `inception/requirements/requirement-verification-questions-multimodal-display.md` · 기존 U1 FD(`construction/u1-ingestion/functional-design/`)
**범위**: 정규화 단계에서 **그림·도표 이미지 자산을 추출·저장**하고 매니페스트로 노출. **표시 전용** — 벡터 인덱스(`IndexRecord`)·임베딩·검색 경로는 **불변**(자산은 검색 대상 아님). 비전 LLM 추론은 차기 사이클(범위 밖).
**원칙**: 기술 무관 알고리즘 수준. 추출 라이브러리·bbox 임계·이미지 포맷/해상도·서명 만료 등 수치는 NFR/Infra Design.

---

## 1. 유닛 컨텍스트 (기존 자산 재사용)

- `IngestionPipelineService.ingestOne`(business-logic §1.1): `fetch_full_text → parse → validate → (철회) → dedup(isNew) → StoredFullText.put → chunk → embed → upsert(원자) → markIngested`.
- 관련 엔티티: `RawDocument`(OA 전문), `ParsedPaper{abstract, body/sections, objectRef?}`, `StoredFullText{paperId, version, objectRef}`.
- 관련 포트: `ArxivSourcePort.fetch_full_text`, `FullTextStorePort.put_full_text`, `ControlPlaneStorePort`(dedup·tombstone), `ObservabilityPort`.
- **현재**: 캡션 텍스트는 본문(`body/sections`)에 보존되나 **그림·도표 이미지 자산은 추출·저장 안 함.** OA 라이선스 게이트(BR-1)는 전문에 이미 적용.

## 2. FD 산출물 계획 (체크박스)

- [x] `domain-entities.md` 확장: **`FigureTableAsset`**(assetId·paperId·version·type{figure|table}·caption·sectionRef·ordinal·objectRef·sourceMode{structured|page-crop}) + **`AssetManifest`**(paperId·version·assets[]) + 식별자 규칙(`assetId` 결정성). → §10 추가.
- [x] `business-logic-model.md` 확장: `ingestOne`에 **자산 추출·저장 단계** 삽입(위치·dedup 게이팅·tombstone/CHANGED 정리·원자성 경계) + 데이터 흐름 ASCII 갱신. → §6 추가.
- [x] `business-rules.md` 확장: 혼합 추출 소스 판정·OA 게이트 재사용·자산 멱등/정리·매니페스트 일관·실재 자산만(생성 금지) 규칙. → §7 BR-22~28·P7/P8 추가.
- [x] 신규 포트 시그니처(개념): `AssetStorePort` + 매니페스트 영속. → domain §10.
- [x] 불변식(INV)·PBT 후보 식별(자산 추출 결정성·매니페스트↔자산 정합). → P7/P8.

**답변 상태**: ✅ 확정 (2026-06-22) — **Q1~Q7 전부 권장안 A** (사용자 "진행"). 모순 없음. FD 산출물 생성 완료.

## 3. 가정 (Assumptions)

- A1. 자산은 **검색 비대상** → `IndexRecord`/임베딩/`VectorIndexWriter` 경로 **불변**(표시 전용).
- A2. 캡션 텍스트는 기존대로 본문에 보존(중복 추출 안 함); 자산 메타의 `caption`은 본문 캡션 참조/연결.
- A3. 읽기 측(U7 full-text/paper API, U5 렌더)·서명 URL·계약 필드는 **본 U1 FD 범위 밖**(공유계약·U7 단계에서 다룸). U1은 **생산자**.

---

## 4. 명확화 질문 (FD 게이트 — [Answer]에 AI 권장안 사전 기입, 검토·override)

> 동의하면 그대로, 바꾸려면 letter 교체 또는 **X) 기타**. 특히 **Q1(파이프라인 위치)·Q4(원자성)·Q6(매니페스트 영속)** 이 실질 결정.

### Q1. 자산 추출·저장의 파이프라인 위치

`ingestOne` 어디에서 자산을 추출·저장하는가?

A) **parse에서 추출(ParsedPaper에 asset 디스크립터 동반) + 저장은 dedup 이후 NEW|CHANGED만**(StoredFullText.put와 같은 지점, step 6) — DUPLICATE는 재추출·재저장 0(NFR-C1 정신). (AI 권장)

B) parse와 무관한 **독립 후처리 단계**로 분리(전문 인덱싱과 완전 비동기).

C) parse에서 추출·저장 동시(dedup 게이팅 없음).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — parse에서 추출, 저장은 NEW|CHANGED만(dedup 이후). DUPLICATE 재추출 0.

### Q2. 혼합 추출(Q2=C) 소스 판정 규칙

구조화(LaTeX) vs 페이지 크롭(PDF)을 무엇으로 가르는가?

A) **arXiv e-print(LaTeX) 소스 가용 시 구조화 추출, 없거나 추출 실패 시 PDF 페이지 크롭 폴백** (AI 권장): 판정 기준 = e-print 소스 존재 + 구조화 추출 성공 여부.

B) 항상 PDF 페이지 크롭(구조화 비사용 — 단순·균일).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — e-print 있으면 구조화, 없거나 실패면 PDF 크롭 폴백. 폴백 트리거·소스 가용성 판정은 본 FD에서 알고리즘 수준 기술, 라이브러리는 NFR.

### Q3. 자산 식별자 & 매니페스트

자산 식별·구성 규칙은?

A) **`assetId(paperId, version, type, ordinal)` 결정적**(`ChunkId`처럼 PBT 결정성), type∈{figure,table}, ordinal=문서 등장 순서; `AssetManifest`=paperId+version별 asset 목록. (AI 권장)

B) 비결정 UUID + 매니페스트로만 정렬 관리.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 결정적 assetId(paperId·version·type·ordinal) + paper별 AssetManifest. 재처리 멱등.

### Q4. 원자성·tombstone 연동 — 자산이 인덱스 커밋을 막는가?

자산 저장 실패가 **논문 인덱싱(INV-1 원자 커밋)** 을 차단하는가? 철회·CHANGED 시 자산은?

A) **자산은 best-effort(인덱스 원자성과 분리)** (AI 권장): 표시 전용이라 자산 추출·저장 실패는 **논문 인덱싱을 막지 않음**(실패는 관측·재시도 신호로만). 단 **tombstone(철회) 시 자산도 제거**, **CHANGED(vN↑) 시 이전 버전 stale 자산 교체/정리**.

B) **자산도 동일 원자 커밋에 포함**(엄격): 자산 저장 실패 시 논문 미커밋·재시도.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — best-effort. 자산 실패는 인덱싱 비차단(관측·재시도), tombstone 시 자산 제거·CHANGED 시 stale 교체. (검색 정합은 인덱스가 권위, 자산은 표시 보조.)

### Q5. 저장 포트 구조

자산 영속을 위한 포트는?

A) **신규 `AssetStorePort` 분리**(단일 책임 — `put_asset`/매니페스트) (AI 권장): 기존 `FullTextStorePort`와 분리, OA 게이트·SEC-9 공개 차단 동일 적용.

B) 기존 `FullTextStorePort` 확장(메서드 추가).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 신규 AssetStorePort 분리(단일 책임). 전문과 동일 OA 게이트·비공개.

### Q6. 매니페스트 영속 — 읽기 측이 어디서 자산을 찾나

U7 full-text/paper API가 자산 참조를 내보내려면 매니페스트를 어디서 읽나? (U1 인제스천에 `postgres` 어댑터 존재.)

A) **자산 바이너리=오브젝트 스토리지(S3), 자산 메타/매니페스트=제어 메타 저장소(RDS)에 기록** (AI 권장): U7이 RDS에서 매니페스트 조회 → S3 서명 URL 발급. 전문 read-path(S3+RDS)와 동형.

B) **매니페스트도 S3에** 자산과 함께(JSON), U7이 S3에서 매니페스트 로드.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 바이너리=S3, 매니페스트/메타=RDS. U7이 RDS 조회→S3 서명 URL. (구체 스키마·테이블은 NFR/Infra.)

### Q7. 자산 메타 필드 (앵커 연동 대비)

매니페스트 항목에 무엇을 담나? (인셉션 Q5: 표·그림 앵커를 자산 참조로 연결.)

A) **assetId·type·caption·sectionRef·ordinal·sourceMode·objectRef·(크롭 시)pageRef/bbox** (AI 권장): 앵커(`AnchorVM.target=figure|table`)가 sectionRef/ordinal로 자산에 매칭되도록 위치 메타 포함.

B) 최소(assetId·type·objectRef)만 — 앵커 연동은 차기.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 위치 메타(sectionRef·ordinal·pageRef/bbox) 포함해 앵커 연동 가능하게.

---

> 답변 확정 후 모호성 점검 → `construction/u1-ingestion/functional-design/`의 `domain-entities`·`business-logic-model`·`business-rules`를 **확장**(기존 문서에 멀티모달 섹션 추가)하고 INV/PBT 식별. 그 다음 게이트 = U1 NFR Requirements(추출 라이브러리·이미지 포맷/해상도·서명 정책 등). 앱 코드 미생성.
