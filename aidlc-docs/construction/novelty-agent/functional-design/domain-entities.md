# Novelty Agent — Domain Entities

**Unit**: Novelty Agent  
**Stage**: Functional Design  
**Scope**: 자연어 연구 의도 또는 업로드 원고에서 유사 연구, 외부 보강 근거, 원고 위험 신호, 차별화 후보, 실험 계획, 진행상태, Notion export 상태를 모델링한다. 구현 기술, 저장소, 큐, MCP 세부는 후속 NFR/Code 단계로 둔다.

## Entity Model

### NoveltyJob

사용자별 novelty 분석 작업의 루트 aggregate.

| Field | Required | Rule |
|---|---:|---|
| `job_id` | Yes | 작업 고유 ID. |
| `owner_id` | Yes | owner-scoped 사용자 ID. |
| `request` | Yes | `NoveltyJobRequest`. |
| `state` | Yes | `ProgressEvent.state` 중 현재 상태. |
| `stage_snapshots` | Yes | 단계별 부분 artifact snapshot. |
| `created_at` / `updated_at` | Yes | 상태 전이와 부분 결과 저장 시 갱신. |
| `completed_at` | No | `completed`, `failed`, `degraded` 종단 상태 시 설정. |

### NoveltyJobRequest

두 입력 경로를 하나의 envelope로 받는다.

| Field | Required | Rule |
|---|---:|---|
| `input_type` | Yes | `natural_language` 또는 `manuscript`. |
| `topic` | Yes | 사용자 연구 의도 또는 원고에서 추출한 주제 요약. |
| `evidence_request` | Yes | `EvidenceFormationPort.form_evidence`에 넘길 요청. |
| `manuscript_ref` | Conditional | `input_type=manuscript`일 때 owner-scoped 첨부 핸들. |
| `constraints` | No | 기간, 분야, 최대 결과 수, 비용/시간 제한. |
| `export_target` | No | Notion export 희망 위치 또는 미지정. |

### EvidenceSnapshot

`EvidenceFormationPort` 결과를 novelty Agent 내부 artifact로 보존한 형태.

| Field | Required | Rule |
|---|---:|---|
| `state` | Yes | `ok` 또는 `abstain`. |
| `claims` | Yes | `EvidenceItem[]`; `abstain`이면 빈 배열 가능. |
| `coverage` | Yes | 다룬 논문, 질의, 누락 범위 요약. |
| `abstain_reason` | No | 사용자에게 노출 가능한 비기술 사유. |
| `contract_version` | No | Evidence 계약 동결 후 식별자. |

`EvidenceFormationPort`는 PROVISIONAL이다. `conflicting`과 `confidence`는 있으면 소비하되 필수로 의존하지 않는다.

### SimilarWorkItem

유사 연구 정리 표의 한 행.

| Field | Required | Rule |
|---|---:|---|
| `artifact_id` | Yes | canonical paper ID, URL, DOI, 또는 normalized external ID. |
| `artifact_type` | Yes | `paper`, `github_repo`, `dataset`. |
| `title` | Yes | 표시 제목. |
| `problem_definition` | No | 근거가 있을 때만 채움. |
| `method` | No | 근거가 있을 때만 채움. |
| `dataset` | No | 근거가 있을 때만 채움. |
| `result` | No | 근거가 있을 때만 채움. |
| `limitation` | No | 근거가 있을 때만 채움. |
| `overlap_with_user_idea` | No | 사용자 topic/원고와 겹치는 지점. |
| `source_refs` | Yes | `SourceRef[]` 또는 외부 artifact ref. |
| `evidence_status` | Yes | `supported`, `insufficient`, `abstained`, `degraded`. |
| `confidence` | No | Evidence 계약에서 제공될 때만 optional로 보존. |

### ExternalFinding

GitHub와 데이터셋 검색 결과의 정규화 artifact.

| Field | Required | Rule |
|---|---:|---|
| `source_type` | Yes | `github` 또는 `dataset`. 뉴스는 v1 제외. |
| `canonical_id` | Yes | canonical URL/ID 기반 dedupe 키. |
| `title` | Yes | repository, dataset, benchmark 이름. |
| `url` | Yes | 사용자가 확인 가능한 출처. |
| `license` | No | 확인 가능할 때만 표시. |
| `task` | No | 데이터셋/benchmark task. |
| `metrics` | No | metric 후보. |
| `baseline_or_code_hint` | No | 구현체, baseline, reproduction 단서. |
| `normalized_at` | Yes | 정규화 시각. |

### ManuscriptRiskSignal

원고 업로드 경로에서 산출되는 검토 신호.

