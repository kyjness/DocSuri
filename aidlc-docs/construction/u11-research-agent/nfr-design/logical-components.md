# U11 Research Agent — Logical Components (논리 컴포넌트 · 토폴로지)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U11 Research Agent · **일자**: 2026-06-24
**근거**: `nfr-design-patterns.md`(Q1~Q14=A) · FD(business-logic-model 컴포넌트) · TD-RA-1~15.
**고도**: 논리 컴포넌트·역할·포트·토폴로지. 인스턴스 수·리전·IaC·수치 = Infra Design.

---

## 1. 컴포넌트 인벤토리 (Q12=A)

| 컴포넌트 | 역할 | 의존(포트) |
|---|---|---|
| **API 라우터** | 진입(스트리밍 SSE / 폴링)·요청 검증 | U6 게이트웨이(authn/rate-limit) |
| **AgentOrchestrator** | 파이프라인 조율(검색→fan-out 추출→교차확인→근거화→조립)·종단 상태 결정 | 아래 전부 |
| **ConversationInputHandler** | 모드 선택·질의·첨부 인테이크·검증(SEC-5) | — |
| **AttachmentIngestor** | 첨부 무해화·doc-model 파싱 재사용 | S3(첨부)·doc-model 빌더 |
| **MultiPaperRetriever** | bounded 다중쿼리 후보 검색(A+) | **U2 검색**(서킷=U2) |
| **EvidenceExtractor** | doc-model 읽기(locator 시드→섹션)·논문별 추출 | **doc-model 읽기**(S3/캐시)·**Bedrock**(U6 게이트웨이) |
| **CrossCheckSynthesizer** | 합의/상충/공백 태깅(추출·비교만) | Bedrock |
| **AgentGroundingAdapter** | U6 **통일 근거화 공유 계약** 정형화·verdict 매핑(항목별 기권) | **U6 근거화** |
| **EvidenceTableAssembler** | 출력 조립·SEC-9 비노출 필터·종단 union | — |
| **AgentCostGuardAdapter** | `getBudgetState` 저하 분기 | **U6 CostGuard** |
| **AgentProgressReporter** | 진행상태·부분결과 스트림 | — |
| **ResearchResultStore** | 세션·턴·결과 owner-scoped 영속 | **RDS** |
| **결과 캐시** | `AgentCacheKey` read/write-through | **Redis(핫) + 영구** |
| **AsyncJobQueue + AgentWorker** | 대규모 분석 비동기 처리(폴링→캐시 히트) | **SQS** + Orchestrator 재사용 |
| **AgentTelemetryPublisher** | 모드·지연·기권/저하·비용 emit | **U6 ObservabilityHub** |
| **의존성별 서킷** | 검색/doc-model/Bedrock/저장 격리(§1.1) | (각 포트 래핑) |
| *(차기)* NoveltyComparator | 모드 B seam(미빌드) | — |

---

## 2. 토폴로지 (런타임)

```
                       ┌──────────── U6 게이트웨이 (authn·authz·rate-limit·SEC-8/11) ────────────┐
[클라이언트/프런트] ──▶ │ API 라우터(SSE/폴링)                                                   │
   (u11-frontend)      └───────────────────────────────┬───────────────────────────────────────┘
                                                        ▼
                                              AgentOrchestrator
        ┌──────────────┬──────────────────┬───────────────┬───────────────┬──────────────┐
        ▼              ▼                  ▼               ▼               ▼              ▼
  [캐시 조회]   [CostGuardAdapter]   MultiPaperRetriever  EvidenceExtractor  CrossCheck   GroundingAdapter
   Redis+영구    └U6 getBudgetState   └U2 검색(서킷=U2)    └doc-model(S3)·    Synthesizer  └U6 통일 근거화
   (HIT=0콜)                          (A+ 다중쿼리·        Bedrock(서킷·                   (항목별 기권)
                                       locator 옵션)       bounded 병렬)
                                                        ▼
                                          EvidenceTableAssembler (SEC-9 필터·5종 union)
                                                        ▼
                              ResearchResultStore(RDS) + 캐시 write + TelemetryPublisher(U6 Hub)
                                                        │
        ┌──── 대규모(Q8 3밴드) ────▶ AsyncJobQueue(SQS) ─▶ AgentWorker(Orchestrator 재사용) ─▶ 캐시 write ─▶ 폴링 히트
```

- **각 외부 의존은 §1.1 서킷/격리로 래핑** — 검색(U2 소유)·doc-model 읽기·Bedrock·U6·RDS/Redis. 거동: Abstain/Partial/기권/fail-closed/폴백.
- **stateless 인스턴스**(상태=RDS/Redis/SQS 외부) → 수평 확장. 비동기 워커 별도 스케일.

---

## 3. 포트 · 단일 권위 경계

- **U6 위임(재구현 금지)**: 게이트웨이(authn/authz/rate-limit)·근거화 통일 계약·`getBudgetState`·ObservabilityHub. U11은 어댑터로 소비.
- **U2 재사용**: 검색(OpenSearch 서킷 U2 소유). U11은 호출만(또는 직접 질의 — FD Q2 미정).
- **doc-model**: 읽기 포트(S3/캐시/빌드) — 아키텍처 게이트(eager 생성).
- **shared DTO**: `shared/dtos/research_agent`(TD-RA-14 승격).

---

## 4. 배포 단위 (Infra 확정)

- **① backend 모놀리스 모듈** `backend/modules/research_agent/`(동기 경로).
- **③ Agent 워커**(대규모 비동기 잡 — SQS 소비) 별도 배포.
- **프런트** `u11-research-agent-frontend` 별도 트랙.
- 인스턴스 수·오토스케일·SQS/Redis/RDS 사이징·전문 인덱스 사이징 = **Infrastructure Design**.

---

## 5. 추적성
컴포넌트 → 패턴(`nfr-design-patterns.md` §1~5) · FD(business-logic-model 메서드·INV-U11) · TD-RA-1~15. 단일 권위(근거화·비용·인증·레이트리밋=U6)·INV-U11-1~7 불변.
