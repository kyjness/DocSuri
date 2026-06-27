# u11-research-agent-nfr-requirements-plan.md — NFR Requirements 계획 + 질문 게이트

**단계**: CONSTRUCTION → NFR Requirements (유닛별 루프) · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `requirements.md`(NFR-P5·NFR-C1 Agent·QT-8·SEC-5/8/11·RES-9/11), `u11-research-agent/functional-design/`(domain-entities·business-logic-model·business-rules), `plans/u11-research-agent-functional-design-plan.md`(Q1~Q17), `plans/docmodel-fulltext-index-pivot-plan.md`(DF-1~6·GQ1/GQ2).
**원칙**: 본 단계는 NFR(성능·확장·가용·보안·신뢰·운영·테스트) + 기술 스택을 정한다. **실험으로 정할 것(granularity GQ1·랭킹 GQ2)은 권장/후보로 열어두고 확정하지 않는다.**

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 NFR 산출물(`nfr-requirements.md`, `tech-stack-decisions.md`)을 만들지 않는다.

---

## 1. NFR 렌즈 (U11 관점)

> **선례 참고(질문 설계 입력)**: U7(LLM 모델 바인딩·비용 라인·캐시 2단·Bedrock 스트리밍·비동기 잡·real-first 테스트), U2(의존성 격리·degradeMode·레이턴시 예산 분해·mock-first 병렬 개발), U3(RDS/Redis·보안 처분), U8(shared DTO 승격·쿼터). 아래 렌즈·질문은 이 선례들을 비교해 도출. **본 게이트는 질문만 — 결정은 답변 후 산출물에서.**

- **성능(NFR-P5)**: 온디맨드·비-SLA·비차단. 다논문 분석은 수 초~분 → 진행상태·부분결과. 검색 SLA(NFR-P1) 비대상. (U7 스트리밍 TTFB·U2 예산 분해 관점)
- **비용(NFR-C1)**: 다논문 LLM 호출 신규 라인 → 기존 $1,600 상한 내 흡수·별도 계상, U6 CostGuard 재사용, 캐시로 중복 차단. (U7 비용 라인 패턴)
- **보안(SEC-5/8/11)**: 로그인·owner-scope, 첨부 무해화·injection 격리, 레이트리밋. (U7 본문 격리·U3 owner 격리)
- **신뢰(RES-9/11)**: 의존성별 타임아웃·재시도·서킷·부분결과 저하, AI 인시던트(비용폭발·할루시네이션·반쪽결과) 탐지. (U2 의존성 격리/degrade 패턴)
- **운영(QT-8/NFR-O1)**: 모드별 호출·지연·기권/저하·비용 텔레메트리(U6 ObservabilityHub). (U2/U7 단일 수집)
- **테스트·병렬개발**: real-first(U7) vs mock-first(U2) 전략 + QT-8 PBT(기권 안정성·DTO roundtrip·owner isolation·캐시·부분결과·출처유효성).

---

## 2. NFR Requirements 실행 계획 (답변 확정 후 수행)

`aidlc-docs/construction/u11-research-agent/nfr-requirements/`에 작성:
- [x] **nfr-requirements.md** *(생성 완료)* — 컨텍스트·성능(NFR-P5)·확장·가용/신뢰(의존성 격리·부분결과)·비용(CostGuard·캐시)·보안표·관측(RES-11)·테스트(real-first·PBT-RA1~6)·추적성(미커버 0).
- [x] **tech-stack-decisions.md** *(생성 완료)* — TD-RA-1~15 ADR(전역 계승 + Sonnet 추출·Bedrock 스트리밍·RDS 세션·S3 첨부·Redis+영구 2단·SQS 비동기 잡·U2 재사용·U6 근거화 통일·real-first·shared DTO 승격). granularity(GQ1)·랭킹(GQ2)·모드B API는 [열림].

---

## 3. 가정 — 전역 계승 (기존 시스템 결정 재사용)

