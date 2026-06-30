# U7 Summarization — 비즈니스 규칙 (Business Rules)

**단계**: CONSTRUCTION → Functional Design · **유닛**: U7 Summarization · **일자**: 2026-06-18
**원칙**: 결정 규칙·검증·제약(기술 무관). 수치 임계·구체 기술은 NFR/Infra.
**근거**: 계획서 §4 답변(Q1~Q17) · 설계 입력 §4·§7·§9·§11·§12 · `domain-entities.md`·`business-logic-model.md`.

---

## 1. 결정 규칙 (Business Rules, BR-S*)

### BR-S1 — 캐시 키 immutable·무효화 (§11 / Q7)
- 신원 = `(paperId, version, task, targetLang, persona, glossaryVer, [ownerId], modelVer, promptVer)`. 같은 키 = 같은 산출물.
- `glossaryVer`는 **사용자별 카운터**로, 본인 용어 편집 시 본인 캐시를 무효화한다(편집 → `glossaryVer++` → 키(경로) 변경 → 신규 객체, 수동 flush 없음). 단 카운터는 내용 식별자가 아니므로 — 서로 다른 사용자가 각자 다른 용어로 같은 정수(예 ver=1)에 도달할 수 있어 — **개인화 산출물(`glossaryVer > 0`)은 `ownerId`로도 갈라** 사용자 간 충돌(타인의 개인화 번역 수신)을 막는다. 베이스라인(`glossaryVer == 0`, 개인 용어 없음)은 owner 무관·공유.

### BR-S2 — 소스 선택·초록 폴백 (§5 / Q1=A)
- `summary` → 전문(**doc-model read**; `.txt`→doc-model 입력 교체, D2 — 선택 로직 불변), `translate` → 초록(기본) 또는 **전문(scope=full, 프론트 노출 기능)**.
- 전문 부재/OA 라이선스 미허용 → **초록 폴백 + "전문 부재" 메타 표기**(NFR-R2). 전문·초록 모두 부재 → `SourceUnavailableDTO`.
- **(Q18/P2) 번역 입력 정렬**: 요약·번역 **모두 정제본(`refined.body`)을 LLM에 전달**(대칭). 번역도 BR-S3 정제·SANITIZE 적용(노이즈/인젝션 무해화), 길이 분기(BR-S6)는 `refined.token_count` 기준과 **전송 입력이 일치**. `translate` 프롬프트는 scope별 분기(초록=`<abstract>`·"초록 번역", 전문=`<paper>`·"본문 번역"). 초록 번역은 `refine(abstract)≈abstract`라 무영향.
- **(PR-2) 번역 출력 구조화**: `translate`(scope=full)의 출력은 **본문과 동일한 구조화 형식**(번역본 doc-model — BR-S18). 입력 정렬은 위와 동일(refined 기준 길이 분기)이되, 생성은 doc-model 구조를 미러해 단위 번역한다. doc-model 부재(레거시/scope=abstract)는 단일-문단 doc-model로 감싸 출력 계약을 통일.

### BR-S3 — 입력 정제 경계 (§4 / Q2=B · Q6=A)
- **(D2 입력 업그레이드)** 입력 = doc-model(구조화). 섹션·캡션·수식·**표(=데이터)**는 doc-model에서 직접 취득(신뢰); 헤딩-정규식 도출은 doc-model 부재 시 폴백. 정제 경계·SANITIZE 로직은 불변.
- **제거**: 참고문헌/인용목록 · Header/Footer · 페이지번호 · 저작권 문구 · 저자 정보(소속).
- **보존(제거 금지)**: **표=구조화 데이터(rows/cols)** · 표/그림 캡션 · Appendix · Supplementary Results 등 **실험 정보 가능 콘텐츠** · 수식(LaTeX, 번역 금지).
- **섹션 도출(폴백)**: doc-model 부재 시 헤딩 패턴 인식 → `Section{label, span}`; 실패 시 span-only. (구체 패턴 목록은 코드/NFR.)
- SANITIZE: 제어문자 제거 · 본문 격리(injection 대비) · 토큰 캡(수치=NFR).

