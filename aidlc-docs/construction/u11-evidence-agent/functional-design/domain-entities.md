# U11 Evidence Formation Agent — 도메인 엔티티 (Domain Entities)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**원칙**: **기술 무관(technology-agnostic)**. 본 문서의 엔티티는 비즈니스 의미만 정의하며, 구체 기술(Bedrock·S3·RDS·SSE·SQS)은 **NFR/Infra**에서 바인딩한다.
**근거**: `inception/application-design/component-dependency.md §7` · `shared/dtos/evidence.schema.json` (D5 FROZEN) · `shared/ports/README.md §4` · `inception/requirements/requirements.md` FR-36~38, NFR-P6, FR-5, SEC-9, C-2.

---

## 0. 엔티티 관계 한눈에 보기

```
EvidenceSession ──(1:N)──▶ EvidenceTurn
      │                         │
      │                    EvidenceRequest (D5 참조)
      │                         │
      │                    AgentRunContext
      │                         │ (오케스트레이터 실행)
      │                    ┌────┴──────────────────────────────┐
      │               PaperSearchResult          AttachmentHandle
      │                    │                         │
      │               EvidenceExtractInput ◀─────────┘
      │                    │
      │               EvidenceItem[] (D5 참조)
      │                    │
      │              ┌─────┴──────┐
      │         (근거 있음)   (근거 없음)
      │              ▼            ▼
      │       EvidenceResult  EvidenceAbstainResult  (D5 참조 — SSOT: evidence.schema.json)
      │              │
      └─────────────▶ TurnResult (세션에 저장)
```

- **소유(생산) 타입**: U11이 정의·생산하는 도메인 엔티티.
- **참조(D5) 타입**: `shared/dtos/evidence.schema.json` FROZEN 계약 — `EvidenceRequest`, `EvidenceResult`, `EvidenceAbstainResult`, `EvidenceItem`, `EvidenceCoverage`, `SourceRef`, `EvidenceScope`. U11이 재정의(포크) 금지.

---

## 1. 세션 · 턴 (FR-36, FR-38)

### `EvidenceSession` (세션, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `sessionId` | `SessionId` | 세션 고유 식별자 | FR-38 |
| `ownerId` | `UserId` | 세션 소유자 — SEC-8 소유권 불변식 | FR-38, SEC-8 |
| `title` | `string?` | 세션 제목 (첫 질문에서 자동 도출 또는 사용자 입력) | FR-38 |
| `turns` | `EvidenceTurn[]` | 멀티턴 대화 이력 (시간순) | FR-36 |
| `createdAt` | `Timestamp` | 세션 생성 시각 | FR-38 |
| `updatedAt` | `Timestamp` | 마지막 턴 시각 | FR-38 |
| `status` | `enum{active, deleted}` | 세션 상태 — `deleted`는 소프트 삭제 | FR-38 |

> **불변식(INV-EV-1)**: `ownerId`는 세션 생성 후 변경 불가. 타인 세션 조회·삭제 시도는 404로 처리(SEC-9, cross-owner 노출 금지).

### `EvidenceTurn` (턴, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `turnId` | `TurnId` | 턴 고유 식별자 | FR-36 |
| `sessionId` | `SessionId` | 소속 세션 | FR-36 |
| `request` | `EvidenceRequest` (D5 참조) | 사용자 입력(topic, scope, paperIds?, attachments?) | FR-36, FR-37 |
| `result` | `TurnResult` | Agent 응답 (성공 또는 기권 또는 진행 중) | FR-37 |
| `createdAt` | `Timestamp` | 턴 생성 시각 | FR-38 |

### `TurnResult` (턴 결과 union, 소유)
| 변형 | 조건 | 필드 |
|---|---|---|
| `TurnSuccessResult` | 근거형성 성공 | `{ outcome: EvidenceResult }` (D5 참조) |
| `TurnAbstainResult` | 근거 없음 / 범위 밖 | `{ outcome: EvidenceAbstainResult }` (D5 참조) |
| `TurnPendingResult` | 비동기 잡 처리 중 | `{ jobId: JobId, startedAt: Timestamp }` |
| `TurnErrorResult` | 시스템 오류 (타임아웃·LLM 실패) | `{ errorCode: string }` — 내부 상세 비노출(SEC-9) |

> **빈 성공 금지(INV-EV-2)**: `TurnSuccessResult`의 `EvidenceResult.claims`가 빈 배열이면 `TurnAbstainResult`로 처리. 근거 없는 성공 응답 금지.

---

## 2. 오케스트레이션 컨텍스트 (FR-37)

