# Novelty Agent — Business Logic Model

**Unit**: Novelty Agent  
**Stage**: Functional Design  
**Principle**: 기술 무관. API framework, DB, queue, browser runtime, Notion MCP client, and model/provider choices are deferred.

## Components

| Component | Responsibility |
|---|---|
| `NoveltyJobOrchestrator` | job 생성, 상태 전이, stage snapshot 저장 순서 제어. |
| `EvidenceConsumer` | `EvidenceFormationPort.form_evidence` 호출 결과를 `EvidenceSnapshot`으로 보존. |
| `FullSearchQueryPlanner` | Evidence claim, topic, 원고 섹션 요약을 bounded query set으로 정규화. |
| `U2FullSearchPort` | 기존 U2 `full` 검색 호출 경계. 새 인덱스/랭킹 로직 없음. |
| `ExternalSearchPlanner` | GitHub/데이터셋용 최소·익명화 질의 생성. 뉴스는 v1 제외. |
| `ExternalFindingNormalizer` | GitHub/데이터셋 결과를 canonical artifact로 정규화하고 dedupe. |
| `SimilarWorkSynthesizer` | Evidence와 U2/external 결과로 유사 연구 표 생성. |
| `ManuscriptRiskAnalyzer` | 원고 업로드 경로에서 유사도/AI 어투 위험 신호 생성. |
| `NoveltyCandidateGenerator` | 근거가 있는 bounded 차별화 후보 생성. |
| `ExperimentPlanBuilder` | 선택 후보를 실험 계획 필수 필드로 구체화. |
| `ProgressPublisher` | 프론트 진행상태와 partial artifact ref를 저장/노출. |
| `NotionExportCoordinator` | preview, approval, export, failure 상태 관리. |

## Use Case: Start Natural Language Job

1. 사용자는 자연어 연구 의도를 제출한다.
2. Orchestrator는 `NoveltyJobRequest(input_type=natural_language)`를 만든다.
3. EvidenceConsumer는 `EvidenceFormationPort.form_evidence`를 호출한다.
4. `state=abstain`이면 job은 사용자용 기권 사유와 함께 중단하거나 재시도 대상으로 둔다.
5. `state=ok`이면 EvidenceSnapshot을 저장하고 `retrieving_corpus` snapshot을 만든다.
6. FullSearchQueryPlanner는 topic과 evidence claims에서 bounded query set을 만든다.
7. U2FullSearchPort는 기존 U2 `full` 검색으로 누락 보강과 유사 논문 확장을 수행한다.

## Use Case: Start Manuscript Job

1. 사용자는 Markdown 또는 TXT 원고 참조를 제출한다. PDF/DOCX는 shared parser/upload handle이 확정될 때까지 v1 backend에서 거절한다.
2. Orchestrator는 `NoveltyJobRequest(input_type=manuscript)`와 owner-scoped `manuscript_ref`를 만든다.
3. 공통 ingestion/doc-model 또는 문헌탐색·근거형성 경로가 파싱한 Evidence/SourceRef만 소비한다.
4. 파싱 실패는 내부 오류를 숨기고 사용자용 실패 사유로 표시한다.
5. 원고 섹션 요약 질의는 U2 full 보강 검색에만 사용하고 외부 검색에는 원문 전체를 보내지 않는다.
6. ManuscriptRiskAnalyzer는 내부 corpus 기준 유사도와 AI 어투 위험 신호를 별도 artifact로 만든다.

## Use Case: Plan and Run U2 Full Search

1. Planner는 evidence claims, 사용자 topic, 원고 섹션 요약에서 후보 질의를 만든다.
2. 질의는 trim, lower-case where safe, whitespace normalization, stop duplicate removal을 거친다.
3. per-job query limit을 넘는 질의는 coverage가 높은 순으로 제한한다.
4. U2 `full` 검색 결과는 canonical paper ID와 SourceRef anchor 기준으로 병합한다.
5. 검색 실패는 source별 `degraded`로 기록한다. EvidenceFormationPort 실패와 구분한다.

## Use Case: Search External Sources

1. ExternalSearchPlanner는 topic, 키워드, 논문 제목, 기술명, 익명화 요약만 사용해 질의를 만든다.
2. Agent Worker는 서버 측 Agent-Browser로 GitHub와 데이터셋 source를 검색한다.
3. 사용자 원문, Evidence 전체, 원고 전문은 외부 사이트로 보내지 않는다.
4. Normalizer는 결과를 `ExternalFinding`으로 정규화한다.
5. canonical URL/ID, title, source type 기준으로 중복 제거한다.
6. source 실패는 job 전체 실패가 아니라 `degraded` partial result로 남긴다.

## Use Case: Build Similar Work Table

1. SimilarWorkSynthesizer는 EvidenceSnapshot, U2 full 결과, ExternalFinding을 source별 artifact로 모은다.
2. 같은 논문/외부 artifact는 canonical key로 합친다.
3. 각 행은 문제정의, 방법, 데이터셋, 결과, 한계, 겹치는 점, SourceRef를 채운다.
4. 근거가 부족한 셀은 추측하지 않고 `insufficient` 또는 `abstained`로 둔다.
5. `confidence`와 `conflicting`은 입력에 있을 때만 표시/보존한다.

