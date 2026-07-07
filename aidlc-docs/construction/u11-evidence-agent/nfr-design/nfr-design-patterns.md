# U11 Evidence Formation Agent — NFR Design Patterns (설계 패턴)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U11 Evidence Formation Agent · **일자**: 2026-06-30
**근거**: NFR Requirements(TD-E1~E11 · nfr-requirements.md) · FD(BR-EV-1~12 · INV-EV-1~5 · business-logic-model.md).
**고도**: 패턴·정책·범위. 수치(타임아웃 ms·서킷 임계·SQS 복잡도 임계·동시성 쿼터)는 Infra/Code-gen.

---

## 1. 복원력 패턴 (Resilience — RES-9 / NFR-R2)

### 1.1 Bedrock(LLM) 호출 격리
- **명시 타임아웃 + 1회 재시도(백오프) + 서킷브레이커** → 장애 시 `TurnErrorResult{ errorCode: "llm_unavailable" }`.
- **격리**: Bedrock 장애는 Agent 루프만 중단. 세션 조회·목록(RDS 경로)에 영향 없음.
- 재시도 1회로 폭주 방지. 수치(타임아웃·백오프·서킷 임계)는 Infra/Code-gen.

### 1.2 Tool 부분 실패 허용 (BR-EV-4)
- **DocModel 읽기(S3) 실패**: 해당 논문 건너뜀 → 나머지 논문으로 근거형성 계속(부분 실패 허용).
- **첨부 처리(AttachmentDocModelAdapter) 실패**: 해당 첨부 건너뜀 → 나머지 논문으로 계속.
- **OpenSearch(PaperSearch) 실패**: `IndexUnavailable` → `TurnAbstainResult{ abstainReason: "out_of_corpus" }` — fail-closed.
- **근거 0건**: INV-EV-2 — `TurnAbstainResult{ abstainReason: "insufficient_evidence" }` — fail-closed.

### 1.3 저하 3계층 구분 ⭐
세 가지를 **원인·행동·종단 상태·텔레메트리**로 명확히 분리:

| 계층 | 원인 | 트리거 | 종단 상태 | 신호 |
|---|---|---|---|---|
| **비용 degradeMode** | 예산 임계(spend ratio ≥ 0.80) | U6 `get_budget_state()` circuit_state가 non-normal | `TurnErrorResult{ errorCode: "cost_degraded" }` | NFR-C1(비용 폭발) |
| **LLM 서킷** | Bedrock 장애·타임아웃·스로틀 | 서킷 OPEN(1.1) | `TurnErrorResult{ errorCode: "llm_unavailable" }` | RES-9(가용성) |
| **코퍼스 저하** | OpenSearch 장애·논문 미수록·근거 0건 | PaperSearchTool 실패 또는 EvidenceExtractor 0건 | `TurnAbstainResult{ abstainReason: "out_of_corpus" | "insufficient_evidence" }` | NFR-R2 |

> **U7과의 차이**: U7은 `RERANK_OFF`·`LEXICAL_ONLY`에서 lexical 폴백으로 부분 응답 가능. U11은 Agent 추론이 LLM 필수 → non-normal degrade **전부 `cost_degraded` 일괄 처리**. 신호는 공유, **저하 매핑은 도메인별**.
> 셋은 **U6 단일 권위 비용 판정**(degradeMode)과 **U11 LLM 의존성 장애**(서킷)와 **코퍼스 가용성**(소스)으로 책임이 다르다. 통합 금지.

---

## 2. 성능 패턴 (Performance — NFR-P6)

### 2.1 Agent 스트리밍 패턴 ⭐
Agent 추론은 순차 LLM 호출 → 중간 생성 토큰 점진 전송:

```
Bedrock Converse 스트림 ──▶ [SSE 점진 전송](liveness·타임아웃 관리)
                                    ▼
                          Agent Tool 호출 결과 ──▶ 다음 추론 스트림
                                    ▼ (반복)
                          EvidenceExtractor ──▶ EvidenceComparisonAssembler
                                    ▼ claims 확정 후
                          INV-EV-3 검증(날조 금지) ──┬─ 통과 ─▶ 클라이언트(최종 claims 전송)
                                                      └─ 실패 ─▶ TurnAbstainResult
```

- **최종 claims 확정 전까지 노출 보류**(INV-EV-3) — 중간 추론 토큰은 스트리밍, 최종 claims는 검증 후만 전송.
- 구체 부분 렌더 전략·SSE 청크 크기는 Code-gen.

### 2.2 동기 vs 비동기 잡 분기 (BR-EV-6, TD-E6)
```
요청 수신
    ▼
복잡도 추정(paperIds 수 · 첨부 유무)
    ├─ 단순 ──▶ 동기 SSE 스트리밍 경로 (게이트웨이 타임아웃 내)
    └─ 복잡 ──▶ SQS enqueue → TurnPendingResult{ jobId } 즉시 반환
                    ▼
               [AgentWorker] 동일 EvidenceAgentOrchestrator 파이프라인 실행
                    ▼ 완료
               EvidenceSessionRepository.saveTurnResult(turnId, result)

[Client 폴링] GET /api/evidence/jobs/{jobId}
    ├─ 진행 중 ──▶ TurnPendingResult{ retryAfterMs }
    └─ 완료    ──▶ TurnSuccessResult | TurnAbstainResult
```

- **임계 기준(복잡도 추정) 수치 = Infra/Code-gen** (예: paperIds ≥ N 또는 첨부 유무).
- 비동기 잡도 동일 날조 금지·기권 규칙 적용(BR-EV-1, INV-EV-2, INV-EV-3).

