# U1 Corpus 생성 파이프라인 — 요구사항 명확화 질문 (Requirement Verification — U1 Corpus)

**단계**: INCEPTION → Requirements Analysis 재진입 (재인셉션 페이즈 1 / U1) · **일자**: 2026-06-26
**담당**: 준희
**대상 기능**: U1 코퍼스 자동 구축 — **멀티소스 수집**(arXiv·Semantic Scholar·OpenAlex)·소스별 **중복 제거**·**FullText 추출**(HTML/GROBID)·**DocModel 완성형 생성**·**DocModel 기반 청킹/임베딩/OpenSearch 인덱싱**·S3 저장·**버전/워터마크 증분**·**Scheduler·Retry/DLQ** 운영.
**영향 유닛**: U1(`ingestion/`) 핵심 · 공유 계약(`shared/dtos/docmodel.schema.json`·`shared/vector-spec/`) · U2(인덱스 소비) · U7(DocModel 소비 + lazy 빌드 큐 역할 변경).
**근거 SSOT**: 재인셉션 차터 `inception/plans/reinception-2026-06-charter.md`(결정 **D6** 등) · 코드 베이스라인 `inception/reverse-engineering/code-baseline-2026-06.md` · (구) doc-model 피벗 게이트 `construction/plans/docmodel-foundation-pivot-plan.md`.
**답변 상태**: ✅ **답변 확정(2026-06-26)**. 각 질문은 차터 기반 **권장(차터)** 기준으로 **전부 A** 확정.

> ⚠️ **이전 결정 뒤집기 명시**: (구) doc-model 피벗 게이트는 **DocModel 생성 = lazy on-demand**(요약 시점, 전 코퍼스 eager 아님; 해당 질문지 Q7=A)로 확정했었다. 재인셉션 **D6**은 이를 **수집 시점 eager 전량 생성 + DocModel 기반 인덱싱**으로 전환한다. 본 질문지 **Q5·Q6이 그 전환의 실질 갈림길**이며, 승인 시 (구) Q7 결정을 대체한다.
>
> **실질 갈림길**: **Q4(DocModel 완성형 정의)·Q5(eager vs lazy)·Q6(인덱싱 소스)**. 나머지는 대부분 구현 정책 확정.

---

## Q1. 수집 소스 범위·우선순위 (차터 페이즈 1)

코퍼스 수집 소스와 우선순위를 다음으로 확정하는가?

- **A) arXiv → Semantic Scholar → OpenAlex, 이 순위로 중복 제거** (차터 권장):
  arXiv = **HTML 우선, 없으면 PDF** · Semantic Scholar = **PDF(GROBID)** · OpenAlex = **PDF(GROBID)**. 상위 소스 우선.
- **B) arXiv 단일 유지** — 현행 코드(`ingestion/adapters/arxiv.py`만 존재).
- **X) 기타**(소스 추가/순위 변경)

[Answer]: A
**권장(차터)**: A

---

## Q2. 중복 제거(dedup) 키·승자 규칙

소스별 수집 후 cross-source 병합 시 동일 논문 판정 키와 충돌 승자를 무엇으로 하는가?
(코드에 `test_dedup_idempotency` 존재 — 현재 dedup 로직의 키 확인·확장 필요.)

- **A) DOI 우선 → 없으면 arXiv id → 없으면 정규화(title+1저자+연도)**, 승자 = Q1 소스 우선순위(arXiv 최상위):
  완성형 DocModel·FullText 품질이 더 좋은 소스를 보존.
- **B) 단일 키(예: DOI만)** — 단순하나 DOI 없는 arXiv 프리프린트 누락 위험.
- **X) 기타**

[Answer]: A
**권장(차터)**: A. 현행 dedup 키를 코드에서 확인해 정합.

---

## Q3. FullText 추출 — HTML / GROBID 도입

FullText 추출 경로를 다음으로 확정하는가?

- **A) arXiv = HTML 파싱 우선(없으면 PDF), 그 외 = PDF→GROBID 구조 추출** (차터 권장):
  GROBID를 신규 도입(현재 코드에 GROBID 어댑터 없음). 추출 실패/저품질은 Retry→DLQ(Q11).
- **B) 전 소스 PDF 텍스트 단순 추출** — GROBID 없이(구조 손실).
- **X) 기타**

[Answer]: A
**권장(차터)**: A

---

## Q4. DocModel "완성형" 정의 — **실질 갈림길**

