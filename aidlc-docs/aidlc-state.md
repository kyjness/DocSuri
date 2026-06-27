# AI-DLC 상태 추적 (State Tracking)

## 프로젝트 정보
- **프로젝트명**: DocSuri (연구 지원 애플리케이션)
- **프로젝트 유형**: Greenfield(그린필드)
- **시작일**: 2026-06-15T04:36:30Z
- **현재 단계**: OPERATIONS - 재인셉션 페이즈 1 / U1 Corpus Operations placeholder 확인 완료. 현 AI-DLC 워크플로우 종료.
- **문서 언어**: 한국어(`aidlc-docs/` 산출물). 업스트림 룰셋(`AGENTS.md`, `.aidlc-rule-details/`)은 영어 유지.

## ⚠️ 검증 재기준선 (Verification Re-baseline) — 2026-06-16

코드 대조 감사(7개 영역 병렬 검증, 각 테스트 스위트 실제 실행) 결과, 아래 항목은 문서가 실제 상태를 **과대 표기**하고 있어 정정한다. **`완료·승인`은 "설계/코드 작성 완료"를 뜻하며 "통합·실 인프라 동작·실 안전장치 작동"을 보증하지 않는다.** 제품은 현재 엔드투엔드 사용 불가(프런트 없음·게이트웨이 없음).

- **U2 미마운트 (High)**: app-shell 부팅 시 discovery는 매번 **graceful-skip**된다(별도 uv 프로젝트 `discovery`가 backend venv에 미설치 → `_mount_discovery` `ModuleNotFoundError`). 통합 앱은 `/auth/*`+health만 노출, **`/api/search` 없음**. 8개 테스트는 레지스트리 *집합*만 단언하고 실제 마운트는 단언하지 않아 skip이 green으로 통과.
- **근거화(Grounding) 실효 없음 (Blocker)**: INV-1 분리는 구조적으로 정확. **U6는 `feature/track6`(미머지)에 구현됨** — 실 `GroundingEnforcementHook.enforce`(`ops/grounding.py`: retrieved 미포함 참조=block·근거 없음=abstain) + `backend/middleware/` 게이트웨이(rate-limit·보안헤더·fail-closed; **단 게이트웨이 자체는 grounding 미호출**). **그러나 라이브 경로 미연결**: `create_app`이 게이트웨이 미설치(테스트만 `configure_u6_middleware` 호출)·discovery 와이어링은 여전히 `StubGroundingHook`(항상 `pass`) 주입(`backend/app.py`·`backend/wiring.py`·discovery 모듈 track6에서 미변경). ⇒ **develop엔 환각/날조 방지(US-D5/US-R1)가 실 경로에서 작동 전무이며, track6 단순 머지만으로도 미해소** — 연결 last-mile(게이트웨이 설치 + 시임에 실 hook 주입, ops↔shared 타입 정합) 필요.
- **CI 부재 (High)**: `.github/workflows/` 없음(CODEOWNERS+PR 템플릿만). `CI=GHA`·`드리프트 CI 가드`는 의도일 뿐 **미구현** — 드리프트 가드/모든 테스트는 수동 실행.
- **U3 결함 (High)**: `auth.py`가 10회 실패 시 `status=LOCKED` 전이 → **BR-A4 무잠금 anti-DoS 규칙 직접 위반**. TOTP MFA·시딩 관리자(BR-A7) 미구현(ADMIN 도달 불가). accounts가 `docsuri_shared` 미소비·DTO 자체 재정의(**SSOT 포크**)·`AccountCreated` raw dict·ObservabilityHub camelCase 오호출.
- **인프라/배포 부재 (High)**: IaC·CD 전무, 인프라 설계는 U3만 존재. U2 real 어댑터(OpenSearch/Bedrock) 미존재 → 실데이터 검색 불가.
- **테스트 수 정정 (Low)**: U1 21→**23**, U2 27→**31**(api extra)/29+1 skip.

**후속 크리티컬 패스**: ① discovery 마운트+CI 마운트-단언 → ② GHA CI(드리프트+pytest+ruff) → ③ U3 정정(BR-A4·SSOT) → ④ **U6 통합 [키스톤·대부분 빌드 완료]: `feature/track6` 머지 + `create_app` 게이트웨이 설치 + discovery 시임에 실 grounding hook 주입(`StubGroundingHook` 대체)** → ⑤ U5 프런트 → ⑥ U2 real 어댑터 → ⑦ 시스템 인프라+U4. _주: track6 머지 시 aidlc-state.md(track6 +5/-1)·audit.md 충돌 예상._

## ✅ 크리티컬 패스 종결 (Critical Path Closure) — 2026-06-18

위 2026-06-16 재기준선이 지정한 후속 크리티컬 패스 ①~⑦가 **전부 랜딩**됐고 시스템 전역 인프라가 AWS에 배포됐다. 본 절은 코드/깃 이력 대조로 확인한 종결 상태를 기록한다(원 재기준선 텍스트는 2026-06-16 시점 사실로 보존; **본 절이 현재 상태의 단일 진실**). 커밋 SHA 병기.