## Use Case: Analyze Manuscript Risk

1. 원고 업로드 경로에서만 실행한다.
2. 내부 corpus와 원고 span 간 유사도를 검토 신호로 만든다.
3. AI 어투 검사는 확정 판정이나 확률 점수를 만들지 않는다.
4. 각 신호에는 span, 설명, matched source, false positive note를 붙인다.
5. 위험 신호가 있어도 novelty candidate와 experiment plan 생성을 차단하지 않는다.

## Use Case: Generate Novelty Candidates

1. CandidateGenerator는 유사 연구의 한계, 데이터셋/코드 가능성, 사용자 topic/원고 의도를 입력으로 받는다.
2. 후보는 근거에서 벗어나지 않는 bounded 범위로 제한한다.
3. 각 후보는 supporting refs를 가져야 한다.
4. conflicting refs는 available한 경우에만 붙인다.
5. novelty score, "새로움 확정", 논문화 가능성 판정은 생성하지 않는다.

## Use Case: Build Experiment Plan

1. 선택 또는 상위 novelty candidate를 `ExperimentPlan`으로 구체화한다.
2. hypothesis, novelty angle, baselines, datasets, metrics, procedure, risks, resources, source refs를 모두 채운다.
3. GitHub 결과는 구현체/baseline/reproduction 단서로만 사용한다.
4. 데이터셋 결과는 접근성, 라이선스, task, metric 후보에 연결한다.
5. 코드 skeleton과 실행 스크립트 생성은 제외한다.

## Use Case: Persist Progress and Partial Results

1. Orchestrator는 stage 시작마다 `ProgressEvent`를 기록한다.
2. 각 stage가 의미 있는 artifact를 만들면 stage snapshot을 저장한다.
3. snapshot 단위는 evidence, similar_work, external_findings, risk_signals, novelty_candidates, experiment_plan, export_status다.
4. 프론트는 polling 또는 streaming으로 상태와 partial artifact ref를 표시한다.
5. job 취소/실패/저하 상태에서도 이미 성공한 snapshot은 조회 가능해야 한다.

## Use Case: Export to Notion

1. 분석 결과는 먼저 DocSuri 내부 owner-scoped 저장소에 저장한다.
2. 사용자는 Notion export preview를 확인한다.
3. 사용자가 승인하면 `approved -> exporting`으로 전이한다.
4. Notion MCP 호출 성공 시 `exported`와 위치를 저장한다.
5. 실패 시 `failed`와 사용자용 오류를 저장한다.
6. 외부 Notion 페이지 삭제는 novelty session 삭제와 자동 연동하지 않고 별도 선택으로 둔다.

## Failure Model

| Failure | Behavior |
|---|---|
| Missing principal | U3/U6 경로에서 fail closed. |
| EvidenceFormationPort abstain | job 생성 단계에서 기권 또는 재시도 대상으로 표시. |
| U2 full failure | source별 `degraded`, 성공한 source로 부분 진행. |
| GitHub/dataset failure | 해당 source만 `degraded`, 내부 corpus 결과 유지. |
| Manuscript parse failure | 원고 경로 실패 사유 표시, 내부 상세 비노출. |
| Risk analyzer failure | 위험 신호 섹션 degraded, novelty/plan 생성은 가능하면 계속. |
| LLM generation failure | 해당 stage degraded 또는 failed, 이전 snapshot 유지. |
| Notion export failure | export 상태만 failed, 내부 결과 유지. |

## Testable Properties

| Property | Check |
|---|---|
| SourceRef roundtrip | corpus/attachment SourceRef shape와 anchor가 직렬화 왕복 후 보존. |
| Source normalization idempotency | 같은 GitHub/dataset/paper artifact의 canonical key가 반복 정규화에도 동일. |
| Dedupe idempotency | `dedupe(dedupe(items)) == dedupe(items)`. |
| Job state transition validity | 허용되지 않은 전이와 종단 뒤 재진입 금지. |
| Required experiment fields | 모든 generated plan이 필수 필드와 source refs를 포함. |
| Owner isolation | owner A job, input, export 상태가 owner B 조회 결과에 섞이지 않음. |
| Export approval invariant | `approved` 없이 `exported` 불가. |

## Traceability

| Story / Requirement | Logic |
|---|---|
| US-NV1, FR-30/31 | Start Natural Language Job, EvidenceConsumer, U2 full search |
| US-NV2, FR-30 | Start Manuscript Job |
| US-NV3, FR-31/32 | Build Similar Work Table |
| US-NV4, FR-31 | Search External Sources |
| US-NV5, FR-34 | Analyze Manuscript Risk |
| US-NV6, FR-32/33 | Generate Novelty Candidates, Build Experiment Plan |
| US-NV7, FR-35 | Persist Progress and Partial Results |
| US-NV8, FR-35 | Export to Notion |
| US-NV9, QT-10 | Failure Model, Testable Properties |
