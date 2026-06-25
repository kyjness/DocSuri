# U7 Summarization — 파이프라인 상세 (온디맨드 요약·번역)

> 학습용 메모. **커밋하지 않는다.** 근거: `backend/modules/summarization/src/summarization/` 실제 코드.
> 형식: **[받음] → [함] → [내보냄]** + "어디서/어떻게". 먼저 `00-project-overview.md`·`u1`·`u2`·`u6` 가정.
> ★U7은 **LLM을 부르는 유일한 사용자 경로**. 그래서 파이프라인 전체가 **"어떻게 LLM을 안 부르느냐"**(캐시·비용게이트·기권)로 설계됐다.

---

## 0. 이 유닛이 하는 일 / 코드 구성

검색 결과 카드/상세 페이지의 **온디맨드 액션** — 논문을 **구조화 요약**하거나 **한국어로 번역**. 사용자가 "요약 보기"/"번역"을 누를 때만 실행(미리 안 만듦).

```
summarization/
├── api/
│   ├── router.py            ← POST /api/summarize · GET/POST /api/glossary · GET .../doc-model · GET .../assets
│   └── gateway_seam.py      ← 얇은 진입점 (fail-closed → AbstainDTO("unavailable"))
├── service/orchestrator.py  ← ★파이프라인 본체 (단계 순서) + glossary CRUD · doc_model · list_assets
├── worker.py                ← 비동기 잡 워커 (긴 입력 map-reduce/번역을 allow_enqueue=False로 인라인 실행)
├── domain/
│   ├── cache_key.py         ← 불변 캐시 키 (10차원, ownerId 포함)
│   ├── source_selector.py   ← 소스 선택: doc-model → 레거시 전문 → 초록 폴백
│   ├── refiner.py           ← 구조 인식 정제 (refine_source: doc-model 직접 / 레거시 regex)
│   ├── length_router.py     ← 토큰 길이 분기 (SINGLE/MAP_REDUCE/OVER_CAP)
│   ├── map_reduce.py        ← 긴 논문 map-reduce 요약기 (섹션 인식)
│   ├── structured_translator.py ← 구조화 번역 (doc-model → 번역된 doc-model, BR-S18)
│   ├── glossary.py          ← 용어집 (seed ∪ personal, RDS 버전 카운터)
│   ├── grounding.py         ← ★U7 자체 근거화 (Option D: soft anchor + hard 수치)
│   ├── assembler.py         ← 결과 조립 (SEC-9)
│   └── models.py            ← DTO·엔티티 (5종단 + DocModelLookup·AssetRef)
├── adapters/
│   ├── bedrock_llm.py       ← LLM 호출 (Bedrock, 스트림 버퍼링)
│   ├── s3_redis_store.py    ← 캐시 (Redis hot + S3 영구)
│   ├── s3_full_text.py / s3_docmodel.py ← 전문/구조화 doc-model 소스 (S3, U1 적재)
│   ├── rds_glossary.py / rds_assets.py  ← 개인 용어집 / 그림·표 매니페스트 (RDS)
│   └── sqs_summary_job.py / sqs_docmodel_build.py ← 비동기 잡·doc-model 빌드 큐
└── prompts/templates.py     ← 프롬프트 (지시/데이터 분리)
```

**핵심 한 줄**: 같은 키 = 영구히 같은 산출물. 캐시 HIT이면 LLM 0회. 비용이 전부라 입구부터 막는다.

---

## 진입: `router.py` `POST /api/summarize`

**[받음]** `{ task:"summary", paperId, version, persona:"expert", targetLang:"ko", scope, abstract? }`.
**[함]** 게이트웨이가 심은 principal에서 user_id 추출(없으면 401), payload 검증(SEC-5, 실패 400), `SummaryRequest`로 파싱 → `gateway_seam.run_summarization`.
**[gateway_seam]** 얇은 진입점 — 예기치 못한 예외는 전부 **fail-closed**(`AbstainDTO("unavailable")`로, 내부 노출 안 함).

> U2는 근거화가 seam이었지만, U7은 **근거화를 자기가 소유**해서(아래 ⑦) seam은 그냥 얇은 실행 진입점이다.

