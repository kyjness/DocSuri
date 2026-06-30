# U7 요약/번역 + Grounding Framework 통합 — 요구사항 명확화 질문 (Requirement Verification — Phase 3)

**단계**: INCEPTION → Requirements Analysis 재진입 (재인셉션 **페이즈 3** / U7 + Grounding) · **일자**: 2026-06-29
**담당**: 유진
**대상 기능**: 페이즈 3 — ① 요약(구조화)·**초록 번역**(scope=abstract, Metadata Abstract 사용)·**전문(全文) 번역**(scope=full, DocModel(v1) 사용) **정합·개선**, ② **단일 Grounding Framework 통합(D3)** — 단일 철학/인터페이스 + 도메인별 Validator(Search/Summary/Agent) 레지스트리.
**영향 유닛**: U7(`backend/modules/summarization/`) 핵심 · 공유 계약(`shared/dtos/summarization.schema.json`·`shared/dtos/docmodel`·`shared/ports`) · U6(`GroundingEnforcementHook` 검색 단일권위·`CostGuardCircuitBreaker`) · U1(eager DocModel 생산자) · U2(검색 grounding 선례) · 페이즈 4·5 Agent(요약을 Tool로 소비).
**근거 SSOT**: 재인셉션 차터 `inception/plans/reinception-2026-06-charter.md`(페이즈 3·**D3** Grounding·**D6** eager DocModel·§5-3 본문=DocModel) · 코드 베이스라인 `inception/reverse-engineering/code-baseline-2026-06.md`(§2 페이즈 3·§4-1 grounding 긴장점·§4-5 DocModel 인덱싱·§3 Summary DTO).
**선행 질문지(맥락)**: `requirement-verification-questions-u7.md`(2026-06-18 최초 구축본 — FR-12~ 편입·전부 A). 본 문서는 그 위에서의 **재인셉션 페이즈 3 정합·통합** 질문지(상위·갱신).
**답변 상태**: ✅ **답변 확정(2026-06-29)** — 전 문항 **A**. 유진님 직접 결정분: **Q6**(전문 번역=DocModel·온디맨드·영구저장 정합)·**Q7**(일시 기권 기준=spend ratio ≥0.80)·**Q9**(뷰 프리셋·커뮤니티 용어집 P3 **폐기**, persona 2벌+용어집 P1/P2 유지)·**Q5**(lazy 큐 = 레거시 백필 전용 한시 유지 후 제거 — eager가 flat-text로 degrade하므로 인덱스⊆docmodel). 나머지(Q1·Q2·Q3·Q4·Q8·Q10)는 사용자 위임으로 권장안 A. **단 Q2는 shared 계약 PR+U6 사인오프를 수반**하므로 requirements 등재 전 최종 확인 여지 표시. **코드 검증 완료**(이전 문서 상속분 전수 재확인 — Q3 수치 임계 0.5·Q4 앵커 형태·Q9 뷰프리셋 부재 등 정정).

