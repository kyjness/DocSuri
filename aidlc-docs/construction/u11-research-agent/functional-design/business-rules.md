# U11 Research Agent — Business Rules (Functional Design)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거(SSOT)**: `requirements.md`(FR-22~25·NFR-P5·QT-8·NFR-C1 Agent·§12·C-2), `stories.md`(US-RA1~8), `plans/u11-research-agent-functional-design-plan.md`(Q1~Q17), `plans/docmodel-fulltext-index-pivot-plan.md`(DF-1~6).
**상태**: 🟡 PROVISIONAL — 게이트 승인·U6 근거화 공유 계약 확정 시 동기화.

---

## 1. 불변식 (INV)

- **INV-U11-1**: 모든 진입은 로그인 필수·owner-scoped(SEC-8, U6 게이트웨이).
- **INV-U11-2**: 근거화 단일 권위 = U6(정책 불변: 근거 없으면 기권·날조 0건·결정적 검증). U11은 정형화·매핑만, 우회·재구현 금지. 메커니즘/형상은 U6 공유 계약 확장으로(Q7).
- **INV-U11-3**: U11은 추출·비교만. 산문 생성 금지(C-2). 재현성 판정/계산 금지.
- **INV-U11-4**: 비용 단일 권위 = U6. 조회·분기만(독자 판정 X).
- **INV-U11-5**: U11 실패/저하는 타 기능을 막지 않음(비차단). 부분결과·진행상태 허용, 빈 성공 금지.
- **INV-U11-6**: 결과·세션·첨부 owner-scoped 영속 + 삭제/초기화 분리 제어(Q12).
- **INV-U11-7**: v1 = 모드 A만 빌드. 모드 B(novelty)는 seam만(Q4=A).

---

## 2. 비즈니스 규칙 (BR-RA)

| ID | 규칙 | Trace |
|---|---|---|
| **BR-RA-1** | 로그인·owner-scoped 접근 — 세션/결과/첨부는 소유자만 조회·수정·삭제. | SEC-8, US-RA1, INV-U11-1 |
| **BR-RA-2** | 첨부 검증·무해화 — 허용 형식/크기만 수용, 위반 시 `InputRejectedDTO`. 본문 격리(injection 대비). | SEC-5/11, US-RA2 |
| **BR-RA-3** | 후보 디덥 — CandidateSet은 PaperId로 디덥. 검색 출력 최소 보장=`paper_id`(+score); block_id locator는 권장 옵션(granularity=GQ1). | US-RA3, DF-5 |
| **BR-RA-4** | 빈 성공 금지 — 후보/근거 없음은 빈 표가 아니라 `AbstainDTO`. | FR-5, US-RA3, INV-U11-5 |
| **BR-RA-5** | 추출·비교 경계 — 근거표/쟁점 태그는 추출 항목의 정렬·대조만. 종합 결론 산문·사용자 원고/문헌리뷰 산문 생성 금지. | C-2, US-RA3, INV-U11-3 |
| **BR-RA-6** | 재현성 비판정 — 재현성을 판정/계산하지 않음. "코드/데이터 공개 사실"만 선택적 추출(각주 포함, DF-6). | FR-22(Q7), §12 |
| **BR-RA-7** | 단일 근거화 권위 — 근거화는 U6 통일 공유 계약(문서충실도). U11은 정형화/매핑만. 항목별 기권(grounded\|abstained), 근거 못 붙은 항목만 기권하고 표 유지. 날조 0건. | FR-5, QT-8, Q7, US-RA4 |
| **BR-RA-8** | 출처 부착 — 모든 EvidenceItem은 검증 가능한 원문 Anchor(구조화 locator + 라벨)를 가진다. "출처 보기"가 동일 locator로 연결. | FR-22, US-RA4 |
| **BR-RA-9** | 교차확인 결정성 — 동일 입력 후보 집합 → 동일 비교 결과(agreement/contradiction/gap). | QT-8, US-RA3 |
| **BR-RA-10** | 비용 게이트 — U6 `getBudgetState`: NORMAL 진행 / OPEN·LEXICAL_ONLY → `CostDegradedDTO`(FR-11). 독자 비용 판정 금지. | NFR-C1, US-RA7, INV-U11-4 |
| **BR-RA-11** | 첨부 역할 한정 — 첨부는 질의 맥락·비교 기준으로만, 근거 출처로 인용 금지(외부 미검증 텍스트 그라운딩 방지). | C-2, SEC-5, US-RA2 |
| **BR-RA-12** | 캐시 신원 immutable — `AgentCacheKey`(정규화 질의·모드·첨부 해시·코퍼스 스냅샷·모델/프롬프트 버전·persona?). 단일 턴 분석만 캐시; 버전 변경 시 무효화. 동일 키 중복 호출 LLM 0콜. | NFR-C1, SEC-11, Q11 |
| **BR-RA-13** | 멀티턴 재그라운딩 — 후속 턴은 이전 맥락을 입력 보조로 쓰되, 근거표는 매 턴 코퍼스에서 재추출·재그라운딩(과거 생성물 재인용 금지). | Q8, FR-5 |
| **BR-RA-14** | 비차단 저하 — 일부 소스/외부 의존 실패 시 부분 결과 + degraded 표시. 에이전트 실패가 타 기능 차단 금지. | NFR-P5, RES-9, FR-11, US-RA6 |
| **BR-RA-15** | 영속·삭제·초기화 분리 — `deleteSession`·`deleteAttachment`·`resetHistory` owner-scoped 분리 제공. 무기한 보관은 명시 정책(차기 재검토). | FR-25, Q12/Q14, US-RA5 |
| **BR-RA-16** | 개인화 비차단 약신호 — U9 persona/관심은 모드 제안·정렬 힌트에만. 실패/부재 시 무개인화 진행. 근거표 내용은 안 바꿈. | Q13, NFR-P5 |
| **BR-RA-17** | 모드 B 경계 — v1은 모드 B 미빌드. 도메인/포트 seam만(외부 API·커버리지 확장 차기). | FR-23, Q4=A, Q14, INV-U11-7 |
| **BR-RA-18** | 진행상태·종단 구분 — 응답은 5종 union(EvidenceTable/Partial/Abstain/CostDegraded/InputRejected). 완전 vs 부분 혼동 금지. | NFR-P5, Q9 |

