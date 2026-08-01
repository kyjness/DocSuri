# Evidence Agent v2 (U11) — 논리 컴포넌트 (Logical Components)

**단계**: CONSTRUCTION → NFR Design (재설계 라운드) · **유닛**: U11 · **일자**: 2026-07-28
**근거**: `functional-design/*` · `nfr-requirements/tech-stack-decisions.md` · 요구사항 게이트 Q6=B·Q7=A·Q15=A.

---

## 1. 토폴로지

```
        ┌──────────────────────────────────────────────────────┐
        │  /api/evidence  (단일 라우터 — research 모듈 제거)     │
        └───────────────┬──────────────────────────────────────┘
                        │  (동기 SSE)          (복잡 요청)
                        ▼                          ▼
                 EvidenceChatService  ──enqueue──▶  Job Queue ──▶ Worker
                        │                                          │
                        └──────────────┬───────────────────────────┘
                                       ▼
                                 EvidenceLoop  (domain — 순수)
                        ┌──────────────┼───────────────┐
                        ▼              ▼               ▼
                  ToolRegistry     LoopBudget      EvidenceGate
                        │                              │
        ┌───────┬───────┼────────┬─────────┬───────────┘
        ▼       ▼       ▼        ▼         ▼
   corpus_  external_ fetch_   read_    view_figure / extract_evidence
   search   search    paper    paper
        │       │       │        │         │
   ┌────┴───┬───┴───┬───┴────┬───┴────┬────┴─────┐
   │ U2     │ 외부   │ u1     │DocModel│ 자산      │   ← 포트 뒤 어댑터
   │ 검색   │ 소스   │ 빌드   │ 스토어 │ 리더      │
   └────────┴────────┴────────┴────────┴──────────┘
                        │
                        ▼
              EvidenceRepository (sessions / turns / trace)
```

**도메인은 어댑터를 모른다** — 루프·게이트·예산은 포트 인터페이스만 안다.

---

## 2. 컴포넌트 책임

| 컴포넌트 | 역할 | 계층 |
|---|---|---|
| `EvidenceRouter` | `/api/evidence` HTTP 표면 — 턴 생성·조회·세션 CRUD·첨부 업로드·잡 폴링 | API |
| `EvidenceChatService` | 세션 load/create, 컨텍스트 조립, 동기/비동기 분기, 결과·트레이스 저장 | Application |
| `EvidenceLoop` | observe/decide/act 반복, 종료 판정 | **Domain(순수)** |
| `ToolRegistry` | allowlist deny-by-default 도구 등록·조회 | Domain |
| `LoopBudget` | 3중 한도 검사·차감 | Domain |
| `EvidenceGate` | 날조 검사 6겹 — 순수 함수 | **Domain(순수)** |
| `EvidenceAccumulator` | 게이트 통과분 누적, 종료 판단 입력 제공 | Domain |
| `EvidenceAssembler` | 비교표·쟁점 조립(결정론) | Domain |
| `EvidenceRepository` | 세션·턴·트레이스 저장(소유자 격리) | Port + Adapter |
| `EvidenceFormationService` | D5 포트 구현 — U12 노출 | Application |
| `EvidenceWorker` | 비동기 잡 실행 + 승격 파싱(CPU) | Worker |

---

## 3. 포트 목록

| 포트 | 구현(현행) | 실패 처리 |
|---|---|---|
| `LlmPort` | OpenAI 어댑터 | 재시도 1 + 브레이커 → `abstain(llm_unavailable)` |
| `CorpusSearchPort` | U2 discovery 재사용 | 브레이커 → 근거 유무에 따라 기권/확인 범위 |
| `ExternalPaperSearchPort` | arXiv 클라이언트 + payload allowlist + 허용 호스트 | 브레이커 → 그 도구만 실패 |
| `PaperPromotionPort` | u1 ingestion 빌드 경로 **인프로세스 호출** | 실패·라이선스 차단은 **정상 결과값** |
| `DocModelReadPort` | DocModel 스토어 read-only | 개별 실패는 건너뜀 |
| `FigureAssetPort` | `shared/`로 올린 비전용 리더(바이트 반환) | 부재/장애 구분 |
| `EvidenceRepositoryPort` | postgres 3테이블 | 재시도 → `TurnErrorResult` |
| `JobQueuePort` | redis 큐 | best-effort enqueue |
| `BudgetStatePort` | U6 `get_budget_state()` | 단일 권위 — 재판정 금지 |

---

## 4. 조건부 마운트

설정이 없으면 그 도구가 등록되지 않고 **에이전트 도구 목록이 자연 축소**된다(기존 `wiring.py` 원칙).

| 없을 때 | 결과 |
|---|---|
| LLM 설정 | 유닛 자체가 마운트되지 않는다 |
| 검색 엔드포인트 | `corpus_search` 미등록 → 내부 코퍼스 탐색 불가(외부만) |
| 외부 소스 설정 | `external_search`·`fetch_paper` 미등록 → 코퍼스 안에서만 |
| 자산 토글/postgres | `view_figure` 미등록 → 그림 근거 없음 |
| DocModel 스토어 | `read_paper` 미등록 → 초록 범위 근거만 |

---

## 5. 프로세스 배치

| 실행 단위 | 담당 |
|---|---|
| API 프로세스 | 라우터 + 동기 SSE 루프(짧은 질의) |
| 잡 워커 | 복잡 요청 루프 + **승격 파싱(CPU 바운드)** + 백그라운드 색인 |

**승격 파싱을 워커에 두는 이유**: 파싱은 CPU를 쓰므로 API 이벤트 루프에서 돌리면 다른 요청의 지연이 튄다(TD-EV2-5).

---

## 6. 삭제 경로

세션 소프트 삭제 → 턴·결과·**트레이스** 함께 파기. 계정 삭제 시 owner-scoped 캐스케이드(U3 `AccountDeleted` 구독). 외부 초록 스냅샷 테이블이 없으므로 **파기 대상은 이 3테이블뿐**이다.

---

## 7. v1 대비 제거·이관

| 대상 | 처리 |
|---|---|
| `backend/modules/research/` (껍데기 표면) | **제거** |
| `research_jobs` · `research_messages` | `evidence_*`로 이관 후 제거 |
| `evidence/orchestrator.py` (고정 파이프라인) | **제거** — 루프로 대체 |
| `evidence/intent.py` (정규식 의도 분류) | **제거** — 질의 해석은 루프 판단 |
| `evidence/extractor.py` 검증 로직 | **이식** — `EvidenceGate`로 승격·확장 |
| `evidence/assembler.py` | **이식** — 결정론 조립 유지 |
| `novelty/adapters/figures.py` 리더 | **`shared/`로 이동** — novelty·evidence 공유 |