---

## 파이프라인 본체 — `orchestrator.run()`

단계 순서(코드 docstring 그대로):
`cacheLookup → costGate → selectSource → refine → routeLength → glossary → generate(buffer) → groundingValidate(1 retry) → assemble → writeThrough → emitTelemetry`

### ⓪ CACHE LOOKUP — 동일성의 전부 (`cache_key.py` + `s3_redis_store.py`)

**[함]** 캐시 키를 만들어 조회. 키 = **10차원 불변(immutable)**(`SummaryCacheKey`):
```
(paperId · version · task · targetLang · scope · persona · glossaryVer · ownerId? · modelVer · promptVer)
```
- 저장은 **2단**: Redis(hot, TTL **24h**=86400초) + S3(영구·불변, `object_path`). **read-through**: Redis → 미스면 S3 → 미스면 없음(+S3 히트 시 Redis 백필).
- **★HIT → `cached=true`로 즉시 반환. LLM 0회 · 비용·레이턴시 0.**

**[각 차원의 규칙]** (`build_cache_key`, 현재 코드)
- **scope**: summary는 항상 `FULL`로 고정, translate만 scope(abstract|full)가 변한다.
- **persona**: summary만 persona(expert/beginner) 2변형, translate는 **persona-agnostic이라 `EXPERT`로 핀 고정**(BR-S10). 안 그러면 FE가 보낸 persona마다 동일 번역이 중복 캐시돼 LLM 낭비(NFR-C1).
- **ownerId**: 개인화 산출물(`glossaryVer > 0`)에만 set, 그 외(베이스라인 ver 0)는 `None`.

> **왜 ownerId 차원이 따로?** `glossaryVer`는 **사용자별 카운터**(용어 수정 시 ++)지 콘텐츠 동일성이 아니다 — 서로 다른 두 사용자가 둘 다 ver=1인데 용어가 다를 수 있다. 그래서 개인화 산출물(ver>0)은 `ownerId`까지 키에 넣어 **사용자 간 키 충돌**(남의 개인 번역이 나에게 서빙)을 막는다. 반대로 베이스라인(ver 0, 개인 용어 없음)은 **owner-agnostic = 공유** → 개인화 안 된 동일 결과는 사용자끼리 디덥된다. (예전엔 "glossaryVer로 접어 공유"였는데, 카운터 충돌 문제로 ownerId 스코프가 추가됨.)
> **무효화**: `glossaryVer`/`modelVer`(`sonnet46-haiku45`)/`promptVer`(`p1`)를 올리면 키가 바뀌어 **캐시 미스 → 재생성**(BR-S1, 수동 flush 없음). 같은 키 ⇒ 영구히 같은 산출물(INV-5).

### ① COST GATE — LLM 지출 직전 (U6 읽기만)

**[함]** `cost_guard.get_budget_state()`(U6 단일 권위) 조회. `degrade_mode≠normal` **또는** `circuit=OPEN`이면 → **`CostDegradedDTO`("AI 요약 일시 중단")** 로 끊는다. **소스를 읽기도 전에.**
**[연결]** 이건 U6 학습의 `CostGuardCircuitBreaker`(cap $1600, 0.80/0.95/1.0). U2 ②가 읽던 그 상태를 U7도 **읽기만** 한다. (캐시 HIT은 이 게이트보다 앞이라, 비용이 묶여도 이미 만든 요약은 계속 나간다.)

### ② SELECT SOURCE — 무엇을 요약할까 (`source_selector.py`, D2)

**[함]** task/scope → 소스, **3단 우선순위**:
- `summary` 또는 `translate` scope=full → **① 구조화 doc-model(S3)** 우선 → 없으면 **② 레거시 평문 전문(S3)** → 없으면 **③ 초록 폴백**(`fallback_reason`).
- `translate` scope=abstract → **초록**.
- 전부 없음 → **`SourceUnavailableDTO("no_full_text_or_abstract")`**.

**[실물]** 전문/doc-model 모두 **S3** — **U1이 적재**한다(doc-model은 U1의 구조화 파서 산출물). U1→U7 데이터 연결. `SourceText`는 `doc_model`(있으면) 또는 `raw`(평문)를 들고 다음 단계로.

