# u9-personalization-nfr-requirements-plan.md — NFR Requirements 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Requirements (유닛별 루프)  
**유닛**: U9 Personalization  
**일자**: 2026-06-23  
**근거**: `construction/u9-personalization/functional-design/`, `requirements.md`(FR-18~20, NFR-P4, QT-7), `unit-of-work.md`(U9), `unit-of-work-dependency.md`(U2/U4/U7/U5 -> U9, U9 -> U3/U6/shared)

**원칙**: U9는 새 서비스나 ML 파이프라인을 만들지 않는다. 기존 backend API, RDS, U6 observability, shared DTO/events를 재사용하고, U9 실패는 기본 비개인화 경로로 저하한다.

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 NFR 산출물(`nfr-requirements.md`, `tech-stack-decisions.md`)을 만들지 않는다.

---

## 1. NFR 렌즈

- **성능**: 행동 이벤트 기록은 caller 본 요청을 지연시키지 않는다. 개인화 조회 실패 시 기본값으로 즉시 저하한다.
- **확장성**: v1은 사용자 수백~저천 명, 의미 이벤트만 기록, 90일 raw retention 전제.
- **가용성**: U9 저장/조회/집계 실패는 검색/요약/번역/라이브러리 실패로 승격하지 않는다.
- **보안/프라이버시**: owner-scoped, metadata allowlist, raw content/token 비저장, delete/reset 제어.
- **운영**: U6 관측으로 기록 실패율, 집계 실패율, 폴백 수를 emit한다.
- **테스트**: QT-7 DTO roundtrip, dedupe, owner isolation, delete/reset, deterministic aggregation.

## 2. NFR Requirements 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u9-personalization/nfr-requirements/`에 작성한다.

- [x] **nfr-requirements.md**
  - performance/degradation requirements
  - security/privacy requirements
  - retention/delete/reset requirements
  - observability requirements
  - QT-7 test requirements
- [x] **tech-stack-decisions.md**
  - API/runtime placement
  - persistence choice
  - event/profile schema ownership
  - async/degradation handling
  - test stack and CI boundary

---

## 3. 명확화 질문

### Q1 — Persistence
U9 raw events와 interest profile은 어디에 저장할까요?

A) **기존 RDS Postgres에 U9 전용 테이블로 저장(권장)** — `user_behavior_events`, `user_interest_profile`, `personalization_settings`를 owner-scoped로 둔다. 새 DB/서비스는 만들지 않는다.

B) Redis에 저장한다.

C) OpenSearch에 저장한다.

X) 기타.

[Answer]: A

### Q2 — API Runtime
U9 API는 어디에 붙일까요?

A) **기존 backend FastAPI app-shell 모듈로 붙인다(권장)** — `backend/modules/personalization/`, U6 게이트웨이 경유, 별도 ECS service 없음.

B) 별도 API service로 분리한다.

X) 기타.

[Answer]: A

### Q3 — Event Recording Latency
이벤트 기록이 본 요청 latency에 미치는 영향은?

A) **best-effort 비차단(권장)** — 가능하면 요청 말미에 짧게 기록하되 실패/timeout은 본 요청 실패로 만들지 않는다.

B) 이벤트 기록 성공을 본 요청 성공 조건으로 삼는다.

C) 항상 별도 큐에만 넣고 API에서는 전혀 기록하지 않는다.

X) 기타.

[Answer]: A

### Q4 — Profile Aggregation Trigger
관심 프로필 집계는 어떻게 실행할까요?

A) **가벼운 lazy/on-demand 집계 + 필요 시 배치 보정(권장)** — 프로필 조회 시 stale이면 재집계하고, 배치 워커는 추후 필요할 때만 추가한다.

B) 모든 이벤트 기록마다 즉시 전체 재집계한다.

C) 실시간 ML pipeline을 만든다.

X) 기타.

[Answer]: A

### Q5 — Retention Enforcement
raw event 90일 보관은 어떻게 강제할까요?

A) **RDS timestamp 기준 purge job 또는 query filter로 강제(권장)** — Code/Infra에서 단순 scheduled cleanup을 둔다.

B) 수동 운영으로만 삭제한다.

C) raw event를 영구 보관한다.

X) 기타.

[Answer]: A

### Q6 — Security Boundary
U9 metadata 보안 경계는?

A) **allowlist + no raw content/token(권장)** — 원문 전문, 앵커 주변 원문, credential, 내부 token, 자유 payload 저장 금지.

B) 분석 편의를 위해 자유 JSON을 허용한다.

X) 기타.

[Answer]: A

### Q7 — Delete/Reset SLA
사용자 삭제/초기화 요청의 처리 기대치는?

A) **동기 요청에서 즉시 반영 가능한 범위는 즉시 처리(권장)** — raw event delete/profile reset은 요청 성공 후 다음 decision부터 반영한다. U9는 삭제된 raw behavior log를 백업 테이블에 복사하지 않는다.

B) 삭제/초기화 요청을 큐에 넣고 나중에만 처리한다.

C) 운영자가 수동 처리한다.

X) 기타.

[Answer]: A (plan_feedback.md 반영: 백업 테이블을 만들지 않고 active raw event를 직접 삭제한다.)

### Q8 — Search Personalization Budget
검색 개인화 조회의 성능 예산은?

A) **작은 bounded profile read만 허용(권장)** — U2 검색 경로에서 U9 lookup이 실패/지연되면 즉시 비개인화 검색으로 진행한다.

B) 검색마다 이벤트 전체를 다시 집계한다.

C) 검색 결과를 U9가 직접 재계산한다.

X) 기타.

[Answer]: A

### Q9 — Observability
U9 관측은 어디로 보낼까요?

A) **기존 U6 ObservabilityHub/EventStore로 emit(권장)** — 기록 실패율, 집계 실패율, decision degraded count, delete/reset count.

B) U9 전용 관측 pipeline을 만든다.

X) 기타.

[Answer]: A

### Q10 — Shared Contracts
U9 DTO/schema는 어떻게 관리할까요?

A) **backend 모듈 DTO로 시작하고 U2/U7/U5 연동 시 shared schema로 승격(권장)** — 초기 문서/코드 범위를 줄인다.

B) 지금 바로 모든 U9 DTO를 shared schema로 만든다.

X) 기타.

[Answer]: A

### Q11 — Test Strategy
U9 테스트 경계는?

A) **unit/PBT 중심 + DB repository는 lightweight integration(권장)** — 기본 CI는 외부 서비스 없이 돌고, QT-7은 Hypothesis로 검증한다.

B) e2e 브라우저 테스트 중심.

C) 수동 테스트 중심.

X) 기타.

[Answer]: A

### Q12 — PBT Framework
QT-7 PBT는 무엇을 쓸까요?

A) **기존 Python/Hypothesis 계승(권장)** — DTO roundtrip, dedupe, owner isolation, deterministic aggregation, delete/reset, fail-open을 생성 테스트로 검증한다.

B) PBT 없이 예시 테스트만 둔다.

X) 기타.

[Answer]: A

---

## 4. 다음 절차

1. Q1~Q12는 권장안(A)으로 확정했다.
2. Q7은 plan_feedback.md 반영으로 A로 정정했다: 백업 테이블을 만들지 않고 active raw event를 직접 삭제한다.
3. `u9-personalization/nfr-requirements/` 산출물 2개를 생성했다.
4. NFR Requirements 승인 후 **NFR Design**에서 timeout, lazy aggregation, repository boundary, cleanup, telemetry patterns를 확정한다.
