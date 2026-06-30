# Novelty Agent — NFR Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Design  
**유닛**: Novelty Agent  
**일자**: 2026-06-29  
**상태**: 확정 — `nfr-design-review.md` 답변 반영, NFR Design 산출물 생성 완료
**근거**: `construction/novelty-agent/nfr-requirements/`, `construction/novelty-agent/functional-design/`

## 1. NFR Design 렌즈

- **Resilience**: source별 retry/timeout/degraded, worker 재시작, cancel, Notion 실패 격리.
- **Scalability**: bounded worker concurrency, queue/backpressure, U2/LLM/Agent-Browser fan-out 제한.
- **Performance**: API fast return, SSE progress latency, artifact snapshot read/write 비용.
- **Security**: owner-scoped access, external query minimization, token encryption, parser boundary.
- **Logical Components**: API controller, job repository, worker, queue, progress stream, validators, adapters.

## 2. NFR Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/novelty-agent/nfr-design/`에 작성한다.

- [x] `nfr-design-patterns.md`
  - async job pattern
  - retry/timeout/degraded pattern
  - progress streaming pattern
  - output validation pattern
  - token/export safety pattern
- [x] `logical-components.md`
  - API controller and service
  - job repository and artifact store
  - worker and queue
  - U2/Agent-Browser/Notion adapters
  - SSE/polling read model
  - validator and telemetry components

---

## 3. 명확화 질문

아래 `[Answer]:`를 모두 채운 뒤 NFR Design 산출물 생성을 진행한다.

### Q1 — Queue pattern
worker로 넘기는 job queue는 어떤 패턴을 쓸까요?

A) 기존 SQS + ECS/Fargate worker 패턴을 재사용한다. (권장)

B) RDS table polling만 사용한다.

C) 새 workflow engine을 도입한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q2 — Worker retry policy
source별 실패 retry는 어떻게 설계할까요?

A) U2/Agent-Browser/LLM/Notion별 짧은 bounded retry + timeout을 두고, 재시도 초과 시 해당 source/stage만 degraded 처리한다. (권장)

B) 모든 실패를 job 전체 재시작으로 처리한다.

C) retry 없이 즉시 실패 처리한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q3 — Progress stream design
SSE progress stream은 어디서 읽을까요?

A) persisted ProgressEvent를 읽어 SSE로 내보내고, reconnect 시 last event 이후부터 재전송한다. (권장)

B) worker memory에서만 push한다.

C) SSE 없이 polling만 유지한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — 단, v1은 Last-Event-ID 기반 event-log replay를 만들지 않고 재접속 시 status endpoint/current snapshot으로 복구한다.

### Q4 — Artifact snapshot layout
stage snapshot은 어떻게 저장할까요?

A) RDS에는 metadata/ref만 두고, 큰 JSON artifact는 S3/object storage에 stage별 key로 저장한다. (권장)

B) 모든 artifact를 RDS JSON 컬럼에 저장한다.

C) 최종 결과만 저장하고 stage snapshot은 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q5 — Worker concurrency and backpressure
worker 동시성은 어떻게 제한할까요?

A) per-worker concurrency, per-job source fan-out, queue visibility/timeout, U6 budget state를 모두 제한 조건으로 사용한다. (권장)

B) 가능한 한 병렬 호출을 많이 실행한다.

C) 항상 job 하나씩만 전역 직렬 처리한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q6 — Output validation component
LLM 출력 검증 컴포넌트는 어디에 둘까요?

A) novelty-local validator로 두고 schema/source_ref/abstain/anchor existence를 검증한다. U6 GroundingEnforcementHook은 복제하지 않는다. (권장)

B) U6 GroundingEnforcementHook을 novelty 출력마다 직접 호출하도록 확장한다.

C) 검증 없이 LLM 출력을 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q7 — Manuscript parser integration
원고 파서는 어떤 adapter 경계로 붙일까요?

A) PDF/Markdown/TXT 파싱은 shared ingestion/doc-model or evidence parser adapter에 두고 novelty worker는 parsed attachment/Evidence만 소비한다. DOCX는 v1 제외. (권장)

B) novelty worker 내부에서 원고를 직접 파싱한다.

C) 프론트에서 원고를 텍스트로 변환해 보낸다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q8 — Notion export safety
Notion export 실패와 토큰 문제는 어떤 패턴으로 처리할까요?

A) export 상태 머신 + encrypted token read + revocation/degraded handling을 두고, 실패해도 내부 결과는 유지한다. (권장)

B) export 실패 시 전체 job을 실패로 되돌린다.

C) Notion 토큰을 job payload에 평문 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q9 — Cancel behavior
사용자가 job을 취소하면 worker는 어떻게 반응할까요?

A) 취소 플래그를 stage 경계마다 확인하고, 새 외부 호출을 중지하며 완료 snapshot은 보존한다. (권장)

B) 이미 시작한 job은 끝까지 실행한다.

C) 취소 시 모든 artifact를 즉시 삭제한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q10 — Frontend degraded display contract
프론트 degraded 표시는 어떤 계약을 따를까요?

A) source/stage별 degraded reason과 남은 partial result를 ProgressEvent와 result section에 모두 표시한다. (권장)

B) degraded source는 숨기고 최종 결과만 표시한다.

C) 하나라도 degraded면 전체 화면을 실패로 표시한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## 4. 답변 후 생성할 산출물 요약

답변 확정 후 다음 문서를 생성한다.

- `nfr-design-patterns.md`: queue/worker, retry/degraded, SSE, validation, export, cancel 패턴
- `logical-components.md`: controller, repository, worker, adapters, stream publisher, validator, telemetry 구성요소