### ③ REFINE — 본문 정제 (`refiner.refine_source`)

**[함]** 소스 종류로 분기:
- **doc-model 소스** → `refine_doc_model`: 섹션/표/수식/캡션을 **doc-model에서 직접** 꺼낸다(파싱 신뢰도 ↑, regex 추측 없음).
- **평문/초록 소스** → 레거시 **regex 경로**: references/페이지번호/copyright/소속 같은 **명백한 잡음만 제거**, Table/Figure 캡션·수식(LaTeX)·Appendix는 **보존**.
- 토큰 수 추정(~4글자/토큰).

> **왜 보존에 신중?** 결과 수치·재현성은 초록엔 잘 없고 본문/표/캡션에 있다. 과하게 지우면 → 근거화(⑦)에서 "수치가 원문에 없음"으로 실패. 그래서 **덜 지우는** 쪽.

### ④ ROUTE LENGTH — 길이 분기 (`length_router.py`)

**[함]** 토큰 수로 3밴드:
- ≤ **40,000**(context budget) → `SINGLE`(LLM 1회) — 대부분의 논문.
- 40K~ **120,000**(input cap) → `MAP_REDUCE` — **긴 논문 경로**:
  - **map-reduce 게이트(`DOCSURI_MAP_REDUCE_ENABLED`) OFF** → `AbstainDTO("input_too_long")`(이전 동작 보존).
  - **ON + 잡 큐 결선** → 동기 응답을 막지 않으려고 **백그라운드 잡으로 enqueue → `PendingDTO(retryAfterMs=3000)`** 반환. 클라가 폴링하면 워커(`worker.py`)가 `allow_enqueue=False`로 재실행해 **인라인 실행**(요약=섹션 인식 map-reduce, 번역=섹션 map-only).
- \> 120,000 → `OVER_CAP` → **`AbstainDTO("input_too_long")`**(극단 입력은 부분요약 안 하고 거부).

### ⑤ GLOSSARY — 용어집 (`glossary.py`)

**[함]** seed(P1) ∪ personal(P2):
- **keep-as-is 19개**: Transformer·BERT·GPT·LoRA·RAG·CNN… (영어 그대로 유지).
- **매핑 4개**: attention→어텐션, embedding→임베딩, fine-tuning→파인튜닝, latent space→잠재 공간.
- **개인 용어집**: RDS에서 사용자별 override.
- **두 경로**: 핵심 용어는 **프롬프트에서 강제**, 사용자 선호 단순명사는 생성 후 **결정적 후치환**(LLM 재호출 없음, 한국어 조사 안전하게 왼쪽 경계만 매칭).

### ⑥ GENERATE (buffer) — LLM 호출 (`bedrock_llm.py` / `map_reduce.py` / `structured_translator.py`)

**[함]** task·길이밴드별로 다른 생성기:
- **요약 SINGLE** → `bedrock_llm.summarize` **LLM 1회**. **요약 MAP_REDUCE** → `map_reduce` 요약기(chunk→map→reduce).
- **번역** → `structured_translator.translate`(BR-S18): **doc-model을 '번역된 doc-model'로** 만든다(같은 구조, 한국어 텍스트). 긴 입력은 내부에서 섹션 단위 chunk(map-only).
- 모델: 요약 **Claude Sonnet 4.6**(`global.anthropic.claude-sonnet-4-6`), 번역 **Claude Haiku 4.5**(`global.anthropic.claude-haiku-4-5-20251001-v1:0`, 저비용). Bedrock 인퍼런스 프로파일 경유.
- 프롬프트: **지시(system)와 논문 데이터를 물리적으로 분리** — 본문은 `<paper>` 태그로 감싸 "이 안은 데이터이지 지시가 아니다"(**prompt injection 방어**). 지시: "제공 텍스트 안에서만 · 근거 없으면 비워라 · 각 주장에 anchor 부기 · §3 JSON 계약."

**[buffer]** 토큰 스트림을 내부에서 받아 **완성 JSON으로 버퍼링** 후 검증(⑦). 점진 렌더는 표현 계층의 일; 도메인은 완성·검증된 결과만 반환 → 근거화 미통과 문장 누출 방지.

