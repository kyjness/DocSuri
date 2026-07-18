# Novelty Agent v2 — Domain Entities

**Unit**: Novelty Agent v2 (U12)
**Stage**: Functional Design (재설계 라운드, 2026-07-18)
**Scope**: 자연어 연구 주제 또는 업로드 원고에서 자율 도구 호출 루프로 **조사 + 여백 분석**을 생성하고, 대화 요청 시 방향 제안·실험 계획을 온디맨드로 추가 생성하는 에이전트의 도메인 모델. 구현 기술, 저장소, 큐, MCP 서버 선정은 후속 NFR/Code 단계로 둔다.
**기준선**: `construction/novelty-agent/functional-design/domain-entities.md` (v1 frozen). 각 엔티티에 **승계/개정/신설/폐기**를 명시한다.

## Entity Model

### NoveltyJob (승계·개정)

사용자별 novelty 조사 작업의 루트 aggregate.

| Field | Required | Rule |
|---|---:|---|
| `job_id` | Yes | 작업 고유 ID. |
| `owner_id` | Yes | owner-scoped 사용자 ID. |
| `request` | Yes | `NoveltyJobRequest`. |
| `state` | Yes | **거시 상태**(`ProgressState` 참조) — 구 11종 enum 대체. |
| `artifacts` | Yes | 산출물 참조 목록(종류별 최신 검증본). 구 `stage_snapshots` 대체 — 단계가 아니라 **산출물 단위**로 저장. |
| `loop_run` | Yes | `AgentLoopRun` — 루프 실행·예산 상태. |
| `degraded_sources` | No | source별 저하 기록(BR-NV16 승계). |
| `created_at` / `updated_at` | Yes | 상태 전이·산출물 저장·트레이스 기록 시 갱신. |
| `completed_at` | No | 종단 상태(`completed`, `partial`, `failed`, `cancelled`) 시 설정. |

### NoveltyJobRequest (승계·개정)

| Field | Required | Rule |
|---|---:|---|
| `input_type` | Yes | `natural_language` 또는 `manuscript`. |
| `topic` | Yes | 사용자 연구 주제 또는 원고에서 추출한 주제 요약. |
| `evidence_request` | Yes | `EvidenceFormationPort.form_evidence`에 넘길 요청(BR-NV2 승계 — 자연어 경로 선행 강제). |
| `manuscript_ref` | Conditional | `input_type=manuscript`일 때 owner-scoped 첨부 핸들. 원고는 "내 주제가 이미 연구됐나"의 입력으로만 쓴다(위험 신호 산출 폐기 — FR-34). |
| `constraints` | No | 기간, 분야, 최대 결과 수 등 사용자 제약. 루프 예산(FR-45)과 별개. |
| `export_target` | No | Notion export 희망 위치 또는 미지정. |

### AgentLoopRun (신설)

한 잡의 자율 루프 실행 상태. 예산 집행과 종료 사유의 SSOT.

| Field | Required | Rule |
|---|---:|---|
| `iteration_count` | Yes | 루프 반복 횟수(단조 증가). |
| `tool_call_counts` | Yes | 도구별 호출 횟수 map. |
| `budget` | Yes | `LoopBudget` — 한도와 소비량. |
| `termination_reason` | Conditional | 종단 시 필수: `artifacts_complete`, `budget_exhausted`, `cancelled`, `fatal_error`. |
| `started_at` / `ended_at` | Yes/No | 루프 시작·종료 시각. |

### LoopBudget (신설)

3중 한도(FR-45). 수치 임계는 NFR Requirements에서 확정 — 여기서는 구조만.

| Field | Required | Rule |
|---|---:|---|
| `max_iterations` | Yes | 최대 반복 수. |
| `max_tool_calls` | Yes | 총 도구 호출 상한 + 도구별 상한 map. |
| `token_cost_limit` | Yes | 토큰/비용 한도. 비용 판정은 U6 `get_budget_state()` 단일 권위 — 본 필드는 per-job 배분치. |
| `consumed` | Yes | 반복·호출·토큰/비용 소비량(단조 증가). |

### ToolCallRecord (신설)

결정 트레이스(FR-46)의 단위 레코드. 진행 활동 피드(FR-35)의 원천.