- **AS-N1**: Python·FastAPI(app-shell)·**OpenSearch**·**Bedrock + Cohere**·**RDS PostgreSQL**·**ElastiCache Redis**·**S3**·EventBridge·**Hypothesis**(PBT)·NFR-C1 $1,600 상한 — 전역 계승.
- **AS-N2**: U6 게이트웨이(authn/authz/rate-limit)·`getBudgetState`·근거화 공유 계약·ObservabilityHub 재사용.
- **AS-N3**: doc-model eager·전문 통합 인덱스·근거화 U6 통일은 **아키텍처 게이트(`docmodel-fulltext-index-pivot`) 결정**을 따른다(U1/U2/U7/infra 조율).
- **AS-N4**: 긴 분석 비동기 잡은 **U7 잡 패턴 재사용**.

---

## 4. 명확화 질문 (`[Answer]:` 태그로 답변; 권장안=A)

### Q1 — LLM 모델 (게이트웨이 재사용)
근거 추출·교차확인에 어떤 모델을?

A) **추출=Sonnet·교차확인 정렬=Sonnet/Haiku 혼합(권장)** — U7과 동일 Bedrock 게이트웨이 재사용. 추출은 충실도 중요(Sonnet), 단순 정렬·포맷은 Haiku 가능. 구체 배분은 평가.

B) 전부 Sonnet.  C) 전부 Haiku.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q2 — 동기 스트리밍 vs 비동기 잡 분기 (NFR-P5)
언제 동기 스트리밍, 언제 비동기 잡?

A) **기본 동기 스트리밍 + 임계 초과 시 비동기 잡(권장)** — 후보 수·예상 토큰이 임계 초과(예: K가 크거나 장문 다수)면 비동기 잡(폴링), 그 외 스트리밍. 임계 수치는 NFR Design.

B) 항상 동기.  C) 항상 비동기 잡.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q3 — 스트리밍 전송 방식
진행상태·부분결과 전송은?

A) **SSE(서버센트이벤트) 우선 + 폴백 폴링(권장)** — 점진 렌더·진행상태. 긴 잡은 폴링(getResult). 구체는 NFR Design.

B) 폴링만.  C) WebSocket.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q4 — 세션·결과 저장소
세션·턴·근거표 영속은?

A) **RDS PostgreSQL(권장)** — owner-scoped 관계 데이터(세션·턴·결과 메타). 큰 근거표 본문은 RDS JSONB 또는 S3 참조(NFR Design). 전역 RDS 재사용.

B) S3만.  C) 별도 DB.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q5 — 첨부 원본 저장 + 한도
첨부 보관·제한은?

A) **S3(owner-scoped, SSE-KMS) + 형식/크기 한도(권장)** — 허용 형식(PDF/텍스트 등)·최대 크기 제한, 무해화 후 doc-model 파싱. 무기한 보관 + 삭제 제어(Q12 FD). 구체 한도는 NFR Design.

B) RDS BLOB.  C) 미보관(즉시 폐기).  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q6 — 캐시 백엔드
`AgentCacheKey` 캐시는?

A) **Redis 핫 + RDS/S3 영구 2단(권장, U7 패턴)** — 단일 턴 다논문 분석 결과 캐시. 키 immutable, 버전 변경 무효화.

B) Redis만.  C) 캐시 안 함.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q7 — 후보 K 상한 + 복원력 (RES-9)
다논문 fan-out 한도·장애 처리는?

A) **bounded K(상한) + 논문별 타임아웃·재시도(백오프)·서킷 → 부분결과 저하(권장)** — 일부 추출 실패 시 부분 결과(degraded 표시), 전체 실패 아님. K·타임아웃 수치는 NFR Design.

B) K 무제한.  C) 하나 실패 시 전체 실패.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q8 — 인덱스 granularity (GQ1) — **확정 아님**
전문 인덱스 단위는?

A) **열어둠 — document/section/block dense(+lexical) 후보, 평가(recall·비용)로 결정(권장)**. NFR엔 후보·평가 계획만 기록, 특정 안 미확정. block_id locator는 granularity 종속 옵션.

B) 지금 block dense 확정.  C) 지금 section dense 확정.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q9 — 랭킹 전략 (GQ2) — **확정 아님**
title/abstract/body boost는?

