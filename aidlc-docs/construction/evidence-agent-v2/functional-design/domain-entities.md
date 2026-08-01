# Evidence Agent v2 (U11) — 도메인 엔티티 (Domain Entities)

**단계**: CONSTRUCTION → Functional Design (재설계 라운드) · **유닛**: U11 문헌탐색·근거형성 · **일자**: 2026-07-28
**원칙**: **기술 무관**. 비즈니스 의미만 정의하고 구체 기술(LLM 프로바이더·S3·RDS·SSE·큐)은 NFR/Infra에서 바인딩한다.
**근거**: 요구사항 게이트 `requirement-verification-questions-evidence-agent-v2.md`(Q1~Q15) · FD 게이트 `plans/evidence-agent-v2-functional-design-plan.md`(Q1~Q12) · `requirements.md` FR-36~38·FR-45~47 · `shared/dtos/evidence.schema.json`(D5) · v1 frozen `construction/u11-evidence-agent/`.
**v1 대비**: 세션·턴·D5 참조 타입은 승계한다. 신설은 **루프 상태·결정 트레이스·출처 핸들 3종·근거 누적기**이며, `PaperSearchResult`(단발 검색 결과)와 `EvidenceExtractInput`(일괄 추출 입력)은 루프 구조에서 의미를 잃어 폐기한다.

---

## 0. 엔티티 관계 한눈에 보기

```
EvidenceSession ──(1:N)──▶ EvidenceTurn
                                │
                       EvidenceRequest (D5 참조)
                                │
                          AgentRunContext ──▶ LoopBudget
                                │
                    ┌───────────┴────────────┐
                 LoopState              ToolCallRecord[]   (FR-46 트레이스)
                    │                        │
              PaperHandle[]            (진행 활동 피드의 원천)
                    │
            EvidenceAccumulator  ◀── 게이트 통과분만 누적
                    │
            ┌───────┴────────┐
       (근거 있음)      (근거 없음)
            ▼                ▼
     EvidenceResult   EvidenceAbstainResult   (D5 참조 — SSOT: evidence.schema.json)
            │
            └──────▶ TurnResult (턴에 저장)
```

- **소유(생산) 타입**: U11이 정의·생산한다.
- **참조(D5) 타입**: `shared/dtos/evidence.schema.json` — U11이 재정의(포크) 금지. 본 라운드에서 `SourceRef`에 두 필드가 **추가 개정**된다(§4).

---

## 1. 세션 · 턴 (FR-36, FR-38)

### `EvidenceSession` (세션, 소유 — v1 승계)
| 필드 | 타입 | 의미 |
|---|---|---|
| `sessionId` | `SessionId` | 세션 식별자 |
| `ownerId` | `UserId` | 소유자 — 생성 후 변경 불가(INV-EV-1) |
| `title` | `string?` | 첫 질문에서 도출 또는 사용자 입력 |
| `turns` | `EvidenceTurn[]` | 멀티턴 이력(시간순) |
| `createdAt` · `updatedAt` | `Timestamp` | |
| `status` | `enum{active, deleted}` | 소프트 삭제 |

### `EvidenceTurn` (턴, 소유 — v2 개정)
| 필드 | 타입 | 의미 | v1 대비 |
|---|---|---|---|
| `turnId` · `sessionId` | id | | 승계 |
| `request` | `EvidenceRequest`(D5) | 사용자 입력 | 승계 |
| `result` | `TurnResult` | 턴 결과 | **전용 필드로 승격**(v1은 `attachments` JSON에 실었다 — 저장 스키마 부채) |
| `trace` | `ToolCallRecord[]` | 이 턴 루프의 결정 트레이스 | **신설**(FR-46) |
| `createdAt` | `Timestamp` | | 승계 |

### `TurnResult` (턴 결과 union, 소유 — v1 승계)
| 변형 | 조건 | 필드 |
|---|---|---|
| `TurnSuccessResult` | 근거 1건 이상 | `{ outcome: EvidenceResult }` |
| `TurnAbstainResult` | 근거 없음 / 범위 밖 | `{ outcome: EvidenceAbstainResult }` |
| `TurnPendingResult` | 비동기 잡 처리 중 | `{ jobId, startedAt }` |
| `TurnErrorResult` | 시스템 오류 | `{ errorCode }` — 내부 상세 비노출(SEC-9) |

> **터미널 상태는 2종을 유지한다**(FD 게이트 Q10·요구사항 게이트 Q10). 탐색이 완결되지 않은 경우는 세 번째 상태가 아니라 `EvidenceCoverage`의 **확인 범위**로 표현한다(§4).

---

## 2. 루프 실행 상태 (FR-37 v2, FR-45, FR-46)

