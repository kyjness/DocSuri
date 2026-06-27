# U11 Research Agent — Business Logic Model (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `requirements.md`(FR-22~25·NFR-P5·QT-8·C-2), `stories.md`(US-RA1~8), `plans/u11-research-agent-functional-design-plan.md`(Q1~Q17), `plans/docmodel-fulltext-index-pivot-plan.md`(DF-1~6).
**원칙**: 기술 무관. 설계 입력 `summarization-translation-pipeline.md` §6 6~7단계 재사용 + "유사논문 검색" 노드 추가(line 374).
**상태**: 🟡 PROVISIONAL — 게이트 승인·U6 근거화 공유 계약 확정 시 동기화.

---

## 0. 컴포넌트 (잠정)

`AgentSessionService` · `ConversationInputHandler` · `AttachmentIngestor` · `MultiPaperRetriever` · `EvidenceExtractor` · `CrossCheckSynthesizer` · `AgentGroundingAdapter`(U6 통일 계약 정형화/매핑) · `EvidenceTableAssembler` · `AgentCostGuardAdapter`(U6 `getBudgetState`) · `AgentProgressReporter` · `ResearchResultStore` · `AgentTelemetryPublisher` · *(차기)* `NoveltyComparator`(seam).

---

## 1. 핵심 파이프라인 — `runEvidenceFormation(turn)` (모드 A)

```
[ 사용자: 모드 A · 질의(+첨부) ]   (US-RA1/RA3)
        ▼
┌─ U6 GATEWAY  authn·authz(SEC-8)·rate-limit(SEC-11) ─┐   ← 로그인 필수·owner-scoped (INV-U11-1)
        ▼
0. lookupCache(AgentCacheKey)  ── HIT ──▶ 즉시 반환(LLM 0콜)   ← 중복 호출 캐시 차단(Q10/Q11)
        ▼ MISS
1. applyCostGate()  = U6 getBudgetState()
        NORMAL → 진행 │ OPEN/LEXICAL_ONLY → CostDegradedDTO(FR-11)   (INV-U11-4)
        ▼
2. retrieveCandidates(query, attachmentContext)   ← "유사논문 검색" 노드 (U2 재사용·A+ 다중쿼리)
        · 질의·첨부를 하위질의로 분해 → U2 여러 번 → 후보 합집합 · PaperId 디덥
        · 출력 = CandidateSet(최소 paper_id; 선택적 block_id locator)
        · 빈 결과 → AbstainDTO (빈 성공 금지, INV-U11-5)
        ▼
3. extractPaperEvidence(candidate)  ∀ 후보 (fan-out)   ← U7 §6 추출 노드 재사용
        · doc-model 읽기(논문 전체; locator 있으면 시드→섹션 확장, 없으면 섹션/문서)
        · {claims·method·results(표 셀 값)·limitations} 추출 + Anchor(구조화 locator) 부착
        · 선택적 코드/데이터 공개 사실(각주 포함) — 재현성 판정 아님(C-2)
        · 추출 불가 항목은 비우고 기권 후보 표시
        ▼
4. crossCheck(evidences[])   ← 신규 합성 노드
        · 주제축(주장/방법/결과)별 agreement/contradiction/gap 태깅
        · 추출 항목의 정렬·대조만 — 새 결론 산문 생성 금지(C-2)
        ▼
5. enforceGrounding(table, candidateSet)  = U6 문서충실도 근거화 공유 계약(Q7 통일)
        · 항목별 매핑·검증 → grounded | abstained (항목 단위 부분 기권)
        · 근거 못 붙은 항목만 기권, 표 전체는 유지(US-RA6)
        · 날조 주장/인용 0건(FR-5·QT-8)
        ▼
6. assemble → EvidenceTableDTO  (부분 실패 시 PartialResultDTO)
        ▼
7. persistResult + cache write + telemetry emit (모드별 호출·지연·기권/저하·비용 — US-RA7)
        ▼ 스트리밍/폴링(긴 분석=비동기 잡 옵션, NFR-P5)
[ 클라이언트: 근거표 점진 렌더 + "출처 보기"(앵커) + 진행상태 ]
```

