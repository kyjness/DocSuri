# U11 Evidence Formation Agent — 비즈니스 로직 모델 (Business Logic Model)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**원칙**: 기술 무관 — 알고리즘·흐름·정책 **형태(shape)** 만. 수치(타임아웃·청크 크기·재시도 횟수·비동기 임계)와 구체 기술(Bedrock·S3·RDS·SQS·SSE)은 NFR/Infra.
**근거**: `inception/application-design/component-dependency.md §7` · `domain-entities.md` · `business-rules.md` · `shared/dtos/evidence.schema.json` (D5 FROZEN) · `shared/ports/README.md §4`.

---

## 1. 서비스 · 컴포넌트

| 컴포넌트 | 역할 |
|---|---|
| `EvidenceChatService` | 채팅 턴 오케스트레이션. 세션 load/create·Agent 실행 위임·턴 결과 저장·스트리밍. |
| `EvidenceSessionManagementService` | 세션 CRUD (목록·삭제·초기화). 소유권 결정은 U3.AuthorizationGuard 위임. |
| `EvidenceAgentOrchestrator` | Agent 핵심 — Tool을 자율 순서로 반복 호출해 EvidenceResult/EvidenceAbstainResult 생산. |
| `EvidenceFormationService` | D5 포트 구현체 — `EvidenceFormationPort.form_evidence`를 구현해 U12에 노출. |
| `EvidenceSessionRepository` | EvidenceSession·EvidenceTurn 저장·조회 (소유자 격리 보장). |
| `EvidencePaperSearchTool` | 논문 검색 Tool — scope에 따라 Vector Store 검색 (auto/mixed). |
| `EvidenceDocModelTool` | DocModel 블록 읽기 Tool — paperId+recordRef 기반 S3 read. |
| `AttachmentDocModelAdapter` | 첨부 파일 일시 처리 — DocModel 추출 후 원시 파일 폐기 (INV-EV-4). |
| `EvidenceExtractor` | DocModel 블록 → EvidenceItem 추출 (C-2 경계 강제). |
| `EvidenceComparisonAssembler` | EvidenceItem[] → 비교표·쟁점 오버레이 조립 (Q2=A). |

---

## 2. 채팅 턴 파이프라인 (FR-36, FR-37, NFR-P6)

```
[U6 GATEWAY] authn · authz(SEC-8) · rate-limit(SEC-11) · cost-state(NFR-C1)
      ▼
0. loadOrCreateSession    EvidenceSessionRepository: sessionId 있으면 load, 없으면 신규 생성
      ▼
1. costGate               CostGuardCircuitBreaker.get_budget_state() (U6 단일 권위)
      ├─ OPEN/저하 ──▶ TurnErrorResult{ errorCode: "cost_degraded" } 반환
      ▼ NORMAL
2. validateAttachments    AttachmentDocModelAdapter: 형식·크기 검증 (BR-EV-4)
      ├─ 실패 ──▶ 즉시 에러 반환 (Agent 실행 금지)
      ▼ 통과
3. routeLength            요청 복잡도 추정 (paperIds 수·첨부 유무)
      ├─ 단순 ──▶ 동기 스트리밍 경로 (step 4~)
      └─ 복잡 ──▶ 비동기 잡 경로 (step 3a)
          3a. enqueue → TurnPendingResult{ jobId } 반환 → Worker가 step 4~ 실행
      ▼
4. agentRun               EvidenceAgentOrchestrator.run(request, agentRunContext)
      ▼ (자율 순서로 반복 호출)
    4a. paperSearch        EvidencePaperSearchTool: scope에 따라 논문 검색 (BR-EV-2)
    4b. docModelRead       EvidenceDocModelTool: 검색 결과 논문 DocModel 블록 읽기
    4c. attachmentProcess  AttachmentDocModelAdapter: 첨부 DocModel 추출 (Q6=A)
    4d. llmExtract         LLM Gateway: DocModel 블록 → 근거 명제 추출 지시
    4e. extract            EvidenceExtractor: LLM 출력 → EvidenceItem[] (INV-EV-3 강제)
    4f. assemble           EvidenceComparisonAssembler: EvidenceItem[] → 비교표·쟁점 오버레이
      ▼
5. abstainCheck           claims=[] → EvidenceAbstainResult (INV-EV-2, BR-EV-1)
      ▼
6. appendTurn             EvidenceSessionRepository.appendTurn(turn with TurnResult)
      ▼ SSE stream
[ 클라이언트(U5): 비교표·쟁점 오버레이 점진 렌더 ]
```

