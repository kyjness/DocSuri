# Novelty Agent — NFR Requirements 계획 + 질문 게이트

**단계**: CONSTRUCTION -> NFR Requirements  
**유닛**: Novelty Agent  
**일자**: 2026-06-29  
**상태**: 확정 — `nfr-answer.md` 답변 반영, NFR Requirements 산출물 생성 완료
**근거**: `construction/novelty-agent/functional-design/`, `requirements.md` FR-30..35/NFR-P5/R3/QT-10, `EvidenceFormationPort`/`SourceRef` 공유계약, U2 `full` 검색 계약

## 1. NFR 렌즈

- **성능**: novelty job은 장시간 agent 작업이므로 API 요청 안에서 동기 완료를 기다리지 않는다.
- **확장성**: v1은 기존 backend/API와 agent worker 경계를 우선 재사용하고, source별 fan-out을 bounded로 제한한다.
- **가용성**: U2 full, GitHub, 데이터셋, LLM, Notion 실패를 source별 `degraded`로 분리한다.
- **보안/프라이버시**: 원고 원문과 Evidence 전체를 외부 검색에 보내지 않고, Notion export는 사용자 승인 후에만 수행한다.
- **운영**: U6 CostGuard/ObservabilityHub를 재사용하고 novelty 전용 비용 권위를 만들지 않는다.
- **테스트**: QT-10은 SourceRef roundtrip, source normalization, job state transition, owner isolation, export state를 검증한다.

## 2. NFR Requirements 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/novelty-agent/nfr-requirements/`에 작성한다.

- [x] `nfr-requirements.md`
  - performance and job execution requirements
  - security/privacy requirements
  - degradation and resiliency requirements
  - observability and cost requirements
  - QT-10 test requirements
- [x] `tech-stack-decisions.md`
  - API/runtime placement
  - job persistence and worker boundary
  - U2 full/search adapter reuse
  - Agent-Browser and Notion MCP execution boundary
  - manuscript parser boundary
  - PBT framework and CI boundary

---

## 3. 명확화 질문

아래 `[Answer]:`를 모두 채운 뒤 NFR Requirements 산출물 생성을 진행한다.

### Q1 — API 실행 방식
novelty job 생성 API는 어디까지 책임질까요?

A) 기존 backend API는 job 생성/상태 조회/취소/승인만 담당하고, 실제 agent loop는 별도 worker에서 실행한다. (권장)

B) API 요청 안에서 전체 novelty 분석을 동기 실행한다.

C) 프론트가 U2/Agent-Browser/Notion을 직접 호출한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q2 — Worker 배치 경계
Agent Worker는 어떤 배치 단위가 좋을까요?

A) 기존 ECS/backend 배포 패턴 안에서 별도 worker process/task로 둔다. 새 상시 서비스는 NFR에서 필요할 때만 최소화한다. (권장)

B) novelty 전용 신규 microservice와 별도 배포 단위를 만든다.

C) 서버리스 함수만으로 각 단계를 쪼갠다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q3 — Job 상태 저장소
job metadata, stage event, partial artifact, export 상태는 어디에 저장할까요?

A) 기존 RDS에 owner-scoped job/event/export metadata를 두고, 큰 artifact는 기존 S3/object storage 패턴을 재사용한다. (권장)

B) 모든 것을 S3 JSON 파일로만 저장한다.

C) Redis 같은 휘발성 저장소에만 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q4 — 진행상태 전달 방식
프론트 진행상태는 어떤 방식으로 제공할까요?

A) v1은 polling 기반 상태 조회를 기본으로 두고, streaming/SSE는 후속 최적화로 둔다. (권장)

B) v1부터 streaming/SSE를 필수로 한다.

C) 완료 후 최종 결과만 조회한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: B

### Q5 — U2 full 검색 성능 경계
U2 `full` 검색 호출량은 어떻게 제한할까요?

A) per-job bounded query set, max papers, timeout, budget을 두고 실패 시 source별 degraded로 둔다. (권장)

B) 검색 recall을 위해 질의/chunk 수 제한을 두지 않는다.

