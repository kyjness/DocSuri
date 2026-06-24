# U7 Summarization Frontend — Logical Components

**단계**: CONSTRUCTION → NFR Design · **유닛**: U7 Summarization Frontend · **일자**: 2026-06-19
**근거**: FD `frontend-components.md`(12 컴포넌트) · NFR Design 패턴(P1~P8) · 프론트 자산. **재계수 아님** — FD 컴포넌트를 논리 토폴로지로 배치.

---

## 1. 논리 토폴로지

```
[서버 경계]
└─ Route /paper/[id] (Server Component 셸) ......... SSR, 라우트 데이터로 PaperHeader 렌더 (P3)
       │  (헤더: 제목·저자·초록·arXiv 링크 — 클라이언트 호출 0)
       ▼
[클라이언트 경계 — 아일랜드]
PaperDetailIsland (Client) ........................ activeView·persona·anchorTarget 상태 소유
├─ SummaryActions ................................. [요약][초록번역][전문번역] → 훅 트리거
├─ PersonaToggle .................................. 요약 전용(P2 캐시히트)
├─ useSummarize(req) → { screenState, outcome, stream } ... 스트림 소비 + union reducer (P1·P5)
│     └─ SummaryView + AnchorChip / TranslationView
├─ useFullText(req) → { screenState, fullText } ... 전문 반환(provisional, P6) + 가상화 (P4)
│     └─ FullTextViewer (윈도잉 + 앵커 하이라이트)
└─ StateView ...................................... 비-해피 공유(degraded·sourceUnavailable·licenseUnavailable 확장)

[검색/라이브러리 표면 — 기존]
ResultCard ........................................ 카드=상세 진입(제목 링크)·우상단 저장 — 카드 요약/tldr 피크 폐지(2026-06-22 UX 패스)

[공유 레이어 — 트리 밖]
ApiClient ......................................... summarize() / getFullText()
├─ classifySummarizeResponse(body.status) ......... union 분류 (P5)
└─ transport ...................................... routeHandlerTransport(BFF, 실 경로) — real-first, mock 없음 (P6)
```

## 2. 핵심 논리 컴포넌트

| 논리 컴포넌트 | 종류 | 책임 | 패턴 |
|---|---|---|---|
| Route `/paper/[id]` 셸 | Server | SSR 헤더·메타 | P3 |
| PaperDetailIsland | Client | 상태 소유·아일랜드 조율 | P3·P5 |
| `useSummarize` | Hook | 스트림 소비·screenState reducer·abort | P1·P5 |
| `useFullText` | Hook | 전문 반환(provisional)·가상화 데이터 | P4·P6 |
| SummaryView/AnchorChip | Client | 6필드 + 앵커→뷰어 | P4 |
| TranslationView | Client | 초록·전문 한국어 + keptTerms | P2 |
| FullTextViewer | Client | 윈도잉 전문 + 하이라이트 | P4 |
| StateView(확장) | Client | 비-해피 공유 | P5 |
| ApiClient.summarize/getFullText | Shared | 단일 진입·시임 | P6 |
| classifySummarizeResponse | Shared | status union 분류 | P5 |

## 3. FD 컴포넌트 ↔ 논리 컴포넌트 매핑

- FD `PaperDetailScreen` → Route 셸 + `PaperDetailIsland`(SSR/CSR 분리, P3).
- FD `SummaryView`/`TranslationView`/`FullTextViewer` → 동일(클라이언트), 데이터는 `useSummarize`/`useFullText` 훅이 공급.
- FD `ApiClient 확장` → Shared `summarize`/`getFullText` + `classifySummarizeResponse`.
- FD `StateView 확장` → 동일(union 추가 kind).

## 4. 데이터플레인 / 경계

- **온디맨드 데이터플레인**: 사용자 액션 → 훅 → ApiClient → BFF transport → U6 게이트웨이 → U7 백엔드. 스트리밍은 BFF 경유 pass-through.
- **비차단 경계**: 클라이언트 텔레메트리(상태 전이)는 렌더를 막지 않음(NFR-FO1).
- **provisional 경계**: `getFullText`/`scope`는 실 transport(BFF) 기준 real-first — 신규 기능은 **백엔드 §6 통합 의존**(mock 우회 없음). 백엔드 계약 확정 시 provisional 타입만 재정합(컴포넌트 불변).

## 5. 추적성

NFR-FP→P1~P4·셸/훅 · NFR-FR→P5·reducer/StateView · NFR-FSEC→P7 · NFR-FM→ApiClient/classifier/generated-types · US-S1~S5 전반.
