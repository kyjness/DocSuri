# U11 Evidence Formation Agent — Logical Components (논리 컴포넌트·토폴로지)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**근거**: NFR Requirements(TD-E1~E11) · FD(10 컴포넌트 — business-logic-model.md) · `nfr-design-patterns.md`.
**원칙**: FD 10 도메인 컴포넌트를 **논리(배포 가능) 컴포넌트**로 매핑(재계수 아님). real-first — 실 어댑터 단일본(+테스트 Fixture/Stub).

---

## 1. 토폴로지 (backend 모놀리스 ① 내 U11 모듈)

```
         [ U6 게이트웨이 ]  authn · authz(SEC-8) · rate-limit(SEC-11) · principal 주입
                 │ (마운트: backend/wiring.py — app-shell 조율 존)
                 ▼
  ┌───────────────────────────────────────────────────────────────────────────┐
  │  FastAPI U11 Router (EvidenceChatController)                              │
  │    POST /api/evidence/turns          — 채팅 턴(동기 SSE | 비동기 잡 전환) │
  │    GET  /api/evidence/sessions       — 세션 목록                          │
  │    DELETE /api/evidence/sessions/{id}— 세션 삭제                          │
  │    POST /api/evidence/sessions/reset — 전체 초기화                        │
  │    GET  /api/evidence/jobs/{jobId}   — 비동기 잡 폴링                     │
  └───────────────────────────────────────────────────────────────────────────┘
         │                                          │
         ▼                                          ▼
  EvidenceChatService                  EvidenceSessionManagementService
  (턴 오케스트레이션)                   (세션 CRUD)
         │                                          │ ← U3.AuthorizationGuard
         │   ┌── 복잡 요청 ──▶ SQS enqueue          ▼
         │   │                (TurnPendingResult)  EvidenceSessionRepository
         │   │                 [AgentWorker]        (RDS PostgreSQL)
         │   │                      │
         ▼   ▼                      ▼
  EvidenceAgentOrchestrator  (동기·비동기 공용)
         │ (자율 Tool 반복 호출)
  ┌──────┼──────────────────────────────────────┐
  ▼      ▼                                      ▼
EvidencePaperSearchTool    EvidenceDocModelTool  AttachmentDocModelAdapter
(U2 OpenSearch 클라이언트)  (S3 read-only)        (임시 S3 + DocModel 파이프라인 → 폐기)
         │                        │
         └──────────────┬─────────┘
                        ▼
               LLM(Bedrock Sonnet 4.6) — Converse 스트리밍
                        ▼
               EvidenceExtractor (INV-EV-3 C-2 경계 강제)
                        ▼
               EvidenceComparisonAssembler (비교표·쟁점 오버레이)
                        ▼
               EvidenceFormationService (D5 포트 구현 → U12 소비)

(비차단) ──▶ ObservabilityHub.emit*  (턴 지연·LLM 호출 횟수·토큰·비용·기권 사유)
(비용 게이트) CostGuardCircuitBreaker.get_budget_state()  ← LLM 호출 직전
```

---

## 2. 논리 컴포넌트 명세

| 논리 컴포넌트 | 책임 | 어댑터/스토어 | FD 컴포넌트 매핑 |
|---|---|---|---|
| **U11 Router** | REST 진입·요청 검증·SSE 스트리밍·폴링 응답 | FastAPI | `EvidenceChatController` |
| **EvidenceChatService** | 턴 오케스트레이션·세션 load/create·잡 분기 | — | `EvidenceChatService` |
| **EvidenceSessionManagementService** | 세션 목록·삭제·초기화. 소유권 = U3 위임 | U3.AuthorizationGuard | `EvidenceSessionManagementService` |
| **EvidenceAgentOrchestrator** | Agent 핵심 — Tool 자율 호출·멀티턴 맥락·LLM 추론 | Bedrock Converse 스트리밍 | `EvidenceAgentOrchestrator` |
| **EvidencePaperSearchTool** | 논문 검색(auto/explicit/mixed scope) | **OpenSearch**(U2 클라이언트 재사용) | `EvidencePaperSearchTool` |
| **EvidenceDocModelTool** | DocModel 블록 읽기(paperId+recordRef → S3) | **S3 read-only**(U1 소유 버킷) | `EvidenceDocModelTool` |
| **AttachmentDocModelAdapter** | 첨부 임시 처리 → DocModel 추출 → 원시 파일 즉시 폐기 | **S3 임시 업로드**(INV-EV-4) | `AttachmentDocModelAdapter` |
| **EvidenceExtractor** | LLM 출력 → EvidenceItem[] (C-2 날조 경계 강제) | — | `EvidenceExtractor` |
| **EvidenceComparisonAssembler** | EvidenceItem[] → 비교표·쟁점 오버레이·EvidenceResult 조립 | — | `EvidenceComparisonAssembler` |
| **EvidenceSessionRepository** | EvidenceSession·EvidenceTurn 영속화·소유자 격리 | **RDS PostgreSQL** | `EvidenceSessionRepository` |
| **EvidenceFormationService** | D5 포트 구현(`EvidenceFormationPort.form_evidence`) — U12 소비 | — | `EvidenceFormationService` |
| **AgentWorker** | SQS 소비 → 비동기 잡 실행(동일 Orchestrator 파이프라인) | **SQS**(별도 배포 단위) | — (인프라 컴포넌트) |
| **CostGate / Telemetry** | 비용 게이트·관측 | **Ports → U6**(`get_budget_state`·`emit*`) | 각 서비스 내 횡단 관심사 |

