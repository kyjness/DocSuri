# u11-research-agent-nfr-design-plan.md — NFR Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → NFR Design (유닛별 루프) · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `u11-research-agent/nfr-requirements/`(nfr-requirements·tech-stack-decisions TD-RA-1~15) · `functional-design/`(BR-RA·INV-U11) · `requirements.md`(NFR-P5·NFR-C1·RES-9/11·SEC) · 아키텍처 게이트 `docmodel-fulltext-index-pivot-plan.md`.
**고도**: 패턴·정책·범위. **수치(타임아웃 ms·TTL·서킷 임계·K 상한·동시성·토큰 캡)·캐시 스토어·배포 타깃·리전은 Infra Design/Code-gen.**
**선례 비교(질문 설계 입력 — 하나만 안 봄)**:
- **U7**(복원력 3계층 저하·캐시우선·스트리밍↔근거화·stateless·보안 방어심층·real-first CI·폴트인젝션)
- **U2**(동기 fail-fast+폴백·**의존성별 독립 서킷**·레이턴시 예산 분해·하이브리드 병렬·공유 캐시/서킷 상태)
- **U3**(Redis 연결 서킷+**fail-closed**·외부 API 복원력[보안우선 vs 가용성우선]·커넥션 풀·점진 지연)
- **U8**(외부 쿼터 카운터·스냅샷 캐시 — 모드 B 차기 참고)

> 본 계획서는 **리뷰 게이트**다. `[Answer]:`가 모두 확정되기 전에 NFR Design 산출물(`nfr-design-patterns.md`·`logical-components.md`)을 만들지 않는다. **본 게이트는 질문만 — 결정은 답변 후.**

---

## 1. 유닛 컨텍스트 (NFR Design 렌즈)

U11 = 온디맨드 **다논문 fan-out** 근거형성. U7/U2와 다른 점: **여러 외부 의존(U2 검색·doc-model·Bedrock·U6)을 한 요청에서 다수 호출**(fan-out) → 의존성별 격리·부분결과·비동기 잡이 핵심. NFR-P5(비-SLA·비차단)라 U2식 "동기 fail-fast"보다 **부분결과·진행상태·bounded 재시도**에 가깝다.

---

## 2. NFR Design 실행 계획 (답변 확정 후, 체크박스)

`aidlc-docs/construction/u11-research-agent/nfr-design/`에 작성:
- [x] **nfr-design-patterns.md** *(생성 완료)* — 복원력(§1 의존성별 격리·저하 4계층·재시도 분리·fan-out 부분실패)·성능(§2 캐시우선·스트리밍↔근거화·bounded 병렬·3밴드)·확장(§3 stateless·쿼터 증폭)·보안(§4 방어심층 표)·배포/폴트인젝션(§5)·추적성.
- [x] **logical-components.md** *(생성 완료)* — 컴포넌트 인벤토리·토폴로지(SQS 잡큐·캐시·의존성별 서킷·U6/U2 어댑터·RDS/S3 스토어)·포트 경계·배포 단위.

---

## 3. 가정 (잘못이면 §4 또는 지적으로 정정)

- **AS-D1**: 수치(타임아웃·TTL·K·동시성·서킷 임계)는 Infra/Code-gen 이연 — 본 단계는 패턴·정책 형태만.
- **AS-D2**: 인증/인가·레이트리밋·근거화·비용 게이트·관측은 U6 위임(포트 소비). U11은 도메인 계층 방어심층만.
- **AS-D3**: 전문 통합 인덱스·eager doc-model·근거화 U6 통일은 아키텍처 게이트 결정 따름(U1/U2/U7/infra 조율).
- **AS-D4**: granularity(GQ1)·랭킹(GQ2)·모드B API는 [열림](실험/차기) — 본 단계 미확정.

---

## 4. 명확화 질문 (`[Answer]:` 태그; 권장안=A, 변경 시 B/C/X+사유)

### A. 복원력 패턴 (Resilience)

#### Q1 — 의존성별 독립 서킷 (U2 1.2 / U3 §1 패턴)
여러 외부 의존(U2 검색·doc-model 빌드/읽기·Bedrock·U6)을 어떻게 격리할까요?

