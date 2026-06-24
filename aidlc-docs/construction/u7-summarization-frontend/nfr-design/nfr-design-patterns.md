# U7 Summarization Frontend — NFR Design Patterns

**단계**: CONSTRUCTION → NFR Design · **유닛**: U7 Summarization Frontend · **일자**: 2026-06-19
**근거**: NFR Requirements(전부 A·ADR-1~5) · FD(BR-SF·VM) · 프론트 자산(ApiClient·classify·StateView·transport seam).
**고도**: 패턴·정책. 수치(ms·윈도우 크기·번들)·구체 라이브러리는 Code-gen/Build & Test.

---

## P1 — 스트리밍 소비 (ADR-1 점진 렌더)

- **패턴**: `ApiClient.summarize()`가 fetch `ReadableStream` 리더를 노출 → `useSummarize` 훅이 청크를 받는 대로 뷰 state에 누적 append → 컴포넌트 점진 렌더.
- **종단 처리**: 스트림 종료 시 최종 바디를 `classifySummarizeResponse(body.status)`로 분류 → `screenState` 확정(page/abstain/degraded/sourceUnavailable/...). 스트리밍 텍스트는 *근거화 통과분*(BR-S8)이라 표시 측 추가 검증 없음(BR-SF-10).
- **생명주기**: 언마운트·라우트 이탈·재탭 시 `AbortController`로 스트림 취소(누수·중복 방지, BR-SF-4).
- **캐시 fast-path**: `cached:true`면 스트림 없이 즉시 렌더(스피너 생략, NFR-FP1).

## P2 — 체감 성능 (NFR-FP1)

- **패턴**: 요청 시작 → 스켈레톤(첫 토큰 전) → 점진 텍스트(첫 토큰 후). 캐시 HIT = 스켈레톤 생략 즉시.
- **persona 전환**: 토글 → 재요청, 캐시 HIT면 즉시(재생성 0, BR-SF-6).
- **목표 형태**: "캐시 HIT 즉시 / 첫 토큰 가시화까지 짧은 지연" — 구체 ms·플러시 주기는 Build & Test.

## P3 — SSR 셸 + CSR 아일랜드 (ADR-2)

- **패턴**: `/paper/[id]` = **서버 컴포넌트 셸**(`PaperHeader`: 제목·저자·초록·arXiv 링크) + **클라이언트 아일랜드**(`SummaryActions`·`PersonaToggle`·결과 뷰·`FullTextViewer`).
- **경계**: 액션/스트리밍/상태는 클라이언트 경계 안에서만(온디맨드). 셸은 라우트 데이터로 즉시 SSR.

## P4 — 대용량 가상화 (ADR-3)

- **패턴**: 전문 번역·전문뷰어는 **윈도잉(가상 스크롤)** — 보이는 영역만 DOM. 앵커 클릭 → 대상 오프셋으로 스크롤 + 하이라이트(`scrollIntoView` + 포커스).
- **정책**: 소형(요약 6필드·초록번역)은 일반 렌더, 임계 이상(전문) 가상화. 임계·윈도우 크기는 Code-gen.

## P5 — 복원력 (NFR-FR)

- **union reducer**: `classifySummarizeResponse` → `SummarizeOutcome` → `screenState` 전수 매핑(누락 0, BR-SF-14). 컴파일 타임 exhaustiveness(타입 union switch).
- **무한로딩 금지**: 요청에 상한 타임아웃 → 초과 시 `error`(재시도 제공). 스트림 무응답도 동일.
- **재시도 정책**: `error`/`degraded` = `onRetry`. `abstain`/`sourceUnavailable`/`licenseUnavailable` = 정상 동작, 자동 재시도 없이 고유 메시지(BR-SF-15).
- **fail-closed**: 알 수 없는 응답·파싱 실패 → `invalid`/`error`(스택·내부식별자 비노출, NFR-FR4).

## P6 — 전송 (ADR-4, real-first)

- **패턴**: `routeHandlerTransport`(BFF) = **실 경로**(U6 게이트웨이 경유·토큰 서버측). **real-first — 프로덕션 mock 대역 없음**(백엔드 U7 정합). 단위 테스트는 test-only stub Transport 허용.
- **provisional**: `getFullText`/`scope`는 실 transport 기준 — 신규 기능은 **백엔드 §6 통합 의존**(mock 우회 없음). 백엔드 계약 확정 시 provisional 타입만 정합(드리프트는 generated-types 흡수).

## P7 — 보안 (NFR-FSEC, 대부분 계승)

- React 기본 이스케이프(외부 텍스트 전부)·`dangerouslySetInnerHTML` 금지 lint 가드.
- 토큰 서버측(BFF)·클라이언트 비노출. 응답 민감값(토큰·비용·캐시키·모델ID) 표시 안 함.
- 안전 링크(http/https + noopener). 날조 0 — 표시 무가공.

## P8 — 테스트 패턴 (도구 형태; 수치는 Build & Test)

- **단위(vitest)**: classifier union 전수성(모든 status), XSS 라운드트립, persona 멱등, 식별자 매핑 결정성, 스트림 중단/완료 일관.
- **PBT 형태**: union→screenState 전사상(fast-check 등 생성기 — 도구는 Build & Test), 외부 텍스트 이스케이프 무해성.
- **E2E(playwright)**: 카드 제목→상세 이동(카드 [요약]/tldr 피크는 폐지 — 2026-06-22 UX 패스), 상세 액션 3종, persona 토글 캐시히트, 앵커→전문뷰어 하이라이트, 비-해피 상태 렌더.

---

## 추적성 (패턴 ↔ NFR/BR)

| 패턴 | NFR | BR-SF |
|---|---|---|
| P1 스트리밍 | NFR-FP1 | BR-SF-4·10 |
| P2 체감 | NFR-FP1 | BR-SF-5·6 |
| P3 SSR/CSR | NFR-FP2 | — |
| P4 가상화 | NFR-FP3 | BR-SF-8 |
| P5 복원력 | NFR-FR1~4 | BR-SF-7·14·15 |
| P6 seam | NFR-FM2 | BR-SF-2 |
| P7 보안 | NFR-FSEC1~4 | BR-SF-9·10·13·16 |
| P8 테스트 | NFR §7 | 전반 |
