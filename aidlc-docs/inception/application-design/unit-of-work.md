# unit-of-work.md — 유닛 정의 (Units of Work)

**단계**: INCEPTION → Units Generation · **일자**: 2026-06-15
**근거**: `application-design/`(U1~U6), UQ1=A(6 유닛), UQ2=A(모노레포), UQ3=A(4 배포 단위), UQ4=A(데모 우선), UQ5=A(공유 계약 `shared/`). 2026-06-26 U1 Corpus 리뷰: 신규 유닛 없이 기존 U1 확장.
**정의**: 유닛 = 개발용 스토리 논리 묶음. 모듈형 모놀리스(DQ1)이므로 일부 유닛은 한 배포 단위(API) 내 **모듈**, 일부는 **독립 배포**(워커·프런트).

---

## 유닛 정의

| 유닛 | 책임 | 유형 | 배포 단위 | 코드 위치 | 경로 종류 |
|---|---|---|---|---|---|
| **U1 Ingestion** | arXiv·Semantic Scholar·OpenAlex AI/ML 논문 수집 → FullText → eager DocModel → DocModel Block 청크·임베딩 → 공유 Corpus 인덱스/OpenSearch·S3 생성·갱신(단일 writer) | 독립 워커 | ② 인제스천 워커 | `ingestion/` | 이벤트/스케줄 |
| **U2 Discovery** | 자연어 질의 동기 검색 읽기 경로(질의 이해·하이브리드 검색·랭킹·근거화 어댑팅·결과 조립) | API 모듈 | ① API | `backend/modules/discovery/` | 동기 REST |
| **U3 Accounts/Auth** | 가입/로그인/세션·자격증명·**객체 소유권 인가 단일 결정점** | API 모듈 | ① API | `backend/modules/accounts/` | 동기 REST(+이벤트 신호) |
| **U4 Library** | 검색 저장·라이브러리·이력(소유자 비공개) | API 모듈 | ① API | `backend/modules/library/` | 동기 CRUD(+이력 이벤트 소비) |
| **U5 Frontend** | SSR 폰 우선 웹 UI(검색·결과·계정·라이브러리·상태; 폰 목업 프레임) | 독립 프런트 | ④ 프런트엔드 | `frontend/` | 동기 REST(클라이언트) |
| **U6 Reliability/Ops** | DQ5 횡단 미들웨어/게이트웨이(API 내) + 운영 워커(탐지·대시보드) | 미들웨어 + 워커 | ① API(게이트웨이) · ③ Ops 워커(탐지·대시보드) | `backend/middleware/` · `ops/` | 동기 게이트 + 이벤트 백본 |
| **U7 Summarization** *(2026-06-18 편입)* | 검색된 단일 논문의 온디맨드 요약(Sonnet)·초록 번역(Haiku)·개인화(persona/뷰/용어집); 근거 앵커·기권; 영구저장(S3)+핫캐시(Redis) | API 모듈(+초장문 비동기 잡 옵션) | ① API (+③ 비동기 잡 옵션) | `backend/modules/summarization/` | 동기 REST(스트리밍) + 이벤트(관측/비용) |
| **U8 Citation Graph** *(2026-06-19 편입)* | 논문 상세보기의 backward references 각주 트리; ID 해소·unresolved 분리·깊이/노드 상한·라이브러리 저장 연동; 외부 citation API 캐시/저하 | API 모듈 | ① API | `backend/modules/citation_graph/` | 동기 REST + 캐시 + 관측 이벤트 |
| **U9 Personalization** *(2026-06-23 편입)* | 의미 있는 사용자 행동 이벤트 기록, 관심 프로필 집계, 개인화 설정/삭제/초기화, 검색·요약·번역 기본값 개인화 제공 | API 모듈 | ① API | `backend/modules/personalization/` | 동기 REST + 비차단 이벤트 기록 |
| **U11 Evidence Agent** *(2026-06-29 편입 — 재인셉션 Phase 4 / requirements "[U4]")* | 로그인 필수 대화형 다논문 문헌탐색·근거형성 Agent. 사용자 질의/첨부에 대해 여러 논문을 교차확인해 핵심 주장·방법·결과 수치·한계를 추출·비교하고 쟁점 오버레이로 제시; 근거 없으면 기권(FR-5). 세션·결과 owner-scoped 영속. EvidenceFormationPort(D5)를 통해 U12(연구아이디어 Agent, 미래)에 Tool로 노출 | API 모듈 (+비동기 잡 옵션) | ① API (+③ 잡 옵션) | `backend/modules/evidence_agent/` | 동기 REST(SSE 스트리밍) + 비동기 잡 (장분석) |
> **U6 분할 주석**: U6는 두 곳에 산다 — (a) **게이트웨이 미들웨어**(authn/authz·검증·레이트리밋·비용 상태·근거화 강제 후크)는 API 배포 단위 ① 내부, (b) **Ops 워커**(AI 인시던트 탐지기·대시보드)는 이벤트 백본 소비 독립 워커 ③.