### BR-S4 — 용어집 적용 (§9.1 / Q8=A)
- **핵심 용어 보존은 프롬프트 단계에서 강제**(keep-as-is·핵심 매핑 → 프롬프트 주입, 생성 시 일관·문맥 처리).
- **후치환은 사용자 선호 용어에 한정하여 단순 명사를 교정**(캐시 번역에 결정적 후치환, 조사 안전한 단순 명사만, LLM 재호출 0).
- 사용자 용어 수정 → 개인 용어집 upsert → `glossaryVer++` → 해당 사용자 키 갱신.

### BR-S5 — 모델 선택 정책 (§2 / Q14=A)
- task가 모델 역량 등급을 **자동 결정**(요약=고역량·번역=경량), 사용자 모델 선택기 **비노출**. **구체 모델 식별자·비용 바인딩은 NFR/Infra.**

### BR-S6 — 길이 분기 (§5 / Q3=A) — **3단계(구현됨, #135)**
- **3경로**: `≤컨텍스트예산`(~40K) → 단일 콜 / `컨텍스트예산~입력상한`(~40K–120K) → **map-reduce** / `>입력상한`(~120K, OVER_CAP) → **거절(`input_too_long`)**.
- **map-reduce**(구현 = `MapReduceSummarizer`): doc-model **섹션 경계 청킹**(+문자 오버랩, 초과 섹션은 윈도우 분할) → 부분요약(map) → 통합(reduce). 통합 출력도 §3 동일 스키마. 근거화는 **전체 `RefinedSource`** 기준 검증(앵커 문서 전역 해소).
- **제약(Map-Reduce Grounding Contract)**: reduce 단계 프롬프트는 최종 출력의 모든 앵커가 자신이 취합하는 "부분 요약(map output) 내부의 주장" 및 "해당 청크의 원문"에서 비롯된 것인지 검증하도록 지시받아야 한다. 합성된 주장이 부분 요약의 컨텍스트를 벗어나 앵커 범위를 이탈하지 않도록 엄격히 통제한다.
- **OVER_CAP은 부분요약(degraded)하지 않고 거절** — 모바일 결정(극단 입력은 솔직히 거절). **번역도 동일 밴드**: MAP_REDUCE 밴드 `translate`는 abstain이 아니라 **섹션별 map-only 번역→이어붙이기**(reduce 없음 — BR-S18); OVER_CAP은 번역도 거절.
- 게이트 `DOCSURI_MAP_REDUCE_ENABLED` OFF 시 MAP_REDUCE 밴드도 abstain(기존 동작 보존). 임계·청크 크기 = NFR. 동기/비동기는 BR-S12.

### BR-S7 — 근거화 게이트 (§7 / Q4=A · Q15=A)
- **U7 고유 결정적 게이트**(검색용 U6 `enforce`와 형상 다름 — 단일 논문 충실도 검증). **결정적 체크만**(앵커 실재성·수치 일치·스키마 완전·잘림/빈출력), **LLM-judge 미사용**.
- 1차 통과 → 저장·노출. 1차 실패 → **1회 재시도 → 그래도 실패 시 기권(fail-closed)**. 정당한 코퍼스밖 abstain = 재시도 없음.
- "단일 근거화 권위 = U6"는 **검색 근거화 한정** 해석; U7 문서-충실도는 별개 종류(설계 입력 §1·§7과 정합, QT-5 FD 검증 결론). 이 경계는 **`shared/ports` §2.1 `GroundingValidatorRegistry`로 제도화** — U7 validator는 `domain=summary`·`authority=advisory`로 등재되고, `authority=enforcement`는 `search` 단독(레지스트리 가드가 위반 시 거부). 등재 자체는 가산적이며 검증 호출 경로(오케스트레이터 seam)·`enforce` FROZEN 시그니처를 바꾸지 않는다.
- **체크 강도 — HARD vs SOFT(개정)**: 빈/잘림·스키마 미완은 **HARD**(전체 기권). 앵커 실재성은 **SOFT** — 검증 못 한 앵커는 **드롭(요약 본문은 유지)**하고 전체 기권하지 않는다(표 재구성·패러프레이즈·수식의 verbatim 미스매치로 멀쩡한 요약을 통째로 버리는 false-positive 방지). **수식 span(LaTeX/유니코드 수학)은 실재성 검사 면제**. 수치 일치는 HARD지만 **비율 기반** — 원문에 없는 수치 비율이 임계(기본 50%)를 넘을 때만 기권(소수 오차 허용, 다수 날조는 차단 — 반환각 유지). fail-closed가 앵커 단위로 적용됨. **matcher 정밀화**: 동등 수치는 정규화로 매칭 — 퍼센트↔분수(95.3%↔0.953)·천단위 구분(1,200↔1200)·**반올림 톨러런스**(표기 정밀도 기준 half-a-ULP 밴드, 95.3↔95.34)로 false-abstain을 줄이되, 밴드는 좁아(반올림 한정) 날조 통과는 막는다. **수치 임계값(0.5) 자체의 재보정은 별개**(held-out 코퍼스 선행 — 데이터 게이트).
- **출력 토큰 상한**: 요약 LLM 호출은 충분한 `max_tokens`(8192)로 — 한국어 구조화 JSON이 작은 상한에서 잘리면 파싱 실패→기권이 되므로 잘림을 막는다.