A) **의존성별 독립 격리(서킷/타임아웃/폴백) + 거동 분리(권장)** — '의존성'은 인프라 프리미티브가 아니라 **U11이 직접 호출하는 실패 도메인** 단위:
  - **① 후보 검색**(U2 검색 재사용 — **OpenSearch·질의 임베딩 서킷은 U2 내부 소유**) 장애 → `AbstainDTO`(후보 0·빈 성공 금지). *U11이 공유 인덱스를 U2 API 거치지 않고 직접 질의하면 그땐 OpenSearch가 U11 직접 의존 — U2 API 재사용 vs 직접 질의는 FD Q2에서 NFR/Code 미정.*
  - **② doc-model 읽기**(뒤에 S3/캐시/빌드) 일부 실패 → 해당 논문 제외 `PartialResultDTO`.
  - **③ Bedrock LLM**(추출/교차확인·U6 게이트웨이 경유) → 타임아웃·1회 재시도·서킷 → 기권/부분.
  - **④ U6 근거화·CostGuard** → fail-closed(근거 불가=기권 / 비용 OPEN=`CostDegradedDTO`).
  - **⑤ 세션 스토어(RDS)** → fail-closed(영속 불가 시 명시 실패) · **결과 캐시(Redis)** → 영구 폴백/재생성(U3 Redis 서킷 정신).
  한 의존성 장애가 전체로 전파되지 않음(의존성별 거동 상이).

B) 단일 통합 서킷.  C) 서킷 없이 단순 타임아웃.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q2 — 저하 계층 분리 (U7 1.3 3계층 패턴)
원인이 다른 저하를 어떻게 구분할까요?

A) **4계층 분리(원인·트리거·종단상태·신호)(권장)** — ① 비용 degradeMode(U6 `getBudgetState`→`CostDegradedDTO`·RES-11a) ② 의존성 서킷(Bedrock/검색/doc-model 장애→기권/부분) ③ fan-out 부분실패(일부 논문→`PartialResultDTO`·RES-11c) ④ 근거 부재(코퍼스밖→`AbstainDTO`). 통합 금지(운영 진단 모호).

B) 성공/실패 2계층.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q3 — 재시도 정책 (U7 1.1/1.2 분리)
재시도를 어떻게 둘까요?

A) **분리·bounded(권장)** — Bedrock 호출 장애 재시도(1회·백오프) ≠ 근거화 1차 실패 재시도(1회→그래도 실패 시 항목 기권). 의미·카운트 별개, 폭주 방지. 정당한 코퍼스밖 기권은 재시도 없음.

B) 통합 재시도 N회.  C) 재시도 없음.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q4 — fan-out 부분 실패 (U11 고유 · NFR-P5)
K 논문 중 일부 추출 실패 시?

A) **완료분 부분결과 + degraded 표시(권장)** — 일부 논문 실패해도 성공분으로 `PartialResultDTO`(degraded 소스 명시), 전체 실패 아님. 비차단(INV-U11-5).

B) 하나라도 실패 시 전체 실패.  C) 실패 조용히 누락.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### B. 성능 패턴 (Performance)

#### Q5 — 캐시 우선 (U7 2.1 / U2 2.2 패턴)
`AgentCacheKey` 캐시 전략은?

A) **read-through(Redis 핫→영구) + write-through, HIT=LLM 0콜(권장)** — 키 immutable, 버전(코퍼스/모델/프롬프트) 변경=신규 객체(stale 없음). 단일-턴 분석만.

B) 캐시 없음.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q6 — 스트리밍 ↔ 근거화 (U7 2.2 패턴 · FR-5)
부분결과 스트리밍과 날조 0를 어떻게 양립?

A) **버퍼-검증-스트리밍(권장)** — 논문별/항목별 근거화 통과분부터 점진 노출, 미통과 토큰 유출 0(FR-5 우선). 내부 스트리밍은 liveness·진행상태용.

B) 검증 전 전체 스트리밍.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q7 — bounded 병렬 fan-out (U2 2.3 병렬 + U7 2.3 async)
K 논문 추출을 어떻게?

A) **async I/O + bounded 동시성 병렬(권장)** — 논문별 추출을 동시 실행하되 상한(동시성·K)으로 Bedrock 쿼터·비용 폭주 방지. 수치는 Infra.

B) 순차 처리.  C) 무제한 병렬.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q8 — sync ↔ async 잡 라우팅 (U7 TD-S9 3밴드)
긴 분석을 어떻게 분기?

A) **3밴드(권장)** — 소규모(동기 스트리밍) / 대규모(SQS 비동기 잡·폴링→캐시 히트) / OVER_CAP(거절·안내). 게이트웨이 타임아웃 회피. 임계 수치는 Infra/튜닝.

