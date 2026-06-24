# U1 Ingestion — 멀티모달 자산 추출 NFR Requirements 계획 (Multimodal Asset Extraction)

**단계**: CONSTRUCTION → NFR Requirements (기존 U1 NFR 확장) · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: U1 FD 확장(`domain-entities §10`·`business-logic-model §6`·`business-rules §7`) · 기존 U1 NFR(`tech-stack-decisions.md` TD-1~10·`nfr-requirements.md`) · `requirements.md` FR-17·NFR-C1($1600 시스템 전역)
**상속(변경 없음)**: TD-1 Python · TD-2 OAI-PMH/Atom · TD-7 S3(전문 보관) · TD-8 Hypothesis · TD-9 컨테이너 · TD-10 uv/락파일/SBOM. **임베딩·OpenSearch(TD-3/4)는 무관**(자산 검색 비대상).
**범위**: 자산 추출 도구 · 이미지 정규화/포맷 · 저장(S3/RDS) · 보안(이미지 파싱·SSRF) · 비용/처리량 · 복원력. **표시 전용** — 온라인 SLA 무관(인제스천=오프라인 배치).

## 1. FD 산출물 분석 (NFR 함의)

- **혼합 추출(Q2=C, BR-23)**: e-print(LaTeX) 구조화 / PDF 페이지 크롭 폴백 → **두 도구 경로**의 라이브러리 선정 필요.
- **best-effort 비차단(Q4=A, BR-27)**: 추출 실패는 인덱싱 비차단 → 추출 단계 타임아웃·서킷이 인덱스 경로와 독립.
- **OA 게이트 재사용(BR-26)·SEC-9 비공개(BR-26)**: 자산 바이너리 private + at-rest 암호화, 외부(외부 소스 이미지) 파싱 = 보안 표면.
- **결정성(P7)**: 동일 입력→동일 자산. 추출 도구의 결정성/버전 핀.
- **비용(NFR-C1)**: distinct 논문×버전 1회 추출(디덥, BR-22) → bounded. 단 시드 재구축(수십만) 배치 처리량·도구 컴퓨트 영향.

## 2. NFR 산출물 계획 (체크박스)

- [x] `nfr-requirements.md` 확장: 추출 성능(배치 처리량)·보안(이미지 파싱·SSRF·decompression bomb)·복원력(추출 타임아웃/서킷)·비용(NFR-C1 자산 라인) NFR 항목. → §11 추가.
- [x] `tech-stack-decisions.md` 확장: **TD-11**(PDF 크롭 도구)·**TD-12**(LaTeX 구조화 도구)·**TD-13**(이미지 포맷/정규화)·**TD-14**(자산 저장 S3+RDS)·**TD-15**(이미지 보안 재인코딩). → 추가.

**답변 상태**: ✅ 확정 (2026-06-22) — **Q1~Q7 전부 권장안 A** (사용자 "진행"). 모순 없음. NFR 산출물 생성 완료.

---

## 3. 명확화 질문 (NFR 게이트 — [Answer]에 AI 권장안 사전 기입, 검토·override)

> 특히 **Q1(PDF 추출 도구)·Q3(이미지 정규화/보안)·Q5(자산 저장소)** 가 실질 결정.

### Q1. PDF 페이지 크롭(page-crop) 추출 도구 — **실질 결정**

소스 없는 논문의 그림·도표를 PDF에서 어떻게 검출·크롭하나?

A) **PyMuPDF(fitz) 휴리스틱** (AI 권장): 내장 이미지 블록 + 캡션("Figure N"/"Table N") 근접 영역 크롭. **추가 ML/GPU 없음**(CPU 배치), 의존성 경량, $1600 전역 상한·오프라인 배치에 적합. 검출 정밀도는 ML 모델 대비 낮음(차기 업그레이드 여지).

B) **레이아웃 분석 ML 모델**(pdffigures2/deepfigures류): 그림·표 검출 정밀도 우수. 단 Java/GPU·컴퓨트·운영 복잡도↑, 시드 수십만 처리 비용↑.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — PyMuPDF 휴리스틱(CPU, ML 없음). 정밀도가 부족하면 차기 사이클에 B(ML 검출)로 승격. 임계·캡션 매칭 규칙은 NFR Design.

### Q2. LaTeX 구조화(structured) 추출 범위 — 표(table) 처리

e-print 가용 시 그림은 그래픽 파일 직접 추출이 자연스럽다. **표(LaTeX `table`/`tabular`)는 이미지가 아닌데** 어떻게?