A) **열어둠 — 필드별 boost·U2/U11 랭킹 프로파일 공유·질의유형(topic/passage)별을 후보로, 실험 결정(권장)**. NFR엔 평가 계획만.

B) 지금 가중치 확정.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q10 — 비용 분해 + CostGuard (NFR-C1)
Agent 비용 통제는?

A) **U6 CostGuard/`getBudgetState` 재사용 + Agent 별도 텔레메트리 라인 + 캐시 중복 차단(권장)** — 임계 초과 시 일시 기권(CostDegraded). 기존 상한 내 흡수.

B) Agent 자체 카운터.  C) 비용 통제 없음.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q11 — 보안 (SEC-5/8/11)
보안 NFR은?

A) **owner-scope 강제 + 첨부 무해화·본문 격리(injection) + 레이트리밋 + 서명 URL 자산(권장)** — 전역 보안 계층 재사용. doc-model 자산 픽셀 비노출(SEC-9).

B) 일부만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q12 — 운영 관측성 (QT-8/NFR-O1/RES-11)
무엇을 관측?

A) **모드별 호출 수·처리시간·기권/저하 비율·외부 의존 오류율·비용 라인 → U6 ObservabilityHub(권장)** — AI 인시던트(비용폭발·할루시네이션·반쪽결과) 탐지·경보(RES-11 a/b/c).

B) 비용만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q13 — 테스트 전략 + PBT
QT-8 검증은?

A) **Hypothesis PBT(QT-8 6종) + 결정적 근거화 체크 + 평가셋(OP/팀)(권장)** — 기권 안정성·DTO roundtrip·owner isolation·캐시·부분결과·출처유효성. 전역 PBT Partial 모드 유지.

B) 예시 테스트만.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q14 — 외부 학술 API (모드 B)
모드 B 커버리지 확장은?

A) **NFR에 미확정·차기 이월(권장)** — 모드 B는 v1 미빌드(Q4=A). 외부 API 선택·쿼터·캐시(U8 패턴)는 차기 사이클. NFR엔 seam만.

B) 지금 외부 API 선정.  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q15 — 테스트·병렬개발 전략 (U7 real-first ↔ U2 mock-first)
출하 코드에 mock 어댑터를 둘까요? 프런트(`u11-research-agent-frontend`)·타 유닛 병렬 개발은?

A) **real-first(U7 방식, 권장)** — 출하 코드는 포트 + 실 어댑터 단일본(production mock 미구현). 단위 테스트만 테스트 전용 Fixture/Stub + Hypothesis PBT, 통합은 실 의존성.

B) **mock-first(U2 방식)** — 포트 + mock/real 2구현·환경 토글. 프런트·의존 유닛이 mock으로 병렬 개발, 계약 불변 스왑.

C) 혼합(핵심 경로 real-first + 프런트 계약용 mock 픽스처만).  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

### Q16 — shared DTO 계약 승격 (U7/U8 선례)
`research_agent` DTO(AgentResponse 5종 union·EvidenceTable·세션 등)를 어떻게 둘까요?

A) **`shared/dtos/research_agent`로 승격(PROVISIONAL) + 별도 shared PR(권장)** — U4/U7 선례. 프런트·U6 근거화 계약 정합·드리프트 가드 대상.

B) U11 모듈 내부에만 둔다(공유 안 함).  X) 기타.

[Answer]: **A** *(2026-06-24 — 전부 A)*

---

## 5. 다음 절차
1. **Q1~Q16 답변 확정 완료**(2026-06-24 — 전부 A).
2. **산출물 생성 완료**: `nfr-requirements.md`·`tech-stack-decisions.md`.
3. **리뷰 게이트** — 사용자 검토 후 **NFR Design**(서킷·캐시·스케일·저하 패턴 수치) → Infrastructure Design → Code Generation.
4. granularity(GQ1)·랭킹(GQ2)·K/임계·모드 B API는 실험/NFR Design/차기로 열어둠.
5. 전문 인덱스·eager doc-model·근거화 통일(아키텍처 게이트)은 U1/U2/U7/infra 조율·별도 승인.
