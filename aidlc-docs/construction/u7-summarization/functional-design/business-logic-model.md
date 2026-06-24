# U7 Summarization — 비즈니스 로직 모델 (Business Logic Model)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U7 Summarization · **일자**: 2026-06-18
**원칙**: 기술 무관 — 알고리즘·흐름·정책 **형태(shape)** 만. 수치(TTFB·토큰 캡·타임아웃·재시도 횟수)와 구체 기술(Bedrock·S3·Redis)은 NFR/Infra.
**근거**: 설계 입력 §6(상세 파이프라인) · 계획서 §2·§4 답변 · `domain-entities.md` · `business-rules.md`.

---

## 1. 서비스 · 컴포넌트

- **서비스**: `SummarizationOrchestrationService` — 온디맨드 동기(스트리밍) 파이프라인 조정 + `publishSummarizationTelemetry`(비차단).
- **컴포넌트(9)**: `SummarizationController`(진입) · `SummaryCacheStore` · `CostGate` · `SourceSelector` · `InputRefiner` · `GlossaryResolver` · `LengthRouter` · `LlmSummarizer`/`LlmTranslator`(LLM 게이트웨이 어댑터 경유) · `GroundingValidator` · `ResultAssembler`.
- **실 어댑터 단일본(real-first)**: `LlmGatewayAdapter`·`FullTextSourceAdapter`·`SummaryStoreAdapter` — 포트 유지, 첫 구현부터 실(Bedrock·S3·Redis), mock 대역 없음(Q10/Q11).

---

## 2. 온디맨드 파이프라인 (설계 입력 §6 환원)

```
[U6 GATEWAY] authn · authz(SEC-8) · rate-limit(SEC-11)         ← 비용 발생 = 남용 방어
      ▼
0. cacheLookup        SummaryCacheStore: read-through(핫→영구)
      ├─ HIT ─▶ 즉시 반환 (LLM 0콜)                              ← US-S5 즉시·비용 0
      ▼ MISS
1. costGate           CostGate: get_budget_state()  (U6 단일 권위)
      ├─ OPEN/저하 ─▶ CostDegradedDTO 기권 (FR-11) + RES-11a 신호
      ▼ NORMAL
2. selectSource       SourceSelector: summary→전문(doc-model) / translate→초록 또는 전문(scope)
      └─ 전문/초록 부재 ─▶ 초록 폴백(메타 표기) 또는 SourceUnavailableDTO (Q1)
      ▼
3. refine             InputRefiner: 노이즈 제거(한정) · 캡션/Appendix/수식 보존 · 섹션 도출(Q2/Q6) · SANITIZE
      ▼
4. loadGlossary       GlossaryResolver: P1 시드∪P2 개인 (translate 우선) (Q8)
      ▼
5. routeLength        LengthRouter: tokenCount>예산 → 긴 입력(요약 map-reduce/번역 map-only) / else 단일 콜 (Q3)
      ▼
6. generate(stream)   LlmSummarizer(Sonnet)/StructuredTranslator(Haiku): 영역분리·grounding지시(요약)·persona·용어집·§3 JSON / 번역=id별 세그먼트→번역본 doc-model
      ▼
7. groundingValidate  GroundingValidator: 결정적 앵커/수치/스키마 (Q4·Q15) — 실패 시 1회 재시도→기권
      ▼
8. assemble+write     ResultAssembler → SummaryStoreAdapter write-through(영구+핫) → emitTelemetry(비차단)
      ▼ 스트리밍
[ 클라이언트: 점진 렌더 + "출처 보기"(앵커) + 뷰 프리셋(재생성 0) ]
```

---

## 3. 컴포넌트별 알고리즘 (수준: 알고리즘·정책)

### 3.1 `SummaryCacheStore` (read-through / write-through, §11)
- **read**: 핫(Redis) → 미스 → 영구(S3) → 미스 → 생성. 키 = `SummaryCacheKey`(immutable).
- **write**: 생성 성공 시 영구 + 핫 write-through. 키 변경(modelVer/promptVer/glossaryVer/version) = 신규 객체(자동 무효화).
- 캐시 HIT는 비용 게이트 우회(LLM 0콜 = 비용 0, Q13).