> **포트 + 실 어댑터 단일본**(real-first): 각 어댑터는 포트 인터페이스 구현이며 출하 구현은 실(OpenSearch·S3·RDS·SQS·Bedrock) 1종. **Production Mock Adapter 없음**; 단위 테스트는 테스트 Fixture/Stub로 포트 대체(출하 아님).

---

## 3. 데이터플레인 vs 컨트롤/텔레메트리 경계

- **동기 데이터플레인**(사용자 응답 경로): Router → ChatService → CostGate → Orchestrator → Tools → LLM → Extractor → Assembler → SSE 스트리밍 응답.
- **비동기 데이터플레인**: Router → ChatService → SQS enqueue → TurnPendingResult 즉시 반환. [AgentWorker] → 동일 Orchestrator 파이프라인 → RDS write.
- **세션 관리 플레인**: Router → SessionManagementService → U3.AuthorizationGuard → SessionRepository.
- **비차단 텔레메트리**(응답 경로 밖): `emit*` → `ObservabilityHub`(fire-and-forget). 발행 실패 = 응답 무영향.
- **비용 게이트**(데이터플레인 내, LLM 직전): `get_budget_state()` — 판정은 U6, U11은 분기만.

---

## 4. 신규 데이터 자산 (기존 인프라 재사용 + 신규 최소)

| 자산 | 용도 | 신규/기존 |
|---|---|---|
| **RDS PostgreSQL** `evidence_sessions` · `evidence_turns` 테이블 | 세션·턴 영속화(멀티턴·소유권 격리) | **신규 테이블** (기존 U3/U4/U7 DB와 공존) |
| **SQS** Evidence Agent Job Queue | 비동기 잡 오프로드 | **신규 큐** (U7 요약 큐와 분리) |
| **S3 임시 prefix** `evidence-attachments/tmp/{jobId}/` | 첨부 임시 업로드 → 추출 후 즉시 삭제 | **기존 버킷 재사용** (신규 prefix만) |
| **OpenSearch(U2 소유)** | 논문 검색 — U11은 read-only 소비자 | 기존 U2 자산(신규 인프라 0) |
| **S3(U1 소유)** DocModel 버킷 | DocModel 블록 read-only — U11은 소비자 | 기존 U1 자산(신규 인프라 0) |
| **Bedrock** Sonnet 4.6 | Agent 추론·추출 | 기존 IAM 액세스(U7 확장) |

> **신규 관리형 서비스**: RDS 테이블 DDL(마이그레이션) + SQS 큐 1개. 나머지 전부 기존 자산 재사용.
> 비용 라인·DDL·키 정책·IAM 상세 = **Infrastructure Design**.

---

## 5. 마운트·조율 경계

- U11 모듈은 `backend/modules/evidence_agent/`(독립 pyproject) → backend 모놀리스 app-shell 마운트(`backend/wiring.py`).
- **AgentWorker**(비동기) = `backend/workers/evidence_agent_worker/` → 별도 배포 단위(Infra CDK slice).
- **게이트**: `DOCSURI_EVIDENCE_ASYNC_ENABLED`(기본 OFF)·`DOCSURI_EVIDENCE_JOB_QUEUE_URL`. 미설정 시 async path 비활성.
- **조율 존**(`backend/wiring.py`·게이트웨이 라우팅)은 app-shell 담당자 사인오프 — U11은 마운트 계약 제안.
- **D5 공유 계약** `shared/dtos/evidence.schema.json`·`shared/ports/EvidenceFormationPort` = FROZEN. U11 재정의 금지.
