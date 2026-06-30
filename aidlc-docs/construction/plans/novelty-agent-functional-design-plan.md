# Novelty Agent Functional Design Plan + 질문 게이트

**단계**: CONSTRUCTION → Functional Design
**일자**: 2026-06-29
**상태**: 확정 — `FD-Answer-1.md` 답변 반영, Functional Design 산출물 생성 완료

## 1. 유닛 컨텍스트

- **대상**: 차별화(novelty) 형성 Agent
- **책임**: 자연어 연구 의도 또는 업로드 원고에서 유사 연구, 차별화 후보, 실험 계획, 원고 위험 신호, 진행상태, Notion export를 제공한다.
- **경계**: 문헌탐색·근거형성 Agent 내부 구현은 범위 밖이다. novelty Agent는 `EvidenceFormationPort`/`SourceRef` 공유계약만 소비한다.
- **주요 스토리**: US-NV1..US-NV9
- **주요 요구사항**: FR-30..35, NFR-P5, NFR-R3, QT-10
- **v1 제외**: 뉴스 검색, novelty 점수, "새로움 확정" 판정, 논문화 가능성 점수, 코드 skeleton/실행 스크립트 생성.

## 2. Functional Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/novelty-agent/functional-design/`에 작성한다.

- [x] `domain-entities.md`
- [x] `business-logic-model.md`
- [x] `business-rules.md`
- [x] `frontend-components.md`

## 3. 명확화 질문

아래 `[Answer]:`를 모두 채운 뒤 Functional Design 산출물 생성을 진행한다.

### Q1 — job 입력 envelope
novelty job의 공통 입력 구조는 어떻게 둘까요?

A) 공통 `NoveltyJobRequest`에 `input_type: natural_language | manuscript`, `topic`, `evidence_request`, `manuscript_ref?`, `constraints`, `export_target?`를 둔다. (권장)

B) 자연어 job과 원고 업로드 job을 완전히 다른 request 타입으로 분리한다.

C) EvidenceFormationPort 결과만 입력으로 받고 원 사용자 입력은 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q2 — EvidenceFormationPort 결과 소비 방식
EvidenceFormationPort 결과는 novelty Agent 안에서 어떤 위치를 차지하나요?

A) 모든 경로의 1차 근거이며, novelty Agent는 `EvidenceResult.claims/supporting/conflicting`을 읽어 후속 검색과 아이디어 생성을 제한한다. (권장)

B) 참고용 컨텍스트일 뿐이고 novelty Agent가 자체 근거를 다시 만든다.

C) 원고 업로드 경로에서만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q3 — U2 full 검색 호출 단위
U2 `full` 검색은 어떤 질의 묶음으로 호출할까요?

A) Evidence claim, 사용자 topic, 원고 섹션 요약 질의를 합쳐 중복 제거한 bounded query set으로 호출한다. (권장)

B) 사용자 topic 하나만 사용한다.

C) 원고의 모든 chunk를 각각 검색 질의로 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q4 — 결과 병합과 중복 제거
EvidenceFormationPort, U2 full 검색, GitHub, 데이터셋 결과를 어떻게 병합할까요?

A) source별 normalized artifact로 모은 뒤 `source_type`, canonical URL/ID, title, SourceRef anchor 기준으로 dedupe한다. (권장)

B) LLM에게 모든 결과를 넘겨 중복 제거를 맡긴다.

C) 중복 제거 없이 source별 섹션에 그대로 표시한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q5 — 유사 연구 표의 도메인 모델
유사 연구 정리 표의 기본 행/열은 어떻게 둘까요?

A) 행=논문/외부 artifact, 열=문제정의·방법·데이터셋·결과·한계·겹치는 점·SourceRef·confidence/근거상태. (권장)

B) 행=쟁점, 열=논문별 입장으로 둔다.

C) 표가 아니라 카드 리스트로 둔다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q6 — 차별화 후보 생성 규칙
차별화 후보는 어떤 규칙으로 만들어야 하나요?

A) 기존 한계, 데이터셋/코드 가능성, 사용자의 topic/원고 의도에서 벗어나지 않는 bounded 후보만 만들고 각 후보에 supporting/conflicting SourceRef를 붙인다. (권장)

B) LLM이 자유롭게 새로운 연구 방향을 브레인스토밍한다.

C) 차별화 후보는 만들지 않고 유사 연구 표만 제공한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q7 — 실험 계획 엔티티
실험 계획은 어떤 엔티티로 모델링할까요?

A) `ExperimentPlan{hypothesis, novelty_angle, baselines[], datasets[], metrics[], procedure[], risks[], resources[], source_refs[]}`로 둔다. (권장)

B) 자유 Markdown 문서 하나로 둔다.