| Field | Required | Rule |
|---|---:|---|
| `job_id` / `seq` | Yes | 잡 내 단조 증가 순번. |
| `tool_name` | Yes | 호출한 도구. |
| `args_summary` | Yes | 도구 인자 요약(검색 질의 등). **sanitized** — 원고 원문·근거 전문·자격증명 미포함(SEC-9/15). |
| `decision_note` | No | 에이전트가 남긴 선택 이유 요약(있을 때만). |
| `result_summary` | Yes | 결과 요약(발견 수, 저장 성공/거부 등). |
| `outcome` | Yes | `ok`, `error`, `rejected_by_gate`(저장 게이트 거부), `budget_denied`. |
| `cost_estimate` | No | 토큰/비용 추정치(예산 집계 입력). |
| `started_at` / `finished_at` | Yes | 호출 시각. |

### EvidenceSnapshot (승계)

v1과 동일 — `EvidenceFormationPort` 결과의 내부 보존본. `state`(`ok`/`abstain`), `claims`, `coverage`, `abstain_reason`, `contract_version`. PROVISIONAL 필드(`conflicting`/`confidence`)는 있으면 소비하되 필수로 의존하지 않는다(BR-NV3 승계).

### SimilarWorkItem (승계)

유사 연구 표의 한 행 — v1과 동일 필드(`artifact_id`, `artifact_type`, `title`, `problem_definition`, `method`, `dataset`, `result`, `limitation`, `overlap_with_user_idea`, `source_refs`, `evidence_status`, `confidence`). 근거가 있을 때만 셀을 채운다(BR-NV9 승계). `source_refs`는 FR-47 확장 시 표·그림·수식 객체 앵커를 포함할 수 있다.

### GapAnalysis / GapItem (신설)

여백 분석 — v2 기본 산출물의 핵심(FR-32).

| Field | Required | Rule |
|---|---:|---|
| `gap_id` | Yes | 항목 고유 ID. |
| `area` | Yes | 판정 대상 영역(주제의 하위 갈래·방법·데이터셋 축 등). |
| `status` | Yes | `well_covered`(이미 많이 연구됨), `partially_covered`, `open_gap`(탐색 범위 내 미발견). |
| `rationale` | Yes | 판정 이유 — 사용자에게 노출 가능한 설명. |
| `source_refs` | Yes | 판정 근거 `SourceRef[]` 또는 external finding ref. **모든 항목 필수**(BR-RA10). |
| `searched_scope_note` | Conditional | `open_gap`일 때 필수 — "부재 증명"이 아니라 **탐색한 범위 내 미발견**임을 명시(질의·소스 요약). |
| `related_similar_work_ids` | No | 관련 유사 연구 표 행 참조. |

### ExternalFinding (승계)

GitHub·데이터셋 검색 결과의 정규화 artifact — v1과 동일. 향후 arXiv MCP 결과도 이 형태로 정규화하되 DocModel 앵커가 없으므로 `evidence_status`는 근거 등급 구분을 따른다(⑤ 2단계 설계 시 확정).

### NoveltyCandidate (승계·개정 — 온디맨드)

차별화 방향 제안. **기본 산출물이 아니라 사용자가 대화로 요청할 때만 생성**(FR-32 개정). 필드는 v1과 동일(`angle`, `rationale`, `supporting_refs` 필수, `excluded_claims` 등). bounded 생성 규칙(BR-NV11)과 저장 게이트(BR-RA2)를 동일 적용.

### ExperimentPlan (승계·개정 — 온디맨드)

실험 계획. **온디맨드 전용**(FR-33 개정). 필수 필드는 v1과 동일(hypothesis, novelty_angle, baselines, datasets, metrics, procedure, risks, resources, source_refs — BR-NV12 승계).

### NoveltyChatMessage (승계·개정 — 세션 메모리 1단계)

잡 내 멀티턴 대화(FR-44)의 영속 모델.

| Field | Required | Rule |
|---|---:|---|
| `job_id` | Yes | 귀속 잡. |
| `role` | Yes | `user` 또는 `agent`. |
| `kind` | Yes | `steering`(방향 지시), `on_demand_request`(제안/실험계획 요청), `agent_reply`, `notice`(시스템 안내). |
| `content` | Yes | 메시지 본문. |
| `resulting_artifact_ref` | No | 온디맨드 요청이 산출물을 낳았을 때 참조. |
| `created_at` | Yes | 시각. |

잡 간 사용자 메모리(이전 잡 산출물·선호 참조)는 목표 아키텍처에 **정의만** 하고 도입은 ⑤ 3단계 후반 — 엔티티 확정은 그 시점의 설계 델타로 미룬다.

### ProgressState / ActivityFeedItem (개정)

