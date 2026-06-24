# u8-citation-graph-nfr-design-plan.md — NFR Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Design (유닛별 루프)  
**유닛**: U8 Citation Graph  
**일자**: 2026-06-21  
**근거**: `construction/u8-citation-graph/functional-design/`, `construction/u8-citation-graph/nfr-requirements/`

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 NFR Design 산출물을 만들지 않는다.

## 1. NFR Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u8-citation-graph/nfr-design/`에 작성한다.

- [x] **logical-components.md**
  - API handler, CitationGraphService, provider client, Redis snapshot store, quota guard, telemetry publisher
- [x] **patterns.md**
  - cache-first read, lazy 2-hop expansion, bounded traversal, provider degrade, safe error union
- [x] **runtime-architecture.md**
  - FastAPI integration, U6 gateway path, Redis TTL, Semantic Scholar timeout/retry boundary
- [x] **test-strategy.md**
  - fixture provider tests, Hypothesis graph invariants, opt-in real provider contract tests

## 2. 명확화 질문

### Q1 — API Shape
U8 API는 어떻게 나눌까요?

A) **조회와 저장만 둔다**: `GET /citation-tree`, `POST /citation-tree/save`. refresh/expand는 query flag로 처리한다. (권장)

B) 조회, refresh, expand, save를 전부 별도 endpoint로 둔다.

X) 기타.

[Answer]: A

### Q2 — Timeout Values
Semantic Scholar timeout은 어떻게 잡을까요?

A) **connect/read 합산 2초 목표 + 재시도 1회**로 둔다. (권장)

B) 5초 이상 기다린다.

X) 기타.

[Answer]: A

### Q3 — Redis TTL
snapshot TTL은 그대로 7일로 확정할까요?

A) **7일 TTL**로 확정한다. (권장)

B) 24시간으로 줄인다.

X) 기타.

[Answer]: A

### Q4 — Node Limit Enforcement
50노드 상한은 어디서 강제할까요?

A) **TreeBuilder에서 최종 응답 직전 한 번 강제**하고, provider limit도 보조로 건다. (권장)

B) provider query limit만 믿는다.

X) 기타.

[Answer]: A

### Q5 — Contract Test
실 provider 계약 테스트는 어디에 둘까요?

A) **기본 CI 제외 marker/env-gated 테스트**로 둔다. (권장)

B) 기본 CI에서 항상 실행한다.

X) 기타.

[Answer]: A
