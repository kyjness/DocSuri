# 에이전트 Tool 포트 계약 골격 (Agent Tool Port Contract — SKELETON)

**단계**: INCEPTION 재진입 · 설계 선행(D5 선행조건) · **작성일**: 2026-06-26 / **갱신**: 2026-06-28(페이즈 4·5 번호·의존 A 반영) · **상태**: 🟡 **SKELETON / PROVISIONAL**
**상위 문서**: `inception/plans/reinception-2026-06-charter.md`(재인셉션 차터, **D2 의존 확정 A · D5 계약 게이트**)
**확정 입력(질문지)**: `inception/requirements/requirement-verification-questions-literature-evidence-agent.md`(문헌탐색·근거형성 유닛 — **Q1~Q3가 본 계약의 evidence 형태를 확정**).
**근거 코드**: `shared/python/src/docsuri_shared/ports.py`·`shared/ports/README.md`(포트 패턴) · `discovery/ports/search_ports.py`(Search 소비) · `shared/dtos/docmodel.schema.json`·`summarization.schema.json`(앵커/근거) · `shared/vector-spec/`(IndexRecord).

> **목적**: **페이즈 4(문헌탐색·근거형성 Agent)** 가 **페이즈 5(연구아이디어 Agent)** 에게 노출하는 **Tool 포트**와
> **근거 출력 DTO**의 *골격*을 정의한다. 5→4 의존은 **확정(A, 2026-06-28)** 이므로, 이 계약을 동결하면
> **D5 계약 게이트 병렬**이 풀려 4·5 질문지/구현을 병렬로 진행할 수 있다(차터 §4.1).
>
> **본 문서는 골격(skeleton)이다.** 메서드 시그니처·envelope·상태 variant는 잡았으되, **evidence 필드 디테일**
> (근거 항목/컬럼·confidence·상충 표현 등)은 **문헌탐색·근거형성 유닛 질문지 Q1~Q3 답변으로 확정**한다(§7 오픈 항목).
> 발명하지 않으며, 기존 `shared/ports` 패턴(추상 선언 / 단일 구현 / 주입 소비)과 기존 계약(IndexRecord·DocModel
> Block id·Summary Anchor)을 재사용한다.

---

## 1. 포트 위상 (기존 `shared/ports` 패턴 재사용)

```
            shared/ports  (추상 인터페이스 선언)
                  ^                         ^
        depends-on|  (lib 주입)             | implements
                  |                         |
   페이즈 5 (소비자)                 페이즈 4 (단일 구현자)
   연구아이디어 Agent (석현님)       문헌탐색·근거형성 Agent (화랑님)
```

- **선언**: `shared/ports`에 추상 인터페이스(`EvidenceFormationPort`) — 데이터 아님, 메서드 시임.
- **구현(producer)**: 페이즈 4 유닛(문헌탐색·근거형성) **단독**.
- **소비(consumer)**: 페이즈 5 유닛(연구아이디어, 주입 lib). 페이즈 5는 `EvidenceFormationPort`를 **재구현 금지**.
- **순환 차단**: 5 → `shared/ports`(추상) ← 4. 5가 4 구체 모듈을 직접 import하지 않음(GroundingEnforcementHook 패턴 동일).

---

## 2. 포트 인터페이스 골격

| 메서드 | 시그니처(골격) | 상태 | 의미 |
|---|---|---|---|
| `form_evidence` | `form_evidence(request: EvidenceRequest, ctx) -> EvidenceResult` | 🟡 SKELETON | 다논문 교차확인 → 근거 비교·정리 → 출처·기권. 페이즈 5의 Research Gap/Novelty 입력. |

> 긴 다논문 분석은 비동기 잡 옵션(U7 잡 패턴 재사용) — 동기/비동기 표면은 질문지 Q9, §7 오픈.

---

## 3. 타입 카드 골격 (계약 형태 — 직렬화 포맷 아님)

> ⚠️ 아래 필드는 질문지 **Q3=권장(A)** 기준 골격이다. 확정 전까지 PROVISIONAL.