A) **그림=e-print 그래픽 파일 직접 추출; 표=항상 PDF 영역 크롭**(structured 모드라도 표는 page-crop) (AI 권장): LaTeX 표는 래스터화 비용·복잡도가 커, 표는 일관되게 크롭.

B) 표도 LaTeX→이미지 렌더(별도 LaTeX 컴파일 파이프라인).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 그림은 e-print 그래픽 직접, 표는 항상 PDF 크롭. structured의 이점은 주로 그림 화질에 집중.

### Q3. 이미지 포맷·정규화 — **보안 포함**

저장·서빙 이미지의 포맷/정규화 정책은? (외부 소스 이미지 = 파싱 공격 표면.)

A) **안전 디코더로 재인코딩(WebP) + 최대 치수/픽셀 상한(decompression bomb 가드) + 메타데이터 스트립** (AI 권장): 원본 바이트 그대로 서빙 금지 — 항상 재인코딩. WebP로 모바일 대역폭 절감, 치수 상한으로 폭탄 방어. 구체 수치(해상도·DPI·상한)는 NFR Design.

B) 원본 포맷 보존(재인코딩 없음) — 최소 처리, 단 보안·대역폭 불리.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — WebP 재인코딩 + 치수/픽셀 상한 + 메타 스트립. 원본 바이트 비서빙(보안).

### Q4. 추출 컴퓨트 배치·결정성

추출은 인제스천 워커(TD-1 Python)에서 어떻게 도나?

A) **기존 인제스천 워커 인라인(per-paper, NEW|CHANGED만) — CPU 배치, 도구 버전 핀(결정성 P7)** (AI 권장): 별도 서비스 없이 `ingestOne` 자산 단계에서. 시드 처리량은 워커 동시성(기존 NFR Q11) 내, 자산은 인덱스와 분리(best-effort).

B) **자산 추출 전용 워커/서비스 분리**(별도 배포·스케일).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 기존 워커 인라인(CPU 배치, 버전 핀). 분리 서비스는 처리량 문제 확인 시 차기. (런타임 타깃·동시성 수치는 Infra.)

### Q5. 자산 저장소 — **실질 결정**

자산 바이너리·매니페스트를 어디에? (FD Q6=A: 바이너리 S3, 메타 RDS.)

A) **바이너리=기존 S3(TD-7) 별도 prefix/버킷(private·SSE) + 매니페스트/메타=공유 RDS PostgreSQL(U3/U4/U7 자산)** (AI 권장): 신규 스토어 0, 전문 보관(S3)·용어집(RDS) 패턴 재사용. SEC-9 공개 차단·SEC-1 at-rest.

B) 바이너리·메타 모두 S3(JSON 매니페스트) — RDS 미사용.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 바이너리=S3(private·SSE), 메타/매니페스트=공유 RDS PostgreSQL. 신규 스토어 없음. 서명 URL 발급은 읽기 측(U7).

### Q6. 비용(NFR-C1) — 자산 라인

자산 추출·저장 비용을 어떻게 계상하나?

A) **기존 $1600 시스템 전역 상한 내 흡수 + 자산 라인 별도 계상** (AI 권장): distinct 논문×버전 1회(디덥 BR-22) → bounded. ML 모델 없음(Q1=A) → CPU·S3 스토리지 위주. U6.CostGuard 시스템 상한 강제. 텔레메트리에 자산 추출/스토리지 라인 추가.

B) 자산 전용 서브예산 별도.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — $1600 내 흡수 + 자산 라인 별도 계상. CPU·S3 위주로 bounded. Infra 비용표에 자산 라인 추가.

### Q7. 복원력 — 추출 타임아웃·서킷

추출 단계 실패/지연 처리는?

A) **추출·소스 fetch에 타임아웃+서킷, 실패는 best-effort 비차단(BR-27) + ASSET_* 관측·재시도** (AI 권장): 기존 RES-9 패턴 재사용, 인덱스 경로와 독립. 수치는 NFR Design/Infra.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 타임아웃+서킷, best-effort 비차단, ASSET_* 관측·재시도. 수치는 NFR Design.

---

> 답변 확정 후 모호성 점검 → `construction/u1-ingestion/nfr-requirements/`의 `nfr-requirements.md`·`tech-stack-decisions.md`를 **확장**(TD-11~15·NFR 항목). 그 다음 게이트 = U1 NFR Design / Infrastructure Design. 앱 코드 미생성.
