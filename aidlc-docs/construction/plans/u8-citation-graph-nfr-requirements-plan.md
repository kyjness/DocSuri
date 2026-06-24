# u8-citation-graph-nfr-requirements-plan.md — NFR Requirements 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Requirements (유닛별 루프)  
**유닛**: U8 Citation Graph  
**일자**: 2026-06-19  
**근거**: `construction/u8-citation-graph/functional-design/`, `requirements.md`(FR-15~16, NFR-P3, NFR-C1, QT-6), `unit-of-work.md`(U8), `unit-of-work-dependency.md`(U8->U3/U4/U6)

**원칙**: U8은 LLM을 쓰지 않는다. 새 인프라를 늘리기보다 기존 backend, U6, Redis/RDS/S3 중 필요한 것만 쓴다.

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 NFR 산출물(`nfr-requirements.md`, `tech-stack-decisions.md`)을 만들지 않는다.

---

## 1. NFR 렌즈

- **성능**: NFR-P3. 캐시 히트는 빠르게, 첫 외부 조회는 로딩/부분 결과 허용.
- **가용성**: citation provider 실패 시 cache-first, 없으면 `Unavailable` 또는 `RateLimited`.
- **보안**: 로그인 필수, owner-scoped 저장, provider key 비노출, 안전한 오류 표면.
- **비용/쿼터**: U6 CostGuard와 U8 provider quota counter 소비.
- **테스트**: QT-6 그래프 불변식, provider 계약 테스트, DTO roundtrip.

## 2. NFR Requirements 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u8-citation-graph/nfr-requirements/`에 작성한다.

- [x] **nfr-requirements.md**
  - NFR-P3 응답 목표 형태
  - provider 실패/쿼터 저하 요구사항
  - 보안/관측/비용 요구사항
  - QT-6 테스트 요구사항
- [x] **tech-stack-decisions.md**
  - citation provider
  - snapshot cache/store
  - provider credential handling
  - backend runtime/API integration
  - PBT/contract/integration test boundary

---

## 3. 명확화 질문

### Q1 — Citation Provider
U8 v1의 외부 citation provider는 무엇으로 시작할까요?

A) **Semantic Scholar Graph API 단일 provider로 시작**한다. OpenAlex/arXiv 보강은 coverage 문제가 실측될 때 추가한다. (권장)

B) Semantic Scholar primary + OpenAlex fallback을 v1부터 구현한다.

C) OpenAlex 단일 provider로 시작한다.

X) 기타.

[Answer]: A

### Q2 — Provider Credential
provider API key가 필요한 경우 어디에서 읽을까요?

A) **기존 ECS/Secrets Manager/env 주입 경로를 사용**하고, 코드에는 key를 넣지 않는다. 로컬은 `.env`/AWS profile만 허용한다. (권장)

B) 설정 파일에 평문으로 둔다.

X) 기타.

[Answer]: A

### Q3 — Snapshot Cache/Store
7일 snapshot은 어디에 둘까요?

A) **기존 Redis에 TTL 7일로 저장**한다. 영구 보관은 하지 않는다. Redis miss면 provider 재조회 또는 unavailable. (권장)

B) S3에 영구 snapshot을 저장하고 Redis를 hot cache로 둔다.

C) RDS 테이블에 저장한다.

X) 기타.

[Answer]: A

### Q4 — Response Target
NFR-P3 응답 목표를 어떻게 잡을까요?

A) **캐시 hit P50 < 500ms 목표, 첫 provider 조회는 로딩/부분 결과 허용**으로 둔다. 검색 SLA NFR-P1에는 포함하지 않는다. (권장)

B) 첫 provider 조회까지 P50 < 500ms로 잡는다.

X) 기타.

[Answer]: A

### Q5 — Timeout/Retry
provider 호출 실패 처리는 어떻게 할까요?

A) **짧은 timeout + 재시도 1회 + cache-first degrade**. 재시도 후 실패하면 캐시 또는 `Unavailable`. (권장)

B) 성공할 때까지 여러 번 재시도한다.

X) 기타.

[Answer]: A

### Q6 — Rate Limit / Quota
provider rate limit은 어디서 관리할까요?

A) **U6 게이트웨이 rate limit + U8 provider quota counter**를 함께 쓴다. 임계 초과 시 cache-only 또는 `RateLimited`. (권장)

B) U8 내부에서만 관리한다.

X) 기타.

[Answer]: A

### Q7 — Backend Integration
U8 API runtime은 어디에 붙일까요?

A) **기존 backend FastAPI app-shell 모듈로 붙인다**. U6 게이트웨이 경로를 통과하고 별도 서비스는 만들지 않는다. (권장)

B) 별도 ECS service로 분리한다.

X) 기타.

[Answer]: A

### Q8 — Shared DTO
U8 응답 DTO는 어떻게 관리할까요?

A) **backend 모듈 내부 DTO로 시작하고, FE 상세보기 분기와 맞출 때 shared DTO로 승격**한다. (권장)

B) 지금 바로 shared DTO/schema를 만든다.

X) 기타.

[Answer]: A

### Q9 — Observability
U8 관측은 어디로 보낼까요?

A) **U6 ObservabilityHub/EventStore로 emit**한다. 별도 관측 파이프라인은 만들지 않는다. (권장)

B) U8 전용 로그/메트릭 파이프라인을 만든다.

X) 기타.

[Answer]: A

### Q10 — Library Save Contract
U4 Library 저장 메타 부족분은 어떻게 처리할까요?

A) **U8 minimal meta adapter로 저장**한다. 없는 필드는 null/empty, 추가 보강 조회는 하지 않는다. (권장)

B) 저장 전 U2 검색/card meta를 재조회한다.

X) 기타.

[Answer]: A

### Q11 — Test Strategy
U8 테스트 경계는 어떻게 잡을까요?

A) **단위/PBT는 fixture provider로, 통합은 opt-in 실 provider 계약 테스트**로 둔다. CI 기본 레인은 외부 API 없이 돈다. (권장)

B) 모든 테스트가 실 provider를 호출한다.

X) 기타.

[Answer]: A

### Q12 — PBT Framework
QT-6 PBT는 무엇을 쓸까요?

A) **기존 Python/Hypothesis를 계승**한다. depth/node/folding/cycle/unresolved/DTO roundtrip을 생성 테스트로 검증한다. (권장)

B) PBT 없이 예시 테스트만 둔다.

X) 기타.

[Answer]: A

---

## 4. 다음 절차

1. Q1~Q12의 `[Answer]:`를 채운다.
2. 모호 답변이 없으면 `u8-citation-graph/nfr-requirements/` 산출물 2개를 생성한다.
3. NFR Requirements 승인 후 **NFR Design**에서 timeout 수치, circuit, cache key, logical components를 확정한다.
