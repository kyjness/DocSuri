# U8 Citation Graph — Business Rules

**Unit**: U8 Citation Graph  
**Stage**: Functional Design

## Business Rules

### BR-CG1 — Backward References Only

U8 v1은 선택 논문이 인용한 논문(backward references)만 표시한다. Forward citations와 3-hop 이상 탐색은 제외한다.

### BR-CG2 — Login Required

모든 U8 조회와 저장 액션은 U3/U6 인증·게이트웨이 경로를 통과해야 한다. 인증 정보가 없으면 fail closed 한다.

### BR-CG3 — Depth Limit

기본 조회는 1-hop이다. 사용자가 노드를 펼칠 때만 해당 노드의 2-hop을 lazy-load한다. 응답 깊이는 항상 2 이하이다.

### BR-CG4 — Visible Node Limit

한 응답의 표시 노드는 최대 50개다. 초과 시 정렬 기준 상위 50개만 반환하고 `truncated=true`와 남은 개수 추정치를 제공한다.

### BR-CG5 — Sort Order

확정 노드는 인용수 내림차순, 동률이면 최신 연도 우선, 마지막으로 제목 오름차순으로 정렬한다. 누락값은 정렬상 가장 낮은 값으로 취급한다.

### BR-CG6 — Canonical ID Priority

확정 노드의 canonical ID는 arXiv ID, DOI, Semantic Scholar paperId, provider URL 순으로 선택한다.

### BR-CG7 — Unresolved Isolation

ID 해소 실패 항목은 별도 unresolved 목록에 제목 문자열만 표시한다. unresolved는 저장, 확장, 확정 엣지 생성 대상이 아니다.

### BR-CG8 — Duplicate and Cycle Folding

동일 canonical ID가 여러 경로에서 나오면 첫 등장만 실제 노드로 표시한다. 이후 등장은 `alreadyShown=true` 참조로 접는다. 순환이 감지되면 확장을 중단한다.

### BR-CG9 — Manual Refresh

수동 새로고침은 TTL 전에도 provider 재조회를 시도한다. 성공하면 snapshot을 교체하고, 실패하면 기존 snapshot을 유지한다.

### BR-CG10 — Cache-First Degradation

Provider 실패 또는 쿼터 제한 시 캐시된 snapshot이 있으면 캐시 결과를 우선 표시한다. 캐시도 없으면 `Unavailable` 또는 `RateLimited` 상태를 반환한다.

### BR-CG11 — Library Save

확정 노드는 U4 Library 저장 계약으로 저장한다. U8은 U4 저장 로직을 재구현하지 않고 minimal meta adapter만 둔다.

### BR-CG12 — Safe Error Surface

사용자 응답은 provider 내부 오류, stack trace, 내부 경로, credential 정보를 노출하지 않는다.

### BR-CG13 — No LLM Citation Inference

U8은 LLM으로 인용 엣지를 추정하지 않는다. 확정 엣지는 provider 데이터와 ID 해소 결과만 사용한다.

### BR-CG14 — Telemetry

각 조회는 최소 `paperId`, `cacheHit`, `providerStatus`, `nodeCount`, `unresolvedCount`, `depthRequested`, `depthReturned`, `truncated`, `latencyMs`를 U6 관측 이벤트로 발행한다.

## Response State Rules

| State | Rule |
|---|---|
| `Success` | 요청 범위의 확정 노드가 있고 unresolved가 없다. |
| `Partial` | 확정 노드와 unresolved가 함께 있거나 일부 provider 결과만 사용 가능하다. |
| `Unavailable` | 캐시와 provider 모두 실패해 인용 정보를 표시할 수 없다. |
| `RateLimited` | U6/provider 쿼터로 새 조회가 중단된다. |

## QT-6 Property Requirements

| ID | Property |
|---|---|
| PBT-CG1 | `depthReturned <= 2` invariant. |
| PBT-CG2 | `visibleNodeCount <= 50` invariant. |
| PBT-CG3 | Duplicate folding is idempotent. |
| PBT-CG4 | Cycles stop without unbounded traversal. |
| PBT-CG5 | Unresolved entries are never saveable or expandable. |
| PBT-CG6 | Response DTO roundtrip preserves state and counts. |

## Security Compliance

| Rule | Status | Rationale |
|---|---|---|
| SECURITY-05 | Compliant | Request fields require type, length, format, and bound validation. |
| SECURITY-08 | Compliant | Login required, owner-scoped U4 save via U3/U6 path. |
| SECURITY-09 | Compliant | Safe error surface only. |
| SECURITY-11 | Compliant | Rate/abuse path delegated to U6; misuse cases covered. |
| SECURITY-15 | Compliant | External provider/store failures degrade fail-closed/cache-first. |
| SECURITY-01/02/04/06/07/10/12/13/14 | N/A at FD | Concrete infrastructure, IAM, headers, dependency and alert configuration are NFR/Infra/Code concerns. |

## Resiliency Compliance

| Rule | Status | Rationale |
|---|---|---|
| RESILIENCY-01 | Compliant | U8 dependency and user impact documented in unit artifacts. |
| RESILIENCY-05 | Compliant | U6 telemetry event fields defined. |
| RESILIENCY-10 | Compliant | Provider failure, quota, cache-only, and unavailable states defined. |
| RESILIENCY-09 | Compliant | Provider quota/rate handling captured; concrete limits deferred to NFR. |
| RESILIENCY-02/03/04/06/07/08/11/12/13/14/15 | N/A at FD | Deployment, DR, health checks, and incident process are NFR/Infra/Ops concerns already handled globally or deferred. |

## PBT Compliance

| Rule | Status | Rationale |
|---|---|---|
| PBT-01 | Compliant | Testable properties PBT-CG1..CG6 identified for code generation. |
| PBT-02/03/07/08/09 | Deferred | Enforced in Code Generation/NFR Requirements per partial PBT mode. |
| PBT-04/05/06/10 | Advisory/N/A | Not blocking in current partial mode; duplicate folding idempotence is still captured. |

## Traceability Matrix

| Requirement / Story | Rules |
|---|---|
| FR-15 | BR-CG1, BR-CG3, BR-CG4, BR-CG5, BR-CG7, BR-CG8 |
| FR-16 | BR-CG2, BR-CG9, BR-CG10, BR-CG11 |
| NFR-P3 | BR-CG10 |
| NFR-C1 | BR-CG10, BR-CG14 |
| QT-6 | PBT-CG1..PBT-CG6 |
| US-CG1 | BR-CG1, BR-CG2 |
| US-CG2 | BR-CG3, BR-CG4, BR-CG5 |
| US-CG3 | BR-CG6, BR-CG7, BR-CG8, BR-CG13 |
| US-CG4 | BR-CG11 |
| US-CG5 | BR-CG9, BR-CG10 |
| US-CG6 | BR-CG14 |

