# u9-personalization-nfr-design-plan.md — NFR Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Design (유닛별 루프)  
**유닛**: U9 Personalization  
**일자**: 2026-06-23  
**근거**: `construction/u9-personalization/functional-design/`, `construction/u9-personalization/nfr-requirements/`

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 NFR Design 산출물을 만들지 않는다.

## 1. NFR Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u9-personalization/nfr-design/`에 작성한다.

- [x] **logical-components.md**
  - `PersonalizationApi`, `BehaviorEventRecorder`, `ProfileAggregator`, active repository, settings service, read port, retention cleanup command, telemetry publisher
- [x] **nfr-design-patterns.md**
  - fail-open personalization, bounded profile read, lazy aggregation, direct active-table delete, scheduled retention cleanup, metadata allowlist, U6 observability

## 2. 명확화 질문

### Q1 — Fail-Open Timeout Boundary
U2/U7이 U9 profile/defaults를 읽을 때 timeout은 어떻게 잡을까요?

A) **짧은 내부 timeout 후 즉시 기본값(권장)** — U9 read가 지연되면 `degraded` decision으로 간주하고 U2/U7은 비개인화 경로를 계속한다. 구체 timeout 수치는 Code/NFR Design에서 낮은 기본값으로 둔다.

B) U9 응답을 기다리며 검색/요약 요청 latency 증가를 허용한다.

X) 기타.

[Answer]: A

### Q2 — Lazy Aggregation Boundary
프로필 집계는 어떤 패턴으로 설계할까요?

A) **read-through lazy aggregation(권장)** — 프로필이 없거나 stale이면 같은 U9 모듈 안에서 가볍게 재집계하고, 실패 시 기존 프로필 또는 기본값으로 저하한다. 별도 worker는 만들지 않는다.

B) 별도 aggregation worker를 v1부터 만든다.

C) 이벤트 기록마다 즉시 전체 재집계한다.

X) 기타.

[Answer]: A

### Q3 — Active/Delete Boundary
plan feedback에 따라 삭제 경계를 어떻게 강제할까요?

A) **active table에서 직접 삭제하고 backup table은 만들지 않는다(권장)** — delete는 owner-scoped active rows를 삭제한다. read/aggregate/decision 경로는 active repository와 aggregate profile만 의존한다.

B) backup table에 copy/move 후 active table에서 삭제한다.

C) deleted_at flag만 두고 물리 삭제하지 않는다.

X) 기타.

[Answer]: A

### Q4 — Observability Pattern
U9 관측 이벤트는 어떻게 설계할까요?

A) **운영 카운터/상태만 U6로 emit(권장)** — record failure, aggregation failure, degraded decision, delete/reset, retention purge success/failure만 보내고 raw event metadata는 보내지 않는다.

B) 디버깅을 위해 raw behavior event 일부를 U6 telemetry에 포함한다.

X) 기타.

[Answer]: A

### Q5 — Metadata Validation Pattern
metadata allowlist는 어디에서 강제할까요?

A) **BehaviorEventRecorder 진입점에서 단일 강제(권장)** — event type별 allowlist와 subject validation을 한 번 적용하고, repository는 검증된 envelope만 받는다.

B) caller별로 각자 검증한다.

C) repository 저장 직전 자유 JSON을 허용한다.

X) 기타.

[Answer]: A

---

## 3. 다음 절차

1. Q1~Q5는 전부 권장안(A)으로 확정했다.
2. `u9-personalization/nfr-design/` 산출물 2개를 생성했다.
3. NFR Design 승인 후 **Infrastructure Design** 필요 여부를 판단한다.