C) U2 full 검색을 쓰지 않고 Evidence 결과만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q6 — Agent-Browser 운영 경계
GitHub/데이터셋 검색용 Agent-Browser는 어떻게 운영할까요?

A) 서버 측 worker에서만 실행하고, allowlisted source와 query budget/timeout을 둔다. (권장)

B) 사용자의 브라우저 세션에서 직접 실행한다.

C) Agent-Browser를 제거하고 수동 링크 입력만 허용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q7 — 원고 파서 의존성
원고 업로드 지원은 어떤 방식으로 확정할까요?

A) v1은 PDF/Markdown/TXT만 지원하고 DOCX는 차기 사이클로 둔다. (권장)

B) v1에 DOCX를 포함하되 신규 Python DOCX 파서를 공통 파싱 레이어에 추가한다.

C) DOCX를 외부 SaaS 변환 서비스로 보낸다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q8 — 원고/첨부 보관 정책
업로드 원고와 파싱 산출물 보관은 어떻게 둘까요?

A) owner-scoped 입력 참조와 파싱 산출물을 내부 저장하고, 삭제 요청 시 job/artifact와 함께 삭제한다. 원문 외부 전송은 금지한다. (권장)

B) 원고 원문은 저장하지 않고 세션 중 메모리에만 둔다.

C) 품질 향상을 위해 원고를 장기 학습/분석 corpus로 보관한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q9 — Notion 인증과 토큰 저장
Notion export 인증은 어떻게 처리할까요?

A) 사용자별 OAuth/명시 연결을 사용하고 토큰은 암호화 저장하며 연결 해제와 export 실패 상태를 제공한다. (권장)

B) 서버 공용 Notion token을 사용한다.

C) 매번 사용자가 임시 token을 붙여 넣는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q10 — 비용 제한
novelty job 비용 제한은 어디에서 관리할까요?

A) U6 CostGuard/rate limit을 재사용하고, U2 full/LLM/Agent-Browser/Notion에 per-job budget을 둔다. (권장)

B) novelty 전용 비용 권위와 별도 budget system을 만든다.

C) v1은 비용 제한 없이 품질을 우선한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q11 — Observability
운영 관측성은 어디로 보낼까요?

A) U6 ObservabilityHub/EventStore로 job count, stage latency, source degraded count, U2 full usage, Agent-Browser usage, Notion failure, budget exceeded를 emit한다. (권장)

B) novelty 전용 관측 pipeline을 새로 만든다.

C) 에러 로그만 남긴다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q12 — LLM 출력 검증
유사 연구 표, novelty 후보, 실험 계획의 LLM 출력은 어떻게 검증할까요?

A) schema validation + required source_refs + unsupported cell abstain 규칙으로 검증하고, 실패 시 stage degraded/failed로 둔다. (권장)

B) LLM 출력 Markdown을 그대로 저장한다.

C) 사람이 수동 검토하기 전에는 아무 결과도 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q13 — PBT 프레임워크
QT-10 property-based test는 무엇을 쓸까요?

A) 기존 Python/Hypothesis를 사용하고, TypeScript UI state mapping이 필요하면 fast-check는 Code 단계에서만 추가 검토한다. (권장)

B) PBT 없이 예시 테스트만 둔다.

C) 모든 프론트/백 테스트를 PBT로만 작성한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

### Q14 — 삭제/보존 SLA
novelty session 삭제와 보존 정책은 어떻게 둘까요?

A) owner-scoped 내부 job/input/event/artifact/export 상태는 삭제 요청 후 내부 저장소에서 삭제하고, 외부 Notion 페이지 삭제는 별도 선택으로 둔다. (권장)

B) 내부 데이터와 외부 Notion 페이지를 항상 함께 삭제한다.

C) 최종 결과만 삭제하고 stage event/input은 유지한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## 4. 답변 후 생성할 산출물 요약

답변 확정 후 다음 문서를 생성한다.

- `nfr-requirements.md`: job 비동기, 저장/보존, 보안, 저하, 비용, 관측성, 테스트 요구사항
- `tech-stack-decisions.md`: 기존 backend/worker/RDS/S3/U6/U2 재사용 여부, Agent-Browser/Notion/원고 파싱/PBT 선택