U1이 생성하는 **DocModel 완성형**이 포함해야 하는 최소 구성을 무엇으로 확정하는가?
(계약: `docmodel.schema.json` = `DocModel`/`Section`/`Block`{Paragraph·Table·Formula·Figure·List·Code}·`Provenance`·`SourceTier`·`AssetRef`.)

- **A) 구조 완성형 — 비전 추론 제외 유지** (차터/구 피벗 정합):
  Section/Block 전부 + **표=구조화 데이터(rows/cols)** + **수식=LaTeX/MathML** + **그림=webp 참조(AssetRef)** + Provenance/SourceTier. **그림 비전 추론은 제외**(on-demand 후속, §12 카브아웃 유지).
- **B) 텍스트 본문 위주(표/수식 약식)** — 추출 비용↓, 검색/근거 품질↓.
- **X) 기타**(완성형 경계 조정)

[Answer]: A
**권장(차터)**: A — "완성형" = 구조 완성형(표=데이터·수식=LaTeX·그림 webp 참조), 비전 추론 제외 유지. ※ 비-HTML 폴백 시 표 크롭 이미지 허용 여부는 Q3 추출 품질과 함께 확정.

---

## Q5. DocModel 생성 트리거 — eager vs lazy — **실질 갈림길 (D6)**

DocModel을 언제 생성하는가? **본 질문이 (구) lazy 결정을 뒤집는 지점.**

- **A) 수집 시점 eager 전량 생성** (재인셉션 **D6**):
  U1 파이프라인에서 FullText 추출 직후 DocModel 완성형을 만들어 인덱싱·S3 저장의 기반으로 삼는다.
  비용 = 코퍼스 전량(사용량 비례 아님) → 빌드 비용 상한·우선순위는 Q12.
- **B) lazy on-demand 유지** — (구) doc-model 피벗 Q7=A. 요약 열람 시 `(paperId,version)` 빌드.
- **X) 기타**(혼합: 핵심 슬라이스 eager + 나머지 lazy)

[Answer]: A
**권장(차터·D6)**: A — 수집 시점 eager 전량, (구) lazy 결정 대체. U7 `SqsDocModelBuildQueue`는 누락분 보강/재빌드 역할로 축소(Q9 버전 갱신과 정합).

---

## Q6. 인덱싱 소스 — DocModel 기반 vs full-text — **실질 갈림길 (D6)**

OpenSearch 인덱싱(청크→임베딩)을 무엇 기반으로 하는가?
(현재 코드: `ingestion/processors.py::Chunker`가 **full-text 섹션 분할** 기반 — DocModel 미사용.)

- **A) DocModel(Block) 기반으로 전환** (재인셉션 **D6**):
  Section/Block 경계로 청킹 → 임베딩 → 인덱싱. 표/수식이 청크·근거에 가시. 검색 품질(페이즈 8) 기반 개선.
- **B) full-text 청킹 유지** — 현행. DocModel은 표현/요약 전용.
- **X) 기타**(DocModel 본문 + 표/수식 별도 필드 병행 인덱싱)

[Answer]: A
**권장(차터·D6)**: A — DocModel 기반 인덱싱으로 전환, full-text 청킹은 폐기 또는 폴백으로 격하(Q7에서 청킹 정책 확정).

---

## Q7. 청킹 전략 (DocModel 기반)

DocModel 기반 청킹 정책을 무엇으로 하는가?
(현행 파라미터: `max_chunk_chars=2400`·overlap·`max_chunks_per_paper=128`, 추상 청크 + 섹션 청크.)

- **A) Block 경계 존중 + 길이 상한 분할 + 섹션 헤더 컨텍스트 부여**, 표/수식 블록은 텍스트 표현(예: 표=마크다운/직렬화)으로 청킹:
  현행 파라미터 재사용하되 분할 단위를 섹션→Block로.
- **B) 현행 파라미터·전략 그대로(소스만 DocModel 텍스트)**.
- **X) 기타**

[Answer]: A
**권장(차터)**: A. 표/수식 블록의 임베딩 표현은 검색 품질 영향이 커 페이즈 8과 연계.

---

## Q8. 인덱스 전환 방식 (임베딩 모델 ≠ 변경)

DocModel 기반 인덱싱(Q6)으로의 전환을 **인덱스 소스/스키마 전환**으로 다루는가?
(현재 vector-spec: `model: Cohere Embed v4 (Bedrock)`·`specVersion: v2`·`dimensions: 1024`·FROZEN.
 코드: `BedrockCohereEmbeddingPort`, `opensearch_index` + `opensearch_index_v2`.)

