# U11 Research Agent — Domain Entities (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `requirements.md`(FR-22~25·NFR-P5·QT-8·§12 Agent 카브아웃·C-2), `stories.md`(에픽 9 US-RA1~8), `plans/u11-research-agent-functional-design-plan.md`(Q1~Q17 확정), `plans/docmodel-fulltext-index-pivot-plan.md`(전문 통합 인덱스·근거화 U6 통일 게이트).
**원칙**: 기술 무관. 저장소/인덱스/LLM/스트리밍/잡 큐는 NFR/Infra. 본 문서는 도메인 모델만 정의한다.
**상태**: 🟡 PROVISIONAL — 게이트(`docmodel-fulltext-index-pivot`) 승인 및 U6 근거화 공유 계약 확정 시 동기화.

---

## 0. 엔티티 관계 한눈에 보기

```
User ──owns──▶ ResearchSession ──has──▶ ConversationTurn[] (시퀀스)
                                            │ query · attachments[]
                                            ▼
        AgentQuery + Attachment[] ──▶ CandidateSet (PaperCandidate[] + 선택적 BlockLocator[])
                                            ▼
              PaperEvidence[] (논문별: claims·method·results·limitations + Anchor[])
                                            ▼
              EvidenceTable (EvidenceRow[] + CrossCheckTag[]) ──ground──▶ U6 GroundingVerdict
                                            ▼
        AgentResponse = EvidenceTable | PartialResult | Abstain | CostDegraded | InputRejected
                                            ▼
              ResearchResult (owner-scoped 영속) ◀──cache── AgentCacheKey
```

근거 원천 = doc-model(논문 전체: 제목·초록·본문·표=데이터·수식=latex·캡션·각주). 후보 발견 = OpenSearch 전문 통합 인덱스. 런타임 흐름: `검색 → 후보 → doc-model 읽기 → 근거표`.

---

## 1. 세션 · 대화

### `ResearchSession` (연구 세션, 소유 — owner-scoped)
| 필드 | 타입 | 비고 |
|---|---|---|
| `sessionId` | id | 소유 |
| `ownerId` | userId | SEC-8 owner-scoped (INV-U11-1) |
| `mode` | `AgentMode` | 세션 생성 시 선택 |
| `turns` | `ConversationTurn[]` | 시퀀스(시간순) |
| `createdAt` / `updatedAt` | ts | |
| `title?` | str | 첫 질의 파생(표시용) |

### `ConversationTurn` (대화 턴, 소유)
| 필드 | 타입 | 비고 |
|---|---|---|
| `turnId` | id | 세션 내 순서 |
| `query` | `AgentQuery` | |
| `attachments` | `Attachment[]` | 0개 이상 |
| `response` | `AgentResponse` | 종단 상태(§5) |
| `priorContextRef?` | ref | 이전 턴 요약 맥락(Q8 — 재인용 아님) |

### `AgentMode` (열거)
`modeA_evidence`(문헌탐색·근거형성 — v1) · `modeB_novelty`(차기·Q4=A; seam만, 빌드 안 함).

---

## 2. 입력 · 첨부

### `AgentQuery` (질의, 소유)
| 필드 | 타입 | 비고 |
|---|---|---|
| `text` | str | 자연어 질의(정규화) |
| `mode` | `AgentMode` | |
| `normalized` | str | 캐시 키·dedupe용 정규화형 |

### `Attachment` (첨부, 소유)
| 필드 | 타입 | 비고 |
|---|---|---|
| `attachmentId` | id | owner-scoped |
| `contentHash` | hash | 캐시 키 구성요소(Q11) |
| `docModelRef?` | ref | 첨부 파싱 결과(doc-model 파이프라인 재사용·Q6) |
| `role` | const `query_context` | **분석 대상·비교 기준만**(근거 출처 아님 — Q6, C-2 외부 미검증 텍스트 그라운딩 방지) |

> 첨부는 **질의·비교 기준**으로만 쓰이고 **근거 출처로 인용하지 않는다**(Q6=A). 검증·무해화는 business-rules(SEC-5/11).

---

## 3. 검색 후보 (찾기)

### `PaperCandidate` (후보 논문, 참조)
| 필드 | 타입 | 비고 |
|---|---|---|
| `paperId` | arXivId | **최소 보장**(DF-5) |
| `score` | float | 검색 랭킹 점수 |
| `locators?` | `BlockLocator[]` | **권장 옵션**(최종 granularity=GQ1) |

### `BlockLocator` (구조화 locator, 참조 — 선택)
`{ section, blockId?, score }` — 추출 **시드**(있으면 해당 위치부터, 없으면 섹션/문서 읽기). 최종 단위(block/section/document)는 **GQ1에서 확정** — 도메인은 "구조화 locator"로만 약속.

### `CandidateSet` (후보 집합, 소유)
`{ candidates: PaperCandidate[], queryPlan }` — PaperId 디덥(BR-RA-3). 빈 결과는 빈 성공 금지(→ Abstain, INV-U11-5).