> ⚠️ **이 페이즈의 성격 — 그린필드 아님**: `summarization/` 모듈은 이미 domain(refiner·grounding·map_reduce·structured_translator·glossary·source_selector·length_router·cache_key·assembler)·adapters(bedrock_llm·s3_docmodel·s3_full_text·s3_redis_store·rds_glossary·rds_assets·sqs_docmodel_build·sqs_summary_job)·ports·worker·real_wiring까지 존재한다. 페이즈 3의 실체는 "신규 구축"이 아니라 **① 요약/번역의 DocModel·eager 인덱싱 소비 정합, ② Grounding Framework 단일화(D3) — 검색·요약·(예정)에이전트 Validator의 공유 인터페이스/레지스트리 확정** 이다.
>
> **실질 갈림길**: **Q2(Grounding Framework 통합 경계)** 가 핵심이다. Q4(앵커 외부 노출)·Q5(eager DocModel 소비)는 부차 결정, 나머지는 대부분 코드 현실 확인·운영 정책 확정.
>
> **코드에서 이미 확인된 사실(발명 아님)**:
> - **요약 grounding은 U6 `enforce`를 거치지 않는다.** `summarization/domain/grounding.py::GroundingValidator.validate(GroundingInput)`가 U7 자체 **결정론적 문서충실도 검증**(① 앵커 존재 ② 수치 일치 ③ 스키마 완전성 ④ 빈/절단)을 수행한다. docstring이 명시: *"단일권위=U6는 **검색 grounding 한정**으로 읽는다"*. 실패→오케스트레이터 1회 재시도→재실패→기권(fail-closed, INV-4). **LLM-judge 미사용.** 판정 강도가 검사별로 다름: **앵커 존재=SOFT**(검증 불가 앵커는 드롭, 요약 본문+검증된 앵커는 노출 — `orchestrator.py:196` `anchors=verdict.kept_anchors`), **빈/절단·스키마=HARD**(즉시 기권), **수치=HARD이되 fraction-based** — 결과 수치 중 **원문에 없는 비율이 50% 초과일 때만** 기권(`_NUMERIC_MISMATCH_THRESHOLD = 0.5`, 95.3%↔0.953 정규화; 반올림·오탈자 몇 개는 허용). 수식 span은 LaTeX↔unicode 불일치로 앵커 존재검사 면제(수치 가드는 유지).
> - **검색 grounding은 U6 단일권위 FROZEN**: `shared/ports::GroundingEnforcementHook.enforce(candidate, retrieved)` 🔒, 호출 지점=U6 게이트웨이 post-handler. U2는 thin adapter(`grounding_adapter.py` to_grounding_input/map_decision)로 어댑팅만(INV-1).
> - **본문 번역 = DocModel(v1) 이미 구현**: `structured_translator.py`가 source doc-model을 walk → 번역 가능 단위(섹션 제목·문단·리스트·표/그림 캡션)만 번역 → **동일 구조/id의 번역 doc-model 재조립**. 표 수치셀(D8)·수식 LaTeX·코드블록·block/section id·그림 assetRef는 **verbatim 복사**. 긴 입력=map-only(reduce 없음).
> - **요약/번역 입력 = DocModel**: `RefineInput.doc_model`·`SummaryDraft/TranslationDraft.doc_model` 존재. `raw`(plain text)는 doc-model 부재 시 폴백.
> - **요약 앵커는 이미 외부 노출됨**: `summarization.schema.json`의 `SummaryDraft.anchors`가 `Anchor` 배열로 노출(required). **실제 `Anchor` 형태 = `{field, target, span, label}`** — `target`은 enum **`section|table|figure`**, `label`은 사람용 라벨("Section 3.1"), `span`은 원문 인용. **`blockId`/`sectionId` 같은 DocModel block 앵커 id는 계약에 없다**(앵커 단위 = 타입+라벨+인용, block id 아님). 조립 시 `AnchorVerdict.kept_anchors`(검증 통과분)만 실린다(`orchestrator.py:196`). → 본 질문지 Q4는 "노출 여부"가 아니라 **노출 입도·DocModel block id 도입 여부**를 다룬다(페이즈 2 Q3 이월분).
> - **3종 산출물·온디맨드·영구저장**: `Task={summary, translate}`·`Scope={abstract, full}` — **요약**(scope 무시·항상 전문), **초록 번역**(translate+abstract), **전문 번역**(translate+full). 모두 결과 카드 **온디맨드 액션**(긴 작업은 `sqs_summary_job` 비동기 백그라운드, BR-S6/S8 폴링). 저장은 `S3RedisSummaryStore` = **Redis hot(TTL) + S3 permanent 2-tier**(immutable key `summaries/{paper}/v{ver}/…`, write-through, "same key ⇒ same artifact, forever") — **3종 모두 캐시+S3 영구**.
> - **비용 게이트(U6 단일권위)**: `ops/cost_guard.py` cap=**$1,600/월**, ratio=spend/cap → `<0.80` NORMAL · `≥0.80` RERANK_OFF · `≥0.95` LEXICAL_ONLY · `≥1.0` circuit OPEN. U7 `orchestrator._is_cost_degraded`는 **degrade_mode≠normal 또는 circuit open이면 LLM 차단**(CostDegradedDTO) → **80%($1,280)부터 요약 일시 기권**. U7은 분기만(`get_budget_state` 🔒), $ 수치는 U6 소유.

---

## Q1. 페이즈 3 범위 — 정합·개선 + Grounding 통합 경계

페이즈 3 "U7 요약/번역 + Grounding Framework 통합"의 작업 범위를 다음으로 확정하는가? (대량/품질 고도화·표셀 번역·각주블록 등 세부는 후속.)