> **U7 주석 (요약/번역)**: U7은 결과 카드의 **온디맨드 보조 기능**(검색 SLA NFR-P1 비대상, NFR-P2). U6 게이트웨이를 단일 진입으로 도달하며, **U1 DocModel/FullText(S3 read = capability)·U6 근거화 후크/비용 게이트(`shared/ports` lib)에 의존**한다(U2와 동일 패턴 — 코드 순환 없음). LLM 호출은 U2 검색과 별개 경로. 대부분 단일 콜 동기 스트리밍, **초장문(map-reduce)만 비동기 잡**(배포 ③). 산출물은 S3 영구 + Redis 핫캐시(키 immutable, 논문당 평생 1회 생성).

> **U8 주석 (인용 그래프/각주 트리)**: U8은 논문 상세보기 페이지에서 호출되는 **로그인 필수 온디맨드 읽기 경로**다. v1은 backward references만 다루며 forward citations·3-hop 이상·FE 구현은 제외한다. 외부 citation API(Semantic Scholar 우선)는 온디맨드 조회 + 7일 snapshot 캐시로 감싼다. 노드 저장은 U4 Library 계약을 재사용한다.

> **U9 주석 (개인화/행동 인텔리전스)**: U9는 사용자별 원시 행동 이벤트와 집계 관심 프로필을 소유한다. v1은 검색 결과의 작은 boost/rerank와 요약/번역 기본값 제안만 다루며, 별도 추천 목록·전체 클릭스트림·hover/scroll 추적·강한 리랭크·실시간 ML 추천 파이프라인은 제외한다. U9 실패는 U2/U4/U7 본 기능을 막지 않는 비차단 저하로 처리한다.

> **U10 자리 주석**: U10 = **마이페이지**(타 팀원 구현 중, 커밋/푸시 전 — 본 문서 미반영). 마이페이지의 책임 정의는 해당 팀원 작업이 머지될 때 본 문서에 반영한다(여기서 발명하지 않음).
>
> **U11 주석 (문헌탐색·근거형성 Agent)**: U11 = 재인셉션 차터 페이즈 4(requirements "[U4]"). LLM Agent가 Search·DocModel·Summary 도구를 자율 오케스트레이션해 다논문 근거를 형성한다. 스트리밍 우선(NFR-P6), 긴 분석은 비동기 잡 옵션(U7 패턴 재사용). EvidenceFormationPort 단일 구현자(D5 계약 게이트) — U12(연구아이디어 Agent, 미래)가 소비. U11 실패는 본 유닛 응답만 영향(U2/U4/U7/U9 비차단).
>
> **연구 에이전트 번호 재부여 완료(2026-06-29)**: 구 통합 "U11 Research Agent"는 폐기되고 **U11(문헌탐색·근거형성) / U12(연구아이디어, 미래)**로 분리 확정(재인셉션 차터 §4). U11은 본 문서에 정의. U12는 U11 Application Design 완료 후 별도 인셉션 사이클 진행.

## 배포 단위 (UQ3=A)
1. **API 서비스** — U2 + U3 + U4 + **U7 + U8 + U9 + U11** + U6 게이트웨이 미들웨어 (동기 REST, 모듈형 모놀리스)
2. **인제스천 워커** — U1 (이벤트/스케줄)
3. **Ops/탐지 워커** — U6 탐지기·대시보드 (이벤트 백본) **(+ U7 초장문 요약 비동기 잡 옵션)**
4. **프런트엔드** — U5 (SSR)

공유 capability(기술 미확정): Corpus/OpenSearch 인덱스, DocModel/FullText 오브젝트 스토리지, GROBID 런타임, 관리형 DB/영속화, 이벤트 버스/백본, 임베딩/LLM 게이트웨이, DLQ. **(U7 추가 활용: 오브젝트 스토리지[DocModel/FullText read + 요약 영구저장]·핫캐시[Redis]·LLM 게이트웨이[Sonnet/Haiku]. U8 추가 활용: citation snapshot 캐시/스토어·외부 citation API 쿼터 카운터. U9 추가 활용: 사용자 행동 이벤트/관심 프로필 RDS 테이블.)**