### BR-S8 — 스트리밍 ↔ 근거화 (Q12=A)
- **버퍼-검증-스트리밍**: 근거화 통과 전까지 사용자 노출 보류 → 근거 없는 토큰 유출 금지(FR-5 최우선). 통과분부터 점진 렌더.

### BR-S9 — 종단 상태 union (FR-11 / Q5=A)
- `SummaryResultDTO`(통과·완전) · **`PendingDTO`(긴 요약·긴 번역 비동기 잡 진행 중·`retryAfterMs` — BR-S12)** · `AbstainDTO`(근거화 실패/코퍼스밖) · `CostDegradedDTO`(비용 OPEN/저하) · `SourceUnavailableDTO`(소스 부재).
- **빈 성공 금지**. 비용저하·소스부재와 무관하게 근거화 실패면 **기권 우선**. `PendingDTO`는 비종단(클라이언트 폴링 → 캐시 히트로 종단 결과 수신).

### BR-S10 — persona 생성 (§9.2 / Q9=A)
- **생성 변형 = persona(expert/beginner)뿐**, 논문당 최대 2벌(캐시 키 포함). U7은 풍부한 출력만 보장한다.
- **뷰 프리셋 폐기(Q9 / 코드 부재)**: 요청에 `view` 필드 없음·뷰 파생 생성 변형 없음. 표시 슬라이싱(전체/tl;dr/섹션별)은 같은 §3 JSON에 대한 **순수 U5 클라이언트 렌더**일 뿐 U7 입력·캐시 식별자가 아니다.
  - expert: 전문용어·약어·수식 유지. beginner: 첫 등장 시 괄호 설명·약어 전개·수식 자연어 해설(이후 원어 유지).

### BR-S11 — 재현성 추출 (§12 / Q16=A)
- **정규식 힌트 + LLM 추출 병행** → `reproducibility{code, data}`. 정규식(github.com·"code available"·"dataset" 등)은 high-precision 링크, LLM은 문맥. 날조 링크는 BR-S7 근거화가 차단.

### BR-S12 — 동기/비동기 (§12 / Q17=A) — **구현됨(#135, slice 5b)**
- 기본 **동기**(단일 콜, 대부분의 논문). 초장문(map-reduce/map-only)만 **비동기 잡**: API가 미스 시 잡을 큐에 enqueue하고 **`PendingDTO`(BR-S9)** 반환 → 클라이언트가 `retryAfterMs` 백오프로 폴링. **워커**가 잡을 소비해 인라인 실행(게이트웨이 타임아웃 회피)하고 결과를 **STORE write-through** → 폴링이 캐시 히트로 결과 수신.
- **(PR-2) 잡 큐·워커는 task-agnostic**: 동일 큐/워커가 `summary`(map-reduce)·`translate`(map-only, BR-S18) 잡을 모두 처리(요청 `task` 포함). 신규 인프라 없음.
- 비동기 잡도 **동일 근거화/기권 규칙**. enqueue는 best-effort(요청 경로 비차단)·인프로세스 dedup, 멱등 backstop = 캐시 히트. 게이트 `DOCSURI_SUMMARY_JOB_QUEUE_URL` 미설정 시 inline 실행(타임아웃 위험, NFR/Infra). **워커는 별도 배포 단위**(Infra §… — slice 6).