---

## 3. QT-8 속성(PBT) 후보 (Q16=A)

1. **근거표/DTO roundtrip** — `AgentResponse` 5종 union 직렬화·역직렬화 보존.
2. **기권 안정성** — 근거 없으면 항상 기권(grounded 표기 0건), 날조 인용 0건.
3. **owner isolation** — 비소유자 접근 시 항상 거부(세션/결과/첨부).
4. **캐시 키 immutability/dedupe** — 동일 입력 → 동일 키 → 캐시 히트; 버전 변경 → 무효화.
5. **부분결과 불변식** — 완전(EvidenceTable)과 부분(Partial)이 섞이지 않음; degraded 소스 명시.
6. **출처 링크 유효성** — 모든 grounded 항목의 Anchor locator가 doc-model에 실재.

> PBT는 기존 Partial 모드 유지. 평가셋 구체 수치·케이스 소유 = OP/팀(QT-1과 동일 체계).

---

## 4. 추적성 매트릭스

| 요구사항/스토리 | 규칙·로직 |
|---|---|
| FR-22 (근거형성·모드 A) | BR-RA-3/5/7/8/9, §1 파이프라인 |
| FR-23 (novelty·모드 B 차기) | BR-RA-17(seam) |
| FR-24 (대화 입력·첨부) | BR-RA-2/11, AgentQuery/Attachment |
| FR-25 (결과·세션 영속·전용 진입) | BR-RA-1/15, ResearchResult, frontend-components |
| NFR-P5 (온디맨드·비차단) | BR-RA-14/18, PartialResult |
| NFR-C1 Agent (비용) | BR-RA-10/12 |
| QT-8 (근거·novelty 인수) | BR-RA-7/8/9, §3 PBT |
| §12 Agent 카브아웃·C-2 | BR-RA-5/6/11, INV-U11-3 |
| FR-5 (근거화·기권) | BR-RA-4/7/8/13 |
| SEC-8/5/11 | BR-RA-1/2/11 |
| US-RA1~8 | (위 행 매핑) |
| 전문 인덱스·근거화 통일·doc-model eager | 게이트 DF-1~6 (별도 승인) |