- **A) 정합·개선 + Grounding Framework 통합** (차터 권장):
  ① 요약/번역이 **eager DocModel(인덱싱 기반)·멀티소스**를 올바로 소비(Q5), ② 요약/번역 API·캐시·기권 경로 안정화·검증(Q7), ③ **단일 Grounding Framework 확정**(Q2) — 검색·요약 Validator의 공유 철학/인터페이스 + (예정)에이전트 Validator '자리' 확보. LLM-judge·표셀 번역·각주블록·다국어는 **명시 이월**(Q10).
- **B) U7 전면 재작성** — 기존 모듈 폐기·재구축(코드 자산 폐기 비용·리스크↑).
- **X) 기타**(범위 가감)

[Answer]: A (위임 — 권장안)
**권장(차터)**: A — 코드 자산 보존, "정합·개선 + Grounding 통합"으로 한정. 후속 항목은 명시 이월.

---

## Q2. Grounding Framework 통합 (D3) — 단일 인터페이스 + 도메인 Validator 레지스트리 — **실질 갈림길**

차터 D3은 "유닛 신설 없이 `shared/ports`를 **단일 철학·단일 인터페이스 + 도메인별 Validator(Search/Summary/Agent) 레지스트리**로 확장"을 요구한다. **그러나 코드 현실은 이미 분리되어 있다**: 검색=U6 `enforce`(candidate↔retrieved 레코드 SET, FROZEN), 요약=U7 `GroundingValidator`(요약↔단일 논문 refined source, 결정론·문서충실도). 둘은 **검증 종류가 다르다**(provenance-set vs document-fidelity). 이 둘과 (예정)에이전트 Validator를 어떻게 "단일 프레임워크"로 묶는가?

- **A) 코드 현실 추인 + `shared/ports`에 도메인-중립 Validator 추상 인터페이스 선언, 레지스트리 등재** (차터·코드 정합 권장):
  공유하는 것은 **철학과 계약 형태**(fail-closed·기권≠빈결과(BR-9/BR-8)·날조0·verdict={pass/block/abstain}·violation 비노출 SEC-9)이고, **검증 로직은 도메인별**로 둔다. `shared/ports`에 `DomainGroundingValidator`(가칭) 추상 + Validator 레지스트리(Search→U6 enforce 어댑팅 / Summary→U7 GroundingValidator / Agent→페이즈 4)를 선언. **enforce 호출 지점은 도메인 seam 유지**(검색=U6 게이트웨이 post-handler, 요약=U7 오케스트레이터). "단일권위 enforce(검색)" FROZEN 시그니처는 **무변경**, "단일권위"의 의미를 **검색 grounding 한정**으로 차터/ports.md에 명문화(코드 docstring과 일치).
- **B) 요약 grounding을 U6 `enforce`로 통일** — 검색형 시그니처(candidate/retrieved record SET)에 문서충실도 검증을 끼움 → FROZEN 시그니처 변경·의미 오버로드·검증 종류 혼합으로 rework·테스트 붕괴 위험.
- **C) 현행 분리 유지하되 shared 레지스트리/추상화 안 함** — 통합 "프레임워크" 목표 미달(철학·계약 공유의 제도화 부재).
- **X) 기타**(예: enforce를 도메인 디스패처로 일반화 — FROZEN 변경·U6 사인오프 수반)

[Answer]: A (위임 — 권장안 / ⚠️ shared 계약 PR·U6 사인오프 수반 = requirements 등재 전 최종 확인 여지)
**권장(차터·D3·코드)**: A — 코드 현실(검색·요약 Validator 분리)을 추인하고, 공유는 **추상 인터페이스+레지스트리+단일 철학**으로 제도화. FROZEN enforce 무변경, "단일권위=검색 한정" 명문화. (Validator 추상·레지스트리는 shared 계약 PR + U6 사인오프.)

---

## Q3. 요약 grounding 판정 방식·기준 보정 — **실질 결정(기존 추정값 재검)**

요약 grounding의 판정 방식(결정론 vs LLM-judge)과 **수치 임계 기준**을 어떻게 확정하는가?

