# Novelty Agent v2 — Business Rules

**Unit**: Novelty Agent v2 (U12)
**Stage**: Functional Design (재설계 라운드, 2026-07-18)
**방식**: FD 게이트 Q13=A — v1 규칙(BR-NV1~19) 승계/개정/폐기 판정 표 + 루프 신설 규칙(BR-RA-*)만 상세 기술.

## 1. BR-NV1~19 승계 판정 표

| v1 규칙 | 판정 | 근거 |
|---|---|---|
| BR-NV1 Shared Contract Boundary | **유지** | 공유 계약(`EvidenceFormationPort`/`SourceRef`)만 소비, 재구현 금지 — 불변. |
| BR-NV2 Evidence First | **유지** | 자연어 잡은 루프 시작 전 `form_evidence` 강제(FD 게이트 Q14=A). |
| BR-NV3 Provisional Evidence Fields Optional | **유지** | 계약 미변경. |
| BR-NV4 Reuse U2 Full Search | **유지** | 전용 인덱스·독자 랭킹 금지 — 불변. |
| BR-NV5 Bounded Query Set | **개정** | 고정 질의 set → 루프에서 질의 구성은 에이전트 자율. 폭주 방지는 질의 목록 고정이 아니라 **예산 상한(BR-RA3)** 이 담당. "원고 전 chunk를 질의로 무제한 발사 금지"의 정신은 도구별 호출 상한으로 승계. |
| BR-NV6 External Search Privacy Boundary | **개정·강화** | 최소 질의 원칙 승계 + **도구별 payload allowlist를 어댑터가 기계식 강제**(BR-RA7)로 확장 — 에이전트가 인자를 자유 구성하는 시대의 방어. |
| BR-NV7 v1 External Sources | **개정** | GitHub+데이터셋 유지, 뉴스 제외 유지. 외부 arXiv 검색은 근거 등급 체계(⑥ 게이트) 확정 후 시점 미정으로 추가 — 메커니즘 중립(FR-31 개정). *(2026-07-25 개정: 종전 "⑤ 2단계(MCP)에서 추가".)* |
| BR-NV8 Deterministic Normalization/Dedupe | **유지** | 정규화·중복 제거는 결정론 — LLM 재량 금지. |
| BR-NV9 No Unsupported Table Cells | **유지** | 근거 없으면 셀 비움(`insufficient`/`abstained`). |
| BR-NV10 No Novelty Score or Certainty Claim | **유지** | "새로움 확정"·score·논문화 판정 금지 — 여백 분석에도 동일 적용(open_gap ≠ 새로움 보증). |
| BR-NV11 Bounded Candidate Generation | **개정** | 규칙 내용 유지 + 적용 시점이 온디맨드 경로로 이동(FR-32 개정). |
| BR-NV12 Experiment Plan Required Fields | **유지** | 필수 9필드 — 온디맨드 경로에서도 저장 게이트가 강제. |
| BR-NV13 Manuscript Risk Non-Blocking | **폐기** | FR-34 폐기 — 위험 신호 기능 v2 제외. |
| BR-NV14 AI Style Warning Not Probability | **폐기** | 동상. |
| BR-NV15 Stage Snapshot Persistence | **개정** | "단계별 스냅샷" → **산출물 단위 저장 + 결정 트레이스**(BR-RA4). 재접속·부분 결과·진행 표시 요구는 산출물 참조 + 트레이스 투영이 충족. |
| BR-NV16 Source-Specific Degradation | **유지·개정** | source별 저하 분리 유지. 루프 문맥 추가: 도구 실패는 먼저 에이전트에 오류로 반환(대체 경로 판단 기회) 후 지속 실패 시 저하 기록(NFR-R3 개정). |
| BR-NV17 Notion Export Requires Approval | **유지·강화** | 승인 없는 export 금지 + **Notion은 루프 도구가 아님**(BR-RA12). |
| BR-NV18 Owner-Scoped Delete | **개정** | 삭제 대상에 **결정 트레이스·잡 내 대화** 추가. 외부 Notion 페이지 삭제는 별도 선택 유지. |
| BR-NV19 Anchor Validation Reuses Shared Logic | **유지** | 공유 앵커 검증 방향 유지. FR-47(객체 앵커 확장) 도입 시에도 검증 로직은 공유 계약 측에서 확장 — novelty 독자 정책 금지. |

## 2. 신설 규칙 (BR-RA-*)

### BR-RA1 — Loop Termination Authority
루프의 정상 종료는 **필수 산출물(EvidenceSnapshot·유사 연구 표·GapAnalysis) 전부가 검증·저장된 상태**에서만 인정한다. 그 외 종료는 `partial`(예산 소진)·`cancelled`·`failed`뿐이다. 에이전트의 "충분하다" 판단은 종료 제안일 뿐 판정 권위가 아니다.

