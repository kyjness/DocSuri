# U8 Citation Graph — Domain Entities

**Unit**: U8 Citation Graph  
**Stage**: Functional Design  
**Scope**: 논문 상세보기의 backward references 각주 트리 API. FE 구현과 기술 스택 선택은 제외한다.

## Entity Model

### CitationGraphRequest

각주 트리 조회 요청.

| Field | Required | Rule |
|---|---:|---|
| `principalId` | Yes | U3/U6 인증 경로에서 주입된 로그인 사용자. |
| `rootPaperId` | Yes | 루트 논문 ID. arXiv ID, DOI, provider paperId, provider URL 중 하나. |
| `depth` | No | 기본 1, 최대 2. |
| `expandNodeId` | No | 2-hop lazy-load 대상 노드. 없으면 루트 1-hop 조회. |
| `cursor` | No | 50노드 상한 이후 후속 페이지가 필요할 때만 사용. |
| `refresh` | No | true면 TTL 전에도 provider 재조회 시도. |

### CitationGraphResponse

응답은 4분기 union이다.

| State | Meaning |
|---|---|
| `Success` | 확정 노드만으로 요청 범위를 만들 수 있음. |
| `Partial` | 확정 노드와 unresolved 항목이 함께 존재함. |
| `Unavailable` | 캐시와 provider 모두 사용할 수 없어 루트 외 인용 정보를 반환할 수 없음. |
| `RateLimited` | U6 또는 provider 쿼터 제한으로 새 조회가 중단됨. 캐시가 있으면 캐시 스냅샷을 함께 반환할 수 있음. |

### CitationRoot

사용자가 상세보기에서 보고 있는 논문.

| Field | Rule |
|---|---|
| `canonicalId` | arXiv ID -> DOI -> provider paperId -> provider URL 순으로 선택. |
| `title` | 상세보기 또는 provider에서 확인된 제목. |
| `year` | 확인 가능한 경우만 표시. |
| `citationCount` | provider가 제공하면 표시, 없으면 null. |

### CitationNode

트리에 표시 가능한 확정 노드.

| Field | Rule |
|---|---|
| `nodeId` | canonical ID. |
| `title` | 필수. |
| `year` | 선택. |
| `citationCount` | 선택. |
| `depth` | 1 또는 2. |
| `childrenState` | `NotLoaded`, `Loaded`, `Truncated`, `Unavailable`. |
| `alreadyShown` | 동일 논문이 이미 실제 노드로 표시된 경우 true. |
| `saveable` | unresolved가 아니고 canonical ID가 있으면 true. |

### CitationEdge

루트 또는 노드가 인용한 backward reference 관계.

| Field | Rule |
|---|---|
| `fromNodeId` | 루트 또는 부모 노드 canonical ID. |
| `toNodeId` | 자식 노드 canonical ID. |
| `relation` | v1에서는 항상 `references`. |
| `depth` | 대상 노드 깊이. |

### UnresolvedCitation

ID 해소 실패 항목. 확정 노드가 아니다.

| Field | Rule |
|---|---|
| `rawTitle` | 사용자에게 보여줄 수 있는 제목 문자열. |
| `rawYear` | 있으면 표시. |
| `reason` | `MissingIdentifier`, `AmbiguousMatch`, `ProviderOmittedData`. |
| `saveable` | 항상 false. |
| `expandable` | 항상 false. |

### CitationSnapshot

동일 루트 논문의 캐시 가능한 결과 묶음.

| Field | Rule |
|---|---|
| `rootPaperId` | 요청 루트. |
| `depthCovered` | 캐시가 커버하는 깊이. |
| `nodes` | 최대 50개 표시 대상. |
| `edges` | nodes 간 확정 엣지. |
| `unresolved` | 별도 unresolved 목록. |
| `createdAt` | TTL 판단 기준. |
| `providerStatus` | 마지막 provider 호출 결과. |

### CitationTreePolicy

기술 무관 비즈니스 상수.

| Field | Value |
|---|---|
| `defaultDepth` | 1 |
| `maxDepth` | 2 |
| `maxVisibleNodes` | 50 |
| `sortOrder` | citationCount desc, year desc, title asc |
| `direction` | backward references only |

### CitationGraphError

사용자 응답에는 내부 오류를 노출하지 않는다.

| Error | User State |
|---|---|
| `Unauthorized` | U3/U6에서 차단. |
| `ProviderTimeout` | 캐시 있으면 Partial/Success, 없으면 Unavailable. |
| `ProviderRateLimited` | RateLimited. |
| `InvalidPaperId` | Unavailable with safe message. |
| `StoreFailure` | 캐시 없이 provider 성공이면 Success 가능, 저장 실패는 telemetry. |

## Testable Properties

| Property | Category | Rule |
|---|---|---|
| DTO serialize/deserialize preserves response shape | Round-trip | `CitationGraphResponse` roundtrip. |
| Tree never exceeds depth 2 | Invariant | Any generated graph is clipped at depth 2. |
| Visible nodes never exceed 50 | Invariant | Builder returns at most 50 display nodes. |
| Duplicate folding is idempotent | Idempotence | Folding twice equals folding once. |
| Unresolved entries are never saveable or expandable | Business invariant | Holds for every unresolved item. |

## Traceability

| Source | Covered By |
|---|---|
| FR-15 | `CitationRoot`, `CitationNode`, `CitationEdge`, `CitationTreePolicy` |
| FR-16 | `CitationNode.saveable`, `CitationSnapshot`, `CitationGraphError` |
| QT-6 | Testable Properties |
| US-CG1..CG5 | Request/response, tree nodes, unresolved, saveability, failure states |
| US-CG6 | `providerStatus`, telemetry fields in business logic |

