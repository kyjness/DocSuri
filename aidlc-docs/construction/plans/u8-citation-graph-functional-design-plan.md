# u8-citation-graph-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (유닛별 루프) · **유닛**: U8 Citation Graph · **일자**: 2026-06-19  
**근거(SSOT)**: `aidlc-docs/inception/requirements/requirements.md`(FR-15~16·NFR-P3·QT-6·§12 U8 카브아웃), `user-stories/stories.md`(에픽 7, US-CG1~CG6), `application-design/{unit-of-work,unit-of-work-dependency,unit-of-work-story-map}.md`, `requirement-verification-questions-citation-graph.md`  
**원칙**: 이 단계는 **기술 무관**이다. Semantic Scholar/OpenAlex 선택, Redis/RDS/S3 캐시, FastAPI wiring, rate limit 구현, TTL 수치는 **NFR Requirements/Infra Design**에서 확정한다.

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 FD 산출물(`domain-entities.md`, `business-logic-model.md`, `business-rules.md`)을 만들지 않는다.

---

## 1. 유닛 컨텍스트

- **책임**: 로그인한 사용자가 논문 상세보기 페이지에서 선택한 논문의 **backward references 각주 트리**를 조회하고, 확정 가능한 인용만 노드로 표시하며, 인용 노드를 U4 Library에 저장할 수 있게 하는 API 모듈.
- **Owner 스토리**: US-CG1, US-CG2, US-CG3, US-CG4, US-CG5.
- **기여 스토리**: US-CG6(Owner=U6, U8은 관측 신호원).
- **범위 내**: backward references, 기본 1-hop/최대 2-hop, 화면당 50노드, 제목·연도·인용수, unresolved 분리, snapshot 캐시, 라이브러리 저장 연동, 관측 이벤트.
- **범위 밖**: forward citations, 3-hop 이상, 그래프 추천 산문, 문헌리뷰 생성, 논문 상세보기 FE 구현.
- **예비 컴포넌트**:
  - `CitationGraphController`
  - `CitationGraphService`
  - `CitationSnapshotStore`
  - `CitationProviderPort`
  - `CitationResolver`
  - `CitationTreeBuilder`
  - `CitationGraphPolicy`
  - `LibrarySaveGateway`
  - `CitationTelemetryPublisher`

---

## 2. Functional Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u8-citation-graph/functional-design/`에 작성한다.

- [x] **domain-entities.md**
  - `CitationGraphRequest`
  - `CitationGraphResponse`
  - `CitationRoot`
  - `CitationNode`
  - `CitationEdge`
  - `UnresolvedCitation`
  - `CitationSnapshot`
  - `CitationTreePolicy`
  - `CitationGraphError`
- [x] **business-logic-model.md**
  - `getCitationTree(paperId, depth, cursor?)`
  - snapshot cache lookup → provider fetch → ID resolution → tree build → unresolved split → telemetry
  - node save → U4 Library save gateway
  - failure path: cached snapshot first, no cache then explicit unavailable state
- [x] **business-rules.md**
  - backward-only invariant
  - max depth / max nodes
  - resolved vs unresolved rules
  - duplicate/cycle folding
  - login-required rule
  - library save rule
  - cache/refresh rule shape
  - QT-6 graph invariant properties
  - traceability matrix

---

## 3. 가정

- **AS-1**: 논문 상세보기 FE는 타 분기 책임이다. U8은 API 계약과 도메인 규칙만 설계한다.
- **AS-2**: 전체 기능은 로그인 필수다. U8은 U3/U6 인증·게이트웨이 경로를 통과한다.
- **AS-3**: U8은 U4 저장 계약을 재사용한다. 라이브러리 저장 로직을 재구현하지 않는다.
- **AS-4**: citation provider와 snapshot store의 구체 기술은 NFR/Infra에서 묻는다.
- **AS-5**: U8은 LLM을 사용하지 않는다. 인용 엣지는 외부 API와 ID 해소 결과만 신뢰한다.

---

## 4. 명확화 질문

### Q1 — API 응답 종단 상태
각주 트리 API의 응답 union을 어떻게 나눌까요?

A) **Success / Unavailable / Partial / RateLimited** 4분기. Success는 확정 노드 포함, Partial은 일부 unresolved 포함, Unavailable은 캐시·외부 API 모두 실패, RateLimited는 쿼터/레이트 제한. (권장)

B) Success / Error 2분기.

X) 기타.

[Answer]: A

### Q2 — unresolved 항목 노출 수준
ID 해소 실패 항목을 사용자에게 어떻게 보여줄까요?

A) **별도 unresolved 목록으로 제목 문자열만 표시**하고, 확정 노드처럼 저장/확장하지 않는다. (권장)

B) 트리 안에 흐린 노드로 표시하되 저장/확장은 막는다.

C) 사용자에게 표시하지 않고 telemetry만 남긴다.

X) 기타.

[Answer]: A