### BR-S13 — 비용 게이트 배치 (NFR-C1 / Q13=A)
- LLM 호출 **직전**(캐시 MISS 후) `get_budget_state()`. OPEN/저하 → `CostDegradedDTO` + RES-11a 신호. 캐시 HIT는 게이트 우회(비용 0).

### BR-S14 — 경계·보안 불변
- **C-2 추출 경계**: 검색된 단일 논문 내용만 요약/번역. 사용자 원고/문헌리뷰 산문 생성 금지.
- **SEC-9**: 내부 필드(토큰·비용·캐시키·모델/프롬프트 식별자·raw LLM 메타) 외부 DTO 비노출.
- **SEC-11**: 레이트리밋·남용 방어 = U6 게이트웨이 강제.
- **fail-closed(SEC-15)**: 근거화 미통과·LLM 장애·비용 OPEN → 기권으로 수렴(날조·빈화면·스택 비노출).

### BR-S15 — 자산 읽기·노출 (FR-17, 2026-06-22) (표시 전용)
- `GET /api/papers/{id}/assets`: 인증 필수(SEC-8) · **OA 라이선스 게이트(BR-SF-11 재사용)** — 비-OA → `license_unavailable`. 공유 RDS `paper_asset` **읽기 전용**(U1 단일 writer) → `object_ref` **단기 만료 서명 URL**로만 노출(**SEC-9** — object_ref·내부 메타 비노출). ordinal 정렬. OA·자산 0 = `ok`+빈 배열.
- 요약 LLM·근거화·캐시 경로 **불변**(자산은 별도 읽기 경로).

### BR-S16 — 계약 SSOT 수립 (갭 #1, §8 예고 이행)
- 수기 `summarize.ts`를 **`shared/dtos/summarization.schema.json` SSOT**로 승격(요약/번역/full-text + 신규 `AssetRef`/`PaperAssetsResponse`). 프론트 타입은 스키마 **생성**(드리프트 0). SEC-9 비노출 불변.

### BR-S17 — 상태 매핑 정합 (갭 #2/#3)
- 응답 union에 `unauthorized`(401) 명시, `validation_error`는 `message` 포함. 프론트 분류기가 **상태로 판정**(검증오류→입력 확인 경로, 인증오류→인증 경로) — 일반 'error' 뭉개기 제거.

### BR-S18 — 구조화 번역 출력 + 긴 번역 map-only (PR-2, 2026-06-24)
- **출력 계약**: `TranslationDraft`는 평문 한 덩어리(`koreanText`)에서 **번역본 doc-model**(`docModel: DocModel` + `keptTerms`)로 개정. 본문 번역 = **본문과 동일한 구조화 형식**(섹션 트리·블록 미러). 스키마는 `summarization.schema.json`이 `docmodel.schema.json#/$defs/DocModel`을 **크로스파일 `$ref`**(복제·드리프트 회피). 프론트는 **원본 본문과 동일한 리치 뷰어**로 렌더.
- **번역 단위·보존**: 번역 대상 = 섹션 제목·문단 텍스트·리스트 항목·표/그림 **캡션**. **verbatim 보존(번역 금지)** = **표 셀(숫자·데이터, D8)** · **수식 LaTeX** · **코드 블록** · 블록/섹션 **id**(원본 미러) · 그림 `assetRef`. 인라인 수식(`\( … \)`)은 보존. → 번역본 doc-model은 원본과 동일 구조로 같은 뷰어가 렌더(그림 자산은 동일 `assetId`로 조인).
- **재조립 안정성**: LLM은 **id→번역텍스트**로 받아(구조 누락/재정렬 방지) 백엔드가 소스 doc-model 구조에 주입해 번역본 doc-model을 **결정적으로 재조립**(누락 id는 원문 보존). 출력이 **자기완결**(번역본이 자체 doc-model 보유·렌더 시 별도 doc-model fetch 없음)이라 파서 재빌드로 id가 바뀌어도 캐시된 번역본은 내부 일관성 유지 → 번역 캐시 키에 parserVersion 불요(요약과 동일).
- **긴 번역 map-only**: MAP_REDUCE 밴드 `translate`는 doc-model **섹션 경계로 분할 → 섹션별 번역(map) → 이어붙이기**(reduce 없음 — 요약과 다름; 번역은 통합 불필요). 청킹은 `MapReduceSummarizer` 패턴 재사용. OVER_CAP은 거절(`input_too_long`) 유지. 동기/비동기는 BR-S12(요약 잡 큐·워커 재사용, `task=translate`).
- **근거화 없음**: 번역은 grounding-free(BR-S7 미적용) — 앵커/수치검증 대상 아님. 빈 번역은 1회 재시도 후 `empty_translation` 기권.