### 2.3 세션 조회 응답성
- (ownerId, sessionId) 복합 인덱스 → DB 조회 수준 응답. 목록은 ownerId 단일 인덱스 + updatedAt 정렬.
- 세션 조회 경로는 LLM 미경유 → Bedrock 장애와 독립.

### 2.4 async I/O
Bedrock·OpenSearch·S3·RDS·SQS 외부 호출 async — Agent 루프 내 Tool 호출 중첩 가능. 구체 병렬화 전략은 Code-gen.

---

## 3. 확장성 패턴 (Scalability)

### 3.1 stateless Agent 모듈 + 공유 외부 상태
- Agent 모듈 **stateless** — 세션·턴 상태는 RDS(영속). backend 인스턴스 수평 복제 가능.
- Agent 실행 중 중간 상태는 메모리 내(AgentRunContext) → 인스턴스 고정 없음(단일 요청 내 완결).

### 3.2 워커 수평 확장
- 비동기 잡 워커(AgentWorker) = **별도 배포 단위**(SQS 소비 컨테이너). 큐 깊이 기반 Auto Scaling. 수치는 Infra.

### 3.3 Bedrock 동시성/쿼터
- async I/O + 계정 쿼터 내 동시 호출. `ThrottlingException` → 백오프/기권(1.1 경로 흡수). 쿼터·오토스케일은 Infra.

---

## 4. 보안 패턴 (Security — 방어심층)

| 위치 | 패턴 | 요구 |
|---|---|---|
| `EvidenceChatController`(진입) | 요청 검증(topic 길이·scope 유효값·paperIds 형식) | SEC-5 |
| `EvidenceAgentOrchestrator`(LLM 지시) | **본문 격리** `[지시]│[데이터]<paper>…</paper>` (프롬프트 인젝션 방어, C-2) | INV-EV-3 |
| `EvidenceExtractor`(출력) | **C-2 경계 강제** — DocModel 블록 미근거 항목 제거 | INV-EV-3 |
| `TurnResult` 직렬화(출력) | **SEC-9 비노출 필터** — 벡터 점수·청크 ID·LLM 내부 상태 차단 | INV-EV-5 |
| 전역 예외 핸들러(FastAPI) | **fail-closed** — 스택 트레이스·내부 상세 비노출 | INV-EV-5·SEC-9 |
| `EvidenceSessionRepository`(RDS) | **ownerId 스코프** — 타인 세션 교차 접근 차단(404) | INV-EV-1·SEC-9 |
| `AttachmentDocModelAdapter` | 추출 즉시 **원시 파일 폐기**(S3 임시 키 삭제) | INV-EV-4·C-1 |
| 로깅 | 원문·추출 명제·프롬프트 PII·저작권 무분별 로깅 금지 | SEC-3 |
| **위임** | 인증·레이트리밋 = U6 게이트웨이. 인가 = U3.AuthorizationGuard | SEC-8/11 |

---

## 5. 배포 · 복원력 테스트 (QT-8 / RES-12)

### 5.1 CI 레인 (real-first)
- **항상 실행**: 단위(pytest, **테스트 Fixture/Stub** + Hypothesis PBT-EV-1~5) + ruff + shared 드리프트 가드(evidence.schema.json·ports.py).
- **별도 게이트 레인**: 통합 테스트(실 Bedrock·OpenSearch·S3·RDS·SQS) — 자격증명 필요(Infra 구성), PR 게이트 또는 주기 실행.
- **backend 공유 CI/CD** — app-shell 조율 필요.

### 5.2 복원력 폴트 인젝션 (RES-12)
- Bedrock 장애/타임아웃 → `llm_unavailable`(1.1)
- OpenSearch 장애 → `out_of_corpus`(1.2)
- S3 DocModel 읽기 실패 → 부분 건너뜀(1.2)
- 비용 non-normal → `cost_degraded`(1.3)
- 근거 0건 → `insufficient_evidence` 기권(1.2, INV-EV-2)
- 날조 감지(C-2) → 해당 EvidenceItem 제거 → 0건이면 기권
- 인젝션 입력 → 본문 격리(§4)
- 실행 소유 = Build&Test/Operations.

---

## 6. 추적성 매트릭스

| 패턴 | NFR/요구 | BR/INV | 검증 |
|---|---|---|---|
| §1.1 Bedrock 격리 | RES-9, NFR-R2 | BR-EV-7, BR-EV-12 | 폴트 인젝션(5.2) |
| §1.2 Tool 부분 실패 | NFR-R2 | BR-EV-4, INV-EV-2 | 단위·통합 |
| §1.3 저하 3계층 | NFR-C1, RES-9, NFR-R2 | BR-EV-7, BR-EV-12 | 폴트 인젝션 |
| §2.1 Agent 스트리밍 | NFR-P6, FR-5 | BR-EV-6, INV-EV-3 | PBT-EV-3·통합 |
| §2.2 동기/비동기 분기 | NFR-P6 | BR-EV-6 | 통합 |
| §2.3 세션 응답성 | NFR-P6 | FR-36, FR-38 | 통합 |
| §3 stateless/워커 확장 | NFR-S | — | 통합 |
| §4 보안 방어심층 | SEC-3/8/9/11, C-1/C-2 | INV-EV-1~5 | PBT-EV-1~5·단위·통합 |
| §5 CI/복원력 | QT-8, RES-12 | PBT-EV-1~5 | CI |

**커버리지**: NFR-P6·NFR-C1·NFR-R2·NFR-O1·RES-9/12·QT-8·SEC-3/8/9/11·C-1/C-2·FR-5/36/37/38 (미커버 0).