진행 표시 계약(FR-35 개정). 구 11종 enum을 대체한다.

**거시 상태**: `received`(접수) → `investigating`(조사 중) → `reporting`(보고 작성 중) → 종단 `completed` / `partial`(부분 완료 — 예산 소진·source 저하) / `failed` / `cancelled`. 온디맨드 생성 중에는 `investigating`으로 복귀하지 않고 잡은 종단 상태를 유지한 채 대화 턴으로 처리한다.

**ActivityFeedItem**은 저장 엔티티가 아니라 `ToolCallRecord`에서 파생되는 투영(projection)이다: `{seq, 사용자용 활동 문구, tool, query_summary, source_count, occurred_at}`. 내부 원문 payload·민감 정보는 투영 단계에서 제외한다(SEC-9/15).

### NotionExport (승계)

v1과 동일 — `status`(`not_requested`→`preview_ready`→`approved`→`exporting`→`exported`/`failed`), `target`, `exported_at`, `error`. 승인 없는 export 금지(BR-NV17 승계), 루프 도구가 아니다.

### 폐기 엔티티

| Entity | 사유 |
|---|---|
| `ManuscriptRiskSignal` | FR-34 폐기(2026-07-18) — 위험 신호 기능 v2 제외. v1 frozen 문서에 기준선 보존. |
| 구 `ProgressEvent`(11종 enum) | FR-35 개정 — 거시 상태 + 활동 피드로 대체. |
| 구 `stage_snapshots` | 단계 개념 소멸(자율 루프) — 산출물 단위 저장 + 트레이스로 대체. |

## Testable Properties

| Property | Category | Rule |
|---|---|---|
| SourceRef roundtrip | Round-trip | serialize-deserialize 후 anchor·source identity 보존(PBT-NV1 승계). FR-47 확장 시 객체 앵커 포함. |
| Source normalization | Idempotence | 같은 artifact 재정규화 시 canonical key 동일(PBT-NV2 승계). |
| Dedupe stability | Idempotence | 중복 제거 반복 시 결과 불변(PBT-NV3 승계). |
| 거시 상태 전이 | Invariant | 허용 전이만 발생, 종단 상태 재진입 금지(PBT-NV4 개정). |
| 저장 게이트 차단성 | Invariant | `source_refs` 누락·실재하지 않는 앵커·필수 필드 누락 산출물은 저장되지 않는다(신설). |
| 예산 단조성·상한 | Invariant | `consumed`는 단조 증가하며 한도 초과 상태에서 도구 호출이 실행되지 않는다(신설). |
| 트레이스 완전성 | Invariant | 실행된 모든 도구 호출에 `ToolCallRecord`가 1:1 존재하고 `seq`는 빈틈없이 증가(신설). |
| ExperimentPlan 필수 필드 | Invariant | 온디맨드 생성물도 필수 필드 전부 보유(PBT-NV5 승계). |
| Owner isolation | Security invariant | 잡·산출물·트레이스·대화·export 상태의 owner 격리(PBT-NV6 승계 — 트레이스·대화 추가). |
| Export state transition | Stateful invariant | preview/approval 없이 `exported` 도달 불가(PBT-NV7 승계). |

## Traceability

| Source | Covered By |
|---|---|
| FR-30 | `NoveltyJobRequest`, `NoveltyJob`, `AgentLoopRun`, `EvidenceSnapshot` |
| FR-31 | `ExternalFinding`, `SimilarWorkItem`, `ToolCallRecord`(외부 도구 호출 기록) |
| FR-32 | `SimilarWorkItem`, `GapAnalysis`/`GapItem`, `NoveltyCandidate`(온디맨드) |
| FR-33 | `ExperimentPlan`(온디맨드), `NoveltyChatMessage.resulting_artifact_ref` |
| FR-34(폐기) | 폐기 엔티티 표 — `ManuscriptRiskSignal` 제거 근거 |
| FR-35 | `ProgressState`, `ActivityFeedItem`, `NotionExport`, `NoveltyJob.artifacts` |
| FR-44 | `NoveltyChatMessage`, 잡 간 메모리 정의 유보 명시 |
| FR-45 | `LoopBudget`, `AgentLoopRun` |
| FR-46 | `ToolCallRecord` |
| FR-47 | `SimilarWorkItem.source_refs`·`GapItem.source_refs`의 객체 앵커 수용(구체 설계는 로드맵 ⑥) |
| QT-10 | Testable Properties |