## 2. 속성 기반 테스트 속성 (QT-4 / PBT 범위)

| ID | 속성 | 근거 |
|---|---|---|
| **PBT-S1** | 캐시 키 결정성/멱등 — 동일 입력 → 동일 `SummaryCacheKey` → 동일 산출물(immutable 라운드트립) | BR-S1 |
| **PBT-S2** | 정제 멱등 — 재정제 불변(`refine(refine(x))==refine(x)`); 보존 콘텐츠(캡션·Appendix·수식) 불변 | BR-S3 |
| **PBT-S3** | 후치환 멱등 — keep-as-is 용어 불변, 단순 명사 후치환 재적용 불변 | BR-S4 |
| **PBT-S4** | `SummaryResponse` DTO 라운드트립 — 4 종단 상태 직렬화/역직렬화 보존 · 내부 필드 비노출 유지 | BR-S9·SEC-9 |
| **PBT-S5** | 앵커 검증 건전성 — 앵커가 가리킨 섹션/span이 `RefinedSource`에 실재할 때만 통과(없으면 기권) | BR-S7 |
| **PBT-S6** | 자산 응답 라운드트립·비노출 — `PaperAssetsResponse` 직렬화 보존; `AssetRef`에 `object_ref`·내부 메타 비노출(서명 URL만) | BR-S15·SEC-9 |

> 차단성/권고 분류·Hypothesis 전략은 NFR Requirements(전역 PBT 정책 계승).

---

## 3. 추적성 매트릭스 (미커버 0 검증)

| 컴포넌트/규칙 | 요구사항 | 스토리 |
|---|---|---|
| SourceSelector·LlmSummarizer·§3 출력 (BR-S2/S5/S6) | FR-12, C-2 | US-S1 |
| LlmTranslator·GlossaryResolver (BR-S4) | FR-13, C-2 | US-S2 |
| GroundingValidator·Anchor (BR-S7/S8) | FR-5, QT-5, FR-11 | US-S3 |
| persona/뷰·용어 선호 (BR-S10/S4) | FR-14, SEC-8 | US-S4 |
| SummaryCacheStore·스트리밍 (BR-S1/S8/S12) | NFR-P2 | US-S5 |
| CostGate·텔레메트리·근거화 운영 (BR-S13/S7) | NFR-C1, RES-11a/b, QT-5, SEC-11 | US-S6(기여) |
| InputRefiner 보존 정책 (BR-S3) | FR-12, QT-5 | US-S1, US-S3 |
| 재현성 추출 (BR-S11) | FR-12 | US-S1 |
| 종단 union·fail-closed (BR-S9/S14) | FR-11, SEC-15 | US-S3, US-S5 |

**불변식 재인용**: INV-1(C-2 추출 경계) · INV-2(비용/관측 U6 단일 권위) · INV-3(SEC-9 비노출) · INV-4(fail-closed) · INV-5(캐시 키 immutable) — 계획서 §5.

**커버리지**: FR-12·13·14 · FR-5 · FR-11 · NFR-P2 · NFR-C1 · QT-5 · C-2 · SEC-8/9/11/15 · RES-9 · NFR-R2 · US-S1~S6 전수 매핑(미커버 0).
