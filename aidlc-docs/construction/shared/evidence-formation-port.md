# shared/ 공용 계약 — EvidenceFormationPort

**단계**: CONSTRUCTION → 공용 계약 선행 작성 · **일자**: 2026-06-29
**상태**: PROVISIONAL — 문헌탐색·근거형성 Agent 질문지 Q1~Q3 확정 전 초안.
**대상**: 연구 에이전트 공유 계약. 현재 `develop` 기준 구 통합 연구 에이전트는 폐기되고 문헌탐색·근거형성 / 연구아이디어 2개 유닛으로 분리되어 있으므로, 본 문서는 그중 **문헌탐색·근거형성 Agent가 연구아이디어 Agent에 제공하는 포트 계약**을 정의한다.
**근거**: `inception/plans/reinception-2026-06-charter.md` D2/D5 · `inception/requirements/requirement-verification-questions-literature-evidence-agent.md` · `inception/application-design/agent-tool-port-contract-draft.md` · `construction/shared/docmodel.md` · `construction/shared/vector-spec.md` · `construction/shared/ports.md`.

---

## 1. 목적

`EvidenceFormationPort`는 문헌탐색·근거형성 Agent가 다논문 근거를 만들고, 연구아이디어 Agent가 그 결과를 입력으로 재사용하게 하는 공유 포트다.

컴포넌트를 서로 맞춘다는 뜻이 아니라, 두 유닛이 서로의 내부 구현을 import하지 않고 같은 요청/응답 모양을 쓰도록 잠그는 계약이다.

| 항목 | 내용 |
|---|---|
| 선언 위치 | `shared/ports` 추상 인터페이스 |
| 구현자 | 문헌탐색·근거형성 Agent 단독 |
| 소비자 | 연구아이디어 Agent |
| 의존 방향 | 연구아이디어 Agent → `shared/ports` ← 문헌탐색·근거형성 Agent |
| 금지 | 연구아이디어 Agent가 근거형성 로직을 재구현하거나 문헌탐색 Agent 구체 모듈을 직접 import |

---

## 2. 포트

| 메서드 | 시그니처 | 상태 | 의미 |
|---|---|---|---|
| `form_evidence` | `form_evidence(request: EvidenceRequest, ctx: AgentContext) -> EvidenceResult` | PROVISIONAL | 주제/논문 범위/제약을 받아 다논문 근거 항목을 만들고 출처와 기권 상태를 반환 |

동기/비동기 표면은 질문지 Q9에서 확정한다. 계약상 터미널 결과는 `EvidenceResult` 하나로 고정하고, 스트리밍·잡·폴링은 전송 방식으로만 둔다.

---

## 3. 타입

### 3.1 EvidenceRequest

| 필드 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `topic` | string | Y | 연구 주제, 질문, 또는 비교하고 싶은 주장 |
| `scope` | EvidenceScope | Y | 검색 주도, 명시 논문 집합, 혼합 중 하나 |
| `constraints` | EvidenceConstraints | N | 기간, 분야, 최대 논문 수, 언어 등 실행 제약 |
| `attachments` | AttachmentRef[] | N | 사용자 첨부. 처리 여부와 파싱 방식은 질문지 Q6에서 확정 |

### 3.2 EvidenceScope

| 필드 | 타입 | 의미 |
|---|---|---|
| `mode` | `search_driven` \| `paper_set` \| `mixed` | 근거 대상 논문을 모으는 방식 |
| `paper_ids` | PaperId[] | 명시 논문 집합일 때 사용 |
| `query` | string | 검색 주도일 때 사용. 없으면 `topic`을 기본 질의로 사용 |

### 3.3 EvidenceResult

| 필드 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `state` | `ok` \| `abstain` | Y | 근거 산출 성공 또는 기권 |
| `claims` | EvidenceItem[] | Y | 근거 명제 목록. `abstain`이면 빈 배열 가능 |
| `coverage` | EvidenceCoverage | Y | 실제 다룬 논문/질의/누락 범위 요약 |
| `abstain_reason` | string | N | 사용자에게 노출 가능한 비기술 기권 사유 |

### 3.4 EvidenceItem

| 필드 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `statement` | string | Y | 추출 기반 근거 명제 |
| `kind` | `claim` \| `method` \| `result` \| `limitation` | N | Q1 권장안 기준 분류. 최종 폭은 Q1에서 확정 |
| `supporting` | SourceRef[] | Y | 명제를 지지하는 출처 |
| `conflicting` | SourceRef[] | N | 명제와 상충하는 출처. 포함 여부는 Q3에서 확정 |
| `confidence` | number | N | 0~1 신뢰도. 포함 여부와 산정 책임은 Q3에서 확정 |

### 3.5 SourceRef

| 필드 | 타입 | 필수 | 의미 |
|---|---|---:|---|
| `source_type` | `corpus` \| `attachment` | Y | 코퍼스 논문 근거인지 사용자 첨부 근거인지 구분 |
| `paper_id` | PaperId | N | `source_type=corpus`일 때 필수 논문 식별자 |
| `record_ref` | IndexRecordRef | N | `source_type=corpus`일 때 필수 `vector-spec.md` 검색/코퍼스 레코드 핸들 |
| `attachment_ref` | AttachmentRef | N | `source_type=attachment`일 때 필수 owner-scoped 첨부 핸들 |
| `anchor` | DocModelAnchor | Y | 코퍼스 DocModel 또는 첨부 파싱 산출물의 Section/Block id, 선택 span |
| `quote` | string | N | 짧은 검증용 발췌. UI/저장 정책에 따라 생략 가능 |