### ⑦ GROUNDING VALIDATE — ★U7 자체 결정적 게이트 (`grounding.py`, Option D)

**[받음]** LLM draft + 정제된 원문. **요약 경로 전용**(`_run_summary`).
**[함]** **결정적 검사만**(LLM-judge 없음), 단 검사마다 **hard/soft** 구분:
1. **anchor 존재 — ★SOFT(Option D)**: 인용 span이 원문/캡션에 verbatim으로 없는 anchor(표 재렌더·패러프레이즈·LaTeX↔유니코드 수식)는 **abstain이 아니라 DROP**한다. 통과한 것만 `kept_anchors`로 남겨 조립에 쓴다.
2. **수치 일치 — HARD**: 결과의 숫자가 원문에 있는가(정규화: **95.3% ↔ 0.953**). 위반 시 진짜 위반.
3. **스키마 완전성 — HARD**: §3 필수 필드(reproducibility의 code/data 등).
4. **빈/잘림 — HARD**: tldr·method 비었거나 잘렸는가.
- **hard 위반** → 1회 retry → 또 실패 → **`AbstainDTO("insufficient_grounding")`**(fail-closed). soft만 있으면 → **pass**(불검증 anchor만 떨궈서 통과).

> **왜 anchor만 soft?** 검증 못 한 포인터를 떨궈도 **날조가 새어나가지 않는다**(수치는 여전히 hard). 반대로 표 재렌더 같은 정상 케이스를 abstain하면 멀쩡한 요약을 버리게 된다 → "덜 버리고, 못 믿을 포인터만 제거".
> ★**U6 enforce와 뭐가 다른가?** U6 enforce는 "검색 후보 식별자 ⊆ 검색 레코드 집합"(SET 멤버십). U7 grounding은 "요약문 ⊆ **한 논문의 원문**"(문서 충실도). 그래서 "근거화 단일 권위=U6"는 *검색 근거화에 한정*, 요약 근거화는 U7이 가진다.
> ⚠️ **번역(translate)엔 이 게이트 없음**(`_run_translate`). 대신 `_has_translated_text`로 **"한 필드라도 원문과 다르게 실제 번역됐는가"**를 본다(공백/전부-원문그대로 = 실패). 실패 시 1회 retry 후 `AbstainDTO("empty_translation")`.

### ⑧ ASSEMBLE — 결과 조립 (`assembler.py`)

**[함]** `SummaryResultDTO` 생성. **SEC-9 화이트리스트** — tokens·cost·cacheKey·model id는 **비노출**.
- 요약: tldr·contributions·method·results·limitations·reproducibility{code,data}·anchors(=`kept_anchors`만).
- 번역: 번역된 doc-model(+ 사용자 선호 단순명사 **후치환** 적용).

### ⑨ WRITE-THROUGH + ⑩ TELEMETRY

**[함]** `store.put` — **S3 먼저**(durable truth) → Redis 백필(TTL 24h). 그다음 텔레메트리 emit(U6 ObservabilityHub, **비차단 — 절대 raise 안 함**).
**[내보냄]** **5종단 중 1** → HTTP 200: `SummaryResultDTO`(ok) · `PendingDTO`(pending) · `AbstainDTO` · `CostDegradedDTO` · `SourceUnavailableDTO`.

---

## 곁다리: 추가 엔드포인트 (전부 라우터에서 OA 라이선스/주입 게이트)

- **`GET/POST /api/glossary`** — 개인 용어집 Phase 2a. 호출자 principal(SEC-8) 기준 **owner-scoped**. GET=저장 용어 목록(배지 에디터 프리필), POST=용어 upsert(검증 SEC-5, 성공 시 `glossaryVer++` 반환 → 그 사용자 캐시 무효화). 장애 시 fail-closed 503.
- **`GET /api/papers/{id}/doc-model`** — 구조화 doc-model(리치 뷰/요약 입력, BR-30). **기본 OFF → `license_unavailable`**. 캐시 히트면 doc-model 반환, 미스면 **U1의 lazy 빌드 (re)트리거 → `building`(클라 폴링)** 또는 빌드 큐 없으면 `source_unavailable`. doc-model은 **URL-free**(SEC-9, 그림 서명 URL은 `/assets`에서).
- **`GET /api/papers/{id}/assets`** — 그림/표 매니페스트(FR-17). **기본 OFF → `license_unavailable`**. **서명 URL만** 노출(SEC-9, 원 object_ref 비노출). full-text 뷰어와 독립(D1).