---

## 3. 컴포넌트별 알고리즘

### 3.1 `EvidenceChatService`
- 세션 load(기존 sessionId) 또는 create(첫 질문) — `EvidenceSessionRepository` 위임.
- `AgentRunContext` 구성: 세션 이전 턴 목록(멀티턴 맥락), 인증 주체, 비용 신호, requestId.
- `EvidenceAgentOrchestrator.run()` 위임 → 결과 수신.
- 결과를 `TurnResult`로 래핑 후 `appendTurn`.
- **스트리밍**: Orchestrator 진행 중 생성 토큰을 점진 전송. 결과 확정 전까지 최종 claims 노출 보류(INV-EV-3).

### 3.2 `EvidenceAgentOrchestrator`
- Tool을 **자율 순서로** 반복 호출해 충분한 근거를 수집할 때까지 탐색.
- 멀티턴 맥락(`AgentRunContext.session.turns`)을 참조해 이전 턴 논문·근거를 재활용(BR-EV-3).
- **추출 경계(INV-EV-3)**: LLM 추출 지시에 "논문 DocModel 블록 내용만 근거로 사용, 없는 내용 생성 금지" 명시.
- 근거 수집 완료 → `EvidenceExtractor` → `EvidenceComparisonAssembler` 순 실행.
- 수집 실패·범위 밖 → `EvidenceAbstainResult` 직접 생성.
- LLM 장애·타임아웃 → 정의된 재시도 후 `TurnErrorResult` (수치=NFR).

### 3.3 `EvidencePaperSearchTool`
- `scope=auto/mixed`: topic으로 Vector Store 하이브리드 검색 → `IndexRecord[]` 반환.
- `scope=explicit`: `paperIds` 목록으로 직접 조회 (자동 검색 금지 — BR-EV-2, INV-EV-3).
- `scope=mixed`: auto 검색 결과 + explicit 목록 병합 → paperId 기준 중복 제거.
- 검색 실패(Vector Store 장애) → `IndexUnavailable` → Orchestrator에 전달 → 기권.

### 3.4 `EvidenceDocModelTool`
- `paperId` + `recordRef` 기반으로 DocModel JSON 읽기 (S3 read-only, U1 단일 writer).
- DocModel 없음(코퍼스 미수록·파싱 미완) → 해당 논문 건너뜀. Orchestrator가 나머지 논문으로 계속.

### 3.5 `AttachmentDocModelAdapter` (Q6=A)
- 첨부 파일을 DocModel 파이프라인(U1 패턴 재사용)으로 일시 처리.
- 추출 완료 즉시 **원시 파일 폐기** (INV-EV-4).
- 처리 실패 → 해당 첨부 건너뜀·나머지 논문으로 계속 (BR-EV-4 부분 실패 허용).

### 3.6 `EvidenceExtractor`
- LLM 출력에서 `EvidenceItem{ statement, supporting[], conflicting[] }` 파싱.
- **C-2 경계 강제**: `statement`가 입력 DocModel 블록 원문에 근거하지 않으면 해당 항목 제거.
- `SourceRef` 구성: `paperId` + `recordRef` + `anchor?` + `quote?` (내부 벡터·점수 미포함 — INV-EV-5).

### 3.7 `EvidenceComparisonAssembler`
- `EvidenceItem[]`를 **논문 간 비교형**으로 재편 (동일 주제 지지·상충 병치 — BR-EV-5, Q2=A).
- 쟁점 오버레이: `conflicting`이 있는 명제를 별도 강조.
- `EvidenceCoverage{ paperCount, queryUsed? }` 산출 (내부 점수 미포함 — INV-EV-5).
- 최종 `EvidenceResult{ state: ok, claims, coverage }` 조립.

### 3.8 `EvidenceSessionManagementService`
- **목록 조회**: `EvidenceSessionRepository.listByOwner(userId)` → `updatedAt` 내림차순 반환.
- **삭제**: U3.AuthorizationGuard 소유권 확인 → `EvidenceSessionRepository.softDelete(sessionId)` (BR-EV-8). 타인 세션 → 404 (INV-EV-1).
- **초기화**: `EvidenceSessionRepository.deleteAllByOwner(userId)` (BR-EV-9). 본인 세션만 삭제.