### `AgentRunContext` (실행 컨텍스트, 소유 — v2 개정)
| 필드 | 타입 | 의미 | v1 대비 |
|---|---|---|---|
| `session` | `EvidenceSession` | 이전 턴 맥락 | 승계 |
| `currentTurn` | `EvidenceTurn` | 처리 중인 턴 | 승계 |
| `authSession` | `AuthSession` | 인증 주체(U3 위임) | 승계 |
| `requestId` | `RequestId` | 추적 상관키 | 승계 |
| `budgetSignal` | `BudgetState`(U6) | 비용 게이트 입력 | 승계 |
| `budget` | `LoopBudget` | 이 턴의 3중 한도 | **신설**(FR-45) |
| `attachmentDocs` | `AttachmentDoc[]` | 첨부 문서 핸들 | 승계(INV-EV-4) |

### `LoopBudget` (루프 예산, 소유 — 신설, FR-45)
| 필드 | 의미 |
|---|---|
| `maxIterations` | 루프 반복 상한 |
| `toolCaps` | 도구별 호출 상한(`corpus_search`·`external_search`·`fetch_paper`·`read_paper`·`view_figure`·`extract_evidence`) |
| `tokenBudget` | 토큰·비용 한도 — U6 예산 상태에 종속 배분 |
| `spent` | 소비 현황(반복 수·도구별 호출 수·누적 토큰) |

> **비용 판정은 U6 단일 권위**(NFR-C1). `LoopBudget`은 U6가 준 상태를 이 턴에 배분한 것이지 자체 비용 판단이 아니다. 구체 수치는 NFR Requirements.

### `LoopState` (루프 상태, 소유 — 신설)
| 필드 | 의미 |
|---|---|
| `iteration` | 현재 반복 회차 |
| `papers` | `PaperHandle[]` — 지금까지 확보한 논문 |
| `accumulator` | `EvidenceAccumulator` — 게이트를 통과한 근거 |
| `lastObservations` | 최근 도구 결과 요약(관찰 윈도우) |
| `pendingImages` | 이번 `decide`에 실릴 이미지 첨부 — **소비 후 즉시 폐기**(1회성) |
| `terminationReason` | `enum{ sufficient, budget_exhausted, no_evidence, fatal_error }?` |

> **관찰에는 호출 인자가 함께 실린다** — 결과만 보이면 모델이 그것이 어떤 호출에서 나왔는지 몰라 같은 질의를 반복한다(novelty ⑤3 실측 교훈).
> **이미지 첨부는 1회성** — 지우지 않으면 관찰 윈도우에 남는 동안 매 턴 재전송되어 같은 토큰이 반복 계상된다(BR-RA11 선례).

### `ToolCallRecord` (결정 트레이스 1건, 소유 — 신설, FR-46)
| 필드 | 의미 |
|---|---|
| `seq` | 턴 내 순번 |
| `tool` | 호출한 도구명 |
| `argsSummary` | 인자 요약(질의문·논문 id 등) — **sanitized**, 원문 payload 금지(SEC-9) |
| `outcome` | `enum{ ok, empty, error, gate_rejected, budget_denied }` |
| `resultSummary` | 결과 요약(건수·상태) — claim/quote 텍스트 금지(INV-EV-3 진행 노출 경계) |
| `costUsd?` · `tokens?` | 비용 계상 |
| `at` | 시각 |

> 이 레코드가 **진행 활동 피드의 유일한 원천**이다(FD 게이트 Q7=A). 별도 이벤트 스트림을 두지 않는다.

---

## 3. 출처 핸들 (FR-31 등급 체계, FR-47)

### `PaperHandle` (확보한 논문 1편, 소유 — 신설)

루프가 확보한 논문의 출처·근거 범위를 하나로 표현한다. v1의 `PaperSearchResult`(단발 검색 결과 묶음)를 대체한다.

| 필드 | 의미 |
|---|---|
| `paperId` | 표시용 식별자. 코퍼스=arXiv id / 외부=`arxiv:{id}v{n}`(**버전 고정**) / 첨부=`userdoc:{uuid}` |
| `recordRef` | 실재성 검증 핸들. 코퍼스=`IndexRecord` id / 외부=`external:arxiv:{id}v{n}` / 첨부=`upload:{ownerId}:{jobId}:{attachmentId}` |
| `origin` | `enum{ corpus, external, attachment }` |
| `scope` | `enum{ fulltext, abstract }` — 본문을 확보했는가 |
| `docModel` | `DocModel?` — `scope=fulltext`일 때만 존재 |
| `abstractText` | `string?` — `scope=abstract`일 때의 대조 텍스트(**그 턴 안에서만 유효**, 영속 저장하지 않는다) |

> **외부 논문의 초록 원문은 보관하지 않는다**(FD 게이트 Q5=A). 인용 시점 검증은 그 자리에서 끝나고, 사후 감사는 **버전 고정 식별자로 재취득**해 대조한다 — arXiv은 개정 후에도 모든 버전을 보존한다.
> **`scope=fulltext`인 핸들은 반드시 `docModel`을 갖는다**(PBT 대상 — 범위 표기 불변).