## 코드 조직 전략 (Greenfield, UQ2=A 모노레포)
```text
<repo-root>/
├── frontend/                # U5 — SSR 폰 우선 웹 (배포 ④)
├── backend/                 # 배포 ① API (모듈형 모놀리스)
│   ├── modules/
│   │   ├── discovery/       # U2
│   │   ├── accounts/        # U3
│   │   ├── library/         # U4
│   │   ├── summarization/   # U7 — 요약/번역(온디맨드, Sonnet/Haiku)
│   │   ├── citation_graph/  # U8 — 각주 트리/backward references
│   │   └── personalization/ # U9 — 행동 이벤트/관심 프로필/개인화 설정
│   └── middleware/          # U6 게이트웨이(authn/authz·검증·레이트리밋·비용·근거화 후크)
├── ingestion/               # U1 — 인제스천 워커 (배포 ②)
├── ops/                     # U6 — 탐지기·대시보드 워커 (배포 ③)
└── shared/                  # UQ5=A 공유 계약 단일 소유
    ├── vector-spec          # 임베딩 스키마(U1 writer ↔ U2 reader 동일 공간 불변식)
    ├── dtos                 # 결과/카드/계정/라이브러리 DTO
    ├── events               # 이벤트 스키마(SearchExecuted, AI 인시던트)
    └── ports                # 횡단 후크 인터페이스(근거화·비용) — 의존성 역전(코드 순환 방지)
```
구체 언어·프레임워크·런타임은 **NFR Requirements/Construction**에서 확정(이전 사이클 Python 백엔드 + Next.js 프런트는 선행 사례).

## 빌드/개발 순서 (병렬화 조율 반영 - 2026-06-16)
개발 기간 단축을 위해 `shared/` 공용 규약을 선행 작성한 뒤, 아래와 같이 3개 독립 트랙으로 병렬 개발을 진행합니다.

* **준비 단계**: `shared/` 규약 고정 (`vector-spec` 및 API DTO, 이벤트 스펙 선행 작성)
* **[트랙 1] 데이터 파이프라인**: **U1 Ingestion** (멀티소스 Corpus 인제스천 워커) ──> **U6 Reliability/Ops** (비동기 탐지 워커)
* **[트랙 2] 인증 및 사용자 데이터**: **U3 Accounts** (가입/로그인) ──> **U4 Library** (저장/라이브러리)
* **[트랙 3] 사용자 검색 및 UI**: **U2 Discovery** (Mock API 기반 선행 개발) ──> **U5 Frontend** (UI 화면 및 인터랙션)
* **[확장 / 2026-06-18] 요약·번역**: **U7 Summarization** — 코어(U1~U6) 빌드·배포 완료 후 편입되는 신규 유닛. **선행 의존**: U1(DocModel/FullText S3 capability)·U6(근거화 후크·CostGuard)·shared(DTO·ports) = 이미 가용. 결과 카드 표면은 U2/U5와 연결. 단일 트랙으로 CONSTRUCTION 유닛 루프 진행(**실배포 기준 real-first 구현** — LLM·스토어 어댑터는 포트 뒤 실 구현 단일본[Bedrock·S3·Redis], mock/인메모리 대역 없음. _2026-06-18 U7 FD 답변 Q10/Q11로 확정._).
* **[확장 / 2026-06-19] 인용 그래프·각주 트리**: **U8 Citation Graph** — 논문 상세보기 페이지의 4개 액션 중 각주 트리 API를 제공한다. **선행 의존**: U3/U6(로그인·게이트웨이), U4(라이브러리 저장 계약), U5/상세보기 분기(FE 표면), shared(DTO·events). Requirements/User Stories/Units Generation까지만 진행하고, Construction은 별도 승인 후 시작한다.
* **[확장 / 2026-06-23] 개인화/행동 인텔리전스**: **U9 Personalization** — 행동 이벤트와 관심 프로필을 소유하는 API 모듈. **선행 의존**: U3/U6(로그인·게이트웨이), U2(검색 결과 개인화), U4(라이브러리 신호), U7(요약/번역 기본값), U5(설정/표시), shared(DTO·events). Construction은 U9 단일 유닛 루프로 진행한다.
* **[확장 / 2026-06-24 → 2026-06-28 재구성] 연구 에이전트**: 구 통합 "U11 Research Agent"는 폐기되고 **문헌탐색·근거형성 / 연구아이디어 2개 유닛으로 분리**(재인셉션 차터 §4). 유닛 번호·경계·선행 의존(2유닛 간 의존 포함)은 **신규 인셉션 사이클의 units-generation에서 재부여**한다.

> 각 유닛은 CONSTRUCTION의 유닛별 루프(Functional/NFR/Infra Design → Code Generation)로 진행한다.
