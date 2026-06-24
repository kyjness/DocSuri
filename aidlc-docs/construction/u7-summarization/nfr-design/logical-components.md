# U7 Summarization — Logical Components (논리 컴포넌트·토폴로지)

**단계**: CONSTRUCTION → NFR Design · **유닛**: U7 Summarization · **일자**: 2026-06-19
**근거**: 계획서 §4 Q9=A · NFR Requirements(TD-S1~S12) · FD(9 컴포넌트) · `nfr-design-patterns.md`.
**원칙**: FD 9 도메인 컴포넌트를 **논리(배포 가능) 컴포넌트**로 매핑(재계수 아님). real-first — 실 어댑터 단일본(+테스트 Fixture/Stub).

---

## 1. 토폴로지 (backend 모놀리스 ① 내 U7 모듈)

```
            [ U6 게이트웨이 ]  authn · authz(SEC-8) · rate-limit(SEC-11) · principal 주입
                   │ (마운트: backend/wiring.py — @ELSAPHABA 조율 존)
                   ▼
        ┌──────────────────────────────────────────────┐
        │  FastAPI U7 Router (SummarizationController)   │  POST /api/summarize (task=summary|translate)
        │                                                │  GET/POST /api/glossary (개인 용어집 조회·저장, BR-S4)
        └──────────────────────────────────────────────┘
                   ▼
        ┌──────────────────────────────────────────────┐
        │  SummarizationOrchestrationService            │  온디맨드 파이프라인(동기 스트리밍)
        │  cache→cost→source→refine→glossary→len→gen→   │
        │  groundingValidate→assemble→write→telemetry   │
        └──────────────────────────────────────────────┘
          │        │        │        │         │        │
          ▼        ▼        ▼        ▼         ▼        ▼
  ┌─────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │SummaryStore │ │FullText  │ │Glossary  │ │BedrockLlm    │ │Grounding     │ │Ports → U6    │
  │Adapter      │ │Source    │ │Repository│ │GatewayAdapter│ │Validator     │ │(Cost/Observ) │
  │S3+Redis     │ │Adapter S3│ │RDS PG    │ │Bedrock stream│ │(U7 결정적)   │ │get_budget/   │
  └─────────────┘ └──────────┘ └──────────┘ └──────────────┘ └──────────────┘ │emit*         │
                                                                                └──────────────┘
   (비차단) ──▶ ObservabilityHub.emit*  (토큰·비용·지연·persona·task·근거화 결과)
```

---

## 2. 논리 컴포넌트 명세

| 논리 컴포넌트 | 책임 | 어댑터/스토어 | FD 컴포넌트 매핑 |
|---|---|---|---|
| **U7 Router** | REST 진입·요청 검증·스트리밍 응답 | FastAPI | `SummarizationController` |
| **OrchestrationService** | 파이프라인 조정·종단 상태 결정 | — | `SummarizationOrchestrationService` |
| **SummaryStoreAdapter** | read/write-through 캐시 | **S3(영구) + ElastiCache Redis(핫)** | `SummaryCacheStore` |
| **FullTextSourceAdapter** | 전문 read(capability) | **S3**(`stored_full_text_ref`) | `SourceSelector`(전문 경로) |
| **GlossaryRepository** | 시드(코드)∪개인(영속) 용어집 | **RDS PostgreSQL**(개인, owner 스코프) | `GlossaryResolver` |
| **BedrockLlmGatewayAdapter** | 요약/번역 생성(스트리밍) | **Bedrock**(Sonnet/Haiku, U6 게이트웨이 경유) | `LlmSummarizer`/`LlmTranslator` |
| **InputRefiner** | 정제·섹션 도출·본문 격리 | (정규식·휴리스틱) | `InputRefiner` |
| **LengthRouter** | 단일/맵-리듀스 분기 | — | `LengthRouter` |
| **GroundingValidator** | 결정적 앵커/수치/스키마 검증 | (U7 고유) | `GroundingValidator` |
| **ResultAssembler** | 조립·SEC-9 필터·후치환 | — | `ResultAssembler` |
| **CostGate / Telemetry** | 비용 게이트·관측 | **Ports → U6**(`get_budget_state`·`emit*`) | `CostGate` |

> **포트 + 실 어댑터 단일본**(real-first): 각 어댑터는 포트 인터페이스 구현이며 출하 구현은 실(S3·Redis·RDS·Bedrock) 1종. **Production Mock Adapter 없음**; 단위 테스트는 테스트 Fixture/Stub로 포트 대체(출하 아님).

---

## 3. 데이터플레인 vs 컨트롤/텔레메트리 경계

- **온디맨드 데이터플레인**(동기, 사용자 응답 경로): Router → Orchestration → cache/source/refine/glossary/gen/grounding/assemble → 스트리밍 응답.
- **비차단 텔레메트리**(응답 경로 밖): `emit*` → `ObservabilityHub`(fire-and-forget). 발행 실패 = 응답 무영향.
- **비용 게이트**(데이터플레인 내, LLM 직전): `get_budget_state()` 조회 — 판정은 U6, U7은 분기만.

---

## 4. 신규 데이터 자산 (기존 인프라 재사용 — 상세는 Infra)

- **S3**: `summaries/{paperId}/v{version}/{task}_{lang}_{persona}_{modelVer}_{promptVer}.json`(요약 영구) — 기존 버킷/전문과 공존.
- **Redis(ElastiCache)**: 요약 핫캐시 키스페이스(TTL) — 기존 세션 캐시와 키스페이스 분리.
- **RDS PostgreSQL**: 개인 용어집 테이블(`user_glossary` 등, owner FK·`glossary_ver`) — 기존 accounts/library DB와 공존.
- **Bedrock**: Sonnet/Haiku 모델 액세스(IAM) — 기존 임베딩(Cohere) 액세스와 공존.

> 신규 관리형 서비스 0(전부 기존 프로덕션 자산 재사용). 비용 라인·테이블 DDL·키스페이스·IAM 정책 상세 = **Infrastructure Design**.

---

## 5. 마운트·조율 경계

- U7 모듈은 `backend/modules/summarization/`(독립 pyproject) → backend 모놀리스 app-shell 마운트(`backend/wiring.py`).
- **⚠️ 조율 존**(`backend/wiring.py`·게이트웨이 라우팅)은 @ELSAPHABA 사인오프 — U7은 마운트 계약 제안.
- 신규 DTO 계약 `shared/dtos/summarization`(PROVISIONAL) → 별도 shared PR 승격.
