# Novelty Agent — Frontend Components

**Unit**: Novelty Agent  
**Stage**: Functional Design  
**Scope**: 사용자가 novelty job을 시작하고, 에이전트 탐구 과정을 보며, 부분 결과와 최종 결과를 검토하고, Notion export를 승인하는 모바일 웹 UI 구조를 정의한다. 시각 디자인과 구체 컴포넌트 라이브러리는 Code 단계로 둔다.

## Component Model

| Component | Responsibility |
|---|---|
| `NoveltyJobLauncher` | 자연어 topic 입력, 원고 업로드, constraints, export 희망 여부를 받아 job 생성. |
| `ManuscriptUploadField` | PDF, Markdown, TXT 첨부와 파싱 실패 메시지 표시. |
| `NoveltyProgressTimeline` | `ProgressEvent.state`, current tool, source count, degraded/failure 상태 표시. |
| `PartialResultSections` | stage snapshot별 부분 결과 접기/펼치기. |
| `SimilarWorkTable` | 유사 연구 표 표시. |
| `ExternalFindingsPanel` | GitHub/데이터셋 결과 표시. 뉴스는 v1 숨김. |
| `ManuscriptRiskPanel` | 원고 유사도/AI 어투 검토 신호 표시. |
| `NoveltyCandidatesPanel` | bounded 차별화 후보와 supporting/conflicting refs 표시. |
| `ExperimentPlanView` | 실험 계획 필수 필드 표시. |
| `NotionExportPreview` | 내부 결과 preview, 승인, export 상태 표시. |

## Component Details

### NoveltyJobLauncher

| Input / State | Rule |
|---|---|
| `input_type` | segmented control: 자연어 / 원고. |
| `topic` | 필수, 최대 길이는 NFR/Code에서 확정. |
| `manuscript_ref` | 원고 경로에서만 필수. |
| `constraints` | 기간, 분야, 최대 source 수 같은 선택값. |
| `export_target` | Notion export는 미리보기 후 승인으로만 실행. |

제출 시 job 생성 API만 호출한다. 전체 agent loop를 동기 요청 안에서 기다리지 않는다.

### NoveltyProgressTimeline

| State | UI Meaning |
|---|---|
| `queued` | 작업 접수. |
| `retrieving_corpus` | 내부 corpus/Evidence 수집. |
| `searching_external` | GitHub/데이터셋 보강 탐색. |
| `summarizing_prior_work` | 유사 연구 정리. |
| `checking_similarity` | 원고 위험 신호 계산. 원고 경로에서만 표시. |
| `forming_ideas` | 차별화 후보 생성. |
| `planning_experiment` | 실험 계획 생성. |
| `exporting_notion` | 승인된 Notion export 수행. |
| `completed` | 분석 완료. |
| `degraded` | 일부 source/stage 실패, 부분 결과 표시. |
| `failed` | 더 진행 불가. |

내부 tool raw log는 그대로 노출하지 않는다. 사용자가 이해할 수 있는 단계명, source 수, 최소 질의 요약, 부분 결과만 표시한다.

### SimilarWorkTable

| Column | Rule |
|---|---|
| 문제정의 | 근거 있을 때만 표시. |
| 방법 | 근거 있을 때만 표시. |
| 데이터셋 | 근거 있을 때만 표시. |
| 결과 | 근거 있을 때만 표시. |
| 한계 | 근거 있을 때만 표시. |
| 겹치는 점 | 사용자 topic/원고와의 overlap. |
| 출처 | SourceRef 또는 외부 artifact 링크. |
| 근거상태 | supported/insufficient/abstained/degraded. |

`confidence`는 계약 입력에 있을 때만 보조 표시한다. 없는 경우 빈 점수나 가짜 신뢰도를 만들지 않는다.

### ExternalFindingsPanel

