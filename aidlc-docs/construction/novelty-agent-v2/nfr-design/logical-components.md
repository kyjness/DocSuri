# Novelty Agent v2 — Logical Components

**Unit**: Novelty Agent v2 (U12)
**Stage**: NFR Design (2026-07-18)
**배치 원칙**: `backend/modules/novelty/` 내부 재작성(arch Q4=A) — 헥사고날 분리, 기존 conditional mounting 관례 유지. 코드 생성 시 아래 배치가 기준.

## 1. 컴포넌트 지도

```
backend/modules/novelty/
├── domain/                     ← 실행 환경 무지(no adapter import)
│   ├── loop.py                 루프 코어: observe→decide→act, 종료 판정(BR-RA1)
│   ├── budget.py               LoopBudget 집행(BR-RA3) — 검사·소비 기록
│   ├── gate.py                 산출물 저장 게이트(BR-RA2) — 결정론 검증
│   ├── models.py               NoveltyJob·AgentLoopRun·ToolCallRecord·GapAnalysis 등
│   └── projection.py           트레이스 → 활동 피드·거시 상태 투영(FR-35)
├── ports/                      Protocol 정의
│   ├── llm.py                  tool-calling LLM 포트
│   ├── tools.py                도구 포트: corpus_search·form_evidence·external_search·view_figure
│   ├── assets.py               자산 포트: figure/수식 crop 매니페스트·바이트(view_figure)
│   ├── queue.py                잡 큐 포트(적재·소비·실행 잠금)
│   └── store.py                잡·산출물·트레이스·대화 저장 포트
├── adapters/
│   ├── local_wiring.py         redis 큐·postgres 저장·Bedrock tool-calling
│   ├── real_wiring.py          SQS·RDS·Bedrock (배포 기준선 — 계약 보존)
│   ├── external/               GitHub·데이터셋 (직접 구현 어댑터 — TD-NV2-4)
│   │   └── sanitize.py         도구별 payload allowlist 강제(BR-RA7)
│   ├── evidence.py             U11 EvidenceFormationPort 소비(공유 계약)
│   └── figures.py              view_figure 도구 + paper_asset/S3 리더(⑤3)
├── api.py                      잡 생성/조회/취소 + 잡 귀속 대화(스티어링·온디맨드)
└── worker.py                   워커 엔트리포인트 — 큐 소비→루프 실행(NFR-NV2-1)
```

## 2. 컴포넌트 책임

| 컴포넌트 | 책임 | 참조 |
|---|---|---|
| 루프 코어(`domain/loop.py`) | 매 턴 LLM 결정 요청 → 예산 검사 → 도구 실행 → 트레이스 기록 → 종료 판정. 어댑터 무지 | FD BLM §2 |
| 저장 게이트(`domain/gate.py`) | `save_artifact` 경로 유일 관문 — SourceRef 실재성·필수 필드·bounded 규칙. LLM 무관 순수 함수 중심 | BR-RA2 |
| 예산 집행(`domain/budget.py`) | 3중 한도 검사·소비 기록. 수치는 설정 주입(NFR §3 시작값) | BR-RA3, FR-45 |
| 트레이스 기록기 | 도구 호출 1:1 `ToolCallRecord` 기록. 기록 불가 지속 시 루프 중단(NFR-NV2-13) | BR-RA4, FR-46 |
| 투영기(`domain/projection.py`) | 트레이스 → 사용자용 활동 피드 문구, 거시 상태 계산. 파생 뷰 — 실패해도 잡 비실패 | FD BLM §7 |
| API(`api.py`) | 접수·조회(커서 폴링)·취소 플래그·대화 수신. 실행하지 않음 | NFR-NV2-5·6·10 |
| 워커(`worker.py`) | 큐 소비, `job_id` 실행 잠금, stale 잡 감지·failed 처리, 협조적 취소 확인 | NFR-NV2-2·3·10 |
| sanitize 어댑터 | 외부로 나가는 도구 인자의 allowlist 필터 — 도구별 규칙 표를 데이터로 보유 | BR-RA7, NFR-NV2-15 |

## 3. 잡 수명 시퀀스

```
FE → API: 잡 생성 ─ owner 검증·U6 예산 확인·(자연어) evidence 선행 예약 ─→ 큐 적재, 즉시 응답
워커: 큐 소비 → 실행 잠금 → form_evidence(선행) → 루프[decide→budget→tool→trace]* → 게이트 저장
     → 필수 세트 완성 → reporting → completed  (또는 partial/cancelled/failed)
FE ←폴링← API: 거시 상태 + 활동 피드 커서 + 산출물 참조
FE → API: (종단 후) 대화 — 스티어링 질문 / 온디맨드 요청 → 단일 턴 처리(같은 게이트) → 응답+산출물 병합
FE → API: Notion preview 요청 → 승인 → export (루프 밖)
```

## 4. Conditional Mounting

- 모듈 마운트 조건: 저장소 + 잡 큐 + LLM 프로바이더 설정 존재 시 API 마운트, 워커는 동일 설정으로 별도 기동. 외부 탐색 어댑터는 각자 설정 존재 시에만 도구 레지스트리에 등록(없으면 해당 도구 미노출 — 에이전트 도구 목록이 자연 축소).
- `view_figure`는 자산 스토어 설정(`DOCSURI_MULTIMODAL_ASSETS_ENABLED` — u1/u7과 공유하는
  토글) + postgres 세션 팩토리가 있을 때만 등록한다(구현 완료 2026-07-27). 버킷 env는
  조건이 아니다 — 객체 주소는 `paper_asset.object_ref`가 들고 있고, `DOCSURI_S3_BUCKET`은
  인제스천 스택에만 있어 조건에 넣으면 배포 환경에서 도구가 무증상으로 사라진다.
  워커가 도구 레지스트리를 만드는 유일한 프로세스이므로 토글은 **워커 태스크**에 있어야 한다.
- Notion은 도구 레지스트리에 절대 등록되지 않는다(BR-RA12) — export 경로는 API 측 별도 서비스.

## Traceability

| Source | Covered By |
|---|---|
| FD BLM §0~§10 | §1~§3 배치·시퀀스 |
| NFR-NV2-1~3(워커·멱등·stale) | worker.py 책임, §3 |
| NFR-NV2-5·6·14(API·폴링) | api.py 책임 |
| BR-RA2/3/4/7/12 | gate·budget·트레이스·sanitize·mounting 규칙 |
| TD-NV2-1~8 | adapters/ 구성(local_wiring 1차, real_wiring 기준선 보존) |