### 3.9 `EvidenceFormationService` (D5 포트 구현 — U12 소비)
- `EvidenceFormationPort.form_evidence(request, ctx)` 구현.
- 내부적으로 `EvidenceAgentOrchestrator.run(request, ctx)` 위임.
- 긴 분석: Job Queue에 발행 후 완료 대기 (U12 소비 시에는 동기 완료 보장 필요 — 비동기 내부 처리).
- **U12는 이 추상에만 의존** — U11 구체 모듈 직접 import 금지 (shared/ports §4 순환 차단).

---

## 4. 비동기 잡 경로 (NFR-P6, Q9=A)

```
EvidenceChatService
      │ 복잡 요청 감지
      ▼
  Job Queue enqueue(jobId, EvidenceRequest, sessionId, turnId)
      │
      ▼ 즉시 반환
  TurnPendingResult{ jobId, startedAt }

[Worker]
      ▼
  EvidenceAgentOrchestrator.run(...)  ← 동일 파이프라인
      ▼ 완료
  EvidenceSessionRepository.saveTurnResult(turnId, result)

[Client 폴링]
  GET /api/evidence/jobs/{jobId}
      ├─ 진행 중 ──▶ TurnPendingResult{ retryAfterMs }
      └─ 완료    ──▶ TurnSuccessResult | TurnAbstainResult
```

- 비동기 잡도 **동일 날조 금지·기권 규칙 적용** (BR-EV-1, INV-EV-2, INV-EV-3).
- 잡 enqueue는 best-effort (요청 경로 비차단).

---

## 5. 멀티턴 맥락 흐름 (FR-36)

```
[1번째 턴] topic="딥러닝 단백질 구조 예측" → EvidenceResult(claims=[A,B,C])
      ▼ 세션 저장

[2번째 턴] topic="AlphaFold2 관련만 더 자세히" → AgentRunContext.session.turns=[1번째]
      ├─ Orchestrator가 이전 턴 논문(claims의 SourceRef)을 우선 참조
      └─ 추가 검색 필요 시 PaperSearchTool 재호출
      ▼ EvidenceResult(claims=[A', D])  ← A를 더 구체화 + 신규 D
```

---

## 6. 이벤트 경로 (비차단 — NFR-O1)

- 각 채팅 턴 완료 후 `채팅 턴 지연·에러·스트리밍 건강도` → `ObservabilityHub.emitMetric/emitLog` (U6 단일 권위).
- **응답 경로 밖** (fire-and-forget). 발행 실패는 응답에 영향 없음.

---

## 7. 추적성 매트릭스

| 서비스/컴포넌트 | 요구사항 | 스토리 |
|---|---|---|
| EvidenceChatService · EvidenceSessionRepository (세션·멀티턴) | FR-36 | US-EV1, US-EV5 |
| EvidenceAgentOrchestrator · PaperSearchTool · DocModelTool · EvidenceExtractor · ComparisonAssembler (다논문 근거형성·추출) | FR-37, FR-5, C-2 | US-EV2, US-EV3, US-EV4 |
| EvidenceAgentOrchestrator abstain 경로 (기권) | FR-5, FR-37, SEC-9 | US-EV6 |
| EvidenceChatService 비동기 잡 · TurnPendingResult (스트리밍·비차단) | NFR-P6 | US-EV2, US-EV9 |
| EvidenceSessionRepository · AttachmentDocModelAdapter (첨부 일시 처리) | FR-37, C-1 | US-EV4 |
| EvidenceSessionManagementService (세션 목록·삭제·초기화) | FR-38, SEC-8 | US-EV7, US-EV8 |
| EvidenceFormationService (D5 포트 구현) | D5, FR-37 | — (U12 소비) |
| CostGate (비용 게이트) | NFR-C1 | US-EV9 |
| ObservabilityHub emit (관측성) | NFR-O1 | US-EV9 |

**커버리지**: FR-36·37·38 · FR-5 · NFR-P6 · NFR-C1 · NFR-O1 · SEC-8/9/11 · C-1/C-2 · D5 · US-EV1~EV9 전수 매핑 (미커버 0).