### 3.2 `CostGate` (Q13)
- LLM 호출 **직전**(캐시 MISS 후·생성 전) `get_budget_state()`. `OPEN/LEXICAL_ONLY/저하` → `CostDegradedDTO`. **U7은 비용 판정 재구현 없음**(U6 단일 권위, INV-2).

### 3.3 `SourceSelector` (Q1)
- `summary` → `FullTextSourceAdapter`로 **doc-model read**(전문; cache miss 시 U1 doc-model lazy 생성 트리거 — BR-30/U1 §7). `translate` → 초록(보유). 전문 부재/라이선스X → 초록 폴백 + `fallbackReason`(NFR-R2), 둘 다 부재 → `SourceUnavailableDTO`.
- **(D2)** 입력 소스만 `.txt`→doc-model 교체 — 선택·폴백·DTO 로직 불변.

### 3.4 `InputRefiner` (Q2=B / Q6=A)
- **(D2 입력 업그레이드)** 입력 = doc-model(구조화). 섹션·캡션·수식·**표(=데이터)**를 doc-model에서 직접 취득(신뢰) — 아래 헤딩-정규식 도출은 doc-model 부재(레거시 `.txt`) 시 폴백.
- **제거**: 참고문헌/인용목록 · Header/Footer · 페이지번호 · 저작권 · 저자정보. **보존**: 표(=데이터 rows/cols) · 표/그림 캡션 · Appendix · Supplementary Results · 수식(LaTeX, 번역 금지).
- **섹션 도출(폴백)**: doc-model 부재 시 헤딩 패턴(예: `INTRODUCTION`, `5.2`, `Table 3`, `Figure 2`) 인식 → `Section{label, span}`. 실패 시 span-only.
- SANITIZE: 제어문자 제거 · 본문 격리(injection 대비) · 토큰 카운트.

### 3.5 `GlossaryResolver` (Q8)
- `seedTerms`∪`keepAsIs`(공유) ∪ `userOverrides`(개인, `glossaryVer`). 
- **2경로**: 핵심 용어 보존·매핑 → 프롬프트 강제 주입; 사용자 선호 단순 명사 → 생성 후 결정적 후치환(조사 안전 단순 명사 한정).

### 3.6 `LengthRouter` (Q3) — **3단계 구현됨(#135)**
- `≤컨텍스트예산` → 단일 콜 / `컨텍스트예산~입력상한` → 긴 입력 경로(요약=**map-reduce** `MapReduceSummarizer`: 섹션 인지 청킹+오버랩 → 부분요약(map) → 통합(reduce); 번역=**map-only** `StructuredTranslator`: 섹션 경계 청킹 → 섹션별 번역(map) → 소스 구조에 재주입, **reduce 없음** — BR-S18) / `>입력상한`(OVER_CAP) → **거절**(`input_too_long`, 부분 처리 안 함 — BR-S6, 두 task 공통).
- **동기/비동기(BR-S12)**: 단일 콜=동기. 긴 입력=비동기 잡(API enqueue→`PendingDTO`→폴링→워커 inline 생성→write-through). **잡 큐·워커는 task-agnostic**(요약 map-reduce·번역 map-only 동일 큐/워커, `task` 포함). 게이트 OFF(map-reduce 미배선)면 MAP_REDUCE 밴드는 두 task 모두 abstain(기존 보존). **임계·청크 크기는 NFR.**

### 3.7 `LlmSummarizer` / `StructuredTranslator` (생성, §6 stage 6)
- 모델 자동 선택(task→역량 등급; 요약=고역량/번역=경량, 선택기 비노출 — Q14). **구체 모델(Sonnet/Haiku)·Bedrock 바인딩은 NFR/Infra.**
- **요약 프롬프트**: 영역 분리(`[지시] ┃ [데이터]<paper>…</paper>`, injection 방어) · **(D8) 표는 구조화 데이터로 직렬화(`<table>` rows/cols + 캡션·앵커)·수식은 LaTeX로 주입 → 표 숫자·수식이 요약·근거화에 가시** · grounding 지시(제공 텍스트 내에서만·항목별 근거 위치·근거 없으면 기권) · persona 분기(expert/beginner) · 용어집 강제 · 초록 밖 디테일(결과·한계·재현성) · 출력 §3 JSON 계약.
- **번역(BR-S18)**: `StructuredTranslator`가 소스 doc-model의 번역 유닛을 `[{id,text}]`로 추출 → 게이트웨이 `translate_segments`(영역 분리 `<segments>` JSON 데이터·injection 방어; 수식·숫자·코드·id 보존 지시·용어집 강제) → `id→번역텍스트` 수신 → 소스 구조에 재주입해 **번역본 doc-model** 재조립. 누락 id는 원문 보존(결정적). 번역은 grounding-free(3.8 미적용); 빈 번역=1회 재시도 후 `empty_translation` 기권. 후치환 용어집은 번역본 doc-model의 모든 텍스트 필드에 적용(BR-S4).
- 스트리밍 생성(§4). 복원력 정책(§5).