- **① discovery 마운트 + 마운트-단언 — 종결.** `backend/wiring.py::_mount_discovery`가 실제 라우터를 마운트(`/api/search` 라이브); 테스트가 200+`cards` 및 `skipped==[]`를 단언(레지스트리 집합 단언 아님). 커밋 `ae58e0f`·`404c1a7`.
- **② GHA CI — 종결.** `.github/workflows/ci.yml` 8 레인(shared[드리프트 가드 `tools/generate.py --check`+ruff+pytest]·ingestion·discovery[`--extra api`]·ops·backend[마운트 단언]·root-suites[accounts+library]·frontend[tsc+타입 드리프트 가드+lint+vitest+next build]) + `cd.yml`(main 푸시). 커밋 `f9a7e8a`(첫 게이트)·`7edd316`(ops)·`404c1a7`(accounts/library)·`30a0773`·`bd8817b`(frontend).
- **③ U3 정정 — 종결.** BR-A4 무잠금(자동 LOCKED 제거·백오프+CAPTCHA만, LOCKED=관리자 수동 경로 한정)·SSOT 포크 제거(`docsuri_shared` 소비)·BR-A7 실 TOTP MFA+시딩 관리자(ADMIN 도달). 커밋 `bbac74f`·`f835a26`·`9b390b9`.
- **④ U6 통합(게이트웨이+실 grounding hook) — 종결.** `create_app`이 게이트웨이 미들웨어 설치(`configure_u6_middleware`); `_mount_discovery`가 mock·real 양 경로에 실 `GroundingEnforcementHook` 주입(`StubGroundingHook`은 discovery mock 패키지에만 잔존·미배선); 게이트웨이 세션쿠키→`request.state.principal` 주입. 커밋 `ba4a62e`·`b6bb92d`·`568677c`.
- **⑤ U5 프런트 — 종결·배포.** production 패스 머지(PR #63, `86404d1`); HTTPS 프로덕션 배포(Fargate+ALB+CloudFront @ docsuri.org, `d1740b0`); BFF 빌드 복구(`344172e`).
- **⑥ U2 real 어댑터 — 종결.** OpenSearch k-NN+BM25 + Bedrock Cohere 질의 임베더 + EventBridge 퍼블리셔; env 토글로 mock/real. 커밋 `b87348d`·`a25d8ed`.
- **⑦ 시스템 인프라 + U4 — 종결·배포.** U4 라이브러리 머지(`b70f2ee`). 시스템 전역 Infrastructure Design(`construction/infrastructure-design/infrastructure-design.md`, `ac21ae2`); AWS CDK Python IaC 5 스택(Network·Search·Compute·Ingestion·Frontend, `ddf8858`); CD 파이프라인(ECR 빌드·푸시+ECS 롤링, `db1b187`); 프로덕션 DB/세션 실연결(RDS Postgres+ElastiCache TLS, `01fd553`·`5f7acce`); API HTTPS 하드닝(CloudFront+ACM+시크릿 오리진, `504cb64`·`28ed940`); CloudWatch EventStore 어댑터(`8b54b62`)·SQL 마이그레이션 러너(`5de4348`); SES 실 발송(boto3+도메인 인증+IAM, `50da0d5`)+바운스/불만 자동 억제+SNS(`0437b40`).

**라이브 배포(런타임·리포지토리 대조 불가)**: 4 CDK 스택 라이브 배포·API ALB healthy = 계정 028317349537/서울(`ap-northeast-2`), 팀 보고(2026-06-17). 본 종결은 IaC 코드·커밋 대조까지 보증하며 실 배포 헬스는 AWS 콘솔/자격증명 확인 필요.

### 잔여 항목 (Residual)
- **CI 린트 사각 (Low)**: 루트 `tests/` 트리를 린트하는 레인 없음 → `ruff check .` 루트 기준 `tests/accounts/*` F401 9건이 CI에 미노출(전부 `--fix` 가능). backend 레인은 `modules/` 제외·root-suites 레인은 모듈 소스만 린트.
- **ci.yml 헤더 주석 stale (Low)**: 1~5행 주석이 "tests/accounts 미연결"이라 표기하나 현 `root-suites` 잡이 해당 스위트를 실행.
- **테스트 수 드리프트 (Info·benign)**: 스위트 증가로 문서 수치 stale(U1 23→26·U6 31→34·U4 컴포넌트 분할·U2 42+1skip). 회귀 아님.
- **Operations 프레임워크 갭**: AI-DLC 룰셋은 Build and Test에서 종료(Operations=placeholder)이나 실 AWS 프로덕션 배포가 프레임워크 밖에서 수행됨 — 운영 런북/롤백/모니터링 문서 미수립(§OPERATIONS 참조).

## 사후 결정 / 핫픽스 (Post-Construction — 규범은 각 유닛 BR·plan `사후 결정` Q)

- **U1 전문 추출 결함 정정 (2026-06-23, #139·커밋 `0ced380`·브랜치 `fix/summarization-pipeline`)**: arXiv e-print(gzip/tar) 미해제 디코딩으로 전문 ~44% 깨짐(�) → **arXiv HTML(native→ar5iv) 우선 + PDF 폴백**으로 교체(결정 D = U1 FD plan Q18 · BR-29). 보관=정규화 평문 1종, 뷰어=평문(앵커 유지). 리치 HTML 렌더/보관은 에셋 패널(FR-17)과 그림·표 겹쳐 에이전트 단계로 분리. `pdfplumber` 코어 승격.
- **U7 번역 입력 정렬 (2026-06-23, P2·커밋 `4039bde`·브랜치 `fix/summarization-pipeline`)**: 전문 번역(scope=full)이 정제 안 한 원문을 초록 프롬프트에 전송 + 길이판정(`refined`)↔전송(`raw`) 불일치 → 번역 입력=`refined.body` 통일·프롬프트 scope 분기(결정 A = U7 FD plan Q18 · BR-S2).
- **🧭 DocModel 기반 전환 — 결정 게이트 수립 (2026-06-23, 미착수·브랜치 예정 `feat/docmodel-foundation`)**: "요약/번역 입력을 평문→구조화 문서모델(doc-model)로 전환 + 자체 리치뷰 + 에이전트 준비" 피벗의 단일 진실원천 게이트 작성 → `construction/plans/docmodel-foundation-pivot-plan.md`. **확정 결정 D1~D8**: doc-model=arXiv HTML 결정적 파싱 JSON(표=데이터·수식=LaTeX·그림=webp 참조)·U7 입력 평문→doc-model 교체(로직 불변)·PDF 원문 미저장(다운로드 버튼 없음)·자체 리치뷰=doc-model 콘텐츠 재렌더(PDF.js 아님)·비전=batch 아닌 에이전트 on-demand 툴·생성 lazy+`(paperId,ver)` 캐시·소스 무관 설계·TD-12(표=PDF크롭) 재검토. **저장**: `doc-model/{id}/v{ver}.json`(구조화 통합) + 기존 `assets/*.webp`(이미지 분리·참조) + 기존 `paper_asset` RDS. **열린 Q1~Q8**(코드 전 확정): ⚠️Q1 arXiv HTML 커버리지 스파이크(배포 확정 선결)·Q3 doc-model 스키마·Q7 요구사항 재진입 여부·Q8 P3(맵리듀스)=doc-model 후속. `:159-162` 비전 항목은 본 doc-model 기반으로 흡수. **blast-radius=기존 U1/U7/U5 FD·TD-12·requirements *편집*(신규 문서는 게이트뿐)**.
- **🧭 DocModel 전환 — blast-radius 기존 문서 편집 (2026-06-23, 브랜치 예정 `feat/docmodel-foundation`)**: 게이트 D1~D8·Q권장안 기준으로 §3 기존 유닛 문서 *편집* 진행(신규=게이트뿐). **U1**: BLM `business-logic-model`(스코프 피벗 노트·§7 doc-model lazy 생성·캐시 단계 신설·§6.3 철회 무효화 연동) · `business-rules`(BR-29 carve-out 뒤집기 — 리치 렌더 범위 안 + ar5iv 필수 / **BR-30 신설** doc-model 구조·생성) · `tech-stack-decisions`(**TD-12 재작성** 표=PDF크롭→HTML 데이터 · **TD-16 신설** HTML 파서 lxml/BeautifulSoup·MathML→LaTeX·입력 보안 · TD-11 최후폴백 강등) · `infrastructure-design`(§1.1b `doc-model/` prefix·SSE-KMS·lazy 캐시 라이프사이클 + IAM 빌더/읽기 역할). **U7**: `domain-entities`(SourceText=doc-model·RefinedSource **+tables[]**·docModelRef) · `business-logic-model`(SourceSelector·InputRefiner doc-model 직접 취득·프롬프트 표=데이터·수식 LaTeX) · `business-rules`(BR-S2/S3) — **로직 불변, 입력만 업그레이드(D2)**. **U5 리치뷰**: 실제 컴포넌트가 사는 `u7-summarization-frontend` `FullTextViewer`→**`DocModelViewer`** 본문화(목차·KaTeX·표 컴포넌트·webp 그림·앵커; `getFullText`→`getDocModel` lazy) + U5 `frontend-components §6`(AssetGallery=그림 전용 축소·**표 크롭 폐기→표 컴포넌트** D8·앵커 매처 재사용). **미편집(잔여)**: requirements.md(FR-12/리치뷰 1급화/§12 — Q7 재진입 결과 대기) · `shared/dtos/`(Q3 doc-model 스키마 SSOT) · U7 NFR/Infra 어댑터 경량 정합. **다음=코드**(`feat/docmodel-foundation`). _커밋·push 보류(사용자 승인 후)._
- **🧭 DocModel 전환 — Q3 스키마 + Q7 요구사항 재진입 완료 (2026-06-23, `fix/summarization-pipeline`, 미푸시)**: **Q3(커밋 `ff258f7`)** — doc-model 계약 확정: **중첩 섹션 트리 + 결정적 블록 id 앵커**. `shared/dtos/docmodel.schema.json`(JSON Schema 2020-12·20 defs·양성/음성 검증) + 스펙 SSOT `construction/shared/docmodel.md` + overview/README 등재(계약 5번째). 루트=getDocModel 응답 union, 아티팩트=DocModel(meta+sections[]); 블록 6종(paragraph·table·formula·figure·list·code); 표=rows/cols·수식=latex·그림=AssetRef(assetId 참조, url 없음 SEC-9); provenance(sourceTier 사다리). **Q7(미커밋)** — 요구사항 재진입: 질문지 `inception/requirements/requirement-verification-questions-docmodel.md` Q1~Q7(전부 게이트 권장안 + 리치뷰=신규 FR-18) → `requirements.md` 등재: **FR-12 개정**(입력=doc-model·앵커=doc-model id)·**FR-17 개정**(그림=이미지·표=데이터 D8)·**FR-18 신설**(자체 리치뷰 1급 D4)·§12 doc-model 카브아웃(PDF 미저장 D3·비전 제외 유지 D5·외부소스 일괄캐시 제외 D7)·QT-5 앵커 보강·§13 추적성. **다음=코드**(`feat/docmodel-foundation`): U1 DocModelBuilder(ar5iv 사다리·lxml)·getDocModel API·U7 입력 어댑터·DocModelViewer + summarization.schema Anchor.target 의미 명확화. _push·PR 보류(승인 후)._

## 워크스페이스 상태
- **기존 코드**: 없음(워킹 트리 블랭크 슬레이트; 이전 데모 사이클 폐기, git `ba3b6a9`로 복구 가능)
- **리버스 엔지니어링 필요**: 아니오(Greenfield — 디스크에 소스 파일 없음)
- **워크스페이스 루트**: 리포지토리 루트(머신별 상대; 예: `<홈>/Projects/DocSuri`) — 절대 경로는 머신마다 다름
- **프로그래밍 언어**: (미정 — Construction 단계)
- **빌드 시스템**: (미정 — Construction 단계)
- **프로젝트 구조**: 비어 있음(AI-DLC Prompt 1부터 재시작)

## 코드 위치 규칙
- **애플리케이션 코드**: 워크스페이스 루트(절대 aidlc-docs/ 안에 두지 않음)
- **문서**: aidlc-docs/ 전용
- **구조 패턴**: code-generation.md의 Critical Rules 참조

## 확장 구성 (Extension Configuration)
| 확장 | 활성 | 모드 | 결정 시점 |
|---|---|---|---|
| Security Baseline | 예 | Full(15개 규칙 전부 차단성) | Requirements Analysis (2026-06-15) |
| Resiliency Baseline | 예 | Full(15개 규칙 전부 차단성) | Requirements Analysis (2026-06-15) |
| Property-Based Testing | 예 | Partial(PBT-02/03/07/08/09만 차단성; 01/04/05/06/10 권고) | Requirements Analysis (2026-06-15); Full→Partial 변경 2026-06-15(팀원 권고, 기술 스택 확정 후 재평가) |

_Resiliency 옵트인은 `requirements.md` 확정 전에 필수 요구사항 명확화를 유발: RTO/RPO + DR 전략(RESILIENCY-02), 변경 관리(RESILIENCY-03), 장애 대응(RESILIENCY-15). `inception/requirements/requirement-clarification-questions.md`에서 질의함. 후속 단계로 보류: CI/CD + 롤백 + 배포 방식(RESILIENCY-04 → NFR Design), 리전 토폴로지(RESILIENCY-08 → Infra Design), 복원력 테스트(RESILIENCY-14 → NFR Design)._

## 단계 진행 (Stage Progress)

### 🔵 INCEPTION 단계
- [x] 워크스페이스 탐지(Workspace Detection) — Greenfield (2026-06-15)
- [~] 리버스 엔지니어링 — N/A (Greenfield, 건너뜀)
- [x] 요구사항 분석(Requirements Analysis) — 완료·승인 (2026-06-15); `requirements.md`. 명확화 2라운드; 모순 전건 해소; 확장 전부 활성
- [x] **요구사항 개정 — 신규 유닛 U7(요약/번역) 편입 (2026-06-18, 팀 합의·브랜치 `feature/u7`·PR #108)**: U1~U6 빌드·배포 완료 후 Requirements Analysis 재진입. 명확화 `requirement-verification-questions-u7.md` Q1~Q7 전부 A(초안 권장안) → `requirements.md`에 **FR-12(AI 요약·구조화·앵커)·FR-13(한국어 번역·용어집)·FR-14(개인화: persona/뷰/용어집)·NFR-P2(온디맨드 비-SLA)·QT-5(요약/번역 근거화)·NFR-C1 U7 Sonnet 비용 라인 보강·C-2 추출 경계·§12 제외(P3·자유입력)** 등재. 설계 입력 `aidlc-docs/inception/requirements/summarization-translation-pipeline.md`(2026-06-18 레포 루트→aidlc-docs 재배치 완료). **다음: User Stories(U7) → Units Generation(U7 등재·U1/U6 의존) → Construction 유닛 루프.** 리뷰 게이트 대기.
- [x] 사용자 스토리(User Stories) — 계획 승인(PQ1–5=A); Part 2에서 `stories.md`(스토리 **21개**, 6 에픽: Hero 1 + Discovery 7 + Accounts 2 + Library 3 + Ingestion 3 + Reliability 5) + `personas.md`(P1 박지훈, P2, OP) 생성; FR-1..11 전부 커버; **승인 완료**. **적대적 비평 패스 완료(2026-06-15, 7/7 critic)** → requirements/stories 보정 반영.
- [x] Workflow Planning — `execution-plan.md` **승인 완료**. 판정: 리버스 엔지니어링만 SKIP, 그 외 전 단계 EXECUTE.
- [x] Application Design — 완료(리뷰 게이트). `application-design/` 5문서(components·component-methods·services·component-dependency·application-design); 6 유닛(U1~U6); 적대적 3 critic→blocking/major 보정 반영(근거화 단일 권위, SearchExecuted 생산자, SEC-8 단일 결정점, QT-3 소유자, 백도어 차단)
- [x] Units Generation — 완료(리뷰 게이트). `unit-of-work.md`·`unit-of-work-dependency.md`·`unit-of-work-story-map.md`; 6 유닛·4 배포 단위·모노레포·데모 우선 순서; 스토리 21개 전수 매핑·코드 의존 DAG(adversarial 검증 solid)
- [ ] Units Generation — **EXECUTE** (예비 유닛: U1 인제스천, U2 디스커버리 API, U3 계정/인증, U4 검색저장/라이브러리, U5 모바일 웹, U6 신뢰성/운영)
- [x] **사용자 스토리 개정 — U7(요약/번역) 에픽 추가 (2026-06-18, 팀 합의·`feature/u7`·PR #108)**: `stories.md`에 **에픽 6 — 요약/번역**(US-S1 구조화 요약·US-S2 한국어 번역·US-S3 출처보기+기권·US-S4 개인화·US-S5 온디맨드 응답·US-S6 비용게이트+근거화 운영) 6 스토리 추가 → 총 27 스토리/7 에픽. P1(US-S1..S5)·OP(US-S6) 매핑, FR-12..14·NFR-P2·QT-5 전수 커버. 페르소나 무변경(P1·OP가 U7 커버).
- [x] **Units Generation 개정 — U7 정식 등재 (2026-06-18, 팀 합의·`feature/u7`·PR #108)**: `unit-of-work.md`(U7 Summarization 유닛 정의·배포 단위 ①+③옵션·코드트리 `backend/modules/summarization/`·확장 트랙)·`unit-of-work-dependency.md`(U7 행/열 추가, U7→U1 capability read·U7→U6 `shared/ports` lib·U5→U7/U6→U7 sync, **코드 DAG 비순환 유지 검증**, 온디맨드 요약 ASCII 흐름)·`unit-of-work-story-map.md`(US-S1..S5 Owner=U7·US-S6 Owner=U6 기여=U7, 전수 27 스토리 검증) 갱신. **7 유닛·4 배포 단위(U7=API 모듈, 초장문만 비동기 잡 옵션).** 리뷰 게이트 대기. **다음: U7 Construction 유닛 루프(Functional Design부터).**
- [x] **요구사항 개정 — 신규 유닛 U8(인용 그래프/각주 트리) 편입 (2026-06-19)**: 명확화 `requirement-verification-questions-citation-graph.md` 22문 답변 확정(Q3/Q10=X, Q4/Q14=B, 나머지 권장안) → `requirements.md`에 **FR-15(각주 트리/backward references)·FR-16(노드 저장/연동)·NFR-P3(온디맨드 비-SLA)·QT-6(인용 엣지 정확도+그래프 불변식)·§12 카브아웃** 등재. v1은 논문 상세보기 페이지의 backward references 각주 트리로 한정, FE 구현·forward citations·3-hop 이상은 제외.
- [x] **요구사항 개정 — Cohere Embed v4.0 마이그레이션 편입 (2026-06-23)**: 명확화 `requirement-verification-questions-v4-migration.md` 4문 전수 답변(A) 반영 → `requirements.md`에 **FR-17(듀얼 라이트)·NFR-M2(Blue/Green 마이그레이션)·NFR-S2(v4 모델 컷오버)** 등재. 기존 v3 인덱스와의 비호환성을 무중단으로 해결하기 위해 신규 인덱스 백필, 듀얼 라이트, 그리고 Instant Cutover 전략을 확정.
- [x] **요구사항 개정 — 재인셉션 페이즈 1 / U1 Corpus 완성형 편입 (2026-06-26, PR #220 머지 후)**: `requirement-verification-questions-u1-corpus.md` Q1~Q12 답변을 **전부 A**로 확정하고, 재인셉션 차터 D6을 `requirements.md`에 반영. **FR-6 전면 개정**(arXiv HTML→PDF, Semantic Scholar/OpenAlex PDF→GROBID, cross-source dedup, FullText, eager DocModel 완성형, DocModel(Block) chunk/embedding/OpenSearch/S3, source별 watermark, scheduler/retry/DLQ, `(paperId,version)` 버전 정합), **FR-18 lazy→phase-1 eager 정정**, **NFR-C1 U1 eager 비용 게이트**, **RES-7/8/9 멀티소스 운영 신호**, **QT-9 U1 Corpus 품질/불변식**, **C-1/§12 PDF 원문 미저장·transient GROBID 카브아웃**, 추적성 행 추가. 구 doc-model Q7(lazy)는 phase-1 Corpus 범위에서 대체하고, lazy 빌드는 누락분·재빌드·백필 경로로 축소. **다음: 리뷰 승인 후 User Stories/Workflow Planning.**
- [x] **사용자 스토리 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**: 신규 에픽 없이 기존 **에픽 4 — 인제스천**을 최소 개정. `u1-corpus-user-stories-assessment.md`와 `u1-corpus-story-generation-plan.md` 생성(계획 결정 전부 A, 체크리스트 완료). `stories.md`의 **US-I1**을 멀티소스 Corpus+eager DocModel+DocModel(Block) 인덱싱으로, **US-I2**를 source별 watermark incremental update로, **US-I3/US-R3/US-R4**를 retry/DLQ/비용/관측 기준으로 보강. `personas.md` OP에 U1 Corpus eager 비용·watermark·DLQ 관측 책임 반영. FR-6/FR-18/NFR-C1/RES-7/8/9/QT-9 추적성 갱신. **다음: Workflow Planning.**
- [x] **Workflow Planning — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**: `u1-corpus-workflow-plan.md` 생성 후 skip decision review를 반영해 Application Design은 **U1-only amendment EXECUTE**, Units Generation은 **review EXECUTE**로 정정. U1 Construction 루프(Functional Design, NFR Requirements, NFR Design, Infrastructure Design, Code Generation)와 Build & Test EXECUTE. 모듈 순서: 공유 계약 확인 → U1 Corpus 파이프라인 → 인프라/관측 → U2 alias/config → backfill → cutover. Mermaid 시각화와 텍스트 대체 포함.
- [x] **Application Design 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**: 전역 재설계 없이 U1 관련 5문서만 최소 개정. `components.md`/`component-methods.md`/`services.md`/`component-dependency.md`/`application-design.md`의 U1 arXiv-only 설계를 멀티소스 Corpus로 정정: `CorpusSourceAdapterSet`, `FullTextExtractionProcessor`, `SourcePriorityDeduplicationGuard`, `DocModelBuildCoordinator`, `DocModelBlockChunker`, `CorpusIndexWriter`, `CorpusRefreshScheduler`. GROBID transient PDF, eager DocModel, DocModel Block anchor, index generation, source watermark, QT-9 추적성을 Application Design 수준에 반영.
- [x] **Units Generation 리뷰 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**: `u1-corpus-units-review-plan.md` 생성 및 `unit-of-work.md`/`unit-of-work-dependency.md`/`unit-of-work-story-map.md` 최소 개정. 결론: 신규 유닛 없음, 기존 **U1 Ingestion**이 멀티소스 Corpus 생성 파이프라인 owner 유지. U2/U7/U11은 Corpus/DocModel capability read 소비자이며 코드 의존 그래프 비순환. U1 arXiv-only 문구를 멀티소스 Corpus/DocModel/OpenSearch/S3 wording으로 정정. **다음: 리뷰 승인 후 U1 Functional Design.**
- [x] **INCEPTION 완료 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**: Requirements Analysis, User Stories, Workflow Planning, U1-only Application Design amendment, Units Generation review 모두 승인 완료. PR 본문 `202606261630_PR.md` 작성. 다음 단계는 Construction의 U1 Functional Design.
- [x] **요구사항 개정 — 신규 유닛 연구 에이전트(대화형 문헌탐색·근거형성 / 아이디어 novelty) 편입 (2026-06-24, 브랜치 `feature/research-agent`·PR #170)**: 명확화 `requirement-verification-questions-research-agent.md`(인셉션 고도 18문항; **Q5=B·Q7=A[재현성 판정 제외]·Q13=X·Q14=B·Q18=A, 나머지 권장**) → `requirements.md`에 **FR-22(대화형 근거형성·모드 A·v1)·FR-23(novelty 비교·모드 B·차기 구현)·FR-24(대화형 입력+첨부)·FR-25(결과·세션 영속+전용 네비 진입)·NFR-P5(온디맨드 비-SLA·비차단)·NFR-C1 Agent 비용 보강·QT-8(근거·novelty 인수)·§12 Agent 카브아웃·C-2 추출·비교 경계** + 성공기준 #7·추적성 9행 등재. **v1=모드 A 구현, 모드 B(novelty)는 다음 사이클**(Q4=A). 생성 산문·재현성 판정 제외(C-2). 설계 입력 `summarization-translation-pipeline.md`(line 374 "파이프라인 재사용 + 유사논문 검색 노드"). **HOW(코퍼스 확장·외부 API·출력 스키마·근거표 컬럼·LLM 모델·멀티턴·네비/세션 UI)는 Construction(Functional/NFR/Infra Design) 라운드로 이월.** 유닛 번호 미배정(마이페이지 U10·개인화추천·트렌드/알림·구독제 이후). **Q18=A → Requirements 등재 완료; User Stories는 별도 승인으로 진행, Units·Construction은 후속.**
- [x] **요구사항 개정 — U3 Accounts 프로덕션화 (2026-06-24, 브랜치 `feature/u3-accounts-production`)**: 팀 보고 'login not operating' 진단 결과 U3 코드·계약·인프라 정상, 근인 = `/auth/login` **422**(`LoginRequest extra='forbid'`+필수필드 → 바디 형상 스큐)가 프런트 `normalizeHttpError` `unknown`('문제가 발생했습니다…')으로 표면화(라이브 프로브 재현: 정상 `{email,password}`→401, 추가/누락 필드→422). 단발 패치 대신 사용자 지시로 U3를 프로덕션급 확장 → Requirements Analysis 재진입. 명확화 `requirement-verification-questions-account-production.md` Q1~Q8 답변(**Q1=ABCD·Q2=A·Q3=Google·Q5=A**, 미서피스 **Q4·Q6·Q7·Q8=권장**) → `requirements.md`에 **FR-26(비밀번호 재설정: Resend·단일사용 30분 토큰·전세션 무효화·열거방지)·FR-27(소셜 OIDC, Google v1·검증이메일 자동연결·신규 ACTIVE)·FR-28(계정 라이프사이클: 비번/이메일 변경·소프트삭제+유예 비동기파기+owner-scoped 캐스케이드 U4/U2/U11)·FR-29(인증 입력 견고화: 공개 인증 추가필드 무시+4xx/422 명확 표면화 — 422 근인 해소)** + 성공기준 #8 + 추적성 행 + **BR-A8~A12 참조** 등재. 경계: U3=백엔드 엔드포인트/규칙 소유, **U10 마이페이지=프로필/설정 UI만**(타 팀원 병행·미커밋). **다음(별도 승인): User Stories(에픽 3 Accounts 보강: 재설정·소셜·라이프사이클) → Units Generation(U3 확장·U10 경계 주석) → Construction(U3 Functional/NFR/Infra Design **HOW 라운드**: OIDC 라이브러리·재설정 토큰/소셜 연결 테이블 스키마·세션 재발급·삭제 유예 잡·DB 마이그레이션 → Code Generation → Build&Test).** 리뷰 게이트 대기.
- [x] **사용자 스토리 개정 — U3 Accounts 프로덕션화 (2026-06-24, `feature/u3-accounts-production`, 사용자 "approved & continue" 승인)**: 방법론=기존 에픽 기반·INVEST·Given/When/Then(9개 선례 동일; `inception/plans/story-generation-plan-account-production.md` 권장안 일괄 채택). `stories.md` **에픽 2 — 계정**에 5 스토리 추가(**US-A3 비밀번호 재설정·US-A4 소셜 로그인 Google OIDC·US-A5 비번/이메일 변경·US-A6 계정 삭제(소프트+유예 캐스케이드)·US-A7 인증 에러 표면화·입력 견고화**) → 총 **53 스토리/10 에픽**. 페르소나 P1/P2 매핑(US-A1..A7)·추적성(FR-26→A3·FR-27→A4·FR-28→A5/A6·FR-29→A7)·커버 푸터 갱신. FR-26~29 전수 커버. **다음(별도 승인): Units Generation(U3 확장·U10 경계 주석) → Construction(Functional/NFR/Infra Design HOW 라운드).** 리뷰 게이트 대기.
- [x] **Units Generation 개정 — U3 Accounts 프로덕션화 (2026-06-24, `feature/u3-accounts-production`, 사용자 "approve & continue" 승인)**: 신규 유닛 없음 — 기존 **U3 확장**. `unit-of-work-story-map.md`에 US-A3~A7 Owner=U3 매핑(총 **53 스토리**·미할당 0) + U3 요약/카운트/노트 갱신. **경계(Q2=A)**: U10 마이페이지(타 팀원)=프로필/설정 UI만·U3=백엔드 `/auth/*` 소유. **신규 의존**: U3→외부 Google OIDC(콜백). **삭제 캐스케이드=이벤트 구동**(U3 `AccountDeleted` 발행 → U4/U2/U11 구독·각자 owner-scoped 파기)으로 U3↔U4/U2/U11 **순환 회피**(의존성 역전, U11↔U6 `shared/ports` 패턴)·코드 DAG 비순환 유지. 기존-유닛 확장이라 `unit-of-work.md`(유닛 정의)·dependency 매트릭스 세부는 story-map 노트로 일원화. **다음(별도 승인): Construction — U3 Functional Design(HOW: OIDC 인가코드 흐름·재설정 토큰/소셜 연결 테이블 스키마·AccountDeleted 이벤트 계약·삭제 유예 잡·DB 마이그레이션) → NFR/Infra Design → Code Generation → Build&Test.** 리뷰 게이트 대기.

### 🟢 CONSTRUCTION 단계 — U3 Accounts 프로덕션화
- [x] **Functional Design 개정 — U3 Accounts 프로덕션화 (2026-06-24, `feature/u3-accounts-production`, 사용자 "Functional Design only, then gate" 선택)**: 코드 없이 **HOW 설계만**(추상·기술 무관). `business-rules.md` **BR-A8~A12**(재설정 토큰 단일사용·소셜 OIDC 검증이메일 연결·이메일 변경 지연반영·삭제 소프트+유예+`AccountDeleted` 이벤트 캐스케이드·공개 인증 입력 추가필드 무시) + 추적성 5행. `domain-entities.md` **§4**(PasswordResetToken·SocialIdentity·EmailChangeRequest·AccountDeletion·`AccountDeleted` 이벤트·OidcProvider·`AccountStatus.DEACTIVATED`). `business-logic-model.md` **§5~9**(PasswordResetService request/confirm·SocialLoginService start/callback OIDC·AccountManagementService 비번/이메일 변경·AccountDeletionService requestDeletion+purgeJob·인증 입력 견고화). 라이브러리/테이블 스키마/이벤트 버스 구현은 **NFR/Infra Design·Code로 이월**. **다음(별도 승인): NFR Requirements/Design → Infra Design → Code Generation(공개 인증 SSOT DTO `extra=ignore` 재생성·OIDC/재설정 라이브러리·DB 마이그레이션 포함) → Build&Test.** 리뷰 게이트 대기.
- [x] **NFR Requirements/Design 개정 — U3 Accounts 프로덕션화 (2026-06-24, `feature/u3-accounts-production`, "continue")**: 코드 없이 기술·패턴 결정만. `tech-stack-decisions.md` **TD-U3-7~10**(이메일=**Resend**[SES 대체]·소셜 OIDC=**httpx+python-jose JWKS**[Authlib 미채택]·신규 RDS 테이블[`password_reset_token`/`email_change_request`/`social_identity`·`account_deletion`·`status.DEACTIVATED`]+state/nonce=Redis 단명·삭제 캐스케이드=**EventBridge `AccountDeleted`**+유예 잡). `nfr-design-patterns.md` **§4~7**(재설정: 해시저장·단일사용 CAS·열거방지·레이트리밋·Fail-Closed / OIDC: state·nonce Redis 단명·JWKS 캐시·`email_verified` 게이트 / 삭제: 2상 이벤트 캐스케이드·멱등·DLQ·비차단 / 공개 인증: `extra=ignore`·422 명확 표면화). **다음(별도 승인): Infra Design → Code Generation → Build&Test.** 리뷰 게이트 대기.
- [x] **Code Generation (시작) — FR-29 인증 입력 견고화 슬라이스 (2026-06-24, `feature/u3-accounts-production`, "start the construction stage")**: 실제 로그인 422 장애 해소 최소 슬라이스 **구현·검증**(코드 첫 착수). **백엔드**: SSOT `shared/dtos/accounts.schema.json`의 `LoginRequest`·`SignupRequest`에서 `additionalProperties:false` 제거 → 재생성(`docsuri_shared` `extra=ignore`; 응답 DTO `SignupResult`/`SessionInfo`는 `extra='forbid'` 유지) — **Python 드리프트 가드 `ok`**. **프런트**: `frontend/lib/api/errors.ts` `normalizeHttpError`에 422 분기 추가 → 불투명 'unknown'('문제가 발생했습니다') 대신 '입력 형식이 올바르지 않습니다…새로고침' 명확 표면화. **TS 타입 무변**(gen-types가 `additionalProperties:false` 고정 옵션·`accounts.ts`는 큐레이티드 — 드리프트 없음). **테스트**: `tests/accounts/test_auth_input_tolerance.py` **3 passed**(입력 DTO extra 무시·응답 DTO forbid 유지). 라이브 즉시 해소는 별도로 develop 프런트 재배포 필요. **남은 Construction(미착수)**: FR-26 재설정·FR-27 OIDC·FR-28 라이프사이클(신규 테이블·`AccountDeleted` 이벤트·purge 잡)·Infra Design·DB 마이그레이션·FE 플로우·테스트. **미커밋.**
- [x] **Code Generation — FR-26 비밀번호 재설정 백엔드 슬라이스 (2026-06-24, `feature/u3-accounts-production`, "continue to the next slice")**: 백엔드 풀 구현·검증. **DTO**: SSOT `PasswordResetRequest`/`PasswordResetConfirm`(extra=ignore)+재생성·`dtos.py`/`schemas.py`/`accounts.ts` 재내보내기. **저장소**: `password_reset_tokens`(token_hash PK·SHA-256 해시저장·단일사용 선삭제). **서비스** `PasswordResetService`: request(열거방지 no-op·활성계정만 30분 토큰·Resend)·confirm(만료/단일사용/BR-A1 재검증/Argon2 재해싱/**전 세션 무효화**). **이메일** 3프로바이더 `send_password_reset_email`+렌더. **세션** `invalidate_all_for_user`(`user_sessions` Redis 셋 인덱스). **컨트롤러** `POST /auth/password-reset/request|confirm`(요청=일반응답·확정=400/503/500 매핑). **검증: ruff clean · accounts 39 passed(reset 6 신규·회귀 0) · Python 드리프트 ok.** **미구현(이월)**: FE 재설정 요청/확정 페이지·DB 마이그레이션 SQL·앱셸 와이어링. **미커밋.**
- [x] **Code Generation — FR-27 소셜 로그인(OIDC) 조정 코어 (2026-06-24, `feature/u3-accounts-production`, "move on to FR-27")**: 보안 핵심(H1) 신원 조정 로직만 구현 — OIDC 트랜스포트는 이월(테스트 가능성 위해 분리). `models` `OidcProvider`·`SocialLinkConfirmationRequired`(DomainException). `credential` `social_identities` 테이블((provider,subject) PK·status LINKED|PENDING_CONFIRMATION)+`SOCIAL_NO_PASSWORD_HASH` 센티넬+`has_usable_password()`+repo(get/create_social_identity·create_social_account ACTIVE 무비번). `SocialLoginService.reconcile`(검증 클레임→account_id: 미검증 거부·`(provider,subject)` 기존연결 멱등·소셜-only 동일이메일 자동연결·**기존 *비밀번호* 계정=H1 자동병합 금지→PENDING_CONFIRMATION 기록+`SocialLinkConfirmationRequired`**·신규=ACTIVE+LINKED). **검증: ruff clean · accounts 44 passed(social 5 신규·회귀 0).** **이월(다음)**: Google OIDC HTTP/JWKS verifier(httpx+python-jose)·Redis state/nonce·컨트롤러 start/callback/`/auth/social/link`·세션 발급 와이어링·FE·DB 마이그레이션. **미커밋.**
- [x] **Code Generation — FR-28 계정 라이프사이클 코어 (2026-06-24, `feature/u3-accounts-production`, "continue the construction phase")**: 백엔드 코어 풀 구현·검증 — 실 EventBridge 트랜스포트만 이월(FR-27 OIDC 분리와 동일 패턴). **models** `AccountStatus.DEACTIVATED`. **credential** 신규 테이블 `email_change_requests`(token_hash PK·해시저장·계정당 1활성)·`account_deletions`(account_id PK·purge_after·state DEACTIVATED|PURGED) + CRUD(email-change·deletion·`get_due_deletions`·`delete_account_permanently` 캐스케이드[accounts+verification/reset 토큰+social_identities+email_change]·`mark_deletion_purged`·`delete_account_deletion`). **AccountManagementService**(BR-A10): `change_password`(현 비번 재인증→BR-A1→Argon2 재해싱→**전 세션 무효화**)·`request_email_change`(형식·중복검사[사용중=**열거방지 무처리** SEC-BR-2]·30분 단일사용 토큰·새주소 확인링크+**현주소 변경알림 M2**·지연반영)·`confirm_email_change`(만료/단일사용/레이스 재확인→로그인 식별자 반영). **AccountDeletionService**(BR-A11): `request_deletion`(DEACTIVATED+전세션 무효화+유예레코드·**`AccountDeleted` 미발행** H2)·`reactivate`(유예중 복구 M1)·`purge_job`(유예 경과분 일괄: **`AccountDeleted` 발행**[accountId 멱등키·eventId·`AccountDeletedPublisher` 포트+기본 Logging 발행자]→영구삭제→PURGED·멱등). **email** `_send` 프리미티브(Mock/SES/Resend) + 이메일변경 확인/알림 메일. **auth** 보안픽스: 로그인 시 **DEACTIVATED 차단**(기존 PENDING/LOCKED만 검사 → 소프트삭제 계정이 세션 발급되던 갭 해소). **controller** `/auth/change-password`·`/auth/email-change/request|confirm`·`/auth/account/delete`(세션 필수·쿠키 클리어·503/400/500 매핑). **검증: ruff clean(accounts 레인) · accounts 58 passed(account_management 8·account_deletion 6 신규·회귀 0) · 컨트롤러 임포트/라우트 등록 OK · app-shell mount 4 passed.** **이월(다음)**: 실 EventBridge `AccountDeleted` 발행·구독자 완료검증/DLQ·재활성화 UX(로그인-감지→복구)·purge_job 크론/워커 와이어링·FE 플로우·DB 마이그레이션 SQL. **미커밋.**
- [x] **사용자 스토리 개정 — 연구 에이전트 에픽 추가 (2026-06-24, `feature/research-agent`·PR #170)**: PART 1 평가(`research-agent-user-stories-assessment.md`) + 스토리 생성 계획(`research-agent-story-generation-plan.md`, PQ1~6 **전부 권장안 A 승인**) → PART 2: `stories.md`에 **에픽 9 — 연구 에이전트 / 문헌탐색·근거형성**(US-RA1 전용 진입+모드선택+입력·US-RA2 문서 첨부·US-RA3 다논문 근거 정리[모드A]·US-RA4 근거화·기권·US-RA5 결과·세션 영속+전용 메뉴 재열람·US-RA6 온디맨드 진행상태·비차단 저하·US-RA7 비용게이트+근거화 운영[OP]·US-RA8 novelty 비교[모드B·**다음 사이클** Q4=A]) 8 스토리 추가 → 총 48 스토리/10 에픽. `personas.md` P1/OP 보강. FR-22~25·NFR-P5·NFR-C1 Agent·QT-8 전수 커버, §12 카브아웃·C-2 경계·제외 범위(생성 산문·재현성 판정·모드B v1빌드) 인수 기준 명시. **다음(별도 승인): Units Generation(신규 유닛 등재·번호 배정) → Construction.**
- [x] **Units Generation 개정 — 연구 에이전트 정식 등재 (2026-06-24, `feature/research-agent`·PR #170)**: 분해 계획(`research-agent-unit-of-work-plan.md`, UQ1~5 **전부 권장안 A 승인**; **UQ2=A → 유닛 번호 U11**). 원본(U1~U6)·U9 분해 계획 모두 참고. **U10=마이페이지(타 팀원 구현 중·커밋 전)를 가정**하고 번호 점유로 처리(AI-DLC 관례: 번호=정식 생성 시점 부여) → 신규 유닛 **U11 Research Agent**(`backend/modules/research_agent/`). `unit-of-work.md`(U11 정의·U10 자리 주석·U11 주석[v1=모드A·모드B 차기·추출 경계·HOW 이월]·배포 단위 ① API+긴 분석 비동기 잡·코드 조직·빌드 순서 확장)·`unit-of-work-dependency.md`(U11 행/열 추가, U11→U2/U3/U6/U7 의존[+모드B 차기 U8·U9 비차단], `shared/ports` 의존성 역전으로 U11↔U6 순환 없음, 비순환 DAG 검증, 온디맨드 다논문 ASCII 흐름)·`unit-of-work-story-map.md`(US-RA1~6·RA8 Owner=U11·US-RA7 Owner=U6 기여=U11, 48 스토리 전수 매핑·미할당 0) 갱신. **10 유닛(U1~U9+U11)·4 배포 단위(U11=API 모듈+긴 분석 비동기 잡 옵션).** v1=모드 A, 모드 B(novelty)는 다음 사이클. **다음(별도 승인): Construction(U11 Functional/NFR/Infra Design 라운드 — 근거표 컬럼·외부 API·LLM 모델·멀티턴·UI 결정).**
- [x] **Construction — U11 Functional Design 완료·승인 (2026-06-24, 브랜치 `feature/research-agent-construction`·PR #183)**: Part 1 질문게이트 Q1~Q17 확정 + Part 2 산출물 4종(`construction/u11-research-agent/functional-design/` domain-entities·business-logic-model·business-rules[INV-U11-1~7·BR-RA-1~18·QT-8]·frontend-components[Q15=B 풀버티컬]). **핵심 결정**: Q1=파이프라인 A(U7 배관 재사용+U11 전용 추출 노드) **+ ★전문 통합 인덱스·eager doc-model 전환(아키텍처 게이트 `plans/docmodel-fulltext-index-pivot-plan.md`)★** · Q2=A+ · Q5=A(논문 비교형+쟁점) · **Q7=A(근거화 U6 단일 권위 통일 — U7 AnchorVerdict도 U6 공유 계약 이관·확정)** · Q15=B. 검색 locator·granularity(GQ1)·랭킹(GQ2)·LLM/스토리지는 권장/옵션·NFR 이월. **게이트(전문 인덱스·eager doc-model·근거화 통일·DF-6 각주/메타)는 #136/#120·D6 되돌림+배포 U7 변경이라 U1/U2/U7/infra 조율·별도 승인 필요.**
- [x] **Construction — U11 NFR Requirements 완료·승인 (2026-06-24, PR #183)**: 질문지(U7/U2/U3/U8 선례 반영·Q1~Q16) **전부 A** → 산출물 `u11-research-agent/nfr-requirements/` 2종(nfr-requirements.md·tech-stack-decisions.md TD-RA-1~15: Sonnet 추출·Bedrock 스트리밍·RDS 세션·S3 첨부·Redis+영구 2단·SQS 비동기잡·U2 재사용·U6 근거화 통일·real-first·shared DTO 승격). granularity(GQ1)·랭킹(GQ2)·모드B API=[열림].
- [x] **Construction — U11 NFR Design 완료·승인 (2026-06-24, PR #183)**: 질문지(U7/U2/U3/U8 패턴 종합·A~F·Q1~Q14) **전부 A**(+Q1 정밀화: 의존성별 격리=U11 직접 호출 실패도메인[검색U2·doc-model읽기S3·Bedrock·U6·RDS/Redis] 단위; OpenSearch는 U2 재사용 시 U2 내부 서킷). 산출물 `u11-research-agent/nfr-design/` 2종(nfr-design-patterns[의존성별 격리·저하 4계층·재시도 분리·fan-out 부분실패·캐시우선·스트리밍↔근거화·bounded 병렬·3밴드·방어심층·폴트인젝션]·logical-components[토폴로지·SQS 잡큐·포트 경계]). 수치·GQ1·GQ2=Infra/실험 이연. **다음: Infrastructure Design(진행 중 — U7/U8/U3/시스템 선례 종합 질문지).** develop 병합(U10 마이페이지·U3 소셜로그인 등) 반영(커밋 0de39ca).
- [x] **Workflow Planning — Cohere Embed v4.0 마이그레이션 (2026-06-23)**: `execution-plan.md` 업데이트 완료. 리버스 엔지니어링, 애플리케이션 설계, 유닛 생성, 기능 설계, NFR 요구사항 SKIP. **NFR 설계, 인프라 설계, 코드 생성, 빌드 & 테스트 EXECUTE 확정**.
- [x] **사용자 스토리 개정 — U8 에픽 추가 (2026-06-19)**: `stories.md`에 **에픽 7 — 인용 그래프 / 각주 트리**(US-CG1 상세보기 각주 트리·US-CG2 깊이/노드 메타·US-CG3 unresolved 분리·US-CG4 라이브러리 저장·US-CG5 실패/쿼터 저하·US-CG6 운영 관측성) 6 스토리 추가 → 총 33 스토리/8 에픽. P1(US-CG1..CG5)·OP(US-CG6) 매핑, FR-15..16·NFR-P3·QT-6 커버.
- [x] **Units Generation 개정 — U8 정식 등재 (2026-06-19)**: `unit-of-work.md`(U8 Citation Graph 유닛 정의·배포 단위 ① API 모듈·코드트리 `backend/modules/citation_graph/`)·`unit-of-work-dependency.md`(U8 행/열 추가, U8→U3/U6 로그인·게이트웨이, U8→U4 저장 계약, U7→U8 출처 연동, 코드 DAG 비순환 검증, 각주 트리 ASCII 흐름)·`unit-of-work-story-map.md`(US-CG1..CG5 Owner=U8·US-CG6 Owner=U6 기여=U8, 전수 33 스토리 검증) 갱신. **8 유닛·4 배포 단위(U8=API 모듈).** **후속: U8 Construction Functional Design 질문 게이트 진입 완료, 답변 대기.**

### 🟢 CONSTRUCTION 단계 (유닛별 루프)

**U1 Ingestion** (프로덕션 직행 1번; 데모 트랙 폐기):
- [x] Functional Design — **완료·승인·프로덕션 재스코핑 (2026-06-16)**. `construction/u1-ingestion/functional-design/`(domain-entities·business-logic-model·business-rules). 프로덕션: **Q1=D 풀 슬라이스(5cat×5yr 수십만)·Q2=C OA 전문 청킹·Q12=B 이벤트 경로 활성·Q13=B 철회 tombstone**. INV-1 커밋순서·논문 단위 원자성·PBT-08 P1~P6. **FD 완전 추상(기술 무관)**. 적대적 검증 3패스.
- [x] **Functional Design 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-functional-design-plan.md` 생성(추가 질문 없음; U1 Corpus Q1~Q12=A 상속). 기존 U1 FD 3문서에 **2026-06-26 Corpus 우선 적용 섹션** 추가: `domain-entities.md`(SourceName/SourceTier, canonical PaperId, SourceWatermark, FullTextCandidate, eager DocModel, DocModelChunk, CorpusIndexGeneration, DLQ), `business-logic-model.md`(source별 incremental loop → FullText/GROBID transient PDF → source-priority dedup → eager DocModel → Block chunk → embedding → index generation/S3 → alias cutover), `business-rules.md`(BR-C1~C15, QT-9/PBT P-C1~P-C7). 기존 arXiv-only/lazy DocModel/단일 watermark/구식 chunk 규칙과 충돌 시 Corpus 섹션 우선. **앱 코드 미생성.** 승인 시 다음: U1 NFR Requirements.
- [x] **NFR Requirements 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-nfr-requirements-plan.md` 생성(추가 질문 없음; 기존 결정 상속). `nfr-requirements.md`에 U1 Corpus 우선 적용 NFR 추가: phase-1 최근 AI/ML 1년, source fan-out, internal GROBID 처리량, DocModel generation/alias, stage별 retry/DLQ, source별 watermark, raw PDF transient, ObservabilityHub metric/log, QT-9/PBT. `tech-stack-decisions.md`에 TD-C1~C8 추가: Python worker 유지, source adapters, internal containerized GROBID, HTML+TEI deterministic parser, Cohere Embed v4/specVersion v2, OpenSearch generation/alias, EventBridge+SQS/DLQ, private S3, $1600 account budget + U1 per-run hard stop. **앱 코드 미생성.** 승인 시 다음: U1 NFR Design.
- [x] **NFR Design 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-nfr-design-plan.md` 생성(추가 질문 없음; NFR Requirements 결정 상속). `logical-components.md`에 Corpus 우선 적용 컴포넌트 추가: EventBridge source scheduler, Corpus work queue/DLQ, Ingestion Worker, internal GROBID runtime, DocModel parser, Control Plane DB, private Corpus S3, Bedrock Cohere Embed v4, OpenSearch generation, ObservabilityHub. `nfr-design-patterns.md`에 stage-aware retry/DLQ, source-specific circuit breaker, cost hard-stop, generation cutover/rollback, parser hardening, QT-9 verification pattern 추가. **앱 코드 미생성.** 승인 시 다음: U1 Infrastructure Design.
- [x] **Infrastructure Design 개정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-infrastructure-design-plan.md` 생성(추가 질문 없음; 기존 AWS 인프라 상속). `infrastructure-design.md`에 Corpus AWS 매핑 추가: existing EventBridge/SQS/DLQ/ECS Fargate worker/S3/RDS/OpenSearch/Bedrock/Budget 재사용, internal GROBID sidecar, source별 scheduler, Corpus S3 prefixes, control-plane tables, IAM/network/alarms. `deployment-architecture.md`에 rollout/rollback 추가: migrations → disabled deploy → candidate generation → source별 enable → budgeted backfill → QT-9/U2/U7 smoke → alias cutover. **앱 코드 미생성.** 승인 시 다음: U1 Code Generation.
- [x] **PR #225 리뷰 보정 — DocModel 완성형 계약을 Infrastructure Design 단계까지 반영 (2026-06-26)**. 사용자 리뷰에 따라 DocModel을 `fullText` 전문 텍스트 투영본 + `sections[].blocks[]` 멀티모달 구조(paragraph/table/formula/figure/list/code)로 보정하는 결정을 Functional/NFR/NFR Design/Infrastructure Design 문서에 반영. 이미지 바이트/base64/서명 URL은 DocModel에 넣지 않고 `figure.assetRef.assetId`로 private `assets/` 저장소를 참조한다. **코드·스키마·generated DTO·프론트 타입·테스트 변경은 Infrastructure Design 단계 범위 밖이므로 PR에서 제거했고, 다음 U1 Code Generation에서 구현한다.**
- [x] **Code Generation Part 1 계획 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-code-generation-plan.md` 생성. 범위: DocModel `fullText` 계약 보정, parser fullText projection, eager DocModel build 경로, DocModel block-aware chunk/index metadata, multi-source adapter/GROBID boundary, source별 watermark/canonical dedup, retry/DLQ payload, OpenSearch generation/alias, U7/frontend 소비자 정합, targeted tests. **앱 코드 미생성.** 승인 시 Code Generation Part 2 실행.
- [x] **Code Generation Part 2 실행 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 계획서 `construction/plans/u1-corpus-code-generation-plan.md` 16단계 전부 완료. 구현: DocModel required `fullText` + generated DTO/frontend type, parser fullText projection, eager DocModel build before index, DocModel block-aware chunk/index metadata, corpus source adapter/GROBID boundary, canonical dedup state/Postgres migration, source-aware retry/DLQ payload, OpenSearch generation validation/alias cutover, runtime/CDK GROBID sidecar wiring, U7/frontend consumer 정합. 코드 요약 `construction/u1-ingestion/code/u1-corpus-code-summary.md`. 검증: shared schema drift check, shared 66 passed, ingestion 129 passed/1 skipped + ruff clean, ops 42 passed, discovery 53 passed/3 skipped, summarization 116 passed/3 skipped, frontend targeted vitest 19 passed + tsc, git diff --check 통과.
- [x] **Code Generation 리뷰 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**. 리뷰 지적 4건 반영: `CorpusSourceAdapterSet`을 refresh/pipeline에 주입하고 provider-backed Semantic Scholar/OpenAlex `sourceRecord` job 경로를 추가, arXiv HTML 미가용 시 PDF/full-text fallback DocModel 생성, `IndexRecord.blockRefs[]` 구조화 저장 및 BM25 noise 제거, GROBID 429/일시적 4xx retriable 분류. 회귀 테스트: source refresh/ingest smoke, text fallback DocModel, GROBID 429/400, `blockRefs[]` 구조화 assertion.
- [x] **Code Generation 추가 리뷰 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 팀원 리뷰 후속 반영: lazy `BUILD_DOC_MODEL`도 HTML 미가용 시 eager와 동일하게 PDF/full-text fallback DocModel을 생성, canonical dedup state에 arXiv도 기록, source priority(arXiv > Semantic Scholar > OpenAlex)를 적용해 상위 source winner가 있으면 외부 PDF/GROBID fetch 전에 duplicate skip, 상위 source가 나중에 도착하면 하위 source chunk를 tombstone 처리. Phase boundary 명시: Semantic Scholar/OpenAlex 실 HTTP provider, legacy reindex의 DocModel chunk 전환, vision-model asset rollout은 Operations/follow-up. 검증: ingestion pytest 132 passed/1 skipped, ingestion ruff clean.
- [x] **Code Generation 재검토 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. `cf923a8` 재검토 피드백 반영: withdrawal-detected paper는 tombstone 후 canonical winner 기록을 건너뛰어 정상 외부 복본을 삭제하지 않도록 했고, canonical loser 제거 시 index tombstone과 함께 DocModel cache invalidation 및 asset cleanup을 대칭 수행한다. 회귀 테스트: withdrawn arXiv가 existing external canonical winner를 보존하는지, arXiv가 lower-priority winner를 교체할 때 loser DocModel/assets cleanup이 호출되는지 검증.
- [x] **Code Generation blockRef 재검토 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. `IndexRecord.blockRefs[]`를 문자열 배열에서 `{paperId, version, sectionId, blockId, blockType}` 구조체 배열로 정정하고, DocModel chunker가 별도 abstract chunk를 만들지 않도록 해 모든 DocModel-derived index record가 실제 DocModel block을 참조한다. OpenSearch mapping helper도 structured nested field로 갱신. 당시 DOI-only external vs arXiv canonical alias/sourceProvenance 확장은 follow-up으로 분리했으며, 아래 SourceProvenance/alias follow-up 종결 항목에서 반영 완료.
- [x] **Code Generation abstract/mapping 재검토 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. `0ffeee0` 재검토 피드백 반영: DocModel parser가 abstract를 `s0.p1` 블록으로 모델링해 semantic embedding을 복원하고, `chunk_doc_model`의 unused abstract parameter를 제거했다. `blockRefs` OpenSearch mapping은 검색하지 않는 provenance 성격에 맞춰 non-indexed object로 바꿨고, `provision_v2_index.py`는 `papers_index_body()`를 import해 mapping SSOT를 재사용한다. 당시 SourceProvenance, DOI/arXiv alias, 철회 winner canonical state cleanup은 별도 follow-up으로 분리했으며, 아래 후속 항목들에서 종결했다.
- [x] **Code Generation fullText/canonical cleanup 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 요청에 따라 🅔와 철회 winner canonical cleanup까지 반영: text-bearing block이 없는 DocModel은 `fullText`를 첫 실제 block ref에 연결해 fallback chunk를 생성하고, successful tombstone은 해당 `paperId`가 winner인 canonical dedup rows를 삭제한다. In-memory/Postgres control-plane store 모두 `delete_canonical_dedup_state_for_paper()` 구현.
- [x] **Code Generation SourceProvenance/alias follow-up 종결 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 남은 SourceProvenance와 DOI/arXiv alias follow-up 반영: `IndexRecord`에 optional internal `doi`, `sourceArxivId`, `sourceProvenance`를 추가하고 OpenSearch mapping은 alias keyword + provenance non-indexed object로 갱신했다. `ParsedPaper`가 sourceName/sourceId/sourceTier/sourceUrl/DOI/arXiv alias를 보존하고 assembler가 record에 기록한다. canonical dedup은 DOI, arXiv, title/author/year alias rows를 같은 winner로 묶고, lower-priority external winner를 arXiv가 대체할 때 기존 DOI alias까지 새 winner로 이동한다. DOI-only external과 arXiv metadata는 title alias로 교차 매칭된다.
- [x] **Code Generation 코퍼스 빌드 전 리뷰 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 코퍼스 채우기 전 남은 항목 반영: DocModel 계약을 FROZEN으로 전환하고 footnote/references/page 제외 및 PDF/GROBID 단일 paragraph degrade를 명시했다. `lexicalTerms`는 본문 청크 전용 analyzed 필드로 줄이고, `title`/`abstract` 표시 필드를 lexical 검색에도 재사용해 추후 boost 튜닝을 재색인 없이 query 변경으로 적용 가능하게 했다. Semantic Scholar/OpenAlex 실 HTTP provider를 추가하고 GROBID가 있을 때 production runtime에 배선했다. `migrate.py backfill`은 legacy `chunk()` 직접 경로를 제거하고 OAI metadata를 기존 pipeline/DocModel indexing 경로로 넣는다. local runtime에도 in-memory DocModelBuilder를 주입해 local/prod indexing path를 맞췄다. HTML 본문 abstract가 `meta.abstract`와 중복될 때 첫 abstract section을 제거해 semantic embedding 이중계상을 막는다. `DocModelBuilder`는 cached provenance `parserVersion`/`schemaVersion`이 현재 builder와 일치할 때만 cache hit로 인정한다. `trigger-full-rebuild` preflight는 production corpus build 전에 multimodal assets ON, external source용 GROBID URL, `DOCSURI_BEDROCK_MODEL_ID_V2` unset, worker rollout 완료 및 redeploy freeze 확인을 강제한다.
- [x] **Code Generation 문서 정합 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 추가 점검에서 남은 문서-코드 불일치를 정리했다. `construction/shared/vector-spec.md`를 실제 shared 계약(`specVersion=v2`, Cohere Embed v4, `assert_same_space()` 기반 same-space gate, per-record `modelVer` 없음)에 맞췄고, U1 `business-rules.md`의 오래된 제목+초록 단일 벡터/`lexicalTerms` 계약을 DocModel 기반 초록+본문 다중 청크 및 본문 전용 `lexicalTerms` 계약으로 갱신했다.
- [x] **Code Generation full rebuild 멀티소스 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 추가 실행 경로 점검에서 `trigger_full_rebuild()`가 arXiv seed만 큐잉하고 configured Semantic Scholar/OpenAlex source record를 누락하는 갭을 수정했다. full rebuild는 enabled external source별 watermark를 corpus slice start로 reset하고 `SEED_REBUILD` source-record job을 큐잉한다. 검증: ingestion focused orchestration/cache/lexical/preflight tests 28 passed, ingestion full pytest 147 passed/1 skipped, ingestion ruff clean, shared vector spec 9 passed, discovery OpenSearch adapter 4 passed, shared generate --check passed, git diff --check passed.
- [x] **Code Generation phase-1 corpus slice 보정 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. 사용자 결정에 따라 phase-1 Corpus 범위를 최근 AI/ML 1년으로 확정했다. `CORPUS_START=2025-01-01`, `CORPUS_END=2026-01-01`로 좁히고, `trigger_full_rebuild()`는 arXiv와 Semantic Scholar/OpenAlex seed rebuild 모두 같은 start/end window를 적용한다. 외부 provider가 범위 밖 record를 반환해도 orchestrator가 큐잉 전에 skip한다. 관련 요구사항/차터/Functional/NFR/Infrastructure 문서의 current contract를 1년 슬라이스로 정리했다. 검증: ingestion targeted orchestration/corpus source tests 34 passed, ingestion full pytest 148 passed/1 skipped, ingestion ruff clean, corpus scope drift search clean, git diff --check passed.
- [x] **Code Generation DocModel stale cache 완전 종료 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. `DocModelBuilder`뿐 아니라 U7 `S3DocModelReader` 우회 read path까지 `parserVersion`/`schemaVersion` stale object를 cache miss로 처리하도록 수정했다. shared `docmodel_contract` 상수를 U1 builder와 U7 reader가 같이 사용해 version drift를 줄이고, reader는 pydantic schema validation 전에 provenance를 확인해 old-shape S3 object도 rebuild/miss 경로로 보낸다. 검증: ingestion docmodel builder 8 passed, summarization docmodel endpoint/build trigger 20 passed, summarization full pytest 118 passed/3 skipped, ingestion full pytest 148 passed/1 skipped, shared pytest 68 passed, targeted ruff clean, shared generate --check passed, git diff --check passed. Summarization 전체 `ruff check src tests`는 기존 unrelated test lint baseline으로 실패.
- [x] **Code Generation lexicalTerms write split 완전 종료 — 재인셉션 페이즈 1 / U1 Corpus (2026-06-27)**. `IndexRecord.lexicalTerms`를 본문 청크 전용으로 강제했다. legacy full-text chunk와 DocModel chunk 모두 abstract section record는 `lexicalTerms=""`로 저장하고, 검색용 초록은 별도 analyzed `abstract` 필드에만 남긴다. U2 BM25 reader는 기존대로 `title`, `abstract`, `lexicalTerms` multi-match를 사용해 추후 boost 튜닝을 재색인 없이 query 변경으로 적용할 수 있다. 검증: ingestion full pytest 149 passed/1 skipped, ingestion ruff clean, shared pytest 68 passed, shared vector spec 9 passed, shared generate --check passed, discovery OpenSearch adapter 4 passed, targeted discovery/shared ruff clean, git diff --check passed.
- [x] **Build and Test — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26, 리뷰 게이트)**. 산출물 `construction/u1-ingestion/build-and-test/` 갱신: build-instructions, unit-test-instructions, integration-test-instructions, performance-test-instructions, build-and-test-summary. 검증 기준은 Code Generation Part 2 및 리뷰 보정에서 실제 실행한 결과를 반영: shared schema drift check 통과, shared 66 passed, ingestion 129 passed/1 skipped + ruff clean, ops 42 passed, discovery 53 passed/3 skipped, summarization 116 passed/3 skipped, frontend targeted vitest 19 passed + tsc, git diff --check 통과. Dedicated load harness는 추가하지 않고 bounded backfill + worker telemetry + OpenSearch generation validation으로 성능 검증.
- [x] NFR Requirements — **완료·승인 (2026-06-16)**. `construction/u1-ingestion/nfr-requirements/`(nfr-requirements·tech-stack-decisions). 스택: Python·**OpenSearch[전역]**·**cross-lingual 임베딩(Cohere Embed Multilingual v3, 1024·코사인)[전역]**·EventBridge·SQS·S3·Hypothesis·SEC-10. **NFR-C1=$1600/월(시스템 전역, 기존 $300 대체)**. **엄격 OA 라이선스 검증(BR-1)**. VectorSpec PIN·AS-4 수치 확정.
- [x] NFR Design — **완료·승인 (2026-06-16)**. `construction/u1-ingestion/nfr-design/`(nfr-design-patterns·logical-components). 버전 단조 tombstone(`current_version` compare-and-set)·indexStats 내부경계+캐시TTL·RES-1 의존성맵·verify-all-then-commit·CI=GHA(**설계만; GHA 워크플로우 미구현 — §검증 재기준선**)·RES-12 폴트인젝션. 적대적 검증 + 팀 피드백 2건(tombstone 순서·indexStats 경계) 반영. _ID: RES-12(복원력 테스트)._
- [x] Code Generation — **완료·승인 (2026-06-16)**. `construction/plans/u1-ingestion-code-generation-plan.md` 17단계 전부 완료. `ingestion/` 코드·테스트·배포 스캐폴드·코드 요약 생성 및 검증(`pytest` **23 passed**, `ruff` pass, `uv.lock` 생성) 완료. ⚠️ **PBT-08 P1(디덥 멱등) 속성 테스트 누락**(예시 테스트만 존재); Dockerfile 베이스 태그 핀(sha256 미적용·SEC-10).

**U2 Discovery** (Track 3 @kyjness, mock 선행 → U5):
- [x] Functional Design — **완료·승인 (2026-06-16)**. `construction/u2-discovery/functional-design/`(domain-entities·business-logic-model·business-rules). §4 답변 전부 A: **Q2=A RRF·PaperId 디덥**·**Q3=A baseline 랭킹·relevance 비-raw**·**Q4=A 기권 vs 빈결과 구분(빈 성공 금지)**·Q5=A 검색 인증 필수·Q6=A 2단계 저하·Q7=A NFC·다국어·Q10=A N=20·Q11=A 비차단 이벤트. **INV-1 단일 근거화 게이트(U2 enforce 미호출, U6 단일 권위)**·INV-2 SEC-9 비노출·INV-3 fail-closed·PBT-02/03/07/09. cross-lingual(TD-3 한국어 질의)·capability 어댑터 seam(VectorStoreAdapter·LexicalIndexAdapter·LlmGatewayAdapter) mock-first.
- [x] NFR Requirements — **완료·승인 (2026-06-16)**. `construction/u2-discovery/nfr-requirements/`(nfr-requirements·tech-stack-decisions). **[전역 계승]**: Python·Cohere `search_query`·OpenSearch·Hypothesis·NFR-C1 $1600. **U2 고유**: opensearch-py+**앱 레벨 RRF**+PaperId 디덥·Bedrock 질의 임베딩(검색당 1회)·**임베딩 캐시(TTL)**. **⏳ FastAPI = app-shell 소유자(@ELSAPHABA) 합의 전제(잠정, backend-shared)**. NFR-P1 예산 분해(U2 단계+U6 근거화 별도)·임베딩장애→lexical 폴백/인덱스장애→fail-closed·QT-2 한국어 평가셋.
- [x] NFR Design — **완료·승인 (2026-06-16)**. `construction/u2-discovery/nfr-design/`(nfr-design-patterns·logical-components). 동기 **fail-fast+폴백**(재시도 최소)·**의존성별 서킷**(임베딩→lexical/인덱스→fail-closed)·비용 degradeMode≠장애 서킷·임베딩 **read-through 캐시(TTL)**·**k-NN∥BM25 병렬 RRF**·stateless 수평확장·SEC 계층 분리 방어심층·CI=GHA(**설계만; 워크플로우 미구현**)·RES-12 폴트인젝션.
- [x] Code Generation (mock-first) — **완료 (2026-06-16)**. `backend/modules/discovery/`(pyproject·테스트). **31 passed(api extra)/29+1 skip · ruff clean.** 도메인 6컴포넌트(validator·expander·retriever[RRF·PaperId 디덥]·ranker[N=20]·grounding_adapter·assembler) + orchestrator(plan_and_retrieve/finalize 분리, **INV-1 enforce 미호출**) + `api/gateway_seam`(단일 enforce invocation=게이트웨이 대역) + mock 어댑터/스텁(KO↔EN cross-lingual+QT-2 픽스처) + thin FastAPI 라우터. PBT-02/03/07/09·RES-12 폴트인젝션 테스트. (마운트·근거화는 후속 PR에서 해소 — 아래 real 어댑터 항목 참조.)
- [x] Code Generation (real 어댑터) — **완료·로컬 검증 (2026-06-17, 브랜치 `feature/u2-v2`, 크리티컬 패스 ⑥, 리뷰 게이트)**. `backend/modules/discovery/adapters/`: **BedrockCohereQueryEmbedder**(reader=search_query·dim 검증·실패 시 EmbeddingUnavailable→lexical 폴백), **OpenSearchVectorStoreAdapter**(k-NN cosine)·**OpenSearchLexicalIndexAdapter**(BM25) — U1 writer 인덱스(`docsuri-corpus-v1`) 동일공간 read, hit→`IndexRecord` 역직렬화(SSOT), 실패 시 **IndexUnavailable fail-closed**(INV-3), **EventBridgeEventPublisher**(논블로킹 SearchExecuted→U4). `real_wiring.build_real_orchestrator`(MR-4 계약 불변 스왑)·`scripts/seed_local_opensearch`·pyproject `real` extra(opensearch-py/boto3 lazy). **검증: `pytest` 43 passed(신규 단위 11)+1 skip·ruff clean; docker 라이브 OpenSearch 통합 3 passed(k-NN·BM25·하이브리드 디덥); app-shell 엔드투엔드 200·실 카드 반환(Bedrock 부재 시 graceful degrade).** **app-shell 마운트 토글**(`backend/wiring.py::_mount_discovery`): env(`DOCSURI_OPENSEARCH_ENDPOINT`+`DOCSURI_BEDROCK_MODEL_ID`) 있으면 real, 없으면 mock — 실 근거화 hook은 양 모드 공통(INV-1). **⏳ 의존성 플래그**: 프로덕션 실행은 공유 인프라(OpenSearch 클러스터·Bedrock 접근·이벤트 버스 = U1 보류 인프라 + 시스템 횡단) 필요(env로 분리). **⚠️ 조율존(`backend/wiring.py`) 변경 = @ELSAPHABA 사인오프 필요.**
**U3 Accounts** (Track 2):
- [x] Functional Design — **완료·승인 (2026-06-16)**. `construction/u3-accounts/functional-design/`(domain-entities·business-logic-model·business-rules). 비밀번호 최소 10자 복잡도+로컬 블랙리스트(Q1=B), Argon2id KDF(Q2=A), Sliding 2h+절대 30d 세션(Q3=B), 지수 백오프+10회 CAPTCHA(Q4=B), 이메일 가입 링크 인증 PENDING/ACTIVE(Q5=B), Stateless 인가 결정(Q6=A), 시딩 관리자+TOTP MFA(Q7=B) 확정.
- [x] NFR Requirements — **완료·승인 (2026-06-16)**. `construction/u3-accounts/nfr-requirements/`(nfr-requirements·tech-stack-decisions). 세션 P50<5ms/P99<20ms(Q1=A), argon2-cffi(Q2=A), Multi-AZ 고가용 세션(Q3=A), RDS PostgreSQL+ElastiCache Redis(Q4=A), Google reCAPTCHA v3(Q5=B), Amazon SES(Q6=A) 확정.
- [x] NFR Design — **완료·승인 (2026-06-16)**. `construction/u3-accounts/nfr-design/`(nfr-design-patterns·logical-components). Redis 장애 시 Fail-Closed(Q1=A), reCAPTCHA Fail-Closed 및 SES PENDING 소프트폴백(Q2=B/A), PostgreSQL(10/20)+Redis(50) 커넥션풀(Q3=A), ECS 환경변수 주입 시크릿(Q4=A), 프런트 Origin CORS 명시 바인딩(Q5=A) 확정.
- [x] Infrastructure Design — **완료·승인 (2026-06-16)**. `construction/u3-accounts/infrastructure-design/`(infrastructure-design·deployment-architecture). Fargate 최소 사양(Q1=B), db.t4g.small Multi-AZ(Q2=B), cache.t4g.micro 1+1 Multi-AZ(Q3=B), NAT Gateway 배제 및 ECS Fargate 퍼블릭 서브넷 배치, RDS/Redis 고립 서브넷 배치(Q4=A), SES 도메인 인증(Q5=B) 확정.
- [x] Code Generation — **완료·③ 정정 (2026-06-17)**. _2026-06-16 재기준선 강등 결함은 ③에서 전량 해소: BR-A4 무잠금(자동 LOCKED 제거·백오프+CAPTCHA만)·SSOT 포크 제거(`docsuri_shared` 소비·`AccountCreated` model_dump·snake_case ObservabilityHub)·BR-A7 실 TOTP MFA+시딩 관리자(ADMIN 도달). 커밋 `bbac74f`·`f835a26`·`9b390b9`._ 원 강등 기록(2026-06-16): `construction/plans/u3-accounts-code-generation-plan.md` 17단계를 구현했으나 검증 결과 결함 확인: ⚠️ **BR-A4 위반**(`auth.py` 10회 실패 시 `status=LOCKED` → 무잠금 anti-DoS 규칙 직접 위반); **BR-A7 미구현**(TOTP MFA·시딩 관리자 없음 → ADMIN 도달 불가, `mfa_verified` 하드코딩 False); **SSOT 포크**(`docsuri_shared` 미소비·DTO 자체 재정의·`AccountCreated` raw dict·ObservabilityHub camelCase 오호출); 문서화된 `pytest` 명령 수집 실패(hypothesis·pytest-asyncio 누락); accounts 레인 ruff 132건(modules 제외 설정에 은폐). 의존성 주입 시 15 passed.

**U4 Library** (Track 2 — U3 다음, **Track 2 최종 유닛**):
- [x] Functional Design — **완료 (2026-06-17)**. `construction/u4-library/functional-design/`(domain-entities·business-logic-model·business-rules). 3 소유자 비공개 서브도메인(저장검색 US-L1/FR-8·라이브러리 US-L2/FR-9·이력 US-L3/FR-10). 결정 **D1~D12(권장 기본값 — 리뷰 게이트 override 가능)**: 저장검색 정규화 dedup+정원 200(BR-L1/L2)·라이브러리 `(owner,arxivId)` 멱등+정원 1000+meta 스냅샷(BR-L3/L4/L5)·이력 at-least-once `dedupe_key` 멱등+롤링 500 보존(BR-L6/L7)·키셋 커서 페이지(기본20/최대100, BR-L8)·**rerun=게이트웨이-프런티드(INV-L2 백도어 차단)**·SEC-8 **U3.AuthorizationGuard 위임**→cross-owner 일반화 404(SEC-9/INV-L4). **docsuri_shared DTO SSOT 재사용(포크 금지)**.
- [x] NFR Requirements — **완료 (2026-06-17)**. `construction/u4-library/nfr-requirements/`. [전역/U3 계승]: Python·FastAPI(CG-1)·RDS PostgreSQL·SQLAlchemy·Hypothesis·**NFR-C1 신규 비용 0(CRUD only)**. U4 고유: 포트 리포(InMemory 기본 mock-first + SQL 스캐폴드 + DDL)·base64 키셋 커서·**NFR-R2 가용성 격리(meta 스냅샷)**·QT-4 멱등.
- [x] NFR Design — **완료 (2026-06-17)**. `construction/u4-library/nfr-design/`. owner-scoping 백스톱(INV-L1)·fail-closed authz→404(INV-L4)·멱등 upsert+이벤트 멱등 소비(INV-L3)·롤링 보존 prune·정원 가드·키셋 페이지·감사 sink(SEC-13)·mock-first 포트 스왑. CI=GHA는 **deferred(재기준선: CI 전무)**.
- [x] Infrastructure Design — **완료 (2026-06-17)**. `construction/u4-library/infrastructure-design/`. **U3 인프라 계승**(동일 ECS Fargate 배포①·동일 RDS PostgreSQL); 신규 테이블 `saved_searches`/`library_items`/`search_history`(+ DDL `backend/modules/library/migrations/001`); 신규 관리형 서비스·비용 0; 이력 소비자=공유 이벤트버스(future U6/EventBridge).
- [x] Code Generation — **완료·검증 (2026-06-17)**. `backend/modules/library/`(models·schemas[docsuri_shared 재사용]·validation·ports·repository[memory+sql]·services×3·gateway 스텁·history_consumer·controller[3 라우터]·audit·migration). app-shell **`_mount_library` 마운트(mock-first, 무 DB)**. **검증: `pytest` 64 passed(library 41 + accounts 15 + app-shell 8)·`ruff` clean.** 적대적 설계 검증 18건(0 blocking)→문서 정합 반영. ⚠️ `shared/dtos/library.schema.json` PROVISIONAL→정제 스펙은 별도 shared/ PR(Track3 사인오프) 대기(코드는 로컬 검증으로 무관하게 정상).
- **→ Track 2 (U3 Accounts → U4 Library) 레인 완료.**
- [x] U6 통합·U2 real 어댑터 — **완료 (2026-06-17, ④·⑥; §크리티컬 패스 종결 참조)**

**U5 Frontend** (Track 3 @kyjness, mock-first → U2/U3/U4 DTO 계약):
- [x] Functional Design — **완료·승인 (2026-06-16)**. `construction/u5-frontend/functional-design/`(domain-entities·business-logic-model·business-rules·frontend-components). **히어로 슬라이스 스코프**(가입→로그인→검색→근거화 결과 + 상태UX; 라이브러리/이력은 계약만·후속 패스). 9컴포넌트(AppShell·PhoneMockupFrame·HeroLanding·Signup/LoginForm·SearchScreen·ResultList·ResultCard·StateView·ApiClient). 핵심: SearchResponse 4분기 상태머신(기권≠빈결과 구분)·ResultCard 7필드만(relevance=U2 표시값, raw 차단 SEC-9)·전역스토어 없음·DTO 파생 mock+transport seam(real 전환=설정 교체)·BR-U5-1~22(입력검증·XSS·SEC-12 세션·접근성). 개발지침↔aidlc 충돌 점검: PWA·오프라인 over-scope 제거. **⏳ 기술 스택(TS/SSR·타입 생성)은 NFR Requirements §5-D.**
- [x] NFR Requirements — **완료·승인 (2026-06-16)**. `construction/u5-frontend/nfr-requirements/`(nfr-requirements·tech-stack-decisions). **스택(§5-D)**: Next.js(React App Router SSR·신규 선택)·TS+JSON Schema→TS 생성(드리프트 0)·ApiClient transport-seam(전역 서버상태 라이브러리 없음)·CSS Modules·Vitest+Testing Library/Playwright/DTO 계약 테스트·SSR httpOnly 쿠키 포워딩·pnpm 독립 배포 ④. **U5 LLM 직접호출 없음 → NFR-C1 비용 기여 0**. 오프라인·PWA 제외 확정. 정량 SLO·호스팅·외부 APM은 후속.
- [x] NFR Design — **완료·승인 (2026-06-16)**. `construction/u5-frontend/nfr-design/`(nfr-design-patterns·logical-components). 패턴: 차등 재시도(멱등 GET만)·SSR 실패=완성 페이지·2계층 에러 바운더리·저하 흐름·서버/클라 컴포넌트 경계·캐싱(정적 장기/검색·세션 no-store)·**server-only 호출 경계(토큰 클라 유출 0)**·CSP frame-ancestors self·출력 무해화·stateless SSR 수평확장. 논리 컴포넌트 LC-1~9 + FD 9컴포넌트 매핑. 호스팅·정량 SLO·구체 CSP는 후속(Infra).
- [x] Code Generation (mock-first) — **Part 2 생성 완료·검증 (2026-06-16, 리뷰 게이트)**. 코드 `frontend/`(Next.js App Router·TS·CSS Modules). 16단계 전부. **검증: `tsc --noEmit` 0 errors · `vitest` 32 passed(7 files) · `next build` 성공(First Load JS ~113kB).** 히어로 슬라이스(US-H1·US-D7 + US-D1/D4·A1/A2 기여; US-L* 시그니처 stub만). ApiClient transport seam(MockTransport·real=HttpTransport 설정 교체)·server-only 토큰 경계·SEC-9 7필드·차등 재시도·2계층 에러 바운더리·CSP. 요약 `construction/u5-frontend/code/README.md`. **⚠️ TypeGen 플래그**: SSOT 스키마 루트리스/무타입 한계로 자동 codegen 대신 큐레이트 타입+드리프트검토(`pnpm gen:types`→`types/.schema-raw/`) 채택. **[2026-06-17: 아래 production 패스로 대체·머지됨.]**
- [x] Code Generation (production 패스) — **완료·로컬 검증 (2026-06-17, 브랜치 `feature/u5-v2`, 리뷰 게이트)**. 계획서 `construction/plans/u5-frontend-production-pass-plan.md`(14단계 전부). **스코프: 풀 기능 ①②③**(히어로 + 라이브러리/저장검색/이력; 인프라/CD ④는 공통 인프라 단계로 분리). **P1 계약 정렬**: 프런트 경로를 머지된 실 백엔드로(`/search`→`/api/search`·`/accounts/*`→`/auth/*`); **login 계약 정정**(실 login=쿠키만+`{status,message}`, `ApiClient.login()`→`Promise<void>`, 세션은 `GET /auth/session`); MFA=범위 밖(graceful); 생성타입 드리프트 갱신(라이브러리 DTO 전수 추가). **P2 실 transport(BFF 패턴)**: `app/bff/[...path]` catch-all(서버, `DOCSURI_GATEWAY_URL`→`HttpTransport` 쿠키 포워딩+Set-Cookie 릴레이, 없으면 mock)·클라 `RouteHandlerTransport`(`/bff/*` 동일출처)·`getApiClient` `NEXT_PUBLIC_DOCSURI_REAL_API` 분기·`server-only` 클라 미유출·호출처 5곳 교체. **P3 화면(US-L1/L2/L3)**: ApiClient stub 7개→실구현+rerun/clear, `/library`·`/library/saved`·`/library/history`(커서 페이지·rerun 인라인·담기/저장/삭제/비우기), 공용 `usePaginatedList`·`OutcomeView`·`LibraryTabs`·`cardFromMeta`(relevance 제거 SEC-9), 진입점(AppHeader 내비·ResultCard 담기·SearchScreen 검색저장). **검증: `tsc` 0 · `vitest` 48 passed(9 files; 신규 apiLibrary·libraryScreens + contract 라이브러리 계약) · `next lint` clean · `next build` 성공(라우트 10, `/bff/[...path]` 동적).** 적대적 자기검토 반영(SEC-9/8·커서 경계·login 계약·server-only). **⚠️ 의존성 플래그(U5 외부)**: 게이트웨이 세션쿠키→`request.state.principal` 미주입 → `/library/*`·`/api/search` 실 백엔드 401(fail-closed) = `backend/` 조율존 + 시스템 인프라 단계; reCAPTCHA 토큰 미전송(사이트키 필요); 인프라/CD/호스팅·구체 CSP·정량 SLO=공통 인프라 단계. **[2026-06-17 갱신: PR #63 머지(`86404d1`)·HTTPS 프로덕션 배포(`d1740b0`, Fargate+ALB+CloudFront @ docsuri.org)·BFF 빌드 복구(`344172e`); ⑤ 종결. 게이트웨이 principal 주입(`568677c`)으로 `/library/*`·`/api/search` 401 갭 해소.]**

**U6 Reliability/Ops** (데이터 및 탐지 파이프라인 우선):
- [x] Code Generation — **완료 (2026-06-16)**. `construction/plans/u6-reliability-ops-code-generation-plan.md` 25단계 전부 완료. `ops/` 패키지와 `backend/middleware/` seam 생성. 구현 범위: ObservabilityHub, CostGuardCircuitBreaker, GroundingEnforcementHook, RES-11 a/b/c 탐지기, IncidentEventPublisher, OpsDashboardService, HealthCheckService, ReliabilityEvalProbe, CLI/worker. 검증: `ops/.venv`에서 U6 범위 `pytest ops\tests backend\tests\test_u6_middleware.py` 31 passed, U6 범위 `ruff check ops backend\middleware backend\tests\test_u6_middleware.py` passed, shared contract import 및 CLI smoke passed. 명시 통합 테스트 `pytest ops\tests backend\tests\test_u6_middleware.py tests`는 46 passed. 루트 기본 `pytest`는 기존 `tests/accounts` 15 passed. 루트 `ruff check .`는 기존 `tests/accounts` unused import 9건(F401)으로 실패하여 U6 외 잔여 정리 필요. **[2026-06-17 갱신(④): `create_app` 게이트웨이 설치 + discovery 시임 실 `GroundingEnforcementHook` 주입으로 라이브 경로 연결(`ba4a62e`); PR#45 크로스리뷰 반영(`b6bb92d`); ops CI 레인(`7edd316`); CloudWatch EventStore 어댑터·프로덕션 자동 선택(`8b54b62`). F401 9건은 §크리티컬 패스 종결 잔여 항목으로 추적.]**

**U7 Summarization** (요약/번역 — 코어 U1~U6 완료 후 편입 유닛, 단일 트랙·**실배포 기준 real-first 구현**):
- [x] Functional Design — **완료·승인 (2026-06-18, 브랜치 `feature/u7-v2`·PR #115)**. 계획서 `construction/plans/u7-summarization-functional-design-plan.md`(명확화 질문 **17문** 전수 답변: **A 14·B 1[Q2 노이즈 범위 한정]·X 2[Q10/Q11 real-first]**). 산출물 `construction/u7-summarization/functional-design/`(domain-entities·business-logic-model·business-rules — 도메인 엔티티·9 컴포넌트 파이프라인·BR-S1~S14·PBT-S1~S5·추적성 미커버 0·설계입력 §2~§12 흡수 맵). **핵심 결정**: Q4(U7 고유 결정적 근거화 게이트 — frozen `enforce` 검색형상 미재사용·"단일 권위=U6"는 검색 한정 해석)·Q6(`split_sections` 부재→U7 섹션 도출+span)·Q12(버퍼-검증-스트리밍)·**Q10/Q11 real-first(포트 유지·첫 구현부터 실 Bedrock/S3+Redis·mock 대역 없음)**. **앱 코드 미생성.** _승인 완료(2026-06-18)._
- [x] NFR Requirements — **완료·승인 (2026-06-19)**. 계획서 15문 전수 A(Q14는 A+명시: **Production Mock Adapter 미구현·단위 테스트 Fixture/Stub 허용**). 산출물 `construction/u7-summarization/nfr-requirements/`(nfr-requirements·tech-stack-decisions). **바인딩**: 모델=Sonnet 4.6 요약/Haiku 4.5 번역(TD-S3)·Bedrock 스트리밍(TD-S4)·스토어 S3+Redis(TD-S5)·개인 용어집=**RDS PostgreSQL**(TD-S6)·섹션 도출=정규식·휴리스틱(TD-S7)·**비동기 잡=fast-follow(v1 동기+토큰 캡, TD-S9)**·**real-first 테스트(TD-S12)**.
- [x] NFR Design — **완료·승인 (2026-06-19)**. 계획서 10문 전수 A. 산출물 `construction/u7-summarization/nfr-design/`(nfr-design-patterns·logical-components). **패턴**: Bedrock 격리(타임아웃+1재시도+서킷→기권)·근거화 1회 재시도·**저하 3계층 구분**(비용 degradeMode≠의존성 서킷≠소스 폴백)·캐시 우선 read/write-through·**생성-버퍼-검증-점진렌더**(구조화 JSON은 완성 후 근거화)·stateless+공유 외부 상태·보안 방어심층(인젝션·개인 용어집 owner 격리)·CI real-first(단위 Fixture/Stub 항상+통합 실 의존성 별도 게이트)·RES-12 폴트 인젝션. 논리 컴포넌트 토폴로지(FD 9↔논리 매핑·기존 인프라 재사용·신규 관리형 0). 앱 코드 미생성. _승인 완료(2026-06-19)._
- [x] Infrastructure Design — **완료·승인 (2026-06-19)**. 계획서 9문 전수 A. 산출물 `construction/u7-summarization/infrastructure-design/`(infrastructure-design·deployment-architecture). **신규 관리형 서비스 0**(전부 기존 자산 재사용): 컴퓨트=기존 ECS Fargate 모듈·S3 `summaries/` 프리픽스·Redis `sum:` 키스페이스+TTL·RDS `user_glossary` 테이블(마이그레이션)·Bedrock IAM(모델 ARN 스코프)·CloudWatch/Budget 비용 라인·CI 통합 게이트 레인. 비동기 잡 v1 미프로비저닝. 증분 비용≈Bedrock 토큰(가변). **조율 존**(task role·CI·IaC·마운트)=@ELSAPHABA/Infra. 앱 코드 미생성. _승인 완료(2026-06-19)._
- [x] Code Generation — **Part 1·2 완료·검증 (2026-06-19, 브랜치 `feature/u7-v2`·PR #115)**. 계획서 18단계 전부 [x]. 코드 `backend/modules/summarization/`(src-layout, real-first): 도메인 9컴포넌트(models·refiner·source_selector·cache_key·length_router·glossary·grounding·assembler·orchestrator)·실 어댑터 단일본(bedrock_llm 스트리밍·s3_redis_store·s3_full_text·rds_glossary)·api(router `/api/summarize`·gateway_seam)·prompts(본문 격리)·real_wiring·`migrations/001_create_user_glossary.sql`. **검증: `pytest` 29 passed + 1 skip(통합 self-skip)·`ruff` clean.** Q4 U7 고유 결정적 근거화·Q5 버퍼-검증·저하 3계층·Q8 후치환(한국어 조사 안전)·real-first(Production Mock Adapter 없음·테스트 Fixture/Stub). **⚠️ 마운트=조율 존**: `backend/wiring.py` 미변경(쉘 테스트 보호) — mounter 스니펫을 `code/README.md`에 사인오프-레디로 제시. 인프라 증분(IAM·마이그레이션·CI)=@Infra. _승인 완료(2026-06-19)._
- [x] Build & Test — **완료 (2026-06-19)**. 산출물 `construction/u7-summarization/build-and-test/`(build-instructions·unit-test·integration-test·security-test·build-and-test-summary). **검증: `pytest` 29 passed + 1 skip(통합 게이트 self-skip)·`ruff` clean·임포트 스모크 OK.** 통합 5 시나리오 정의(게이트 레인 전용·real-first). 성능=N/A(NFR-P2 온디맨드). **U7 CONSTRUCTION 종료.** Operations 전 last-mile(프레임워크 밖): app-shell 마운트(@ELSAPHABA)·인프라 증분(@Infra)·`shared/dtos/summarization` 승격·비동기 잡 fast-follow.
- [x] **개인 용어집 편집 후속 (2026-06-22, 브랜치 `feature/u5-frontend-ux`·PR #121)**: BR-S4의 "사용자 용어 수정→upsert"를 사용자 경로로 노출. 백엔드 **`GET/POST /api/glossary`**(owner-scoped·입력 검증·fail-closed, 저장 시 `glossary_ver++`→해당 사용자 캐시 무효화) + 프론트 `TranslationView` keptTerms 배지 탭→저장·미리채우기(**BR-SF-17**). 후치환을 함수 치환으로 보강(사용자 입력의 정규식 역참조 해석 차단). 문서 정합: `nfr-design/logical-components`·`infrastructure-design/deployment-architecture`·프론트 `functional-design/frontend-components`·`business-rules` 갱신. **검증: 프론트 68·백엔드(summarization) 42 통과·lint/ruff clean.** 후속(Phase 2-b): 마이페이지 "내 용어집" 보기·수정·삭제 + `DELETE` 엔드포인트.
- [x] **프론트 카드·내비 UX 패스 (Phase A) (2026-06-22, 브랜치 `feature/u5-card-nav-ux`)**: 프론트 로컬 UX 정리(계약·DTO 불변). ① 상세 요약 단락명 `기여/방법/결과`→`핵심 기여/연구 방법/주요 결과`(+tldr 라벨 `한 줄 요약`). ② **카드 [요약]/tldr 피크 기능 폐지**(`SummaryAction`/`SummaryInline` 제거 — 요약은 상세로 일원화; **Q1·Q2 카드 인라인 결정 대체**). ③ 담기 버튼→카드 **우상단 북마크 아이콘** + 상세 제목 옆 북마크(저장 계약 불변·멱등). ④ 카드 `relevance` **표시 제거**(계약엔 유지) + **클라 정렬 토글(관련도순/최신순)**. ⑤ **하단 고정 탭바(`BottomNav`)** 검색/마이페이지(모바일 우선; 상단 `AppHeader`는 브랜드+로그아웃만 유지. 에이전트 탭은 기능 생길 때·인용수 표시는 U8 머지 후 보류). 추가 미세조정(검색 '논문 검색' 라벨 제거→aria-label·'검색 저장'→'검색어 저장'·저장/정렬 한 툴바·상세 헤더 간격·구분선 축소). 문서 정합: u5 `functional-design/business-rules`(BR-U5-4/5/23)·`domain-entities`·`frontend-components`, u7-frontend `functional-design/frontend-components`·`nfr-design`. **검증: `tsc` 0·`next lint` clean·`vitest` 70 passed·`next build` OK.** 보류 트랙(별건): 그림·도표(멀티모달=요구사항 개정) → **2026-06-22 인셉션 진입**(아래 멀티모달 표시 항목)·필터.

- [~] **doc-model 실데이터 완성 — PR-1 (2026-06-24, 브랜치 `feature/docmodel-realdata`, base `feature/docmodel-foundation`/#161 스택)**: doc-model 피벗 기반(#161: 생산·읽기 API·리치뷰) 위에 실데이터 경로를 비동기로 완성. **① 파서 충실도**(`ltx_appendix` 섹션 인식 — 부록 하위 flatten 해소; `_inline_text`가 `ltx_note` 각주 skip — 본문 오염 제거; theorem 본문은 paragraph로 보존). **② lazy 빌드 트리거(경계 B·비동기)**: 읽기 미스 → U7이 U1 큐에 `BUILD_DOC_MODEL` 잡 enqueue(빌더 직접 의존 X) → 워커가 `DocModelBuilder.build` 실행·캐시 → 읽기 API `building`(폴링) 반환(BR-30/§7.2). **③ 긴 논문 요약 맵리듀스 + 비동기 잡(BR-S6/BR-S12, #135)**: 40K~120K = `MapReduceSummarizer`(섹션 청킹·오버랩·reduce), API enqueue→`PendingDTO`→폴링→요약 워커 inline 생성→write-through; **>120K = 거절(degraded 폐기, 모바일 결정)**; 번역 맵리듀스는 PR-2. 게이트 `DOCSURI_MAP_REDUCE_ENABLED`/`DOCSURI_SUMMARY_JOB_QUEUE_URL`/doc-model 빌드 큐 **기본 OFF → 라이브 무변경**. 공유계약: `docmodel.schema.json` **building**·`summarization.schema.json` **pending** 신설(재생성). 프론트: `useDocModel`/`useSummarize` 폴링(retryAfterMs·상한). **④ CDK 인프라(slice 6, synth 검증·배포 X)**: `infrastructure-design.md`(단일 버킷 prefix·요약 큐+빌드큐 재사용·요약 워커 배포 단위 ④·IAM 3역할) + `compute_stack`(API task role: doc-model GetObject·summary R/W·두 큐 SendMessage·Bedrock·큐 URL env — 활성화는 팀 deploy) + 신규 `summarization_stack`(요약 잡 큐+DLQ + 요약 워커 Fargate, API 이미지 재사용) + app.py 등록. **doc-model 빌드 잡=ingestion 큐+워커 재사용**(신규 큐 불요). **⑤ OA 게이트(slice 7)**: OA 신호 = U1 인제스션 검증(CC만 저장·비-OA 거부, BR-1) → 코퍼스 전부 OA·인앱 렌더 안전 → 게이트는 운영 토글(논문별 라이선스 조회 불요·오버엔지니어링 회피); 주석·문서 정합, 활성화는 팀 deploy. 문서 정합: U1 BLM §7.2·U7 BR-S6/S9/S12·BLM §3.6·NFR TD-S9·shared docmodel §5·infrastructure-design·length_router. **검증: 백엔드 summarization·ingestion·shared(drift 0)·프론트(tsc/lint/93)·`cdk synth`(6스택) 전부 green.** 후속: 번역 구조화(PR-2)·각주 footnote 블록·앵커 id 계약·doc-model 빌드 실패 네거티브캐시.

- [~] **구조화 번역 — PR-2 (2026-06-24, 브랜치 `feature/docmodel-structured-translation`, base `feature/docmodel-realdata` 스택 — #163 머지 시 develop retarget)**: 번역 영역 전부(PR-1 의도적 미룸). doc-first. 설계 게이트 확정: **① 출력 = 번역본 doc-model**(자기완결 — 본문 번역 = 본문과 동일 구조화 형식; `summarization.schema.json` `TranslationDraft` `{koreanText}`→`{docModel: DocModel, keptTerms}`로 개정, `docmodel.schema.json#/$defs/DocModel`을 **크로스파일 `$ref`**로 복제 회피·생성기 지원 확인). **② 긴 번역 = 비동기**(요약 잡 큐·워커 재사용, `task=translate`). **번역 단위**: 섹션 제목·문단·리스트·표/그림 캡션만 번역; **표 셀·수식 LaTeX·코드·블록 id·그림 assetRef = verbatim 보존**(D8). **재조립**: LLM은 id→번역텍스트로 받아 소스 doc-model 구조에 주입해 결정적 재조립(누락 id=원문 보존); 출력이 자기완결이라 parserVersion 캐시키 불요(요약과 동일). **긴 본문 map-only**: MAP_REDUCE 밴드 translate = 섹션별 번역→이어붙이기(reduce 없음), OVER_CAP 거절 유지. 잡 큐·워커는 task-agnostic(요약·번역 공용). 프론트: `DocModelViewer` 렌더부 `DocModelBody`로 분리 → `TranslationView`가 번역본 doc-model 구조 렌더(keptTerms 유지·그림 자산 로드). 문서 정합(doc-first): BR-S18 신설·BR-S2/S6/S9/S12·FR-13·domain-entities·BLM §3.6/3.7·plan PR-2 절. **검증: summarization pytest·ruff 베이스라인·shared drift 0·프론트 tsc/lint/vitest 93 green.** 후속: 표 셀 번역·각주 블록·앵커 id 계약·빌드 실패 네거티브캐시.

- [~] **멀티모달 표시(그림·도표) — INCEPTION 진행 (2026-06-22, 브랜치 `feature/multimodal-display`)**: 보류 트랙 "그림·도표"를 Requirements Analysis 재진입으로 착수. 명확화 질문지 `inception/requirements/requirement-verification-questions-multimodal-display.md` Q1~Q7 확정(**Q2=C 혼합 추출, 나머지 A**) → `requirements.md` 등재(**FR-17** 그림·도표 자산 추출·표시 + FR-12 앵커 자산 연결 보강 + **§12 "그림·도표" 제외를 "비전 추론만 제외"로 한정** + §13 추적성). **범위: 표시 전용**(자산 추출·저장·렌더; 요약/번역 LLM 입력은 텍스트+캡션 유지, 이미지 비전 추론은 차기 사이클). 영향: U1(자산 추출·저장, 소스 가용성 혼합)·공유계약·U7(통과 + 백/프론트 정합 갭 3건 흡수: `summarization.schema.json` SSOT 수립·`validation_error`/`unauthorized` 상태 매핑)·U5(렌더).
  - [x] **U1 Functional Design — 완료 (2026-06-22)**. 계획서 `construction/plans/u1-ingestion-multimodal-functional-design-plan.md` Q1~Q7 전부 권장안 A. 기존 U1 FD 확장: `domain-entities`(§10 FigureTableAsset·AssetManifest·AssetStorePort), `business-logic-model`(§6 ingestOne 자산 추출·저장 — Q1=A parse 추출+dedup 후 NEW\|CHANGED 저장, Q2=C 혼합, Q4=A best-effort·비차단, tombstone/CHANGED 정리), `business-rules`(§7 BR-22~28·P7/P8·FailureReason·추적성). **표시 전용**: 인덱싱/임베딩/IndexRecord 경로 불변(자산 검색 비대상). **앱 코드 미생성.**
  - [x] **U1 NFR Requirements — 완료 (2026-06-22)**. 계획서 `construction/plans/u1-ingestion-multimodal-nfr-requirements-plan.md` Q1~Q7 전부 권장안 A. 기존 U1 NFR 확장: `tech-stack-decisions`(**TD-11** PyMuPDF 휴리스틱 PDF 크롭·**TD-12** e-print 그래픽 직접+표 크롭·**TD-13** WebP 재인코딩·치수상한·메타스트립·**TD-14** S3 prefix+공유 RDS 매니페스트·**TD-15** 이미지 보안 재인코딩), `nfr-requirements`(§11 성능·보안·복원력·비용). 상속: Python·S3·Hypothesis. **ML/GPU 없음**(CPU 배치, $1600 내 흡수). **앱 코드 미생성.**
  - [x] **U1 NFR Design — 완료 (2026-06-22)**. 계획서 `construction/plans/u1-ingestion-multimodal-nfr-design-plan.md` Q1~Q5 전부 권장안 A. 기존 U1 NFR Design 확장: `logical-components`(§5 AssetExtractor·Image Normalizer·AssetStore 컴포넌트 + 토폴로지 + `paper_asset` RDS 상태), `nfr-design-patterns`(§7 page-crop 검출·캡션 매칭 알고리즘·이미지 정규화 파이프라인·best-effort 격리·매니페스트 write-order 정합 P8·보안 + 추적성 행). 기존 인덱스/원자성 토폴로지 불변. **앱 코드 미생성.**
  - [x] **U1 Infrastructure Design — 완료 (2026-06-22)**. 계획서 `construction/plans/u1-ingestion-multimodal-infrastructure-design-plan.md` Q1~Q5 전부 권장안 A. **U1 최초 Infra 산출물**(멀티모달 범위로 한정): `infrastructure-design/infrastructure-design.md`(S3 `assets/` prefix·SSE-KMS·만료없음·`paper_asset` RDS 스키마/마이그레이션·최소권한 IAM·presigned 만료·비용 라인) + `deployment-architecture.md`(워커 co-location·메모리 헤드룸·토폴로지·전달 경로). 기존 전문 S3·공유 RDS 재사용(신규 버킷·DB 0), presigned S3 직접(CloudFront 후속). **선결 상속(미결)**: 워커 런타임 타깃(ECS/Lambda)·리전·CD. **앱 코드 미생성.**
  - [x] **U1 Code Generation — 완료 (2026-06-22)**. 계획 Q1=A(permissive 스택 pypdfium2·pdfplumber·Pillow — PyMuPDF/AGPL 회피, TD-11/13 정정). 브라운필드 `ingestion/`: 신규 `domain/assets.py`·`asset_extraction.py`(caption_kind·finalize P7·ImageNormalizer·AssetExtractor 혼합)·`adapters/assets.py`(ArxivAssetSource·S3RdsAssetStore write-order P8)·`migrations/postgres/002_paper_asset.sql`; 수정 `enums.py`·`ports.py`(AssetSource/StorePort)·`application.py`(best-effort 비차단 자산 단계·tombstone 정리·포트 주입 미주입=off)·`settings.py`(MULTIMODAL_ASSETS_ENABLED off 기본)·`pyproject.toml`(assets extra). 테스트 `tests/test_assets.py`(PBT P7·normalizer)·`tests/test_asset_wiring.py`(기본 off·성공·실패 비차단). **인덱스 경로 코드 불변.** **검증**: compileall·순수 로직 스모크 통과(전체 테스트=Build & Test).
  - [x] **U1 Build & Test — 완료 (2026-06-22)**. `uv sync --extra assets`(pypdfium2·pdfplumber·Pillow 설치) → `pytest` **42 passed/0 failed**, `ruff` **clean**(B904/E501 정정). 자산 신규 테스트(caption·finalize **PBT P7**·ImageNormalizer bomb 가드·best-effort 비차단 wiring) + 인덱스 경로 회귀 통과. 실 추출(`_page_crop`/`_structured`)·`S3RdsAssetStore`는 env-gated 통합으로 이연. 산출물 `construction/u1-ingestion/build-and-test/`(build·unit-test·summary). **U1(생산자) 멀티모달 슬라이스 종결.** 다음(멀티모달 트랙): 공유계약 → U7 → U5.
  - [x] **U7 Functional Design — 완료 (2026-06-22)**. 계획서 `construction/plans/u7-summarization-multimodal-functional-design-plan.md`(위임 진행, 게이트 결정 D1~D5 확정). 기존 U7 FD 확장: `domain-entities §9`(AssetRef·PaperAssetsResponse union·`GET /api/papers/{id}/assets` 엔드포인트·AssetManifestReadPort/AssetUrlSigner·앵커↔자산 연결·갭#1 SSOT·갭#2/#3 상태), `business-rules`(BR-S15 자산 읽기·OA 게이트·presign SEC-9, BR-S16 SSOT 수립, BR-S17 상태 매핑, PBT-S6). **U7은 읽기 측**(생산=U1), 요약/번역 생성·근거화·캐시 불변. **앱 코드 미생성.** 다음: U7 Code(shared schema·`/assets` 엔드포인트·갭 수정·frontend types/classify).
  - [x] **U7 Code Generation + Build & Test — 완료 (2026-06-22)**. 공유: `shared/dtos/summarization.schema.json` **SSOT 수립**(갭#1). 백엔드(`backend/modules/summarization`): `StoredAsset`/`AssetRef`(SEC-9 서명 URL만)·`AssetReadPort`·orchestrator `list_assets`·**`GET /api/papers/{id}/assets`**(인증·OA 게이트·presign)·`adapters/rds_assets.py`(RDS 읽기+S3 presign)·**갭#2** `validation_error` message. 프론트: `summarize.ts`(AssetRef·PaperAssetsResponse·unauthorized/validation_error)·`classifyAssetsResponse`+**갭#2/#3 매핑**·`apiClient.getAssets`. NFR/Infra는 경량 폴드(읽기 포트·presign TTL·`assets_enabled` 게이트). **검증: 백엔드 summarization 48 passed/1skip·자산 7 passed·ruff clean; 프론트 tsc 0·next lint clean·vitest 75 passed(+5).** 요약/번역 생성·근거화·캐시 불변. **U7(읽기 측) 멀티모달 슬라이스 종결.** 다음: U5(상세/뷰어 자산 렌더 컴포넌트).
  - [x] **U5 Code Generation + Build & Test — 완료 (2026-06-22)**. 프론트: `lib/assetAnchor.ts`(순수 매처 — figure/table 앵커↔자산)·`lib/useAssets.ts`(페치 훅)·`components/AssetGallery.tsx`(+css; lazy·치수예약·캡션 이스케이프·서명 URL img·로딩/에러/빈·라이선스 미표시·활성 앵커 스크롤)·`PaperDetailIsland`(자산 섹션+앵커 전달)·mock(`/assets`+SVG 픽스처). 테스트 `test/assetAnchor.test.ts`·`test/assetGallery.test.tsx`. **검증: tsc 0·next lint clean·vitest 80 passed(+5)·next build OK.** 코드 요약 `construction/u5-frontend/code/u5-multimodal-asset-render-code-summary.md`.
  - **✅ 멀티모달 표시(FR-17) 트랙 완결**: U1(추출·저장) → 공유계약/U7(노출·정합 갭 3건) → U5(렌더). 비전 LLM 추론은 차기 사이클. 9커밋 `feature/multimodal-display`(미push). 배포(Operations)는 push/PR·승인 후.
  - [x] **표시 UX 정제 + 자산 점등 코드 배선 (2026-06-22, 브랜치 `feature/multimodal-display`)**: FR-17 표시 슬라이스 후속 패스.
    - **갤러리 UX**: `AssetGallery`를 큰 인라인 이미지 → **컴팩트 썸네일 그리드(모바일 3·데스크톱 4) + 탭하면 전체화면 라이트박스**로 전환(신규 `AssetLightbox`+css; ‹이전/다음›·카운터·ESC/배경/✕ 닫기·←→ 키보드·바디 스크롤 락·포커스). 모바일에서 큰 이미지가 본문을 가리는 문제 + 수십 장 세로 열거 문제를 동시 해소(썸네일 `cover`·라이트박스 `contain`). figure/table 앵커 "출처 보기"=썸네일 스크롤+라이트박스 자동 오픈. **신규 라이브러리 0**.
    - **북마크 토글 버그 수정**: `SaveToLibraryButton`이 저장 후 `disabled`라 취소 불가였음 → 멱등 add가 반환하는 item id 보관 → 재클릭 시 `removeFromLibrary`로 **토글(담기↔빼기)**, 진행 중에만 비활성. (`/library/items` DELETE는 U4 라이브 경로 — 인프라 불필요.)
    - **자산 점등 코드 배선(옵션 B)**: "인프라만 깔면 켜짐" 상태로 배선하되 **기본 OFF 유지**(인프라 없이 안전 머지). 읽기측(U7): `SummarizationSettings.assets_enabled`(`DOCSURI_MULTIMODAL_ASSETS_ENABLED`)·`asset_url_ttl_seconds` 추가 → `real_wiring`가 플래그+DSN 있을 때 `RdsS3AssetReader` 주입 → `_mount_summarization`이 `assets_enabled`를 라우터에 전달. 쓰기측(U1): `build_production_runtime`이 `multimodal_assets_enabled` 시 `AssetExtractor`/`ArxivAssetSource`/`S3RdsAssetStore` 주입(셋 모두 주입돼야 추출 동작). **검증: 프론트 tsc 0·lint clean·vitest 83·build OK; 백 summarization 54 passed/1skip·ruff clean; ingestion 43 passed·ruff clean.**
    - [ ] **🔌 자산 점등 체크리스트 — 실 인프라 배포 (담당 팀원, 승인·비용 결정 후)**: 코드 배선(옵션 B) 완료 → 아래만 하면 프로덕션 점등.
      1. **인프라 프로비저닝(CDK, `ops/cdk/stacks/ingestion_stack.py` 등)**: S3 `assets/` prefix + SSE-KMS 키, presign용 최소권한 IAM(워커=S3 put+RDS write / BFF task role=S3 get+presign). `paper_asset` 마이그레이션은 `backend/migrations/__main__.py` 경로에 이미 포함(배포 시 적용).
      2. **워커 이미지**: ingestion `assets` extra 설치(pypdfium2·pdfplumber·Pillow).
      3. **환경변수 ON**: 워커 `DOCSURI_MULTIMODAL_ASSETS_ENABLED=true`(+`DOCSURI_S3_BUCKET`·`DOCSURI_CONTROL_PLANE_DSN`·`DOCSURI_ASSET_KMS_KEY_ID`); BFF `DOCSURI_MULTIMODAL_ASSETS_ENABLED=true`(+`DATABASE_URL`·`DOCSURI_SUMMARY_BUCKET`·`DOCSURI_ASSET_URL_TTL_SECONDS`).
      4. **백필(비용 결정)**: 추출은 신규 인제스천만 자산 생성 → 기존 코퍼스(수십만 편)는 재인제스천 필요(CPU+S3 비용). 점진 백필 권장.
    - [x] **자산 통합 테스트 A·B (2026-06-22)** — 점등 전 env-gated 구간을 실제로 검증(AWS·비용 0). **A(실 추출, 오프라인)**: `ingestion/tests/test_asset_extraction_real.py` — 합성 텍스트-레이어 PDF로 **실 pdfplumber 캡션 검출 + pypdfium2 렌더 + 크롭 + WebP 정규화** 왕복(figure/table·page-crop·hybrid Q2=C e-print 우선) + 합성 e-print tar로 structured 경로. AWS·네트워크·외부 PDF 픽스처 0. **B(실 SQL, 실 Postgres)**: `ingestion/tests/test_asset_store_real.py`(`S3RdsAssetStore` 쓰기 — S3 put[웹P·SSE]→`paper_asset` 행→P8 write-order→CHANGED 멱등 재저장→remove; S3는 monkeypatch 가짜)·`backend/.../tests/test_assets_rds_real.py`(`RdsS3AssetReader` 읽기 — SELECT 컬럼 매핑·JSONB bbox·null·presign; S3는 주입 가짜). **`DOCSURI_TEST_PG_DSN` 게이트**(미설정 시 스킵 — `test_integration_real.py` 관례), Docker 임시 PG16 netns-공유로 **실행 green 확인**. **C(실 인프라/스테이징 E2E)는 위 점등 체크리스트로 팀원 위임.** **검증: ingestion 47 passed/1skip(B 게이트)·summarization 54 passed/3skip(B 게이트)·ruff clean.**
  - [ ] **🔮 보류 트랙 — 비전 추론(멀티모달 요약·근거화) [차기 사이클 후보]**: `requirements.md` §12 멀티모달 카브아웃(2026-06-22)·FR-17이 명시적으로 **제외 유지**한 범위. 이미지(그림·도표)를 비전 LLM으로 읽어 **요약·근거에 반영**하는 작업. 현재 v1은 요약/번역 LLM 입력이 **텍스트+캡션**으로 한정(이미지 비전 추론 없음).
    - **기반 준비됨**: FR-17 표시 전용 슬라이스가 자산을 이미 S3에 추출·저장(U1)하고 서명 URL로 노출(U7)·렌더(U5)한다 → 비전은 **재인제스천 없이** 기존 자산을 읽는 **추론 레이어 추가**이지 데이터 파이프라인 재작업이 아님.
    - **범위 영향(예상)**: U7 요약 노드 모델 교체(비전 가능 모델·비용/지연 ↑·NFR-C1 비용 상한 재산정)·이미지 앵커 grounding 재설계(FR-5/QT-5 근거화 경계 확장)·Prompt Injection 무해화(이미지 경유 포함). **요구사항 재진입(승인 게이트) 필요** — C-2 생성 경계·FR-5 근거화 정신 유지 확인.
    - **선후 권고**: "차별화/근거형성 에이전트"(`summarization-translation-pipeline.md` #9·#12 — 파이프라인 6~7단계 재사용 + '유사논문 검색' 노드 추가)와는 **독립 트랙**(의존성 없음). 에이전트는 현재 텍스트+캡션 근거화로 동작 가능 → **에이전트 먼저 검증 → 비전을 리프 요약 노드 품질 업그레이드로 후속 도입** 권장(에이전트가 같은 노드를 재사용하므로 근거 품질이 자동 상승; 미검증 흐름에 N배 비용 곱 방지).

**U8 Citation Graph** (인용 그래프/각주 트리 — 2026-06-19 편입 유닛, FE 구현 제외 API 모듈):
- [x] Functional Design — **완료·승인 (2026-06-19)**. 계획서 `construction/plans/u8-citation-graph-functional-design-plan.md` Q1~Q12 전부 권장안(A) 반영 및 체크박스 완료. 산출물 `construction/u8-citation-graph/functional-design/` 3문서(`domain-entities.md`, `business-logic-model.md`, `business-rules.md`) 생성. **앱 코드·FE 미생성.**
- [x] NFR Requirements / NFR Design / Infrastructure Design / Code Generation / Build&Test — **완료 (2026-06-21)**. U8 backend-only citation graph slice 생성 및 검증 완료.
- [~] Cross-Review 반영 — **진행 (2026-06-22)**. 브랜치명은 `feature/u8-v1`로 CI prefix 조건 충족. 코드 수정: 죽은 `depth` 쿼리 제거, provider/cache 중복 제거, save year 범위 밖 값 null 처리, telemetry `emit_log` 방어 및 `depthRequested` 분리. 문서 수정: Redis 단언을 현재 process-local in-memory snapshot seam + production Redis target으로 정정.

**v4-migration** (Cohere Embed v4.0 Migration):
- [x] NFR Design — **완료·승인 (2026-06-23)**. `nfr-design-patterns.md`, `logical-components.md` 생성 완료. Fail-Open 듀얼 라이트 및 arXiv API 기반 Idempotent 백필 전략 승인.
- [x] Infrastructure Design — **완료·승인 (2026-06-23)**. `infrastructure-design.md`, `deployment-architecture.md` 생성 완료. Local execution 및 Automated Cutover 맵핑 확정.
- [x] Code Generation — **완료 (2026-06-23)**. U1 Ingestion 듀얼 라이트 로직, U2 Discovery alias 설정 및 Ops 백필/컷오버 스크립트 작성 완료.
- [x] Build & Test — **완료 (2026-06-23)**. 빌드 및 테스트 가이드 산출 완료.

**공통 후속 단계** (per-unit 또는 횡단):
- [x] 병렬 개발 조율 (2026-06-16 반영) — `shared/` 공용 규약 선행 작성 및 3개 독립 트랙 병렬 진행 확정
- [x] `shared/` 규약 작성 (vector-spec·DTOs·events·ports) — **완료 (2026-06-16)**. `construction/shared/`(5문서). vector-spec 🔒FROZEN(Cohere 1024·코사인·input_type 비대칭·IndexRecord); DTOs/events/ports SSOT 정합·적대적 검증(ship); **63 tests pass·드리프트 스크립트(`tools/generate.py --check`) 동작**. **3 트랙 unblocked.** ⚠️ **드리프트 가드는 수동 스크립트일 뿐 CI 미연결**(`.github/workflows/` 부재); **U3 accounts는 docsuri_shared 미소비(SSOT 포크)** — U1·U2만 실소비.
- [x] U1 NFR Design 승인 (2026-06-16)
- [x] Infrastructure Design — **완료 (2026-06-17, 시스템 전역)**. `construction/infrastructure-design/infrastructure-design.md`(`ac21ae2`) + AWS CDK 5 스택(Network·Search·Compute·Ingestion·Frontend, `ddf8858`). AWS 자원·리전/AZ 토폴로지(RES-2, 서울 단일리전 멀티 AZ)·오토스케일링/쿼터(RES-8) 반영.
- [x] Code Generation — **완료**. 전 유닛(U1~U6) 코드 + 시스템 IaC/CD(`db1b187`)·프로덕션 실연결(`01fd553`·`5f7acce`)·SES(`50da0d5`·`0437b40`).
- [x] 빌드 & 테스트 — **완료·승인 (2026-06-16)**. `construction/build-and-test/`에 build, unit, integration, performance, contract, security, summary 문서 생성. 로컬 U1 검증 결과(`pytest` **23 passed**, `ruff` pass, CLI smoke `NEW`) 반영. ⚠️ **자동 CI 게이트 없음**(수동 실행만; §검증 재기준선).

### 🟡 OPERATIONS 단계
- [~] Operations — **placeholder 확인 완료 (2026-06-16)**. `operations/operations-placeholder.md` 생성. 현재 룰셋상 배포·모니터링·운영 런북 실행은 future scope이며, 워크플로우는 Build and Test 이후 종료.
- [x] **Operations placeholder — 재인셉션 페이즈 1 / U1 Corpus (2026-06-26)**. 사용자 승인으로 Build and Test 리뷰 게이트를 통과하고 Operations placeholder로 전환. `operations/operations-placeholder.md`를 U1 Corpus 최신 검증 결과(ingestion 129 passed/1 skipped, shared/ops/discovery/summarization/frontend 소비자 검증)와 남은 실제 운영 범위(source provider quota, GROBID capacity, bounded backfill, OpenSearch cutover, monitoring)로 갱신. 현 룰셋상 실행 가능한 Operations 단계는 없으므로 이번 AI-DLC 사이클은 여기서 종료.
- [x] **Operations 하드닝 패스 (2026-06-18, PR #79·#84 → develop, 라이브 배포·검증 완료)** — CONSTRUCTION 종료 후 프로덕션 운영 첫 단계. 산출:
  - [x] **운영 런북** `operations/runbook.md` — 시스템 맵·함정(RETAIN 3종·ALB `/healthz` 서킷브레이커·SSO)·비용가드 강등표·복구절차·SLO 3개.
  - [x] **알림 마지막 1마일** (코드에 존재하나 사람에게 미연결이던 갭): G3 `CLOUDWATCH_NAMESPACE` env로 prod 관측 활성·G2 SES 토픽 ops 구독·G4 CloudWatch 알람(5xx·p95)+G1 AWS Budget($1280) → `OpsAlerts` 토픽/ops 메일. 전부 `compute_stack.py` (synth 검증).
  - [x] **검증(라이브, 2026-06-18, 계정 028317349537)**: `cdk deploy Docsuri-Compute -c ops_alert_email=corpseonthemission@icloud.com` → API 롤링 생존(/healthz 200) · SNS 구독 2개 confirm · **테스트 알람(set-alarm-state ALARM)→이메일 수신 확인** · **RDS 스냅샷→`docsuri-restore-test` 복원 available(DBName=docsuri·pg16.13)→폐기**. Budget는 직접 이메일 구독이라 구성 완료(실 발화는 $1280 도달 시).
  - [x] **G3 IAM 보강** (PR #84): task role에 `cloudwatch:PutMetricData`(namespace 스코프)+`logs:*` + `/docsuri/ops` 로그그룹 retention 30일 선생성. `CLOUDWATCH_NAMESPACE` env만으론 부족(권한 부재→AccessDenied 무성 실패)했던 것 보강.
  - [ ] **G3 잔여(U6 후속)**: 모듈 서비스가 `NoopObservabilityHub`에 emit(`discovery/real_wiring.py:84`·`mocks/wiring.py:56`, "until U6 exposes process-wide singletons") → 정상 트래픽 앱 메트릭이 진짜 hub(→CloudWatch)에 미도달. 게이트웨이 에러 경로만 진짜 hub. 수정=`backend/wiring.py`+모듈 팩토리에 `app.state.observability` 주입(ops 범위 밖). **알림/페이징은 네이티브 ALB 메트릭이라 무관하게 작동.**
  - 천장(의도적 미구현): 앱 내부 cost guard의 per-incident SNS publisher — Budget가 빌링 레벨에서 대체.

## 비고
- 이번 사이클은 클린 재시작이다. 폐기된 사이클 1(U1·U2·U4 데모)은 AWS Bedrock(Claude Haiku), Amazon Comprehend, S3 Vectors 기반 Bedrock Knowledge Base, Amplify 호스팅, Python 백엔드, Next.js 프런트엔드를 사용했다. 그중 어느 선택도 기본 계승하지 않으며 선행 사례(prior art)로만 참조한다.
- 브랜치: `develop` (4 트랙 PR + 후속 크리티컬 패스 ①~⑦ PR 전부 머지 완료). **2026-06-18 기준: CONSTRUCTION 코드·인프라 종결·AWS 프로덕션 배포 완료(§크리티컬 패스 종결). 잔여 = 문서 정합·루트 `tests/` 린트 사각(F401 9건)·Operations 런북 결정.**
## U8 Citation Graph — NFR Requirements Complete / NFR Design In Progress

- Date: 2026-06-21
- Unit: U8 Citation Graph
- Completed: NFR Requirements answers Q1~Q12 all set to recommended option A.
- Completed artifacts:
  - `aidlc-docs/construction/u8-citation-graph/nfr-requirements/nfr-requirements.md`
  - `aidlc-docs/construction/u8-citation-graph/nfr-requirements/tech-stack-decisions.md`
- Next stage entered:
  - `aidlc-docs/construction/plans/u8-citation-graph-nfr-design-plan.md`
- Current gate: U8 NFR Design questions Q1~Q5 awaiting answers.
- Code/FE generated: no.

## U8 Citation Graph — NFR Design Complete / Infrastructure Design In Progress

- Date: 2026-06-21
- Unit: U8 Citation Graph
- Completed: NFR Design answers Q1~Q5 all set to recommended option A.
- Completed artifacts:
  - `aidlc-docs/construction/u8-citation-graph/nfr-design/logical-components.md`
  - `aidlc-docs/construction/u8-citation-graph/nfr-design/patterns.md`
  - `aidlc-docs/construction/u8-citation-graph/nfr-design/runtime-architecture.md`
  - `aidlc-docs/construction/u8-citation-graph/nfr-design/test-strategy.md`
- Next stage entered:
  - `aidlc-docs/construction/plans/u8-citation-graph-infrastructure-design-plan.md`
- Current gate: U8 Infrastructure Design questions Q1~Q3 awaiting answers.
- Code/FE generated: no.

## U8 Citation Graph — Infrastructure Design Complete / Code Generation Plan Ready

- Date: 2026-06-21
- Unit: U8 Citation Graph
- Completed: Infrastructure Design answers Q1~Q3 all set to recommended option A.
- Completed artifacts:
  - `aidlc-docs/construction/u8-citation-graph/infrastructure-design/infrastructure-components.md`
  - `aidlc-docs/construction/u8-citation-graph/infrastructure-design/deployment-topology.md`
  - `aidlc-docs/construction/u8-citation-graph/infrastructure-design/configuration.md`
- Next gate:
  - `aidlc-docs/construction/plans/u8-citation-graph-code-generation-plan.md`
- Current gate: Code Generation approval question awaiting answer.
- Code/FE generated: no.

## U8 Citation Graph — Code Generation and Build/Test Complete

- Date: 2026-06-21
- Unit: U8 Citation Graph
- Completed: Code Generation plan approved as option A.
- Code generated:
  - `backend/modules/citation_graph/__init__.py`
  - `backend/modules/citation_graph/controller.py`
  - `backend/wiring.py`
  - `backend/tests/test_citation_graph.py`
  - `backend/tests/test_app_shell.py`
- Verification:
  - `python -m pytest backend/tests/test_citation_graph.py backend/tests/test_app_shell.py -q` -> 15 passed
  - `python -m pytest backend/tests -q` -> 33 passed, 1 skipped
  - `python -m ruff check backend/modules/citation_graph backend/wiring.py backend/tests/test_citation_graph.py backend/tests/test_app_shell.py` -> pass
  - `python -m compileall backend/modules/citation_graph backend/wiring.py` -> pass
- FE generated: no.
- Current gate: user review/approval, commit, or PR direction required.

## U8 Citation Graph — Cross-Review Follow-up

- Date: 2026-06-22
- Branch: `feature/u8-v1` (branch-name CI prefix compliant)
- Code changes:
  - removed dead `depth` query from citation tree API and cache key
  - kept lazy 2-hop controlled by `expandNodeId`
  - nulls out-of-range library save year values before U4 validation
  - guards telemetry against observability objects without `emit_log`
  - keeps `depthRequested` distinct from `depthReturned`
- Documentation changes:
  - corrected Redis wording: current implementation is process-local in-memory TTL seam; Redis remains production adapter target
- Current gate: user review/approval, commit, or PR direction required.

## U9 Personalization — Requirements Questions Created

- Date: 2026-06-23
- Candidate unit: U9 Personalization / Behavior Intelligence
- Trigger: 사용자 행동 로그를 기록하고 분석해 개인화 맞춤 서비스를 제공하는 기능.
- Created artifact:
  - `aidlc-docs/inception/requirements/requirement-verification-questions-u9-personalization.md`
- Completed: questions Q1~Q20 set to recommended answers (Q13=B, all others A).
- Requirements updated:
  - `aidlc-docs/inception/requirements/requirements.md`
  - Added FR-18 behavior event logging, FR-19 user interest profile, FR-20 personalization application, NFR-P4, QT-7, U9 scope exclusions, traceability.
- Current gate: Requirements review/approval. Next recommended stage: User Stories revision for U9.
- Code generated: no.

## U9 Personalization — User Stories Plan Ready

- Date: 2026-06-23
- Stage: INCEPTION / User Stories Part 1
- Assessment completed:
  - `aidlc-docs/inception/plans/u9-personalization-user-stories-assessment.md`
- Plan created:
  - `aidlc-docs/inception/plans/u9-personalization-story-generation-plan.md`
- Decision: execute User Stories for U9 because the change is user-facing, touches behavior data/privacy controls, and affects search/summary/translation workflows.
- Completed: Story generation plan questions PQ1~PQ6 set to recommended answer A.
- Generated artifacts:
  - `aidlc-docs/inception/user-stories/stories.md`
  - `aidlc-docs/inception/user-stories/personas.md`
- Story update: added Epic 8 Personalization / Behavior Intelligence with US-P1..US-P7; updated persona map and FR/NFR/QT traceability.
- Current gate: User Stories review/approval. Next recommended stage: Units Generation revision for U9.
- Code generated: no.

## U9 Personalization — Units Generation Plan Ready

- Date: 2026-06-23
- Stage: INCEPTION / Units Generation Part 1
- Plan created:
  - `aidlc-docs/inception/plans/u9-personalization-unit-of-work-plan.md`
- Recommended decomposition: add U9 as `backend/modules/personalization/` in the existing API deployment; keep US-P1..P6 Owner=U9 and US-P7 Owner=U6 with U9 as signal source.
- Completed: Unit decomposition questions UQ1~UQ5 set to recommended answer A.
- Updated artifacts:
  - `aidlc-docs/inception/application-design/unit-of-work.md`
  - `aidlc-docs/inception/application-design/unit-of-work-dependency.md`
  - `aidlc-docs/inception/application-design/unit-of-work-story-map.md`
- Unit update: added U9 Personalization as an API module at `backend/modules/personalization/`; story map now covers 40 stories with unassigned=0.
- Current gate: Units Generation review/approval. Next recommended stage: U9 Construction Functional Design.
- Code generated: no.

## U9 Personalization — Functional Design Plan Ready

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 Functional Design Part 1
- Plan created:
  - `aidlc-docs/construction/plans/u9-personalization-functional-design-plan.md`
- Decision: execute Functional Design because U9 introduces behavior event entities, interest profile aggregation rules, user controls, and non-blocking personalization failure rules.
- Completed: Functional Design questions Q1~Q12 set to recommended answer A.
- Generated artifacts:
  - `aidlc-docs/construction/u9-personalization/functional-design/domain-entities.md`
  - `aidlc-docs/construction/u9-personalization/functional-design/business-logic-model.md`
  - `aidlc-docs/construction/u9-personalization/functional-design/business-rules.md`
- Design summary: defined BehaviorEvent envelope, 7 event types, owner-scoped UserInterestProfile, bounded personalization decisions, user controls, fail-open default behavior, and QT-7 property candidates.
- Current gate: Functional Design review/approval. Next recommended stage: U9 NFR Requirements.
- Code generated: no.

## U9 Personalization — NFR Requirements Plan Ready

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 NFR Requirements Part 1
- Plan created:
  - `aidlc-docs/construction/plans/u9-personalization-nfr-requirements-plan.md`
- Decision: execute NFR Requirements because U9 stores user behavior data and must define persistence, privacy, latency, degradation, observability, and QT-7 test boundaries.
- Completed: Q1~Q12 set to recommended answer A after plan_feedback.md correction; Q7 now uses direct active-table delete with no backup table.
- Generated artifacts:
  - `aidlc-docs/construction/u9-personalization/nfr-requirements/nfr-requirements.md`
  - `aidlc-docs/construction/u9-personalization/nfr-requirements/tech-stack-decisions.md`
- NFR summary: existing RDS/backend/U6 reuse, best-effort non-blocking recording, lazy/on-demand aggregation, allowlisted metadata, direct active-table delete with no backup table, scheduled purge requirement, U6 observability, Hypothesis QT-7 tests.
- Current gate: NFR Requirements review/approval. Next recommended stage: U9 NFR Design.
- Code generated: no.

## U9 Personalization — NFR Design Plan Ready

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 NFR Design Part 1
- Plan created:
  - `aidlc-docs/construction/plans/u9-personalization-nfr-design-plan.md`
- Decision: execute NFR Design because U9 needs concrete fail-open, lazy aggregation, active repository, direct delete, retention cleanup, metadata validation, and U6 observability patterns.
- Completed: NFR Design questions Q1~Q5 set to recommended answer A.
- Generated artifacts:
  - `aidlc-docs/construction/u9-personalization/nfr-design/logical-components.md`
  - `aidlc-docs/construction/u9-personalization/nfr-design/nfr-design-patterns.md`
- Design summary: fail-open personalization, bounded profile read, read-through lazy aggregation, direct active-table delete, scheduled idempotent retention cleanup, recorder-level metadata allowlist, and U6 operational telemetry.
- Current gate: NFR Design review/approval. Next recommended stage: U9 Infrastructure Design assessment.
- Code generated: no.

## U9 Personalization — Infrastructure Design Plan Ready

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 Infrastructure Design Part 1
- Plan created:
  - `aidlc-docs/construction/plans/u9-personalization-infrastructure-design-plan.md`
- Decision: execute Infrastructure Design because U9 adds RDS tables, deletion/retention cleanup, API deployment mapping, scheduled maintenance task mapping, and U6 observability integration.
- Recommended direction: reuse existing backend ECS/API deployment, RDS PostgreSQL, U6 gateway/observability, and CloudWatch; avoid a new service, queue, cache, analytics lake, or ML pipeline for v1.
- Current gate: U9 Infrastructure Design questions Q1~Q6 awaiting answers.
- Code generated: no.

## U9 Personalization — Infrastructure Design Complete / Code Generation Plan Next

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 Infrastructure Design
- Feedback applied:
  - `plan_feedback.md`
- Corrected prior design:
  - Removed U9 backup table for raw behavior log deletion.
  - User raw-log deletion now directly deletes owner-scoped active rows.
  - Retention cleanup is an idempotent daily EventBridge scheduled ECS task.
  - Retention purge failure must emit U6 telemetry and trigger alerting.
- Completed: Infrastructure Design questions Q1~Q6 resolved to the revised recommended path.
- Generated artifacts:
  - `aidlc-docs/construction/u9-personalization/infrastructure-design/infrastructure-design.md`
  - `aidlc-docs/construction/u9-personalization/infrastructure-design/deployment-architecture.md`
- Current gate: Infrastructure Design review/approval. Next recommended stage: U9 Code Generation planning.
- Code generated: no.

## U9 Personalization — Code Generation Plan Ready

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 Code Generation Part 1
- Infrastructure Design approval:
  - User requested progress up to just before code generation.
- Plan created:
  - `aidlc-docs/construction/plans/u9-personalization-code-generation-plan.md`
- Planned scope:
  - backend-only U9 module, RDS migrations, app-shell wiring, idempotent retention cleanup command, scheduled ECS cleanup infrastructure, tests, and code summary docs.
- Guardrails:
  - No frontend UI, no queue, no new always-on service, no analytics lake, no ML pipeline, and no `user_behavior_event_backup` table.
- Current gate: Code Generation plan approval. Actual app code has not been generated.
- Code generated: no.

## U9 Personalization — Code Generation Complete

- Date: 2026-06-23
- Stage: CONSTRUCTION / U9 Code Generation
- Completed plan:
  - `aidlc-docs/construction/plans/u9-personalization-code-generation-plan.md`
- Created application code:
  - `backend/modules/personalization/`
  - `backend/modules/personalization/migrations/001_create_personalization_tables.sql`
  - `backend/tests/test_personalization.py`
- Modified application/infrastructure code:
  - `backend/app.py`
  - `backend/migrations/__main__.py`
  - `backend/wiring.py`
  - `backend/tests/test_app_shell.py`
  - `ops/cdk/stacks/compute_stack.py`
- Code summary:
  - `aidlc-docs/construction/u9-personalization/code/summary.md`
- Verification:
  - `python -m pytest backend/tests/test_personalization.py -q` -> 11 passed
  - `python -m ruff check backend/modules/personalization backend/wiring.py backend/app.py backend/migrations/__main__.py backend/tests/test_personalization.py backend/tests/test_app_shell.py ops/cdk/stacks/compute_stack.py` -> pass
  - `python -m compileall backend/modules/personalization backend/wiring.py backend/app.py ops/cdk/stacks/compute_stack.py` -> pass
  - Combined `backend/tests/test_personalization.py backend/tests/test_app_shell.py` attempted but local shell lacks existing `docsuri_shared`, `discovery`, and `docsuri_ops` imports required by pre-existing app-shell assertions.
- Current gate: Code Generation review/approval. Next recommended stage: Build and Test after approval.
- Code generated: yes.

## U9 Personalization — Build and Test Complete

- Date: 2026-06-23
- Stage: CONSTRUCTION / Build and Test
- Build/test documents updated:
  - `aidlc-docs/construction/build-and-test/build-instructions.md`
  - `aidlc-docs/construction/build-and-test/unit-test-instructions.md`
  - `aidlc-docs/construction/build-and-test/integration-test-instructions.md`
  - `aidlc-docs/construction/build-and-test/performance-test-instructions.md`
  - `aidlc-docs/construction/build-and-test/contract-test-instructions.md`
  - `aidlc-docs/construction/build-and-test/security-test-instructions.md`
  - `aidlc-docs/construction/build-and-test/build-and-test-summary.md`
- Verification:
  - `python -m pytest backend/tests/test_personalization.py -q` -> 11 passed
  - `$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'; python -m pytest backend/tests/test_personalization.py backend/tests/test_app_shell.py -q` -> 25 passed
  - `$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'; python -m pytest backend/tests -q` -> 57 passed, 1 skipped
  - `python -m ruff check backend/modules/personalization backend/wiring.py backend/app.py backend/migrations/__main__.py backend/tests/test_personalization.py backend/tests/test_app_shell.py ops/cdk/stacks/compute_stack.py` -> pass
  - `python -m compileall backend/modules/personalization backend/wiring.py backend/app.py ops/cdk/stacks/compute_stack.py` -> pass
  - `python -m pip install -r ops/cdk/requirements.txt` -> pass
  - `$env:JSII_NODE="$env:USERPROFILE\scoop\apps\nodejs-lts\current\node.exe"; cdk synth` from `ops/cdk` -> pass, synthesized to `ops/cdk/cdk.out`
- Current gate: Build and Test review/approval. Next stage per AI-DLC is Operations placeholder.

## Research Agent — Requirements Registered

- Date: 2026-06-24
- Candidate unit: Research Agent (대화형 문헌탐색·근거형성 / 아이디어 novelty); 유닛 번호 미배정 (마이페이지 U10·개인화추천·트렌드/알림·구독제 이후)
- Trigger: 네비바 검색↔마이페이지 사이의 대화형 연구 보조 — 여러 논문 교차확인 근거 정리(모드 A) + 내 주제 기존성 유사논문 비교(모드 B). 설계 입력 `summarization-translation-pipeline.md` line 374.
- Branch / PR: `feature/research-agent` / PR #170 (base develop)
- Created artifact:
  - `aidlc-docs/inception/requirements/requirement-verification-questions-research-agent.md` (인셉션 고도 18문항; 1차 답변 기록)
- Answers: Q5=B(커버리지 확장)·Q7=A(재현성 판정 제외)·Q13=X(전용 네비 메뉴+세션 리스트)·Q14=B(무기한 보관)·Q18=A(Requirements까지만), 나머지 권장.
- Requirements updated:
  - `aidlc-docs/inception/requirements/requirements.md`
  - Added FR-22 (대화형 근거형성, 모드 A, v1), FR-23 (novelty 비교, 모드 B, 다음 사이클), FR-24 (대화형 입력+첨부), FR-25 (결과·세션 영속+전용 진입), NFR-P5, NFR-C1 Agent 보강, QT-8, §12 Agent 카브아웃, C-2 경계, 성공기준 #7, traceability 9 rows.
- Scope boundary: v1 = 모드 A 구현; novelty(모드 B)는 다음 사이클(Q4=A). 생성 산문·재현성 판정 제외(C-2). HOW(코퍼스 확장·외부 API·출력 스키마·근거표 컬럼·모델·멀티턴·네비/세션 UI)는 Construction 라운드로 이월.
- Current gate: Requirements review/approval (PR #170). Next stage (별도 승인): User Stories → Units Generation → Construction.
- Code generated: no.
