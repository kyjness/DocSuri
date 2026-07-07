# U11 Evidence Formation Agent — 비즈니스 규칙 (Business Rules)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**원칙**: 결정 규칙·검증·제약(기술 무관). 수치 임계·구체 기술은 NFR/Infra.
**근거**: `inception/requirements/requirements.md` FR-36~38, FR-5, NFR-P6, NFR-C1, SEC-8/9, C-2 · 질문지 Q1~Q10 답변 · `domain-entities.md` · `shared/dtos/evidence.schema.json` (D5 FROZEN).

---

## 1. 결정 규칙 (Business Rules, INV-EV-* / BR-EV-*)

### INV-EV-1 — 세션 소유권 불변식 (FR-38, SEC-8)
- `EvidenceSession.ownerId`는 생성 후 **변경 불가**.
- 세션 조회·턴 추가·삭제·초기화는 **모두 소유자 본인만** 가능.
- 타인 세션 접근 시도는 **404**로 응답 (존재 여부 노출 금지 — SEC-9).
- 소유권 결정은 **U3.AuthorizationGuard 단일 권위에 위임**. U11이 자체 인가 판단 금지 (SEC-8).

### INV-EV-2 — 빈 성공 금지 (FR-5)
- `TurnSuccessResult`의 `EvidenceResult.claims`가 빈 배열이면 `TurnAbstainResult`로 처리.
- 근거 명제 0건을 성공(`state=ok`)으로 반환하는 것은 **금지**.

### INV-EV-3 — 날조 금지·추출 경계 (C-2, FR-5)
- `EvidenceItem.statement`는 **논문 DocModel 블록에서 추출한 명제만** 허용.
- LLM이 생성한 새로운 산문·없는 수치·없는 주장을 `statement`에 삽입하는 것은 **금지**.
- `SourceRef.quote`는 논문 원문 스니펫만 허용 — 생성 산문 금지.

### INV-EV-4 — 첨부 원시 파일 미저장 (C-1 준용, Q6=A)
- 첨부 파일은 DocModel 추출 후 즉시 폐기. **원시 파일을 영구 저장 금지**.
- `AttachmentHandle`은 Agent 실행 컨텍스트 내에서만 유효한 임시 핸들.

### INV-EV-5 — 내부 정보 비노출 (SEC-9)
- 벡터 점수·청크 ID·LLM 내부 상태·근거화 위반 상세는 사용자 응답에 **절대 노출 금지**.
- `abstainReason`은 비기술 사유만 허용 (예: `out_of_corpus`, `insufficient_evidence`).
- 타인 세션 존재 여부 자체도 노출 금지 (→ 404).

---

## 2. 근거형성 규칙

### BR-EV-1 — 기권 조건 (FR-5, SEC-9)
- 다음 경우 `TurnAbstainResult` 반환:
  - 관련 논문을 찾지 못한 경우 (`out_of_corpus`)
  - 논문에서 충분한 근거 명제를 추출하지 못한 경우 (`insufficient_evidence`)
  - LLM 추출 결과가 INV-EV-3(날조 금지)를 위반하는 경우
- **날조 대신 기권이 우선** — 근거가 부족하면 기권. fail-closed.

### BR-EV-2 — 검색 scope 분기 (Q4=A)
- `scope=auto`: 질의 주도 자동 검색(Vector Store). 사용자가 paperIds를 지정해도 무시.
- `scope=explicit`: `EvidenceRequest.paperIds`에 명시된 논문 집합만 사용. 자동 검색 금지.
- `scope=mixed`: 자동 검색 결과 + `paperIds` 명시 집합 병합. 중복 제거 후 사용.
- scope 생략 시 `auto`로 처리.

### BR-EV-3 — 멀티턴 맥락 참조 (FR-36)
- 후속 턴은 **동일 세션의 이전 턴 결과를 맥락으로 참조** 가능.
- 이전 턴에서 언급된 논문·근거 명제를 재활용해 더 구체화된 응답 생성.
- 후속 질문이 이전 Corpus와 완전히 다른 주제면 새로운 scope으로 근거 갱신.

### BR-EV-4 — 첨부 처리 (Q6=A)
- 첨부 파일은 형식(pdf 등)·크기 한도 검증을 **처리 시작 전** 수행.
- 검증 실패 시 즉시 에러 반환. Agent 실행 시작 금지.
- 유효한 첨부는 DocModel 파이프라인(U1 패턴 재사용)으로 일시 처리해 근거 추출 대상에 포함.
- 첨부 처리 실패 시 해당 첨부는 건너뛰고 나머지 논문으로 근거형성 계속 (부분 실패 허용).

### BR-EV-5 — 비교표·쟁점 오버레이 조립 (Q2=A)
- `EvidenceResult.claims`는 논문 간 **비교형** 명제 구성. 단순 나열 금지.
- 동일 주제에 대해 지지(`supporting`)와 상충(`conflicting`) 출처를 함께 제시.
- 상충 출처가 없으면 `conflicting: []` 빈 배열 허용.

---