### 3.6 공통 참조 타입

| 타입 | 출처/정의 |
|---|---|
| `AgentContext` | 호출자, owner-scoped 세션, trace/cost context를 담는 실행 컨텍스트. 최종 필드는 문헌탐색·근거형성 Agent Functional/NFR Design에서 확정 |
| `AttachmentRef` | owner-scoped 첨부 핸들. 처리 여부와 파싱 방식은 질문지 Q6에서 확정 |
| `PaperId` | `00-shared-contracts-overview.md` 횡단 규약 |
| `IndexRecordRef` | `vector-spec.md` IndexRecord 핸들 |
| `DocModelAnchor` | `docmodel.md` Section/Block id + 선택 span |

> ⚠️ **앵커 모델 충돌 (미해결) — 2026-06-30 · `aidlc-suite-review` PR #280**
> 본 §3.6의 `DocModelAnchor`(및 §3.5 `SourceRef.anchor`)는 `docmodel.md §3`의 id 기반 앵커를 **전제**하지만, 배포된 U7 요약 경로 + `summarization.schema.json`은 레거시 **`{ target ∈ enum{section,table,figure}, quote-span(span), regex-label(label) }`** 모델을 방출한다(U7: 백엔드 무변경). 즉 본 포트가 전제하는 id 앵커는 U7이 실제로 발행하는 형상과 정렬되지 않는다.
> 명시적 결정(U7/스키마가 id 앵커로 이행하거나 `docmodel.md §3`을 공식 개정·동결해제)으로 셋을 정렬하기 전까지, novelty/근거형성 에이전트의 앵커 실재성 검증은 id 앵커에 의존할 수 없다. **해결 책임자: TBD.**
> 교차 참조: `docmodel.md §3` · `shared/dtos/summarization.schema.json`(Anchor/AnchorTarget) · `u7-summarization/functional-design/domain-entities.md`(Anchor) · 본 `evidence-formation-port.md §3.6`.

---

## 4. 재사용 계약

새로 만드는 것은 Evidence 포트와 Evidence DTO뿐이다. 출처 실재성은 기존 계약을 재사용한다.

| 목적 | 재사용 계약 | 이유 |
|---|---|---|
| 논문/청크 실재 핸들 | `vector-spec.md` IndexRecord | U2 검색 결과와 같은 코퍼스 식별자 사용 |
| 본문 위치 | `docmodel.md` Section/Block id | U1이 만든 결정적 앵커를 U7/U5/Agent가 같이 사용 |
| 요약 앵커 정합 | `summarization.schema.json` Anchor 의미 | `Anchor.target`을 DocModel id로 해석하는 방향과 정합 |
| 비용/관측 | `ports.md` CostGuardCircuitBreaker, ObservabilityHub | Agent가 비용/관측을 자체 구현하지 않음 |

---

## 5. Grounding 정책

`EvidenceResult`는 페이즈 3 통합 Agent Validator의 대상이다.

| 검증 | 정책 |
|---|---|
| 출처 실재성 | `source_type=corpus`는 `record_ref`와 `anchor`, `source_type=attachment`는 `attachment_ref`와 `anchor`가 존재해야 함 |
| 근거 부족 | `state=abstain`, `claims=[]`, 사용자용 `abstain_reason` 반환 |
| 상충 근거 | 숨기지 않고 `conflicting`에 표현. 최종 필수 여부는 Q3에서 확정 |
| 내부 상세 | 위반 상세, 내부 점수, owner 정보는 외부 DTO에 노출하지 않음 |

문헌탐색 Agent는 근거를 만들고 매핑한다. 전역 grounding 권위와 비용 권위는 `shared/ports`의 기존 단일 권위 정책을 따른다.

---

## 6. 변경 정책

| 항목 | 정책 |
|---|---|
| 동결 조건 | 질문지 Q1~Q3 확정 후 `EvidenceItem` 필드 깊이와 근거표 형태 확정 |
| 하위 호환 | `00-shared-contracts-overview.md`의 DTO 진화 규칙을 따른다. 선택 필드 추가는 허용하고, 필수 필드 제거/의미 변경은 버전업 |
| 변경 승인 | 동결 후 변경은 공유 계약 PR + 문헌탐색·근거형성 Agent / 연구아이디어 Agent 양쪽 사인오프 |
| fixture | 문헌탐색 Agent가 대표 `EvidenceResult` fixture를 제공하고 연구아이디어 Agent는 그 fixture로 병렬 개발 |

---

## 7. 오픈 항목

| 항목 | 결정 위치 |
|---|---|
| 근거 폭: 주장/방법/결과/한계 포함 여부 | 질문지 Q1 |
| 근거표 모양: 논문 비교형/쟁점 매트릭스/리스트 | 질문지 Q2 |
| `conflicting`, `confidence` 포함 여부 | 질문지 Q3 |
| 검색 scope 기본값 | 질문지 Q4 |
| 첨부 처리 방식 | 질문지 Q6 |
| 첨부 파싱 실패 시 `SourceRef` 허용 여부 | 질문지 Q6 / Functional Design |
| 동기/비동기 표면 | 질문지 Q9 |

이 항목이 닫히기 전까지 본 문서는 PROVISIONAL이다.
