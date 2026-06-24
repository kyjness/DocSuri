# u8-citation-graph-infrastructure-design-plan.md — Infrastructure Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> Infrastructure Design (유닛별 루프)  
**유닛**: U8 Citation Graph  
**일자**: 2026-06-21  
**근거**: `construction/u8-citation-graph/nfr-design/`

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 Infrastructure Design 산출물을 만들지 않는다.

## 1. Infrastructure Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u8-citation-graph/infrastructure-design/`에 작성한다.

- [x] **infrastructure-components.md**
  - backend route, Redis keyspace, secret/env, U6 telemetry/quota integration
- [x] **deployment-topology.md**
  - existing backend deployment, no new service, provider egress
- [x] **configuration.md**
  - env names, TTL, timeout, opt-in contract test flag

## 2. 명확화 질문

### Q1 — Secret Name
Semantic Scholar API key env 이름은 무엇으로 둘까요?

A) **`SEMANTIC_SCHOLAR_API_KEY`**로 둔다. (권장)

B) `CITATION_PROVIDER_API_KEY`로 provider-neutral하게 둔다.

X) 기타.

[Answer]: A

### Q2 — Feature Flag
U8 endpoint 출시 플래그가 필요할까요?

A) **서버 env `CITATION_GRAPH_ENABLED=true`로 둔다**. (권장)

B) 플래그 없이 항상 활성화한다.

X) 기타.

[Answer]: A

### Q3 — Redis Key Prefix
Redis prefix는 무엇으로 둘까요?

A) **`citation_graph:v1:`**로 둔다. (권장)

B) 기존 paper cache prefix에 섞는다.

X) 기타.

[Answer]: A
