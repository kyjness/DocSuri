# U8 Citation Graph — Business Logic Model

**Unit**: U8 Citation Graph  
**Stage**: Functional Design  
**Principle**: 기술 무관. Provider, cache store, API framework는 NFR Requirements 이후 결정한다.

## Components

| Component | Responsibility |
|---|---|
| `CitationGraphController` | 요청 검증, principal 확인, service 호출, safe response 반환. |
| `CitationGraphService` | 조회/새로고침/저장 유스케이스 orchestration. |
| `CitationSnapshotStore` | 루트 논문별 snapshot 읽기/쓰기. |
| `CitationProviderPort` | backward references 원천 조회. |
| `CitationResolver` | provider item을 canonical ID로 해소. |
| `CitationTreeBuilder` | 정렬, 중복 folding, 순환 차단, depth/node 상한 적용. |
| `CitationGraphPolicy` | depth, node limit, sort, saveability 규칙. |
| `LibrarySaveGateway` | U4 Library 저장 계약 호출. |
| `CitationTelemetryPublisher` | U6 관측 이벤트 발행. |

## Use Case: Get Citation Tree

1. Controller는 U3/U6가 주입한 `principalId`가 없으면 처리하지 않는다.
2. 요청의 `rootPaperId`, `depth`, `expandNodeId`, `refresh`를 검증한다.
3. Service는 `refresh=false`이면 snapshot을 먼저 조회한다.
4. 유효한 snapshot이 요청 범위를 커버하면 tree response를 즉시 만든다.
5. snapshot이 없거나 `refresh=true`이면 U6 레이트/쿼터 신호를 확인한다.
6. 제한 상태면 캐시가 있을 때 `RateLimited + cached snapshot`, 없으면 `RateLimited`를 반환한다.
7. Provider port로 backward references를 조회한다.
8. Resolver가 각 item을 canonical ID로 해소한다.
9. 해소 실패 item은 `UnresolvedCitation`으로 분리한다.
10. TreeBuilder가 정렬, 50노드 상한, depth 상한, duplicate/cycle folding을 적용한다.
11. 새 snapshot을 저장한다. 저장 실패는 사용자 응답을 실패시키지 않고 telemetry로 남긴다.
12. TelemetryPublisher가 `paperId`, `cacheHit`, `providerStatus`, `nodeCount`, `unresolvedCount`, `depthRequested`, `depthReturned`, `truncated`, `latencyMs`를 발행한다.
13. 확정 노드가 있으면 `Success`, unresolved가 섞이면 `Partial`, provider와 캐시가 모두 실패하면 `Unavailable`을 반환한다.

## Use Case: Lazy Load Second Hop

1. 요청은 `depth=2`와 `expandNodeId`를 포함한다.
2. `expandNodeId`가 unresolved 또는 `alreadyShown` 참조 노드이면 확장을 거부한다.
3. 해당 노드의 backward references만 provider 또는 snapshot에서 읽는다.
4. 기존 트리에 새 자식 노드를 병합하되 전체 화면 노드 수는 50을 넘지 않는다.
5. 초과분이 있으면 `truncated=true`와 남은 개수 추정치를 반환한다.

## Use Case: Manual Refresh

1. `refresh=true`이면 TTL 전이라도 provider 재조회를 시도한다.
2. 성공하면 snapshot을 교체한다.
3. 실패하면 기존 snapshot이 있을 때 기존 snapshot을 유지하고 `Partial` 또는 `Unavailable` 사유를 포함한다.
4. 기존 snapshot도 없으면 `Unavailable` 또는 `RateLimited`를 반환한다.

## Use Case: Save Citation Node

1. Controller는 principal을 확인한다.
2. Service는 node가 확정 노드인지 확인한다.
3. unresolved, `alreadyShown` 참조만 있는 노드, canonical ID가 없는 노드는 저장하지 않는다.
4. `LibrarySaveGateway`는 U8 minimal meta adapter로 U4 `LibraryItemMeta`에 맞춘다.
5. 필수 title과 canonical ID를 보장하고, 없는 카드 필드는 null 또는 empty로 둔다.
6. U4의 owner-scoped idempotent save 결과를 그대로 반환한다.

## Failure Model

| Failure | Behavior |
|---|---|
| Missing principal | U3/U6 경로에서 fail closed. |
| Invalid root ID | safe unavailable response. |
| Provider timeout/error | cached snapshot 우선, 없으면 Unavailable. |
| Provider 429/quota | RateLimited, cache-only 가능. |
| Resolver ambiguity | unresolved로 분리. |
| Snapshot write failure | 조회 응답은 유지, telemetry 기록. |
| Library save failure | 저장 액션만 실패, tree 조회에는 영향 없음. |

## Testable Properties

| Property | Check |
|---|---|
| Depth bound | 어떤 provider graph가 와도 `depthReturned <= 2`. |
| Node bound | 어떤 입력에서도 visible node count <= 50. |
| Duplicate folding | 동일 canonical ID는 첫 등장만 실제 노드, 이후 `alreadyShown`. |
| Cycle stop | A -> B -> A 같은 입력도 무한 확장하지 않음. |
| Unresolved isolation | unresolved는 tree node로 승격되지 않고 save/expand 불가. |
| DTO roundtrip | response union serialize/deserialize 후 state와 주요 counts 보존. |

## Traceability

| Story / Requirement | Logic |
|---|---|
| US-CG1, FR-15 | Get Citation Tree |
| US-CG2, QT-6 | TreeBuilder depth/node/folding rules |
| US-CG3 | Resolver + unresolved split |
| US-CG4, FR-16 | Save Citation Node |
| US-CG5, NFR-C1 | RateLimited/cache-only/unavailable states |
| US-CG6 | TelemetryPublisher |