### BR-RA2 — Deterministic Save Gate
모든 산출물 저장은 결정론 게이트(LLM-judge 없음)를 통과한다: SourceRef 실재성, 필수 필드, bounded 규칙(BR-NV10/11), open_gap 탐색 범위 표기. 위반 시 저장 거부 + 기계 판독 사유 반환(재시도 기회). 게이트를 우회하는 저장 경로를 만들지 않는다.

### BR-RA3 — Triple Budget Limit
최대 반복 수 + 도구 호출 수(도구별 상한 포함) + 토큰/비용 한도의 3중 상한. 비용 판단은 U6 `get_budget_state()` 단일 권위이며 novelty 전용 CostGuard를 만들지 않는다. 소진 시 검증된 산출물만으로 `partial` 종료. 수치는 NFR Requirements에서 확정.

### BR-RA4 — Mandatory Decision Trace
실행된 모든 도구 호출은 `ToolCallRecord`로 1:1 기록한다(누락 금지, `seq` 단조 증가). 기록 내용은 sanitized 요약이며 원고 원문·근거 전문·자격증명을 포함하지 않는다. 트레이스는 루프 도입 1일차부터 수집한다.

### BR-RA5 — Macro Progress States
거시 상태 전이는 §Progress State Rules 표만 허용한다. 종단 상태 재진입 금지. 온디맨드 생성은 종단 상태를 유지한 채 대화 턴으로 처리한다.

### BR-RA6 — On-Demand Artifacts Pass the Same Gate
온디맨드 산출물(NoveltyCandidate·ExperimentPlan)도 BR-RA2 게이트를 동일하게 통과해야 저장·응답된다. 대화 응답 경로라고 검증을 생략하지 않는다.

### BR-RA7 — Adapter-Enforced Payload Allowlist
외부로 나가는 도구마다 허용 payload(topic·키워드·논문 제목·기술명·익명화 요약)를 규칙으로 명시하고 **어댑터가 기계식으로 sanitize/차단**한다. 에이전트 인자 구성의 자유는 어댑터 경계 안에서만 유효하다.

### BR-RA8 — Cooperative Cancellation
취소는 진행 중 도구 호출 완료 후 루프 탈출로 처리한다. 검증·저장된 산출물과 트레이스는 유지된다(`cancelled`). 즉시 강제 종료·저장물 파기는 하지 않는다.

### BR-RA9 — Steering Boundary
잡 내 대화 스티어링은 조사 방향·우선순위만 바꿀 수 있다. 예산 한도, 저장 게이트 규칙, payload allowlist, Notion 승인 요건은 대화로 변경 불가.

### BR-RA10 — Grounded Gap Verdicts
여백 분석의 모든 항목은 `source_refs` 필수. `open_gap` 판정은 부재 증명이 아니라 **탐색 범위 내 미발견**이며 `searched_scope_note`(질의·소스 요약) 표기를 강제한다. open_gap을 "새로움 보증"으로 표현하지 않는다(BR-NV10 연동).

### BR-RA11 — Figure Access Boundary
`view_figure`는 DocModel에 실재하는 figure/표 crop만 조회할 수 있고 호출·토큰 비용은 예산(BR-RA3)에 계상한다. 근거 인용 대상의 객체 확장(FR-47)은 본 규칙이 아니라 공유 계약·U11 설계(로드맵 ⑥)의 몫이다.

### BR-RA12 — Notion Stays Outside the Loop
Notion export는 루프 도구 목록에 존재하지 않는다. preview 조립 → 사용자 승인 → export의 별도 경로만 허용(BR-NV17 승계·강화).

## Progress State Rules

| Transition | Rule |
|---|---|
| `received -> investigating` | owner 검증·(자연어) form_evidence 선행·예산 배분 완료 후 루프 시작. |
| `investigating -> reporting` | 필수 산출물 전부 검증·저장(BR-RA1) 후 보고 조립 시작. |
| `reporting -> completed` | 보고 조립 완료. |
| `investigating/reporting -> partial` | 예산 소진 또는 source 저하로 필수 세트 일부만 완성 — 검증된 산출물로 종료. |
| `investigating/reporting -> cancelled` | 협조적 취소 완료(BR-RA8). |
| any active -> `failed` | 필수 입력/근거/권한 문제로 진행 불가(fatal_error). |
| 종단 상태 재진입 | 금지. 온디맨드 생성·대화는 종단 상태를 유지한 채 처리(BR-RA5). |

## QT-10 Property Requirements