| 타입 | 필드(골격) | 의미 |
|---|---|---|
| `EvidenceRequest` | `topic`(연구 주제/질문) · `scope`(검색주도 \| 명시 paper 집합 \| 혼합 — 질문지 Q4) · `constraints`(기간/분야/최대 논문수) · `attachments?`(첨부 — Q6) | 근거형성 입력. |
| `EvidenceResult` | `claims: EvidenceItem[]` · `coverage`(다룬 논문/쿼리 요약) · `state: ok \| abstain` · `abstain_reason?` | 근거형성 산출(터미널). |
| `EvidenceItem` | `statement`(근거 명제) · `supporting: SourceRef[]` · `conflicting: SourceRef[]` · `confidence?` | 명제 + 지지/상충 출처(교차확인 결과 — Q10). |
| `SourceRef` | `paper_id` · `record_ref`(IndexRecord 핸들) · `anchor`(DocModel Section/Block id, 선택 span) · `quote?` | 결정적 출처 핸들 — **기존 계약 재사용**. |
| `AbstainResult` | `reason`(비기술 코드, 내부 위반상세 비노출 SEC-9) | 근거 부족/범위 밖 기권(Q12). |

**재사용 계약**:
- `SourceRef.record_ref` = `IndexRecord`(`shared/vector-spec`) — 검색 grounding과 동일 실재 핸들.
- `SourceRef.anchor` = DocModel `Section/Block` 결정적 id — 요약 Anchor 계약(`summarization.schema.json` AnchorTarget)과 동일 방식.
- `state/abstain` = 기존 도메인 결과의 pass/abstain 패턴과 정합(근거 없으면 기권, 날조 금지).

---

## 4. 페이즈 4가 소비하는 Tool (이미 존재 — 본 계약 신규 아님)

페이즈 4(문헌탐색·근거형성) 자신은 다음을 Tool로 소비한다(계약 이미 코드에 존재):

```
페이즈 4 (문헌탐색·근거형성)
   |
   +--> Search    (SearchResponse / IndexRecord ; discovery)
   +--> DocModel  (DocModelResponse / Block ; summarization s3_docmodel)
   +--> Summary   (SummaryResponse / Anchor ; summarization)
   +--> Citation  (citation_graph — 계약 표면 추가 확인 필요)
```

> 신규로 동결할 것은 **페이즈 4 → 페이즈 5** 포트(§2)와 **근거 출력 DTO**(§3)뿐. 소비 Tool은 기존 계약 사용.

---

## 5. Grounding 정합 (페이즈 3 통합 / D3)

`EvidenceResult`는 페이즈 3 통합 grounding의 **Agent Validator** 대상이다(도메인별 Validator, 같은 인터페이스).
Agent Validator = 출처 실재성(IndexRecord/Block id 존재)·교차확인 일관성·기권 강제 — 검색(set 멤버십)·요약(문서 충실도)과
**검사 종류는 다르되 verdict(pass/block/abstain)·violations 인터페이스는 공유**. (질문지 Q11과 연동.)

---

## 6. 동결·변경 정책 (D5)

- **동결 단위**: §2 메서드 시그니처 + §3 `EvidenceResult`/`EvidenceItem`/`SourceRef` 형태.
- **선행 조건**: 질문지 Q1~Q3 확정 → 그 결과로 §3 필드 채움 → 동결.
- **변경 정책**: 동결 후 변경은 **shared 계약 PR + 페이즈 4·5 소유자(화랑님/석현님) 사인오프**(기존 ports 변경정책 준용).
- **골든 fixture**: 페이즈 4가 초기 실제 `EvidenceResult` 표본을 **녹화 fixture**로 제공 → 페이즈 5는 그걸로 병렬 개발(D5-ⓑ).

---

## 7. 오픈 항목 (문헌탐색·근거형성 유닛 질문지에서 확정)

질문지 `requirement-verification-questions-literature-evidence-agent.md` 대응:
1. `EvidenceItem` 스키마 깊이 — confidence·상충 표현·정량화 범위(생성 산문 제외 C-2 유지). ← **Q1·Q2·Q3**
2. `scope` = 검색주도 자동 vs 명시 paper 집합 vs 혼합. ← **Q4**
3. `form_evidence` 동기 vs 비동기(긴 분석) 표면 — 폴링/스트리밍 여부. ← **Q9**
4. 첨부 입력(`attachments`) 형식/파싱 — doc-model 파이프라인 재사용 범위. ← **Q6**
5. Citation Tool 계약 표면(`citation_graph` 실측 후) — `SourceRef`에 인용 관계 포함 여부.
6. Agent Validator(페이즈 3) 인터페이스 합치 — verdict/violations 공통 형태 확정. ← **Q11**
7. 세션/영속 — `EvidenceResult` owner-scoped 저장 위치(RDS/오브젝트), 페이즈 5 재사용. ← **Q13**

> **승격 경로**: 위 항목 확정 후 본 골격을 `shared/`(ports + DTO)로 **승격·동결**하면 D5 병렬이 풀린다.