### `AgentRunContext` (실행 컨텍스트, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `session` | `EvidenceSession` | 현재 세션 (이전 턴 맥락 참조용) | FR-36 멀티턴 |
| `currentTurn` | `EvidenceTurn` | 처리 중인 턴 | FR-37 |
| `authSession` | `AuthSession` | 인증 주체 (게이트웨이·U3 위임 — SEC-8) | SEC-8 |
| `requestId` | `RequestId` | 추적·텔레메트리 상관키 | NFR-O1 |
| `budgetSignal` | `BudgetState` (참조) | 비용 게이트 입력 (U6 `get_budget_state()` 산출) | NFR-P6, NFR-C1 |

### `PaperSearchResult` (검색 결과, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `records` | `IndexRecord[]` (참조) | 검색된 논문 인덱스 레코드 (auto/mixed scope) | FR-37 |
| `queryUsed` | `string?` | 실제 사용된 검색 쿼리 (auto/mixed scope — 투명성) | SEC-9 (쿼리 요약만 노출) |
| `scope` | `EvidenceScope` (D5 참조) | 실제 적용된 검색 범위 | FR-37 |

> **불변식(INV-EV-3)**: `explicit` scope이면 `records`는 `paperIds`에 명시된 논문만 포함. 자동 검색 결과 혼입 금지.

### `AttachmentHandle` (첨부 핸들, 소유 — Q6=A)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `attachmentId` | `string` | 첨부 파일 임시 식별자 | FR-37, Q6=A |
| `mimeType` | `string` | 파일 타입 (pdf 등) | FR-37 |
| `sizeBytes` | `int` | 파일 크기 | 크기 한도 검증 |

> **불변식(INV-EV-4)**: 첨부 원시 파일은 저장하지 않는다 (C-1 준용). DocModel 추출 후 임시 처리 결과만 Agent 컨텍스트에 유지.

---

## 3. 추출 입력 (FR-37, C-2)

### `EvidenceExtractInput` (추출 입력, 소유)
| 필드 | 타입 | 의미 | 근거 |
|---|---|---|---|
| `topic` | `string` | 근거형성 주제 (원본 질문 그대로) | FR-37 |
| `docModelBlocks` | `DocModelBlock[]` (참조) | 대상 논문 DocModel 블록 목록 | FR-37, FR-18 |
| `paperIds` | `string[]` | 블록 출처 논문 ID 목록 | SourceRef 구성용 |

> **추출 경계(C-2)**: `EvidenceItem.statement`는 `docModelBlocks`에서 추출한 명제만 허용. LLM이 생성한 새로운 산문 삽입 금지. 원문에 없는 수치·주장을 만들어내는 것은 FR-5 위반(날조).

---

## 4. 세션 관리 (FR-38)

### `SessionDeleteCommand` (삭제 명령, 소유)
`{ sessionId, requestingUserId }` — AuthorizationGuard(U3)에 소유권 결정 위임 후 실행.

### `SessionResetCommand` (초기화 명령, 소유)
`{ requestingUserId }` — 해당 사용자의 모든 세션 삭제. 소유권 범위 초과 삭제 불가(INV-EV-1).

---

## 5. D5 참조 타입 요약 (재정의 금지)

| 타입 | SSOT | 의미 |
|---|---|---|
| `EvidenceRequest` | `shared/dtos/evidence.schema.json` | 근거형성 입력 (topic, scope, paperIds?, attachments?) |
| `EvidenceResult` | `shared/dtos/evidence.schema.json` | 성공 산출 (state=ok, claims[], coverage) |
| `EvidenceAbstainResult` | `shared/dtos/evidence.schema.json` | 기권 (state=abstain, abstainReason) |
| `EvidenceItem` | `shared/dtos/evidence.schema.json` | 근거 명제 (statement, supporting[], conflicting[]) |
| `EvidenceCoverage` | `shared/dtos/evidence.schema.json` | 사용 논문 수·쿼리 요약 |
| `SourceRef` | `shared/dtos/evidence.schema.json` | 출처 핸들 (paperId, recordRef, anchor?, quote?) |
| `EvidenceScope` | `shared/dtos/evidence.schema.json` | 검색 범위 (auto/explicit/mixed) |
| `BudgetState` | `shared/ports` (U6 소유) | 비용 게이트 신호 |
| `IndexRecord` | `shared/vector-spec` (U1 소유) | 코퍼스 인덱스 레코드 |

---

## 6. 값 타입

- `SessionId` · `TurnId` · `JobId` · `UserId` · `RequestId` · `Timestamp` · `AuthSession` — `shared/` 규약과 정합.
- `DocModelBlock` — U1 DocModel 계약(FROZEN) 참조. U11 재정의 금지.