B) 항상 동기.  C) 항상 비동기.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### C. 확장성 패턴 (Scalability)

#### Q9 — stateless + 공유 상태 (U7 3.1 / U2 3.1)
확장 모델은?

A) **stateless 모듈 + 공유 외부 상태(권장)** — 대화/세션 상태=RDS, 결과 캐시=Redis+영구, 서킷 상태 공유(인스턴스 간 일관). backend 인스턴스 수평 복제. 비동기 워커 별도 스케일.

B) 인스턴스 로컬 상태.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q10 — fan-out의 Bedrock 쿼터 증폭 (U7 3.2 / U2 RES-8)
fan-out이 쿼터를 압박하면?

A) **bounded 동시성 + ThrottlingException 백오프/큐잉 → 부분/기권(권장)** — fan-out은 단건의 K배 호출이므로 동시성 상한·비동기 잡으로 흡수. 쿼터·오토스케일 수치는 Infra.

B) 무제한.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### D. 보안 패턴 (Security · 방어심층)

#### Q11 — 보안 계층 분리 (U7 §4 / U2 4.1 / U3 표 패턴)
방어심층을 어떻게 배치?

A) **계층 표(권장)** — 진입(첨부 무해화·형식/크기 검증 SEC-5) · `AttachmentIngestor`/추출 입력(본문 격리 `[지시]┃[데이터]` injection 방어) · 출력(SEC-9 비노출: 캐시키·모델/프롬프트·raw 점수·자산 픽셀) · owner-scope(세션/결과/첨부 SEC-8) · 자산 서명 URL(SEC-9/12) · 전역 예외 fail-closed(SEC-15) · 로깅 PII 차단(SEC-3) · 위임(authn/레이트리밋=U6).

B) 일부만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### E. 논리 컴포넌트 (Logical Components)

#### Q12 — 인프라 컴포넌트 토폴로지
어떤 논리 컴포넌트로?

A) **권장 세트** — API 라우터(스트리밍/폴링) · `AgentOrchestrator` · 의존성별 서킷(검색/doc-model/Bedrock) · 결과 캐시(Redis+영구) · **SQS 비동기 잡 큐 + Agent 워커** · `AgentGroundingAdapter`(U6 통일 계약) · `AgentCostGuardAdapter`(U6) · `AgentTelemetryPublisher`(U6 Hub) · `ResearchResultStore`(RDS) · `AttachmentStore`(S3) · `MultiPaperRetriever`(U2). 토폴로지=`logical-components.md`.

B) 큐 없이 동기만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### F. 배포 · 복원력 테스트

#### Q13 — CI 레인 (U7 5.1 / U2 5.1 real-first)
CI 구성은?

A) **real-first 레인(권장)** — 항상: 단위(pytest 테스트 Fixture/Stub + Hypothesis PBT-RA1~6) + ruff + shared 드리프트 가드. 별도 게이트: 통합(실 U2/doc-model/Bedrock/RDS/Redis/S3) — 자격증명(Infra). 비동기 워커·프런트(`u11-research-agent-frontend`) 별도. **조율 존(wiring/게이트웨이)=app-shell 사인오프.**

B) 통합만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

#### Q14 — 복원력 폴트 인젝션 (U7 5.2 / U2 5.2 · RES-12)
어떤 장애를 주입·검증?

A) **권장 스위트** — U2 검색 장애→Abstain · doc-model 일부 장애→Partial · Bedrock 타임아웃/스로틀→재시도/기권 · 비용 OPEN→CostDegraded · 근거화 실패→1회 재시도→항목 기권 · injection 첨부→본문 격리 · fan-out 부분 실패→Partial. 실행=Build&Test/Operations(QT-8/RES-11 연동).

B) 일부만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

---

## 5. 다음 절차
1. **Q1~Q14 답변 확정 완료**(2026-06-24 — 전부 A; Q1 의존성 경계 정밀화 반영).
2. **산출물 생성 완료**: `nfr-design-patterns.md`·`logical-components.md`.
3. **리뷰 게이트** — 사용자 검토 후 **Infrastructure Design**(타임아웃·TTL·K·서킷 임계·동시성·리전·IaC·배포·비용표) → Code Generation.
4. granularity(GQ1)·랭킹(GQ2)·수치는 Infra/실험으로 이연.
5. 아키텍처 게이트(전문 인덱스·eager doc-model·근거화 통일)는 U1/U2/U7/infra 조율·별도 승인.