### `PromotionOutcome` (승격 결과, 소유 — 신설)

`fetch_paper`의 결과. 실패해도 탐색은 계속된다.

| 값 | 의미 | 후속 |
|---|---|---|
| `promoted` | 본문 취득 + DocModel 생성 성공 | 핸들이 `fulltext`로 승격, 색인은 백그라운드 |
| `license_blocked` | OA·허용 라이선스 아님 | `abstract` 범위 유지 |
| `parse_failed` | 취득·파싱 실패 | `abstract` 범위 유지 |

---

## 4. 근거 누적과 D5 계약

### `EvidenceAccumulator` (근거 누적기, 소유 — 신설)

`extract_evidence`가 게이트를 통과시킨 `EvidenceItem`만 쌓인다. 루프의 종료 판단 입력이다(FD 게이트 Q2=A).

| 필드 | 의미 |
|---|---|
| `items` | `EvidenceItem[]`(D5) — 검증 통과분만 |
| `citedPapers` | 인용된 `PaperHandle` 집합 |
| `conflictSeen` | 상충 출처가 하나라도 잡혔는가 |
| `rejected` | 게이트가 떨어뜨린 건수·사유 분포 — 사용자 비노출, 트레이스·관측용 |

> **누적기를 거치지 않고 결과에 들어가는 근거는 없다**(INV-EV-3 강제 지점).

### D5 참조 타입 — 본 라운드 개정 (FR-47)

`SourceRef`에 두 필드를 추가한다. 나머지 타입은 변경 없다.

| 필드 | 값 | 의미 |
|---|---|---|
| `anchorType` | `paragraph\|list\|code\|table\|figure\|formula` | 인용한 DocModel 블록의 종류 — FE 칩 라벨("표 3"·"그림 2"·"식 4")과 소비자 분기의 근거 |
| `sourceScope` | `fulltext\|abstract\|figure` | **근거 범위**. `fulltext`=원문 verbatim 인용 / `abstract`=초록 범위 인용 / `figure`=그림 해석 기반(인용문이 아님) |

> **범위는 출처 단위다** — 한 답변에 세 종류가 섞이므로 결과 단위인 `EvidenceCoverage`에 둘 수 없다.
> **하위호환**: 둘 다 선택 필드다. U12의 저장 게이트는 `recordRef` 실재성만 보므로 추가 필드를 무시해도 안전하다(FD 게이트 Q10=A).

### `EvidenceCoverage` 개정 — 확인 범위

| 필드 | 의미 | 비고 |
|---|---|---|
| `paperCount` | 근거 추출에 사용된 논문 수 | 승계 |
| `queryUsed` | 사용된 검색 질의 요약 | 승계 — 루프는 질의가 여럿이므로 **대표 질의 목록**으로 해석 |
| `examined` / `candidates` | 확인한 논문 수 / 후보 논문 수 | **신설** — 탐색 미완결 표면화 |
| `stoppedReason` | `enum{ sufficient, budget_exhausted, partial_failure }?` | **신설** — 비기술 사유만(SEC-9) |

> 화면 문구는 내부 용어(`degraded` 등)를 쓰지 않고 수치로 쓴다: *"관련 논문 12편 중 5편까지 확인했습니다."*

---

## 5. D5 참조 타입 요약 (재정의 금지)

| 타입 | SSOT | 본 라운드 |
|---|---|---|
| `EvidenceRequest` · `EvidenceResult` · `EvidenceAbstainResult` · `EvidenceItem` · `EvidenceScope` | `shared/dtos/evidence.schema.json` | 변경 없음 |
| `SourceRef` | 〃 | **개정** — `anchorType`·`sourceScope` 추가 |
| `EvidenceCoverage` | 〃 | **개정** — `examined`·`candidates`·`stoppedReason` 추가 |
| `BudgetState` | `shared/ports`(U6) | 소비만 |
| `IndexRecord` | `shared/vector-spec`(U1) | 소비만 |
| `DocModel` · `Block` | U1 DocModel 계약(FROZEN) | 소비만 — 전 블록 타입이 인용 대상(FR-47) |

## 6. 값 타입

`SessionId` · `TurnId` · `JobId` · `UserId` · `RequestId` · `Timestamp` · `AuthSession` — `shared/` 규약과 정합.

## 7. v1에서 폐기하는 엔티티

| 엔티티 | 폐기 사유 |
|---|---|
| `PaperSearchResult` | 단발 검색 1회를 전제한 묶음 — 루프는 검색을 반복하므로 `PaperHandle` 집합으로 대체 |
| `EvidenceExtractInput` | 일괄 추출 1회를 전제 — `extract_evidence` 도구 인자로 흡수 |
| `QueryIntent`(정규식 의도 분류) | 질의 해석이 루프의 LLM 판단으로 이관(FR-36 v2 개정) |