GitHub 결과는 repository, license, baseline/reproduction 단서를 표시한다. 데이터셋 결과는 name, URL, license/access, task, metric 후보를 표시한다. 품질 점수와 재현 가능 판정은 만들지 않는다.

### ManuscriptRiskPanel

원고 업로드 경로에서만 표시한다. 각 신호는 span, severity, explanation, matched source, false positive note를 보여준다. 법적 표절 판정이나 AI 작성 확률처럼 보이는 숫자는 표시하지 않는다.

### NoveltyCandidatesPanel

각 후보는 angle, rationale, supporting refs, optional conflicting refs, feasibility notes를 표시한다. "새로움 확정", novelty score, 논문화 가능성 판정은 UI에 없다.

### ExperimentPlanView

| Section | Rule |
|---|---|
| Hypothesis | 검증 가설. |
| Novelty angle | 선택 후보와 연결. |
| Baselines | 논문/GitHub 근거와 연결. |
| Datasets | 접근성/라이선스/태스크 포함. |
| Metrics | 실험 평가 지표. |
| Procedure | 단계별 실행 계획. |
| Risks | 실패 가능성과 완화 메모. |
| Resources | 구현/계산/자료 요구. |
| Source refs | 각 섹션별 근거. |

### NotionExportPreview

| Status | UI Rule |
|---|---|
| `not_requested` | export CTA만 표시. |
| `preview_ready` | export될 내용을 preview로 표시. |
| `approved` | 사용자가 승인한 직후 상태. |
| `exporting` | 진행 상태 표시. |
| `exported` | 저장 위치 표시. |
| `failed` | 재시도 가능한 비기술 오류 표시. |

자동 export는 없다. 승인 전에는 Notion MCP를 호출하지 않는다.

## Data Flow

1. Launcher가 job을 생성한다.
2. Frontend는 job 상태를 polling 또는 streaming으로 받는다.
3. Timeline은 `ProgressEvent`를 렌더한다.
4. PartialResultSections는 stage snapshot이 생길 때마다 갱신한다.
5. 완료 후 NotionExportPreview가 preview와 승인 흐름을 제공한다.

## Error and Empty States

| Case | UI Behavior |
|---|---|
| Evidence abstain | 근거 부족 사유와 재시도/입력 수정 안내. |
| U2 full degraded | 내부 corpus 보강 실패 표시, 가능한 결과 유지. |
| GitHub/dataset degraded | 해당 source 실패 표시, 다른 source 유지. |
| Manuscript parse failure | 파싱 실패 사유 표시, 내부 상세 비노출. |
| Risk analyzer degraded | 위험 신호 섹션만 저하 표시. |
| Notion export failed | 내부 결과 유지, export 재시도 가능. |

## Testable Properties

| Property | Check |
|---|---|
| State rendering coverage | 모든 `ProgressEvent.state`가 UI 상태로 매핑된다. |
| Degraded visibility | source별 degraded가 최종 결과에서 숨겨지지 않는다. |
| Approval invariant | preview/approval 전 export action이 비활성이다. |
| Risk copy invariant | AI 확률/법적 표절 판정 문구가 표시되지 않는다. |
| Optional confidence | confidence 부재 시 UI가 빈 점수나 0점을 만들지 않는다. |

## Traceability

| Story / Requirement | Components |
|---|---|
| US-NV1 | `NoveltyJobLauncher`, `NoveltyProgressTimeline` |
| US-NV2 | `ManuscriptUploadField`, `ManuscriptRiskPanel` |
| US-NV3 | `SimilarWorkTable` |
| US-NV4 | `ExternalFindingsPanel` |
| US-NV5 | `ManuscriptRiskPanel` |
| US-NV6 | `NoveltyCandidatesPanel`, `ExperimentPlanView` |
| US-NV7 | `NoveltyProgressTimeline`, `PartialResultSections` |
| US-NV8 | `NotionExportPreview` |
| FR-35 | Progress, partial result, export components |