> ⚠️ **코드에서 드러난 갭(2026-06-29 확인)**: 현행 수치 가드는 `_NUMERIC_MISMATCH_THRESHOLD = 0.5` — **결과 수치의 50% 초과가 원문에 없을 때만 기권**한다(`test_domain_grounding.py`: 25%→통과, 75%→기권). 이는 환각 방지 게이트치고 헐겁다(핵심 수치 2개 중 1개 날조도 통과). 50%가 이렇게 느슨한 이유는 **결정론 matcher가 노이즈를 낸다**(반올림 95.3↔95.31·단위·표 재렌더·`_normalize_number`는 %↔분수만 처리)는 것을 임계로 덮었기 때문 — **"matcher 부정확"과 "날조 허용"을 한 손잡이로 섞음.** 그리고 **충실도 평가셋(QT-1)이 코드에 없다**: `test_domain_grounding.py`=Validator 로직 단위테스트(합성 입력)·`test_integration_real.py`=배관(번들 빌드)뿐, **실제 LLM 요약의 날조율을 재는 라벨링 셋은 부재**(`ports.py::run_eval_set`는 PROVISIONAL 빈 훅). 즉 0.5는 데이터로 보정된 값이 아니라 추정값이다.

- **A) 결정론 유지 + QT-1 평가셋 신설·기준 재보정(노이즈와 날조 분리)** (권장):
  ① **결정론 유지**(비용 0·재현성·감사가능). ② **QT-1 충실도 평가셋 신설**(grounded/날조 라벨 케이스 + `run_eval_set` 구현) — 페이즈 3 산출물. ③ **matcher 정밀화**(반올림 톨러런스·단위 정규화)로 *맞는 수치가 미스로 안 잡히게* 한 뒤 **임계를 strict로 조임**(0.5 → 0~1개 허용). ④ 임계는 평가셋의 **false-abstain vs false-pass 곡선**에서 선택(감으로 정한 분수 폐기). ⑤ (선택) **헤드라인 수치 정확 강제 / 부수 수치 관대** 가중. 앵커 존재=SOFT(검증 통과분만 노출) 유지, 수식 span 면제 유지.
- **B) LLM-judge 추가** — 의미적 충실도 향상 가능하나 비용·비결정성·환각-검증의 환각 위험. (평가셋 없이 도입 시 같은 무보정 문제 반복.)
- **C) 현행 0.5 임계 그대로 유지** — 무보정 헐거운 게이트 존치(faithfulness 구멍 잔존).
- **X) 기타**

[Answer]: A
**권장**: A — 결정론 유지하되 **QT-1 평가셋 신설 + matcher 정밀화 + 임계 strict 재보정**으로 0.5 추정값을 데이터 기반 기준으로 대체. LLM-judge는 평가셋 위에서 페이즈 7 품질 트랙 후보로 이월.

---

## Q4. 요약 앵커 입도 — 현행(타입+라벨+인용) 유지 vs DocModel block id 도입 — 페이즈 2 Q3 이월분

코드 현실: 앵커는 **이미 외부 노출**되며(`SummaryDraft.anchors`), 검증 통과분만 실린다(`kept_anchors`, `orchestrator.py:196`). 실제 형태는 **`{field, target∈{section|table|figure}, span(원문 인용), label("Section 3.1")}`** — **DocModel block id는 계약에 없다.** 페이즈 2는 DocModel Block 앵커의 외부 노출을 페이즈 3로 이월했다. 요약 앵커의 입도를 어떻게 확정하는가?

- **A) 현행 입도 유지(타입+라벨+인용) + 검증 통과분만·내부 비노출, block id 도입은 후속 이월** (권장):
  현행 `{field, target, span, label}` 계약 유지. **violation 코드·내부 점수·refined source 원문 비노출**(SEC-9) 확인. DocModel **block-level id 앵커**(정밀 딥링크·에이전트 evidence 정밀 연계)는 **후속 트랙으로 이월**(Q10) — 페이즈 4 evidence DTO 동결과 함께 결정(D5).
- **B) 페이즈 3에서 DocModel block id를 앵커 계약에 즉시 추가** — `summarization.schema.json` 계약 개정 + DocModel block id 안정성 보장 필요. 에이전트 미착수라 evidence 입도 요구가 미확정 → rework 위험.
- **C) 앵커 외부 노출 축소(paper-level만)** — 현행 기능 후퇴(FR-12 항목별 출처 추적 약화).
- **X) 기타**

