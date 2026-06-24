# U1 Ingestion — 멀티모달 자산 Infrastructure Design 계획 (Multimodal Asset Infra)

**단계**: CONSTRUCTION → Infrastructure Design · **유닛**: U1 Ingestion · **일자**: 2026-06-22 · **브랜치**: `feature/multimodal-display`
**근거 SSOT**: U1 NFR Design(`logical-components §5`·`nfr-design-patterns §7`) · TD-11~15 · U1 FD §6/§7 · `requirements.md` FR-17·NFR-C1($1600)
**스코프**: **FR-17 멀티모달 자산 인프라만** 신설(S3 자산 저장·`paper_asset` RDS·서명 URL/전달·IAM·KMS·비용). 기존 U1 인프라(EventBridge·SQS·OpenSearch·Bedrock·전문 S3)는 NFR 문서 상속.
**선결 상속(미해소·본 기능 범위 밖)**: U1 워커 런타임 타깃(ECS/Fargate vs Lambda, TD-9)·리전·CD는 이전부터 Infra 보류 — 본 기능이 결정하지 않고 상속. 자산 추출은 그 워커에 co-locate.

## 1. 설계 분석 (인프라 매핑 대상)

- **컴포넌트(NFR Design §5)**: AssetExtractor·Image Normalizer(워커 내, CPU) · AssetStore(S3 + RDS).
- **저장**: 자산 바이너리=S3(private·SSE), 매니페스트=`paper_asset`(공유 RDS PostgreSQL).
- **전달**: 읽기 측(U7)이 서명 URL로 노출(SEC-9). CDN 여부 미정.
- **비용**: 추출 CPU + S3 스토리지(distinct×1회, bounded) → $1600 내.

## 2. Infra 산출물 계획 (체크박스)

- [x] `infrastructure-design/infrastructure-design.md` 신설: S3 자산 버킷/prefix·KMS·라이프사이클 · `paper_asset` RDS 스키마/마이그레이션 · IAM(워커 PUT / U7 GET·presign) · 서명 URL 만료 · 비용 라인.
- [x] `infrastructure-design/deployment-architecture.md` 신설: 자산 추출 co-location·컴퓨트 사이징 · 자산 전달 경로(presigned S3 / CDN) · 관측(메트릭) · 기존 U1 토폴로지와의 관계.

**답변 상태**: ✅ 확정 (2026-06-22) — **Q1~Q5 전부 권장안 A** (사용자 "진행"). 모순 없음. Infra Design 산출물 생성 완료.

---

## 3. 명확화 질문 (Infra Design 게이트 — [Answer]에 AI 권장안 사전 기입)

> 특히 **Q1(S3 레이아웃)·Q2(전달 경로 CDN)·Q3(RDS)** 가 실질 인프라 결정.

### Q1. 자산 S3 저장 레이아웃 (Storage)

자산 바이너리를 어디에?

A) **기존 전문 S3 버킷 + 신규 `assets/` prefix(private·SSE-KMS)** (AI 권장): 신규 버킷 0, TD-7 전문 버킷 재사용. IAM은 prefix 단위 분리. 전문(StoredFullText)과 동일 보안.

B) **전용 자산 버킷 신설**: 라이프사이클·CDN origin 분리에 유리하나 버킷 관리 추가.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 기존 전문 버킷 + `assets/` prefix(private·SSE-KMS). CDN 분리가 필요해지면 차기 전용 버킷.

### Q2. 자산 전달 경로 — presigned S3 vs CDN (Networking / Performance) — **실질 결정**

U5가 자산 이미지를 어떻게 받나? (모바일 우선.)

A) **presigned S3 URL 직접 로드(v1)** (AI 권장): U7이 단기 만료 서명 URL 발급 → 클라이언트가 S3에서 직접 로드. 최소 인프라, FR-17 표시 전용에 충분. **CloudFront CDN은 성능 후속**(캐시 적중·전 세계 지연 개선 필요 시).

B) **CloudFront CDN + OAC(서명 URL/쿠키)**: 캐시·지연 우수하나 배포·무효화·비용 추가.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — presigned S3 직접(v1, 최소 인프라). CloudFront는 성능 후속 트랙. 만료(예: ~10분)는 infrastructure-design에 명시.

### Q3. `paper_asset` RDS 위치·마이그레이션 (Storage / Shared)

매니페스트 메타 테이블을 어디에?

A) **기존 공유 RDS PostgreSQL(U3/U4/U7)에 `paper_asset` 테이블 + 버전 관리 마이그레이션** (AI 권장): 신규 DB 0. 인제스천 워커가 쓰기(PUT/DELETE), U7이 읽기. 마이그레이션은 기존 패턴(예: `migrations/00X`).

B) 인제스천 전용 신규 DB(격리).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 공유 RDS PostgreSQL에 `paper_asset` + 마이그레이션. 워커 RW·U7 RO. 스키마 컬럼은 NFR Design §5.2 따름.

### Q4. 컴퓨트 — 추출 co-location·사이징 (Compute)

PDF 렌더(PyMuPDF)·이미지 처리 컴퓨트는?

A) **기존 Ingestion Worker 태스크에 co-locate, 이미지 처리용 메모리/CPU 헤드룸 확보** (AI 권장): 별도 컴퓨트 0(NFR Q4=A). 페이지 렌더·디코딩 메모리 고려해 워커 태스크 사이징에 헤드룸. 워커 런타임 타깃(ECS/Lambda) 자체는 선결 상속 항목.

B) 자산 추출 전용 컴퓨트(별도 태스크/함수).

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — 기존 워커 co-locate + 이미지 처리 메모리 헤드룸. 전용 컴퓨트는 처리량 문제 확인 시 차기. 런타임 타깃은 상속.

### Q5. KMS·라이프사이클·비용·IAM (Security / Cost / Monitoring)

자산 암호화·수명·비용·권한은?

A) **SSE-KMS(기존 U1 S3 키 재사용)·라이프사이클 만료 없음(표시 영구 소스)·최소권한 IAM(워커 PUT/DELETE prefix + paper_asset RW, U7 GET/presign + paper_asset RO)·비용 자산 라인 계상** (AI 권장): 자산은 재생성 가능하나 표시 영구 소스라 만료 없음(스토리지 비용은 bounded·$1600 내). 메트릭(추출 성공/실패·자산 수·스토리지)→ CloudWatch/U6.

X) 기타 (please describe after [Answer]: tag below)

[Answer]: A — SSE-KMS 재사용·만료 없음·최소권한 IAM(워커 PUT/DELETE+RW, U7 GET/presign+RO)·자산 비용 라인·메트릭. (라이프사이클이 필요해지면 Ops 조정.)

---

> 답변 확정 후 모호성 점검 → `construction/u1-ingestion/infrastructure-design/`에 `infrastructure-design.md`·`deployment-architecture.md` 신설(멀티모달 범위). 그 다음 게이트 = U1 Code Generation. 앱 코드 미생성.
