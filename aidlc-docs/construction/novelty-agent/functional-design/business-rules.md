# Novelty Agent — Business Rules

**Unit**: Novelty Agent  
**Stage**: Functional Design

## Business Rules

### BR-NV1 — Shared Contract Boundary

Novelty Agent는 문헌탐색·근거형성 Agent 내부 구현을 import하거나 재구현하지 않는다. 근거 입력은 `EvidenceFormationPort`와 `SourceRef` 공유계약으로만 받는다.

### BR-NV2 — Evidence First

모든 경로는 `EvidenceFormationPort` 결과를 1차 근거로 삼는다. `state=abstain`이면 근거 부족을 사용자에게 표시하고, 이후 검색은 재시도/보강 정책으로만 진행한다.

### BR-NV3 — Provisional Evidence Fields Are Optional

`EvidenceItem.conflicting`과 `EvidenceItem.confidence`는 현재 PROVISIONAL 계약의 optional 필드다. FD와 후속 코드는 이 두 필드가 없어도 동작해야 한다. 근거 상태는 우선 `EvidenceResult.state`, `coverage`, `SourceRef` 실재성에서 산출한다.

### BR-NV4 — Reuse U2 Full Search

U2 `full` 검색은 기존 API/포트를 재사용한다. novelty 전용 인덱스, 독자 랭킹 로직, 독자 검색 품질 판정은 만들지 않는다.

### BR-NV5 — Bounded Query Set

U2 full 검색 질의는 Evidence claim, 사용자 topic, 원고 섹션 요약에서 만든 bounded set으로 제한한다. 원고의 모든 chunk를 무제한 질의로 보내지 않는다.

### BR-NV6 — External Search Privacy Boundary

GitHub/데이터셋 검색에는 사용자 원문, Evidence 전체, 원고 전문을 보내지 않는다. 외부 검색 질의는 topic, 키워드, 익명화 요약, 논문 제목, 기술명 같은 최소 정보로 제한한다.

### BR-NV7 — v1 External Sources

v1 외부 검색 source는 GitHub와 데이터셋으로 제한한다. 최신 뉴스 검색은 다음 사이클 범위다.

### BR-NV8 — Deterministic Normalization and Dedupe

논문, GitHub, 데이터셋 결과는 `source_type`, canonical URL/ID, title, SourceRef anchor를 기준으로 정규화하고 중복 제거한다. 중복 제거를 LLM 자유 판단에 맡기지 않는다.

### BR-NV9 — No Unsupported Table Cells

유사 연구 표의 셀은 근거가 있을 때만 채운다. 근거가 없으면 `insufficient` 또는 `abstained`로 표시한다.

### BR-NV10 — No Novelty Score or Certainty Claim

Novelty Agent는 novelty score, "새로움 확정", 논문화 가능성 판정, 법적 표절 판정을 제공하지 않는다.

### BR-NV11 — Bounded Candidate Generation

차별화 후보는 기존 연구 한계, 데이터셋/코드 가능성, 사용자 topic/원고 의도 안에서만 생성한다. 모든 후보에는 supporting SourceRef 또는 external finding ref가 필요하다.

### BR-NV12 — Experiment Plan Required Fields

실험 계획은 hypothesis, novelty angle, baselines, datasets, metrics, procedure, risks, resources, source refs를 모두 포함해야 한다.

### BR-NV13 — Manuscript Risk Is Non-Blocking

문장 유사도와 AI 어투 경고는 별도 원고 위험 신호 섹션으로 표시한다. 위험 신호는 novelty candidate나 experiment plan 생성을 차단하지 않는다.

### BR-NV14 — AI Style Warning Is Not Probability

AI 어투 검사는 확정 판정이나 AI 작성 확률을 산출하지 않는다. span, 설명, false positive note를 포함한 검토 신호만 제공한다.

### BR-NV15 — Stage Snapshot Persistence

부분 결과는 stage별 artifact snapshot으로 저장한다. 최종 결과만 저장하는 방식은 재접속, 저하 표시, 진행상태 표시 요구를 만족하지 못한다.

### BR-NV16 — Source-Specific Degradation

GitHub, 데이터셋, U2 full, risk analyzer, LLM, Notion 실패는 가능한 한 source/stage별 `degraded`로 분리한다. 성공한 snapshot은 유지한다.

### BR-NV17 — Notion Export Requires Approval

Notion export는 내부 저장과 preview 이후 사용자 승인 없이는 실행하지 않는다. 자동 export는 금지한다.

### BR-NV18 — Owner-Scoped Delete

novelty session 삭제는 job metadata, 입력 참조, 단계 이벤트, partial/final artifacts, Notion export 상태를 owner-scoped로 삭제한다. 외부 Notion 페이지 삭제는 별도 선택이다.

### BR-NV19 — Anchor Validation Reuses Shared Logic

SourceRef와 DocModel anchor 검증은 `docmodel.md`의 Section/Block id와 `ports.md`의 공통 앵커 확인 방향을 따른다. novelty Agent가 별도 앵커 검증 정책을 새로 만들지 않는다.