[Answer]: A (위임 — 권장안)
**권장(차터·D5 정합)**: A — 현행 입도 유지·검증 통과분만 노출. block id 정밀 앵커는 페이즈 4 evidence 계약과 함께(후속).

---

## Q5. lazy DocModel 빌드 큐(`sqs_docmodel_build`)를 유지하는가 — **실질 결정**

> **코드 확인(2026-06-29 정정)**: eager 빌드(`_build_doc_model_before_index`·`_build_doc_model_from_record`)는 파싱/TEI/PDF 실패 시에도 **flat-text doc-model로 degrade**하지 None을 내지 않는다(docstring: "never blocks the index path"). `_index_paper`의 `doc_model is None` 폴백 인덱싱(line 322-323)은 **`_doc_model_builder` 자체가 미배선인 설정 상태**에서만 도달(전량 무-docmodel; per-paper 실패 아님). 따라서 **정상 배선 production에선 "인덱스된 논문 ⊆ s3 doc-model 보유" 가 사실상 성립** — 검색에 뜨는 논문은 모두 doc-model이 있다. ⇒ lazy 큐의 잔존 이유는 "eager 실패 자가복구"가 **아니라**, **eager 정책 이전에 수집된 레거시 코퍼스 백필**(인덱스는 있으나 S3 doc-model이 없는 옛 논문)뿐.

- **A) 백필 창구로만 한시 유지 → 백필 완료 후 제거(deprecate)** (권장):
  요약/번역은 **eager s3 doc-model 우선 소비**. lazy `BUILD_DOC_MODEL` 잡은 **요약 시점 최초 빌드 전제를 폐기**하고 **레거시 백필 전용**으로만 한시 유지. 백필 완료 + "인덱스 ⊆ doc-model" 불변식 확인 후 **큐·소비 경로 제거**. (`orchestrator.doc_model()`의 미스→enqueue→`building=True` 경로도 백필 종료와 함께 단순 미스=`source_unavailable`로 축소 가능.)
- **B) 즉시 제거** — 레거시 백필이 이미 끝났다고 확인되면 지금 제거(코드 단순화). 단 미배선 설정·잔여 레거시가 없음을 보장해야 함.
- **C) 영구 안전망으로 유지** — degrade로 None이 안 나오므로 production 잔존 가치 낮음(보수적 선택).
- **X) 기타**

[Answer]: A — lazy 큐는 **레거시 백필 전용**으로만 한시 유지, 백필 완료+"인덱스⊆docmodel" 확인 후 제거. (per-paper eager 실패 자가복구 목적은 코드상 불필요 — degrade로 None 미발생.)
**권장(차터·D6)**: A — 백필 창구로 한시 유지 후 deprecate. eager가 flat-text로 degrade하므로 "안전망" 명분은 약함 — 백필만 끝나면 제거가 정석.

---

## Q6. 전문(全文) 번역 = DocModel(v1)·온디맨드·영구저장 정합 확인 (차터 §5-3 / 미해결 #3)

차터 §5-3·미해결 #3("본문=DocModel(v1)이 doc-model 피벗 이후 현행 계약과 일치하는지 코드 확인")을 다음으로 닫는가? (코드 = `structured_translator.py`가 이미 source DocModel walk→번역 doc-model 재조립, 표셀(D8)/수식 LaTeX/코드/id/그림 assetRef verbatim.)

- **A) 코드 현실 = 계약 일치 확인·등재(신규 결정 아님)** (권장):
  ① **전문 번역 = TRANSLATE+scope=FULL**, 입출력 모두 **DocModel(v1)** 일관(번역본도 동일 구조/id의 doc-model). ② **온디맨드** — 버튼 누를 때 eager s3 docmodel을 번역(긴 건 비동기 백그라운드 잡·폴링). ③ **번역본 영구저장** — S3 permanent(immutable key) + Redis hot(TTL); 한 번 번역되면 동일 키로 영구 재사용. **요약·초록번역·전문번역 3종 모두** 온디맨드+캐시+S3 영구 동일. requirements에 정합 사실로 등재. **표셀 번역·각주블록·앵커 id 세부**는 후속 이월(Q10).