---

## 2. 메서드 (시그니처는 도메인 수준)

| 메서드 | 책임 |
|---|---|
| `startSession(userId, mode)` | 세션 생성(owner-scoped) |
| `appendTurn(sessionId, query, attachments)` | 턴 추가·검증·라우팅(모드별) |
| `runEvidenceFormation(turn)` | §1 파이프라인(모드 A) |
| `retrieveCandidates(query, attachmentContext)` | U2 재사용·A+ 다중쿼리 → CandidateSet(최소 paper_id; 선택 locator) |
| `extractPaperEvidence(candidate)` | doc-model 읽기(locator 시드/섹션) → PaperEvidence + Anchor |
| `crossCheck(evidences[])` | agreement/contradiction/gap 태깅(추출·비교만) |
| `enforceGrounding(table, candidateSet)` | U6 통일 근거화 계약 정형화/매핑(항목별 기권·재구현 금지) |
| `applyCostGate(context)` | U6 `getBudgetState` 저하 분기 |
| `reportProgress` / `assemblePartial` | 진행상태·부분결과(NFR-P5·RES-9) |
| `listSessions(userId)` / `reopenSession(sessionId)` | 재열람(US-RA5·owner-scoped) |
| `deleteSession` / `deleteAttachment` / `resetHistory` | 분리 제어(Q12·INV-U11-6) |
| `lookupCache(key)` / `persistResult(result)` | 캐시·영속(Q11) |
| `getPersonalizationDefaults(userId)` | U9 비차단 약신호(모드 제안·정렬 힌트만 — Q13) |
| *(차기)* `compareNovelty(...)` | placeholder — 빌드 안 함(Q14) |

---

## 3. 멀티턴 맥락 (Q8=A)

세션=턴 시퀀스. 후속 턴 입력 = 현재 질의 + 첨부 + **(요약된) 이전 맥락**. 단 근거표는 **매 턴 실제 코퍼스에서 재추출·재그라운딩**하고 **과거 생성물을 출처처럼 재인용하지 않는다**(누적 환각 방지).

---

## 4. 첨부 처리 (Q6=A)

`AttachmentIngestor`: 업로드 검증·무해화(SEC-5/11) → doc-model 파이프라인 재사용 파싱 → **질의 맥락/비교 기준**으로만 사용. 근거 소스는 owned 코퍼스(검증 가능)로 한정 — 첨부 자체 인용 안 함.

---

## 5. 실패·저하 경로 (비차단 — NFR-P5·RES-9·INV-U11-5)

- 일부 후보 추출/외부 의존 실패 → 부분 결과 + degraded 표시(`PartialResultDTO`), 전체 실패 아님.
- 근거 없음 → `AbstainDTO`(빈 성공 금지).
- 비용 게이트 → `CostDegradedDTO`(FR-11).
- 첨부 검증 실패 → `InputRejectedDTO`.
- U9 개인화 신호 실패 → 무개인화로 진행(본 기능 비차단·Q13).
- 에이전트 실패가 본 검색(U2) 등 타 기능을 막지 않음.

---

## 6. 재사용 지점 (추적성 핵심 — Q17)

| 노드 | 재사용 대상 |
|---|---|
| 게이트·근거화·비용 | **U6** (gateway·근거화 통일 계약·`getBudgetState`) |
| 유사논문 검색(후보) | **U2** 검색(A+ 다중쿼리·전문 통합 인덱스) |
| 논문별 추출·정제·앵커 | **U7** §6 6~7단계 *배관 노드*(요약 노드 리팩터 X) + doc-model |
| 외부 API 캐시 패턴 | **U8**(모드 B 차기 예약) |
| 개인화 약신호 | **U9**(비차단) |
| 전문 인덱스·doc-model eager | **U1** 인제스천(게이트 DF-1/2/6) |

> 신규 노드 = "유사논문 검색"(후보 fan-out)·"교차확인 합성"(crossCheck)·"근거표 조립"·세션/영속. 자율 에이전트 루프는 **안 함**(목표 절제).