---

## 4. 근거 추출 · 교차확인

### `PaperEvidence` (논문별 추출 근거, 소유)
| 필드 | 타입 | 비고 |
|---|---|---|
| `paperId` | arXivId | |
| `claims` | `EvidenceItem[]` | 핵심 주장 |
| `method` | `EvidenceItem[]` | 방법 |
| `results` | `EvidenceItem[]` | 결과 수치(표 셀 값 포함 — doc-model 데이터) |
| `limitations` | `EvidenceItem[]` | 한계 |
| `dataCodeAvailability?` | `EvidenceItem[]` | 선택적 "코드/데이터 공개 사실"(각주 포함; **재현성 판정 아님** — C-2) |
| `sourceMeta` | `{ title, authors?, published? }` | 출처 표기(서지메타 — doc-model meta·DF-6) |

### `EvidenceItem` (근거 항목, 소유)
`{ text, anchor: Anchor, groundingState }` — 추출 텍스트 + 원문 앵커 + 근거화 판정.

### `Anchor` (근거 앵커, 소유)
`{ paperId, locator: StructuredLocator, label? }` — doc-model **구조화 locator**(granularity=GQ1) + 표시 라벨("Table 3"). U6 근거화·"출처 보기"가 동일 locator를 가리킨다.

### `EvidenceTable` (근거표, 소유 — 출력, Q5=A)
| 필드 | 타입 | 비고 |
|---|---|---|
| `rows` | `EvidenceRow[]` | 행=논문 |
| `crossChecks` | `CrossCheckTag[]` | 합의/상충/공백 오버레이 |

### `EvidenceRow`
`{ paperId, sourceMeta, claims/method/results/limitations: EvidenceItem[], anchors }` — 논문 비교형(Q5=A).

### `CrossCheckTag` (쟁점 태그, 소유 — Q4=A)
`{ axis(주장/방법/결과), kind: agreement | contradiction | gap, paperIds[], evidenceRefs[] }` — **추출 항목의 정렬·대조만**, 새 결론 산문 생성 금지(C-2).

---

## 5. 근거화 · 종단 상태

### `AgentGroundingInput` / `AgentGroundingVerdict` (U6 통일 계약 매핑 — Q7)
근거화는 **U6 단일 권위**. U11은 표 항목을 U6 **문서충실도 근거화 공유 계약**(검색 enforce와 통일된 계약; U7 `AnchorVerdict`도 이 계약으로 이관) 입력으로 정형화하고 verdict를 매핑만 한다(재구현 금지 — INV-U11-2). 형상은 `shared/ports.md` 확정 시 동기화.
- `groundingState ∈ { grounded, abstained }` (항목 단위 — Q7 부분 기권).

### `AgentResponse` (종단 union, 소유 DTO — Q9=A)
| variant | 조건 | 페이로드 |
|---|---|---|
| `EvidenceTableDTO` | 완전 | `EvidenceTable` |
| `PartialResultDTO` | 진행 중 / 일부 소스 실패 | `{ partial: EvidenceTable, progress, degraded[] }` (NFR-P5·RES-9) |
| `AbstainDTO` | 근거 없음 / 코퍼스 밖 | `{ reason }` (빈 성공 금지) |
| `CostDegradedDTO` | 비용 게이트 기권 | `{ reason }` (FR-11·U6 `getBudgetState`) |
| `InputRejectedDTO` | 첨부 검증 실패 | `{ reason }` (SEC-5/11) |

---

## 6. 영속 · 캐시

### `ResearchResult` / `ResultRef` (영속 결과, 소유 — owner-scoped)
`{ resultId, ownerId, sessionId, turnId, response, createdAt }` — 재열람(US-RA5). 삭제/초기화 분리 제어(Q12·INV-U11-6).

### `AgentCacheKey` (immutable 캐시 신원 — Q11)
`(normalizedQuery · mode · attachmentContentHash · corpusSnapshot · model/promptVersion · persona?)` — **단일 턴 다논문 분석만 캐시**(멀티턴 대화 자체는 캐시 아님). `corpusSnapshot`=전문 인덱스/doc-model 버전. 버전 변경 시 무효화(BR-RA-12).

### `AgentError` (오류, 소유)
`{ kind, detail }` — 비차단 저하로 매핑(INV-U11-5).

---

## 7. 모드 B seam (차기 — 빌드 안 함, Q14=A)
`NoveltyComparator`(포트 자리)·외부 학술 코퍼스 포트 placeholder만. v1 로직·외부 API 없음(FR-23 차기·Q4=A).

---

## 8. 값 타입 · 횡단 정합
- `StructuredLocator` — `{ section, blockId? }`(granularity=GQ1). shared DTO로 승격 검토(U7 앵커·근거화 계약과 정합).
- `sourceMeta`(title/authors/published) — doc-model meta(DF-6 보강)에서 취득.
- `AgentMode`·`AgentResponse` variant 태그 — shared 횡단 정합(QT-8 DTO roundtrip).