C) TODO list만 둔다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q8 — 원고 위험 신호 엔티티
표절/유사도와 AI 어투 경고는 어떻게 모델링할까요?

A) `ManuscriptRiskSignal{kind, severity, span, matched_source?, explanation, false_positive_note}`로 통합한다. (권장)

B) 문장 유사도와 AI 어투를 완전히 다른 모델로 분리한다.

C) 전체 문서에 대한 단일 점수만 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q9 — AI 어투 경고 산출 방식
AI 어투 경고는 Functional Design에서 어디까지 고정할까요?

A) 규칙/모델 세부는 NFR/Code로 넘기고, FD에서는 "확정 판정 금지, 위험 신호+근거 span+false positive 안내" 정책만 고정한다. (권장)

B) AI 작성 확률 산식을 FD에서 정의한다.

C) AI 어투 경고를 제거한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q10 — ProgressEvent 상태 전이
진행상태 enum의 상태 전이는 어떻게 제한할까요?

A) `queued → retrieving_corpus → searching_external → summarizing_prior_work → checking_similarity? → forming_ideas → planning_experiment → exporting_notion? → completed`를 기본 happy path로 두고, 어느 단계에서든 `failed/degraded`를 허용한다. (권장)

B) 상태 전이는 자유롭게 두고 UI가 문자열만 표시한다.

C) `queued/running/completed/failed` 4개만 둔다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q11 — 부분 결과 저장 단위
부분 결과는 어떤 단위로 저장할까요?

A) stage별 artifact snapshot을 저장한다: evidence, similar_work, external_findings, risk_signals, novelty_candidates, experiment_plan, export_status. (권장)

B) 최종 결과만 저장한다.

C) 로그만 저장하고 artifact는 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q12 — Notion export 모델
Notion export는 어떤 상태 모델을 가질까요?

A) `NotionExport{status: not_requested | preview_ready | approved | exporting | exported | failed, target, exported_at?, error?}`로 둔다. (권장)

B) 성공/실패 boolean만 둔다.

C) Notion export 상태는 내부 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q13 — 외부 검색 프라이버시 규칙
Agent-Browser 검색 질의는 어떻게 만들어야 하나요?

A) 사용자 원문/Evidence 전체를 보내지 않고, topic·키워드·익명화 요약·논문 제목/기술명 같은 최소 질의만 보낸다. (권장)

B) 품질을 위해 원문 전체를 보낼 수 있다.

C) 외부 검색은 사람이 직접 입력한 키워드만 허용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q14 — source별 degraded 정책
어떤 실패를 degraded로 보고 계속 진행할까요?

A) GitHub/데이터셋/Notion/U2 full/EvidenceFormationPort/LLM 실패를 source별로 분리하고, 필수 source가 아니면 부분 결과로 계속한다. EvidenceFormationPort 실패는 job 생성 단계에서 기권 또는 재시도 대상으로 둔다. (권장)

B) 하나라도 실패하면 전체 job을 실패한다.

C) 외부 source 실패만 degraded로 보고 내부 source 실패는 숨긴다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q15 — owner-scoped 삭제 의미
사용자가 novelty 세션을 삭제하면 무엇을 지워야 하나요?

A) job metadata, 입력 참조, 단계 이벤트, partial/final artifacts, Notion export 상태를 삭제하고, 외부 Notion 페이지 삭제는 별도 선택으로 둔다. (권장)

B) 내부 데이터와 Notion 페이지를 항상 같이 삭제한다.

C) 최종 결과만 삭제한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q16 — QT-10/PBT 불변식
Functional Design에서 어떤 속성 테스트 후보를 고정할까요?

A) SourceRef roundtrip, source normalization idempotency, job state transition validity, required experiment plan fields, owner isolation, export state transition을 고정한다. (권장)

B) DTO roundtrip만 고정한다.

C) 테스트 후보는 Code Generation에서만 정한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## 4. 답변 후 생성할 산출물 요약

답변 확정 후 다음 문서를 생성한다.

- `domain-entities.md`: NoveltyJob, NoveltyInput, EvidenceSnapshot, SimilarWorkItem, ExternalFinding, ManuscriptRiskSignal, NoveltyCandidate, ExperimentPlan, ProgressEvent, NotionExport
- `business-logic-model.md`: job 생성, evidence 소비, U2 full 검색, 외부 검색 정규화, 유사 연구 표, 위험 신호, 후보 생성, 실험 계획, progress/export 저장
- `business-rules.md`: 공유계약 준수, 재구현 금지, source별 degraded, privacy boundary, no novelty score, no legal plagiarism judgment, owner-scoped delete, QT-10
- `frontend-components.md`: job launcher, progress timeline, partial result sections, risk signal panel, experiment plan view, Notion export preview/approval