### Q3 — 중복/순환 처리
동일 논문이 여러 경로에서 나오거나 순환이 생기면?

A) **첫 등장만 실제 노드로 표시하고, 이후는 `alreadyShown` 참조 노드로 접는다**. 순환 확장은 중단한다. (권장)

B) 모든 경로에 중복 노드를 표시한다.

X) 기타.

[Answer]: A

### Q4 — 2-hop 확장 방식
최대 2-hop을 어떻게 로딩할까요?

A) **루트 1-hop 먼저 반환, 사용자가 노드 펼침 시 해당 노드의 2-hop을 lazy-load**한다. (권장)

B) 최초 요청에서 2-hop 전체를 미리 가져온다.

X) 기타.

[Answer]: A

### Q5 — 화면당 50노드 상한 적용
50노드 상한 초과 시?

A) **정렬 기준 상위 50개만 반환하고 `truncated=true`와 남은 개수 추정치를 제공**한다. (권장)

B) 에러로 거부한다.

C) 무한 스크롤로 계속 제공한다.

X) 기타.

[Answer]: A

### Q6 — 노드 정렬 기준
references 노드는 기본적으로 어떻게 정렬할까요?

A) **인용수 내림차순, 동률이면 최신 연도 우선, 마지막 제목순**. (권장)

B) 원 provider 순서 그대로.

C) 연도 오름차순.

X) 기타.

[Answer]: A

### Q7 — 수동 새로고침 의미
7일 snapshot TTL이 있을 때 사용자의 수동 새로고침은?

A) **TTL 전에도 provider 재조회 시도**, 성공 시 snapshot 교체, 실패 시 기존 snapshot 유지. (권장)

B) TTL 전에는 새로고침 버튼 비활성화.

C) 항상 캐시 삭제 후 재조회, 실패하면 빈 상태.

X) 기타.

[Answer]: A

### Q8 — 라이브러리 저장 메타 매핑
U8 노드를 U4 `LibraryItemMeta`로 저장할 때, U8이 가진 최소 필드(제목·연도·인용수)와 U4가 기대하는 카드 메타 차이를 어떻게 처리할까요?

A) **U4 저장 gateway에 U8 전용 minimal meta adapter를 둔다**. 필수 title/arxivId 또는 provider id만 보장하고 없는 필드는 null/empty로 둔다. (권장)

B) U8 노드는 라이브러리 저장 전에 반드시 U2 카드 메타를 재조회한다.

C) U8에서는 저장 기능을 제거한다.

X) 기타.

[Answer]: A

### Q9 — source identifier 우선순위
확정 노드 ID는 어떤 우선순위로 둡니까?

A) **arXiv ID → DOI → Semantic Scholar paperId → provider URL** 순으로 canonical id를 잡는다. (권장)

B) provider paperId만 사용한다.

C) 제목+연도 해시를 사용한다.

X) 기타.

[Answer]: A

### Q10 — 관측 이벤트 필드
U8이 U6로 보내는 관측 이벤트 최소 필드는?

A) **paperId, cacheHit, providerStatus, nodeCount, unresolvedCount, depthRequested, depthReturned, truncated, latencyMs**. (권장)

B) latency/error만.

X) 기타.

[Answer]: A

### Q11 — QT-6 PBT 범위
Functional Design에서 어떤 속성을 QT-6 후보로 고정할까요?

A) **depth≤2, node≤50, duplicate folding, cycle stop, unresolved never expandable/saveable, DTO roundtrip**. (권장)

B) depth/node 상한만.

X) 기타.

[Answer]: A

### Q12 — Construction 구현 전략
U8 구현은 어떤 방식으로 시작할까요?

A) **포트 유지 + 테스트 fixture/stub 허용 + production adapter는 NFR/Infra에서 확정**. (권장)

B) 첫 구현부터 실 외부 citation API만 사용, 테스트 더블 없음.

C) mock-only 데모 구현.

X) 기타.

[Answer]: A

---

## 5. 결정된 불변식

- **INV-U8-1**: U8 v1은 backward references만 제공한다.
- **INV-U8-2**: 로그인 필수이며 U3/U6 인증·게이트웨이 경로를 우회하지 않는다.
- **INV-U8-3**: ID 해소 실패 항목은 확정 노드가 아니며 저장/확장 불가다.
- **INV-U8-4**: 깊이 2, 화면당 50노드 상한을 넘지 않는다.
- **INV-U8-5**: U8은 LLM으로 인용을 추정하지 않는다.

---

## 6. 현재 상태와 다음 절차

1. Q1~Q12는 전부 권장안(A)으로 확정했다.
2. `u8-citation-graph/functional-design/` 산출물 3개를 생성했다.
3. Functional Design 승인 후 **NFR Requirements**에서 기술 스택 질문(Semantic Scholar/OpenAlex, 캐시/스토어, TTL 수치, API runtime, CI 통합 테스트)을 진행한다.