- **B) 번역 본문 모델 재설계** — 근거 필요(현 구조 구체적 문제 정의 선행).
- **X) 기타**

[Answer]: A — 전문 번역=DocModel(v1)·온디맨드·번역본 S3 영구저장 정합 확인(요약·초록번역·전문번역 3종 모두 동일).
**권장**: A — 정합 확인·등재(전문 번역=DocModel(v1)·온디맨드·영구저장). 세부(표셀/각주/앵커 id)는 후속.

---

## Q7. NFR 프로파일 — 온디맨드·스트리밍·비용 (선행 질문지 Q3·Q4 재확인)

요약/번역 NFR을 다음으로 재확정하는가? (선행 질문지 2026-06-18 Q3·Q4 = A.)

- **A) 현행 유지·재검증** (권장):
  검색 SLA(NFR-P1) **비대상** — 온디맨드 액션(캐시 히트=즉시 / 첫 생성=스트리밍 TTFB 목표, 첫 생성 수십 초 허용). 비용은 **U6 CostGuard 재사용**: cap $1,600/월, **spend ratio ≥0.80(=$1,280)부터 요약 일시 기권**(`degrade_mode≠normal`→`_is_cost_degraded`→CostDegradedDTO), ≥0.95 심화, ≥1.0 circuit open. $ 수치·임계는 **U6 단일권위**(U7은 분기만, FR-11). U7 비용 라인 텔레메트리. eager DocModel 전량 빌드 비용은 페이즈 6 운영 사안.
- **B) degrade_mode 의미 재정의** — 현재 U7은 검색용 신호(`RERANK_OFF`/`LEXICAL_ONLY`)를 "non-normal이면 LLM 중단"으로 재해석해 **80%부터 기권**한다(보수적). 요약 전용 degrade 단계(예: 95%까지는 캐시만, 80~95%는 신규 생성만 제한 등)를 U6와 합의해 분리할지 — D3 "검색 신호 재사용" 주제와 연결(FROZEN `get_budget_state` 무변경 범위 내 매핑 조정).
- **X) 기타**(SLA·예산·스트리밍 목표 수치 변경 — NFR Requirements에서 확정)

[Answer]: A — 온디맨드 NFR·U6 CostGuard 재사용 유지. 일시 기권 기준 = spend ratio ≥0.80(=$1,280/$1,600)부터(U6 단일권위). degrade 단계 세분은 필요 시 후속.
**권장**: A — 온디맨드 별도 NFR·CostGuard 재사용 유지(80% 기권 현행). degrade 단계 세분(B)은 필요 시 NFR/D3에서. 수치·콜드스타트는 NFR Requirements에서.

---

## Q8. 페이즈 4·5 에이전트 Summary Tool 계약 시점 — D5

요약/근거 앵커를 에이전트(문헌탐색·연구아이디어)가 **Tool로 소비**할 계약(Summary DTO·evidence 앵커 연계)을 페이즈 3에서 동결하는가, 페이즈 4·5에서 동결하는가?

- **A) 페이즈 3는 요약 동작·앵커 계약 안정화, 에이전트-facing Tool 포트/evidence 연계는 페이즈 4·5 계약 게이트에서 동결** (차터·D5 권장):
  요약 자체·앵커 노출(Q4)은 페이즈 3에서 안정화·검증. 단 에이전트가 소비할 **Tool 포트·근거 출력 DTO 연계**는 D5 "계약 선행 동결" 원칙대로 페이즈 4(문헌탐색·근거형성) 질문지 후 `shared/`에 동결. 페이즈 3에서 에이전트 계약을 선발명하지 않음.
- **B) 페이즈 3에서 에이전트 Tool 계약까지 동결** — 에이전트 요구 미확정 선동결 = rework 위험(D5 전제 위배).
- **X) 기타**

[Answer]: A (위임 — 권장안)
**권장(차터·D5)**: A — 요약·앵커 안정화 ⊃ 에이전트 Tool 계약 동결(페이즈 4·5).

---

## Q9. 개인화 경계 (persona / 용어집) — U9 (현재 코드 기준 재확정)

개인화 범위를 **현재 코드 기준**으로 재확정하는가? (뷰 프리셋·커뮤니티 용어집(P3)은 폐기 — 코드에 뷰 프리셋 부재, P3 미구현.)