## 3. 스트리밍·비동기 규칙

### BR-EV-6 — 스트리밍 우선 (NFR-P6)
- 기본 경로: **SSE 스트리밍**으로 점진 응답.
- 긴 다논문 분석(임계 기준은 NFR에서 확정): **비동기 잡 오프로드**.
  - API가 `TurnPendingResult{ jobId, startedAt }` 반환.
  - 클라이언트는 `GET /api/evidence/jobs/{jobId}` 폴링.
  - 워커 완료 시 결과를 세션 저장소에 저장 → 폴링이 완료 결과 수신.
- 비동기 잡도 **동일 날조 금지·기권 규칙 적용** (INV-EV-2, INV-EV-3).

### BR-EV-7 — 비용 게이트 (NFR-C1)
- LLM 호출 **직전** `get_budget_state()`로 비용 상태 확인.
- OPEN/저하 상태 → `TurnErrorResult{ errorCode: "cost_degraded" }` 반환. LLM 호출 금지.
- 비용 게이트 판단은 **U6.CostGuardCircuitBreaker 단일 권위**. U11이 자체 비용 판단 금지.

---

## 4. 세션 관리 규칙

### BR-EV-8 — 세션 삭제 (FR-38)
- 세션 삭제 시 해당 세션의 **모든 턴 이력과 결과를 함께 삭제**.
- 소유권 검증(INV-EV-1) 통과 후 실행.
- 삭제는 **소프트 삭제** (`status=deleted`). 영구 파기 방식은 NFR/Infra 이월.

### BR-EV-9 — 세션 초기화 (FR-38)
- 전체 초기화는 **요청 사용자의 모든 세션**을 삭제.
- 타인 세션에 영향 없음 (INV-EV-1).

### BR-EV-10 — 세션 목록 조회 (FR-38)
- 조회 결과는 **소유자 본인 세션만** 포함.
- 정렬 기준: `updatedAt` 내림차순 (최근 활동 순).

---

## 5. 보안·경계 불변식

### BR-EV-11 — 레이트리밋·남용 방어
- 레이트리밋·입력 검증·인증은 **U6 게이트웨이 강제**. U11 자체 중복 구현 금지.

### BR-EV-12 — fail-closed
- LLM 장애·타임아웃·비용 OPEN → 기권 또는 에러로 수렴.
- 스택 트레이스·내부 오류 상세 사용자 노출 금지 (SEC-9).

---

## 6. 속성 기반 테스트 속성 (QT-8)

| ID | 속성 | 근거 |
|---|---|---|
| **PBT-EV-1** | 기권 안전성 — `claims=[]`이면 반드시 `state=abstain` 반환 (INV-EV-2) | FR-5 |
| **PBT-EV-2** | 소유권 격리 — 임의 `userId`로 타인 세션 조회 시 항상 404 (INV-EV-1) | FR-38, SEC-8 |
| **PBT-EV-3** | 비노출 불변 — `TurnResult` 직렬화에 벡터 점수·청크 ID·LLM 메타 미포함 (INV-EV-5) | SEC-9 |
| **PBT-EV-4** | scope 격리 — `explicit` scope 결과의 `SourceRef.paperId`가 모두 명시 집합 내 (BR-EV-2, INV-EV-3) | FR-37 |
| **PBT-EV-5** | D5 라운드트립 — `EvidenceResult` / `EvidenceAbstainResult` 직렬화·역직렬화 후 계약 일치 | D5, FR-5 |

---

## 7. 추적성 매트릭스 (미커버 0 검증)

| 규칙 | 요구사항 | 스토리 |
|---|---|---|
| INV-EV-1, BR-EV-8~10 (세션 소유권·CRUD) | FR-38, SEC-8 | US-EV7, US-EV8 |
| INV-EV-2, BR-EV-1 (빈 성공 금지·기권) | FR-5, FR-37 | US-EV6 |
| INV-EV-3, BR-EV-5 (날조 금지·비교표) | C-2, FR-5, FR-37 | US-EV2, US-EV3 |
| INV-EV-4 (첨부 미저장) | C-1, FR-37 | US-EV4 |
| INV-EV-5, BR-EV-12 (비노출·fail-closed) | SEC-9, FR-5 | US-EV6, US-EV9 |
| BR-EV-2 (scope 분기) | FR-37 | US-EV2, US-EV3 |
| BR-EV-3 (멀티턴 맥락) | FR-36 | US-EV5 |
| BR-EV-4 (첨부 처리) | FR-37, Q6=A | US-EV4 |
| BR-EV-6 (스트리밍·비동기 잡) | NFR-P6 | US-EV2, US-EV9 |
| BR-EV-7 (비용 게이트) | NFR-C1 | US-EV9 |
| BR-EV-11 (레이트리밋 위임) | SEC-11 | US-EV9 |

**커버리지**: FR-36·37·38 · FR-5 · NFR-P6 · NFR-C1 · SEC-8/9/11 · C-1/C-2 · QT-8 · US-EV1~EV9 전수 매핑(미커버 0).