## Progress State Rules

| Transition | Rule |
|---|---|
| `queued -> retrieving_corpus` | job 생성과 owner 검증 완료 후. |
| `retrieving_corpus -> searching_external` | EvidenceSnapshot 저장 후. |
| `searching_external -> summarizing_prior_work` | U2/external 결과 정규화 후. |
| `summarizing_prior_work -> checking_similarity` | 원고 입력일 때만. |
| `summarizing_prior_work -> forming_ideas` | 자연어 입력 또는 risk 분석 생략 시. |
| `checking_similarity -> forming_ideas` | risk snapshot 저장 후. |
| `forming_ideas -> planning_experiment` | novelty candidates 생성 후. |
| `planning_experiment -> exporting_notion` | 사용자가 export를 승인한 경우. |
| `planning_experiment -> completed` | export 미요청 또는 preview만 생성한 경우. |
| Any active state -> `degraded` | source/stage별 부분 실패가 있으나 결과 제공 가능. |
| Any active state -> `failed` | 필수 입력/근거/권한 문제로 더 진행 불가. |

## QT-10 Property Requirements

| ID | Property |
|---|---|
| PBT-NV1 | SourceRef DTO roundtrip preserves source identity and anchor. |
| PBT-NV2 | Source normalization is idempotent for paper, GitHub, and dataset artifacts. |
| PBT-NV3 | Dedupe is idempotent and preserves one representative per canonical key. |
| PBT-NV4 | Job state transition rejects invalid edges and terminal-state reentry. |
| PBT-NV5 | ExperimentPlan always contains required fields and source refs. |
| PBT-NV6 | Owner isolation keeps jobs, inputs, artifacts, and export states separated. |
| PBT-NV7 | Notion export cannot reach `exported` without preview and approval. |

## Security Compliance

| Rule | Status | Rationale |
|---|---|---|
| SECURITY-03 | Compliant | Logs/telemetry are restricted to non-PII operational summaries; raw manuscript and tokens are excluded. |
| SECURITY-05 | Compliant | Request envelope, input type, attachment refs, state transitions, and export state require validation. |
| SECURITY-08 | Compliant | Job, input, artifact, delete, and export state are owner-scoped. |
| SECURITY-09 | Compliant | User-facing failures hide internal parser/tool/MCP details. |
| SECURITY-11 | Compliant | External search privacy boundary and misuse cases are defined. |
| SECURITY-12 | Compliant | Notion token handling is delegated to user OAuth/explicit connection with encrypted storage in NFR/Infra. |
| SECURITY-14 | Compliant | Delete/export approval and audit-relevant events are identified. |
| SECURITY-15 | Compliant | Source-specific failure behavior and safe user-facing errors are defined. |
| SECURITY-01/02/04/06/07/10/13 | N/A at FD | Storage encryption, network logs, headers, IAM, dependency pinning, and CI integrity are NFR/Infra/Code concerns. |

## Resiliency Compliance

| Rule | Status | Rationale |
|---|---|---|
| RESILIENCY-01 | Compliant | Critical job orchestration, U2, Agent-Browser, LLM, Notion, and persistence dependencies are identified. |
| RESILIENCY-05 | Compliant | Progress events and source-specific degraded states define observability signals. |
| RESILIENCY-09 | Compliant | Bounded query set and per-job budget boundary are captured for later capacity controls. |
| RESILIENCY-10 | Compliant | Source-specific degraded behavior prevents cascading failure from non-critical dependencies. |
| RESILIENCY-02/03/04/06/07/08/11/12/13/14/15 | N/A at FD | Recovery targets, deployment, health checks, DR, and incident runbooks are NFR/Infra/Ops concerns or already captured globally. |

## PBT Compliance

| Rule | Status | Rationale |
|---|---|---|
| PBT-01 | Compliant | PBT-NV1..PBT-NV7 identify roundtrip, idempotence, invariant, and state transition properties. |
| PBT-02/03/07/08/09 | Deferred | Enforced in Code Generation/NFR Requirements per partial PBT mode. |
| PBT-04/05/06/10 | Advisory/N/A | Current partial mode does not block on these; idempotence and state transition candidates are still captured. |

## Traceability Matrix

| Requirement / Story | Rules |
|---|---|
| FR-30 | BR-NV1, BR-NV2 |
| FR-31 | BR-NV2, BR-NV4, BR-NV5, BR-NV6, BR-NV7, BR-NV8 |
| FR-32 | BR-NV3, BR-NV9, BR-NV10, BR-NV11 |
| FR-33 | BR-NV12 |
| FR-34 | BR-NV13, BR-NV14 |
| FR-35 | BR-NV15, BR-NV16, BR-NV17, BR-NV18 |
| QT-10 | PBT-NV1..PBT-NV7 |
| US-NV1..US-NV9 | BR-NV1..BR-NV19 |