> **코드 확인(2026-06-29)**:
> - **persona**: `Persona.EXPERT`/`Persona.BEGINNER`만(전문가/입문자) — **요약 전용 2벌**(`cache_key.py:22` "summary varies by persona (2 variants)"), **번역은 persona-agnostic**(단일).
> - **용어집 적용(`glossary.py`)**: seed(P1) ∪ 개인 override(P2). 기본 `prompt_enforced=False` → **`post_substitute`**: 번역 출력 위에 **결정론적 덮어쓰기**(LLM 재호출 없음·전체단어·긴것우선·한국어 조사 보존·멱등). 옵션 `prompt_enforced=True` → LLM 프롬프트에 강제. owner-scoped(SEC-8), 개인 용어집 조회 실패 시 **seed-only로 저하**(전체 기권 안 함).
> - **뷰 프리셋**: 코드 부재(삭제됨). **커뮤니티 용어집(P3)**: 미구현.

- **A) 현재 코드 범위로 확정** (권장):
  persona(전문가용/입문자용, 요약 전용 2벌)·용어집(P1 seed + P2 개인, post-substitution 덮어쓰기 기본 / prompt-enforced 옵션) **포함**. **뷰 프리셋·커뮤니티 용어집(P3)·자유입력 per-user 연구노트 관련성 = 범위 외(폐기/§12 제외).** 개인화 신호 본체 경계는 U9 소유(요약은 소비 지점만).
- **X) 기타**(범위 가감)

[Answer]: A — persona(전문/입문 2벌·요약 전용)+용어집(P1 seed+P2 개인, post-substitution 덮어쓰기) 포함. **뷰 프리셋·커뮤니티 용어집(P3) 폐기**, 자유입력 제외. U9 경계 유지.
**권장**: A — persona(2벌)+용어집(P1/P2) 포함. 뷰 프리셋·P3 폐기, 자유입력 제외. U9 경계 유지.

---

## Q10. 후속/제외 항목 명시(범위 경계)

다음을 페이즈 3 **제외 → 후속(품질/세부 트랙)** 으로 명시 이월하는가?

- **A) 이월 확정** (권장):
  표 셀 번역 · 각주 블록 처리 · **DocModel block-level id 정밀 앵커**(Q4 — 페이즈 4 evidence 계약과 함께) · 요약 grounding LLM-judge(Q3) · 다국어 번역. *(뷰 프리셋·커뮤니티 용어집(P3)은 이월이 아니라 **폐기** — Q9.)* 페이즈 3는 **정합·개선 + Grounding Framework 통합 + QT-1 평가셋 신설**까지.
- **X) 기타**(일부를 페이즈 3로 당김 — 근거 필요)

[Answer]: A — 위 항목 후속 이월(뷰 프리셋·P3은 이월 아닌 폐기). 페이즈 3는 정합·개선 + Grounding 통합 + QT-1 평가셋 신설에 한정.
**권장**: A — 위 항목 후속 이월. 페이즈 3는 정합·통합에 한정.

---

## 다음 단계

유진님 답변(특히 **Q2**, 부차 **Q4·Q5**) 확정 후 → 본 질문지 답변을 `requirements.md`에 U7 **FR 개정·NFR·C** + **Grounding Framework(D3)** 추적성으로 등재(단일 인터페이스/레지스트리·도메인 Validator 경계·eager DocModel 소비·앵커 노출 계약). 이후 `stories.md` 요약/번역·근거화 에픽 갱신 → `plans/u7-summarization-workflow-plan.md`(신규) → (필요 시) Application Design U7/`shared/ports` amendment + U6 사인오프 → Units Generation 리뷰 → Construction(FD→NFR→Infra→Code→Build/Test).

> **선행 의존(차터 D4)**: 페이즈 3는 페이즈 1·2 완료에 의존한다. **문서 정합·본 질문지·코드(mock/fixture 기반) 작성은 페이즈 1 라이브 스모크 없이 착수 가능**(차터 §4.2 — 인셉션은 계약 레벨). 단 **페이즈 3 *통합 완료*는 페이즈 1 `ingest-one` 라이브 스모크 통과 후**에만 인정한다(베이스라인 §5 — 요약은 실제 eager DocModel을 소비). 즉 스모크는 페이즈 3의 **통합 완료 게이트**이지 착수 게이트가 아니다.