| ID | Property | 승계 |
|---|---|---|
| PBT-NV1 | SourceRef roundtrip preserves identity/anchor (객체 앵커 확장 수용) | 승계 |
| PBT-NV2 | Source normalization idempotent | 승계 |
| PBT-NV3 | Dedupe idempotent | 승계 |
| PBT-NV4 | 거시 상태 전이 유효성·종단 재진입 금지 | 개정 |
| PBT-NV5 | ExperimentPlan 필수 필드(온디맨드 경로) | 승계 |
| PBT-NV6 | Owner isolation (트레이스·대화 포함) | 개정 |
| PBT-NV7 | Notion export는 preview/approval 없이 exported 불가 | 승계 |
| PBT-RA1 | 저장 게이트 차단성 — 무근거·필드 누락 산출물은 저장 불가 | 신설 |
| PBT-RA2 | 예산 invariant — consumed 단조 증가, 한도 초과 시 도구 실행 없음 | 신설 |
| PBT-RA3 | 트레이스 완전성 — 도구 호출과 ToolCallRecord 1:1, seq 무결 | 신설 |

## Security Compliance

| Rule | Status | Rationale |
|---|---|---|
| SECURITY-03 | Compliant | 트레이스·활동 피드는 sanitized 요약만 — 원문·토큰 제외(BR-RA4). |
| SECURITY-05 | Compliant | 요청 envelope·대화 메시지·도구 인자(어댑터 경계)·상태 전이 검증 정의. |
| SECURITY-08 | Compliant | 잡·산출물·트레이스·대화·export 전부 owner-scoped(BR-NV18 개정). |
| SECURITY-09 | Compliant | 사용자용 표시(활동 피드·오류)는 내부 도구/어댑터 상세 은닉. |
| SECURITY-11 | Compliant | BR-RA7 allowlist + 프롬프트 인젝션 경유 유출 차단(어댑터 기계 강제). |
| SECURITY-12 | Compliant | Notion OAuth·토큰 암호화는 승계(NFR/Infra 구체화). |
| SECURITY-14 | Compliant | 삭제·승인·게이트 거부가 감사 가능 이벤트로 식별됨(트레이스). |
| SECURITY-15 | Compliant | source별 저하·예산 소진의 안전한 사용자 표면화 정의. |
| SECURITY-01/02/04/06/07/10/13 | N/A at FD | 저장 암호화·네트워크·IAM·의존성 고정 등은 NFR/Infra/Code 단계. |

## Resiliency Compliance

| Rule | Status | Rationale |
|---|---|---|
| RESILIENCY-01 | Compliant | 의존성 식별: U2, U11 엔진, 외부 탐색 어댑터, LLM, Notion, 저장소. |
| RESILIENCY-05 | Compliant | 거시 상태 + 트레이스 파생 활동 피드가 관측 신호(구 stage 이벤트 대체·강화). |
| RESILIENCY-09 | Compliant | 3중 예산(BR-RA3)이 용량·폭주 통제의 FD 수준 정의. |
| RESILIENCY-10 | Compliant | 도구 실패 → 에이전트 대체 경로 → source별 저하의 계단식 방어(BR-NV16 개정). |
| RESILIENCY-02/03/04/06/07/08/11/12/13/14/15 | N/A at FD | 복구 목표·배포·헬스체크·DR·런북은 NFR/Infra/Ops 단계. |

## PBT Compliance

| Rule | Status | Rationale |
|---|---|---|
| PBT-01 | Compliant | PBT-NV1~7 승계 + PBT-RA1~3 신설로 roundtrip/idempotence/invariant/state 식별. |
| PBT-02/03/07/08/09 | Deferred | Partial 모드 — Code Generation/NFR에서 강제. |
| PBT-04/05/06/10 | Advisory/N/A | Partial 모드 비차단 — 후보는 표에 보존. |

## Traceability Matrix

| Requirement | Rules |
|---|---|
| FR-30 | BR-NV1, BR-NV2, BR-RA1, BR-RA2 |
| FR-31 | BR-NV4, BR-NV6(개정), BR-NV7(개정), BR-NV8, BR-RA7 |
| FR-32 | BR-NV3, BR-NV9, BR-NV10, BR-NV11(개정), BR-RA10 |
| FR-33 | BR-NV12, BR-RA6 |
| FR-34(폐기) | BR-NV13·14 폐기 판정(§1) |
| FR-35 | BR-RA5, BR-RA12, BR-NV17, BR-NV18(개정), Progress State Rules |
| FR-44 | BR-RA9, BR-NV18(개정 — 대화 삭제) |
| FR-45 | BR-RA3, BR-NV5(개정) |
| FR-46 | BR-RA4 |
| FR-47 | BR-NV19(유지 — 공유 계약 측 확장), BR-RA11 |
| NFR-P5 | BR-RA8(협조적 취소) |
| NFR-R3 | BR-NV16(유지·개정) |
| QT-10 | PBT-NV1~7 + PBT-RA1~3 |