- **A) Cohere Embed v4 / specVersion v2 유지 + DocModel 기반 인덱스 generation/alias 신규 생성(블루/그린 컷오버)**:
  임베딩 **모델 변경 아님** — **인덱스 소스(full-text→DocModel Block)·스키마 전환**. vector-spec specVersion/model/dimensions 불변(전량 re-embed 불필요, 소스만 교체). 모델 교체 자체는 페이즈 8.
- **B) 임베딩 모델도 함께 교체** — vector-spec specVersion 변경 = 전량 re-embed(one-way). 페이즈 8로 미룸.
- **X) 기타**

[Answer]: A
**권장(차터)**: A — 모델 유지, DocModel 인덱스 generation/alias 신규 생성으로 컷오버.

---

## Q9. 버전 관리 — `(paperId, version)` 의미·재빌드

논문 버전 정책을 무엇으로 하는가?

- **A) `(paperId, version)` 키로 DocModel·청크·인덱스·S3 동일 버전 정합, 신버전 도착 시 재빌드→재색인→구버전 교체**:
  소스 갱신(arXiv vN→vN+1) 추적. 캐시/인덱스 immutable per version.
- **B) paperId 단일(버전 무시, 최신 덮어쓰기)**.
- **X) 기타**

[Answer]: A
**권장(차터)**: A

---

## Q10. 증분 갱신 — Watermark 단위

주기 수집의 증분(incremental) 경계를 무엇으로 하는가?

- **A) 소스별 watermark 저장, 마지막 성공 지점 이후만 수집** (차터 운영):
  현재 **단일소스 watermark 존재**(`postgres.py` `watermark` 테이블, name="arxiv"; `arxiv_oai_set` 테스트 = OAI-PMH from-date) → 이를 **소스별(cross-source) watermark로 확장**. 전량 재수집 방지.
- **B) 전량 재스캔 + dedup 의존**.
- **X) 기타**

[Answer]: A
**권장(차터)**: A — 기존 단일 watermark를 소스별로 확장.

---

## Q11. 운영 — Scheduler·Retry·DLQ·실패 신호

수집 운영 정책을 무엇으로 하는가?

- **A) Scheduler 주기 수집 + 단계별 Retry + 실패 시 DLQ + U1 failure signal을 `ObservabilityHub`의 `emitMetric`/`emitLog`로 라우팅** (차터/`shared/ports` 정합):
  `shared/ports` ObservabilityHub 메서드 = `emitMetric`/`emitLog`/`auditAppend`(`emitFailureSignal`은 U1 내부 adapter path가 이 메서드로 라우팅). 실패가 인덱싱을 막지 않게 best-effort(코드 주석 "never blocks indexing"). DLQ 재처리 경로 제공.
- **B) 단순 재시도만(별도 DLQ 없음)**.
- **X) 기타**(주기·재시도 횟수·DLQ 보존 구체화)

[Answer]: A
**권장(차터)**: A. 주기·재시도 한도·DLQ 보존기간 수치는 NFR에서 확정.

---

## Q12. 초기 코퍼스 범위·라이선스·비용 상한

페이즈 1 초기 슬라이스와 게이트를 무엇으로 하는가? (대량 확장은 페이즈 7.)

- **A) 최근 AI/ML 1년 · OA(오픈액세스) 한정 · eager 빌드 비용 상한 설정** (차터):
  분야=AI/ML, 기간=1년, 라이선스=OA 우선(코드 `arxiv_license_fallback` 활용), 비-OA 제외/저하.
  eager 전량(Q5)이므로 빌드 비용 상한·우선순위(인용수/최신성) 명시.
- **B) 기간·분야 무제한** — 비용·정합 위험.
- **X) 기타**

[Answer]: A
**권장(차터)**: A. 비용 상한 수치·우선순위 규칙은 NFR에서 확정.

---

## 다음 단계

준희님 답변(특히 **Q4·Q5·Q6**) 확정 후 → 본 질문지 답변을 `requirements.md`에 U1 **FR-N·NFR·C-N**으로 등재(추적성 포함). (구) doc-model 피벗 Q7(lazy) 결정은 Q5 승인으로 대체 기록한다.

**답변 확정(2026-06-26)**: Q1~Q12 전부 **A**. 차터 D6에 따라 DocModel 생성은 수집 시점 eager 전량 생성으로 전환하고, 인덱싱 소스는 DocModel(Block) 기반으로 전환한다.