### 3.8 `GroundingValidator` (Q4=A / Q15=A)
- **결정적 체크만**(LLM-judge 미사용): ① 앵커 실재성(섹션/표/span이 `RefinedSource`에 실재?) ② 수치 일치(정규화 비교 95.3%↔0.953) ③ 스키마 완전성 ④ 잘림/빈출력.
- 판정 → `AnchorVerdict`. **1차 실패 → 1회 재시도 → 그래도 실패 시 기권(fail-closed)**. 정당한 코퍼스밖 abstain은 재시도 없음.

### 3.9 `ResultAssembler`
- 통과 → `SummaryResultDTO`(draft/translation + anchors + meta). 후치환 용어집 적용(3.5 경로2). write-through + telemetry.

---

## 4. 스트리밍 ↔ 근거화 상호작용 (Q12=A — 버퍼-검증-스트리밍)

```
생성(스트리밍 수신) ──▶ [버퍼] ──▶ groundingValidate ──┬─ pass ─▶ 점진 렌더(통과분부터)
                                                       └─ fail ─▶ AbstainDTO ("근거 부족")
```
- **근거화 통과 전까지 사용자 노출 보류** — 근거 없는 토큰 유출 금지(FR-5 최우선). TTFB는 캐시 HIT(주 경로)로 관리, 첫 생성만 검증 지연 감수. 구체 버퍼 전략·TTFB 수치는 NFR.

---

## 5. 복원력 정책 (형태만 — RES-9 / NFR-R2)

- LLM 호출: **명시적 타임아웃 · 재시도(백오프) · 서킷브레이커** → 장애 시 정의된 저하 모드 = **기권**(FR-11). 수치는 NFR.
- 의존성 격리: LLM 게이트웨이 장애가 캐시 HIT 경로(LLM 0콜)를 막지 않음.

---

## 6. 이벤트 경로 (비차단)

- 성공/기권 후 `토큰·비용·지연·persona·task` → `ObservabilityHub.emit*`(NFR-C1 U7 비용 라인·RES-11 신호). **응답 경로 밖**(fire-and-forget). 발행 실패는 응답에 영향 없음.

---

## 7. 설계 입력 §2~§12 흡수 맵 (`summarization-translation-pipeline.md` → FD)

| 설계 입력 절 | 흡수 위치 | 답변 |
|---|---|---|
| §2 모델 선택 | 3.7 / business-rules BR-S5 | Q14 (역량 등급 자동·선택기 비노출; 구체 모델=NFR) |
| §3 출력 스키마 | domain `SummaryDraft`·`Anchor` | — |
| §4 입력 정제 | 3.4 / BR-S3 | Q2(범위 한정)·Q6(섹션 도출) |
| §5 액션·저장 | 3.1·3.3 | Q1 |
| §6 파이프라인 | §2 흐름·3.x | — |
| §7 품질 게이트 | 3.8 / BR-S7 | Q4(U7 결정적 게이트)·Q15(LLM-judge 미사용) |
| §9.1 용어집 | 3.5 / BR-S4 | Q8 |
| §9.2 개인화 | BR-S10 | Q9 |
| §11 저장·캐시 | 3.1 / BR-S1 | Q7 |
| §12 동기/비동기 | 3.6·§4 | Q17·Q12·Q3 |
| §8/§12 비용·재현성 | §6·3.9 | Q13·Q16 |

> 본 맵이 설계 입력 문서의 추후 **SUPERSEDED 전환 근거**(HOW가 Construction 산출물로 이관됨).