| Field | Required | Rule |
|---|---:|---|
| `kind` | Yes | `similarity` 또는 `ai_style`. |
| `severity` | Yes | `info`, `warning`, `high`. 법적 판정 아님. |
| `span` | Yes | 원고 내 문장/문단 범위. |
| `matched_source` | No | 내부 corpus의 SourceRef 또는 유사 문장 출처. |
| `explanation` | Yes | 사용자에게 노출 가능한 비기술 설명. |
| `false_positive_note` | Yes | 오탐 가능성 안내. |

### NoveltyCandidate

차별화 후보.

| Field | Required | Rule |
|---|---:|---|
| `candidate_id` | Yes | 후보 고유 ID. |
| `angle` | Yes | 차별화 방향. |
| `rationale` | Yes | 기존 한계, 데이터셋/코드 가능성, 사용자 의도와의 연결. |
| `supporting_refs` | Yes | 근거 SourceRef 또는 external finding ref. |
| `conflicting_refs` | No | Evidence 계약이나 분석 결과에 있을 때만 optional. |
| `feasibility_notes` | No | 실험 가능성 단서. |
| `excluded_claims` | Yes | "새로움 확정", novelty score, 논문화 가능성 판정은 포함하지 않음. |

### ExperimentPlan

사용자가 실행할 수 있는 실험 계획.

| Field | Required | Rule |
|---|---:|---|
| `hypothesis` | Yes | 검증하려는 가설. |
| `novelty_angle` | Yes | 선택한 차별화 후보. |
| `baselines` | Yes | 비교 대상 연구/코드. |
| `datasets` | Yes | 데이터셋 후보와 접근성/라이선스. |
| `metrics` | Yes | 평가 지표. |
| `procedure` | Yes | 단계별 실험 절차. |
| `risks` | Yes | 데이터, 구현, 평가 리스크. |
| `resources` | Yes | 필요한 구현/계산/외부 자료. |
| `source_refs` | Yes | 계획 각 항목의 근거. |

### ProgressEvent

프론트 진행상태 표시 이벤트.

| Field | Required | Rule |
|---|---:|---|
| `job_id` | Yes | 대상 job. |
| `state` | Yes | 상태 enum. |
| `tool` | No | 현재 tool 또는 source. |
| `query_summary` | No | 익명화된 최소 검색 질의 요약. |
| `source_count` | No | 발견한 출처 수. |
| `partial_artifact_ref` | No | 저장된 stage snapshot 참조. |
| `error_summary` | No | 사용자용 비기술 실패/저하 설명. |
| `occurred_at` | Yes | 이벤트 시각. |

상태 happy path는 `queued -> retrieving_corpus -> searching_external -> summarizing_prior_work -> checking_similarity? -> forming_ideas -> planning_experiment -> exporting_notion? -> completed`이다. 어느 단계에서든 `failed` 또는 `degraded`로 전이할 수 있다.

### NotionExport

사용자 승인 기반 Notion export 상태.

| Field | Required | Rule |
|---|---:|---|
| `status` | Yes | `not_requested`, `preview_ready`, `approved`, `exporting`, `exported`, `failed`. |
| `target` | No | 사용자 Notion workspace/page/database 선택. |
| `exported_at` | No | 성공 시각. |
| `error` | No | 사용자용 실패 사유. |

## Testable Properties

| Property | Category | Rule |
|---|---|---|
| SourceRef roundtrip | Round-trip | `SourceRef`/external ref serialize-deserialize 후 anchor와 source identity 보존. |
| Source normalization | Idempotence | 같은 artifact를 두 번 정규화해도 canonical key가 같다. |
| Dedupe stability | Idempotence | 중복 제거를 반복해도 결과 집합이 변하지 않는다. |
| Job state transition | Invariant | 허용된 상태 전이만 발생하고 종단 상태 뒤에는 진행 상태로 돌아가지 않는다. |
| Experiment required fields | Invariant | 생성된 `ExperimentPlan`은 필수 필드를 모두 가진다. |
| Owner isolation | Security invariant | 다른 owner의 job/input/export 상태가 섞이지 않는다. |
| Export state transition | Stateful invariant | Notion export는 preview/approval 없이 exported로 건너뛰지 않는다. |

## Traceability

| Source | Covered By |
|---|---|
| FR-30 | `NoveltyJobRequest`, `NoveltyJob`, `EvidenceSnapshot` |
| FR-31 | `EvidenceSnapshot`, `ExternalFinding`, `SimilarWorkItem` |
| FR-32 | `SimilarWorkItem`, `NoveltyCandidate` |
| FR-33 | `ExperimentPlan` |
| FR-34 | `ManuscriptRiskSignal` |
| FR-35 | `ProgressEvent`, `NotionExport`, `stage_snapshots` |
| QT-10 | Testable Properties |
| US-NV1..US-NV9 | Entity model 전체 |