> (이전 `GET .../full-text` 단일 엔드포인트는 **doc-model + assets 두 갈래로 대체**됐다. OA 게이트는 U1 수집 게이트가 이미 OA만 저장하므로 사실상 운영 토글.)

---

## 저하/대기 종단 (섞지 않는다)

| 종류 | 트리거 | 응답 |
|---|---|---|
| **비용** | U6 degrade/circuit OPEN | `CostDegradedDTO` |
| **대기(긴 입력)** | MAP_REDUCE + 잡 큐 → 백그라운드 실행 | `PendingDTO(retryAfterMs)` (클라 폴링→캐시 히트로 수령) |
| **장애** | LLM 2회 실패 | `AbstainDTO("generation_unavailable")` |
| **근거화 실패** | 요약 grounding hard 2회 위반 | `AbstainDTO("insufficient_grounding")` |
| **빈 번역** | 번역 결과 2회 변화 없음/공백 | `AbstainDTO("empty_translation")` |
| **입력 초과** | OVER_CAP, 또는 MAP_REDUCE 게이트 OFF | `AbstainDTO("input_too_long")` |
| **소스 없음** | doc-model·전문·초록 모두 없음 | `SourceUnavailableDTO("no_full_text_or_abstract")` |

→ 클라가 "잠깐 막힘 / 처리 중 / 못 만듦 / 너무 김 / 원문 없음"을 구분해 다르게 안내.

---

## 한 장 요약

```
POST /api/summarize {task, paperId, version, persona, scope}
 ⓪ CACHE  10차원 불변키(+ownerId@ver>0) → Redis(TTL 24h) → S3(영구)  ★HIT → LLM 0회 즉시
 ① COST   U6 get_budget_state (읽기만) → degrade/OPEN → CostDegradedDTO  (지출 직전)
 ② SOURCE doc-model(S3) → 레거시 전문 → 초록 폴백 → 모두 없음 → SourceUnavailable
 ③ REFINE doc-model 직접 / 레거시 regex (references 제거·캡션/수식/Appendix 보존)
 ④ LENGTH ≤40K SINGLE · 40~120K MAP_REDUCE(ON→잡 enqueue→Pending / OFF→too_long) · >120K too_long
 ⑤ GLOSSARY keep-as-is 19 + 매핑 4 ∪ 개인(RDS) — 프롬프트강제 + 후치환
 ⑥ GENERATE summary=Sonnet 4.6(SINGLE/map-reduce) / translate=Haiku 4.5(구조화 doc-model)
            프롬프트 지시↔<paper>데이터 분리(injection 방어), 스트림 버퍼링
 ⑦ GROUNDING ★요약 전용 결정적: anchor=SOFT(미검증 drop) · 수치/스키마/잘림=HARD
            hard 위반 → 1회 retry → Abstain(insufficient_grounding) / 번역=빈 검사만
 ⑧ ASSEMBLE SEC-9 화이트리스트(tokens·cost·model 비노출) · anchors=kept만
 ⑨ WRITE-THROUGH S3 먼저 → Redis 백필   ⑩ TELEMETRY(비차단)
 → 5종단: ok · pending · abstain · cost_degraded · source_unavailable
 [곁다리] GET/POST /api/glossary · GET .../doc-model · GET .../assets (OA 게이트)
```

**전체 연결**: ②의 doc-model/전문 = **U1**이 S3에 적재(구조화 파서 산출물 포함) / ①의 비용 = **U6** cost guard / 진입 principal = **U6** 게이트웨이 / 호출은 **U5** 상세 페이지(요약·번역 모달·리치 뷰)에서. U7은 검색(U2)이 찾아준 논문을 깊이 읽어주는 마지막 조각.
```
