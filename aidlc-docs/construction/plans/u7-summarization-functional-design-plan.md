# u7-summarization-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (유닛별 루프) · **유닛**: U7 Summarization · **트랙**: 단일 트랙(코어 U1~U6 완료 후 편입 유닛) · **일자**: 2026-06-18
**근거(SSOT)**: `aidlc-docs/inception/` — `application-design/{unit-of-work,unit-of-work-dependency,unit-of-work-story-map}.md`, `user-stories/stories.md`(에픽 6 US-S1~S6), `requirements/requirements.md`(FR-12~14·NFR-P2·QT-5·NFR-C1 보강·C-2 경계·§12) · **설계 입력(HOW)**: `requirements/summarization-translation-pipeline.md` §2~§12(모델·스키마·정제·근거화·용어집·캐시·확정 결정) · `construction/shared/{dtos,events,ports,vector-spec}.md` · `shared/`(동결 계약)
**원칙**: 이 단계는 **기술 무관(technology-agnostic)** — 비즈니스 로직·도메인 모델·비즈니스 규칙만 설계한다. 모델 식별자(Sonnet/Haiku)·Bedrock·S3/Redis 구체 기술·수치형 NFR(TTFB·토큰 캡 등)은 **NFR Requirements/Infra Design**에서 확정. 설계 입력 문서가 §12에서 *확정*한 HOW도, **기술/수치 항목은 형태(shape)만** 본 단계로 흡수하고 구체값은 후속 단계로 넘긴다.
**실배포 기준(real-first) 구현**: U7은 LLM·스토어 의존을 **포트(이음새) 뒤에 두되, 첫 구현부터 실제 프로덕션 어댑터**(실 LLM 게이트웨이=Bedrock Sonnet/Haiku, 실 오브젝트 스토어+핫캐시=S3+Redis)로 구현한다. **mock/인메모리 대역 어댑터는 만들지 않는다.** 포트는 의존성 역전·테스트 경계·MR-4 계약 스왑을 위해 유지하되, 출하 구현은 실 어댑터 단일본이다. (FD 비즈니스 로직은 기술 무관 — 구체 바인딩은 NFR/Infra에서 확정.)

> ⚠️ **코드 대조로 드러난 설계 입력↔실제 코드 불일치 2건**(2026-06-18, 본 계획 §4 Q4·Q6에서 결정):
> 1. **근거화**: 설계 입력 §1/§12는 "U6 `enforce` 재사용"을 가정하나, 실제 `enforce(candidate, retrieved: Sequence) → GroundingDecision`는 🔒FROZEN **검색 형상**(후보를 *검색 레코드 집합*에 매핑)이다. U7 앵커는 *논문 1편 안의 섹션·표·span*을 가리키므로 형상이 다르다. QT-5도 "FD에서 재사용 가부 검증"을 명시 → **Q4에서 결정**.
> 2. **섹션 앵커**: 설계 입력 §4는 "U1 `split_sections` 재사용"을 가정하나, 코드에 `split_sections` 없음 — 전문은 raw text(`stored_full_text_ref`)로만 S3 보관. **앵커용 섹션 구조를 U7이 직접 도출**해야 할 수 있음 → **Q6에서 결정**.

---

## 1. 유닛 컨텍스트 (Step 1 — Analyze Unit Context)

- **책임**: 검색 결과 카드에서 사용자가 **선택한 단일 논문**에 대한 **온디맨드 요약/번역 읽기 경로**의 도메인 주체. 흐름: `STORE 조회(read-through) → 비용 게이트 → 입력 선택(요약=전문/번역=초록) → 구조 인지 정제 → (용어집 로드) → 길이 분기 → LLM 생성(스트리밍) → 근거화 게이트 → 조립·STORE write-through → 텔레메트리 emit`. 배포 ① API의 **모듈**(`backend/modules/summarization/`, 독립 앱 아님; app-shell·게이트웨이는 U6/@ELSAPHABA 조율 존). 초장문(map-reduce)만 비동기 잡 옵션(배포 ③).
- **스토리(Owner)**: **US-S1**(AI 구조화 요약) · **US-S2**(한국어 번역) · **US-S3**(출처 보기 앵커 + 근거 부족 시 기권) · **US-S4**(개인화: 수준·뷰·용어 선호) · **US-S5**(온디맨드 즉시[캐시]/스트리밍). **기여**: **US-S6**(Owner=U6 — 요약 비용 게이트 일시 기권 + 근거화 운영; U7은 비용 게이트 호출·근거화 출력 표면 제공).
- **신규 유닛(컴포넌트 미선잠금)**: U1~U6과 달리 U7은 application-design `component-methods.md`에 **사전 잠긴 컴포넌트가 없다**(2026-06-18 편입). 따라서 본 FD가 도메인 컴포넌트·서비스를 **최초 정의**한다(설계 입력 §6 파이프라인 단계를 컴포넌트로 환원). 예비 컴포넌트(§2에서 확정): `SummarizationController`(진입) · `SummaryCacheStore`(read/write-through 포트) · `SourceSelector`(task별 입력) · `InputRefiner`(구조 인지 정제) · `GlossaryResolver`(P1 시드∪P2 개인) · `LengthRouter`(단일/맵-리듀스 분기) · `LlmSummarizer`/`LlmTranslator`(LLM 게이트웨이 어댑터 경유) · `GroundingValidator`(근거 앵커 검증 — Q4 결정에 따라 형상 확정) · `ResultAssembler`(§3 JSON 계약 조립).
- **서비스(1)**: `SummarizationOrchestrationService` — 온디맨드 동기(스트리밍) 파이프라인 조정 + `publishSummarizationTelemetry`(비차단 관측/비용 이벤트).
- **capability 어댑터 이음새(실 구현 단일본)**: `LlmGatewayAdapter`(Sonnet 요약·Haiku 번역 — U6 게이트웨이 경유) · `FullTextSourceAdapter`(U1 `stored_full_text_ref` → S3 전문 read = capability, 코드 의존 아님) · `SummaryStoreAdapter`(S3 영구 + Redis 핫). **세 포트 모두 첫 구현부터 실 어댑터**(Bedrock·S3·Redis); mock 대역 없음(§4 Q10/Q11).
- **공유 계약(소비, 동결/잠금)**:
  - `shared/ports`(**의존**) — `CostGuardCircuitBreaker.get_budget_state()`(🔒, U7 조회 → 비용 게이트), `GroundingEnforcementHook.enforce`(🔒 검색 형상 — **재사용 가부 Q4**), `ObservabilityHub.emit*`(텔레메트리). **U7은 비용·관측을 재구현하지 않는다**(단일 권위 = U6).
  - `shared/dtos`(**신규 생산**) — **summarization 스키마 부재**(`accounts/library/search.schema.json`만 존재). U7은 `SummaryRequest`/`SummaryResponse`(§3 구조화 출력 + 앵커) DTO를 **신규 계약**으로 정의(U4 library의 PROVISIONAL→shared PR 패턴 동일).
  - U1 전문 capability — `stored_full_text_ref`(S3 객체 참조, raw text)로 read만. **섹션 구조 미영속**(Q6).
- **핵심 트레이스**: FR-12, FR-13, FR-14, FR-5, FR-11, C-2(추출 경계), NFR-P2(온디맨드·NFR-P1 비대상), NFR-C1(U7 Sonnet 비용 라인·CostGuard 게이트), NFR-R2(전문 부재 시 초록 폴백·LLM 장애 저하), RES-9(LLM 의존성 격리), QT-5(요약/번역 근거화), SEC-8(인가 — 게이트웨이/U3 위임), SEC-9(내부 필드 비노출), SEC-11(레이트리밋·남용 방어), SEC-15(fail-closed), US-S1..S6.

---

## 2. Functional Design 실행 계획 (Step 2 — 답변 확정 후 수행, 체크박스)

> 산출물은 모두 `aidlc-docs/construction/u7-summarization/functional-design/` 에 생성한다. **§4 답변 확정 전에는 생성하지 않는다.** U7은 백엔드 모듈 — `frontend-components.md`는 U5 FD 루프 산출물이며 본 계획 범위 밖(U7 결과 표면의 클라이언트 렌더=뷰 프리셋은 U5 후속 연동).

- [x] **domain-entities.md** — U7 도메인 엔티티·관계(기술 무관). 예비 컴포넌트(§1)에 대해 망라적:
  - 입력/요청: `SummaryRequest{paperId, version, task(summary|translate), targetLang, persona(expert|beginner)?, view?}`, `RequestContext{authSession, budgetSignal, requestId}`.
  - 캐시 키: `SummaryCacheKey{paperId, version, task, targetLang, persona, glossaryVer, modelVer, promptVer}`(immutable — Q7), `CacheLookup{hit, payload?}`.
  - 소스/정제: `SourceText{kind(full_text|abstract), raw}`, `RefinedSource{body, sections[]?, captions[], formulas[](보존)}`(Q2/Q6), `SanitizedInput{text, tokenCount}`.
  - 용어집: `Glossary{seedTerms[], keepAsIs[], userOverrides[]}`(P1∪P2 — Q8), `TermMapping{from, to}`.
  - 생성/출력: `SummaryDraft{tldr, contributions[], method, results, limitations, reproducibility, anchors[]}`(§3 JSON 계약), `Anchor{field, target(section|table|figure), span}`(Q6 입도), `TranslationDraft{koreanText, keptTerms[]}`.
  - 근거화/종단: `GroundingInput`/`GroundingDecision`(Q4 결정에 따라 enforce 포트 타입 참조 또는 U7 고유 `AnchorVerdict{ok, violations[]}`), `SummaryResponse` union(`SummaryResultDTO`·`AbstainDTO`·`CostDegradedDTO`·`SourceUnavailableDTO` — Q5).
  - **`shared/ports`·신규 `shared/dtos/summarization` 타입과 1:1 정합** 명시(드리프트 0); U7 고유 도메인 타입과 공유 계약 타입 경계 표기.
- [x] **business-logic-model.md** — `SummarizationOrchestrationService` 온디맨드 파이프라인 + 컴포넌트 알고리즘 수준 설계(설계 입력 §6 환원):
  - 흐름: `cacheLookup → [hit→즉시반환] → costGate(get_budget_state) → selectSource(task) → refine → loadGlossary → routeLength → generate(stream) → groundingValidate → assemble → writeThrough → emitTelemetry`.
  - **캐시 우선 경로(US-S5/§11)**: read-through(Redis→S3) HIT 시 LLM 0콜 즉시 반환; MISS만 생성 후 write-through(S3 영구 + Redis 핫).
  - **비용 게이트 경계(Q13/INV)**: LLM 호출 **전** `get_budget_state()`; OPEN/저하 시 `CostDegradedDTO` 기권(FR-11) — U7은 비용 판정 재구현 없음(U6 단일 권위).
  - **근거화 게이트(Q4)**: 생성 출력에 대해 결정적 앵커/수치/스키마 검증 → 통과/기권. **1차 실패 → 1회 재시도 → 그래도 실패 시 기권**(fail-closed, NFR-R1). LLM-judge 안 씀(§7.1 확정).
  - **스트리밍↔근거화 상호작용(Q12)**: 스트리밍 TTFB(NFR-P2)와 "근거 없으면 노출 금지"(FR-5)의 긴장 해소 규칙.
  - **길이 분기(Q3)**: 토큰 예산 초과 시 map-reduce(섹션 인지 청킹+오버랩), 기본은 단일 콜. 형태만(임계 수치=NFR).
  - **이벤트 경로(비차단)**: 성공/기권 후 토큰·비용·지연·persona·task → `ObservabilityHub`(NFR-C1 라인·RES-11 신호) — 응답 경로 밖.
  - LLM 호출 타임아웃·재시도(백오프)·서킷 **정책 형태만**(수치는 NFR; RES-9/NFR-R2).
- [x] **business-rules.md** — 결정 규칙·검증·제약:
  - 캐시 키 immutable 규칙·무효화 = 키(경로) 변경(Q7; §11).
  - task별 소스 선택 규칙 + 전문 부재/라이선스X → 초록 폴백(Q1; NFR-R2).
  - 구조 인지 정제 규칙(참고문헌 제거·LaTeX 보존/번역 금지·표/그림 캡션 유지·섹션 앵커 도출)(Q2/Q6; §4).
  - 용어집 적용 규칙(P1 미번역 keep-as-is·P2 개인 오버라이드·결정적 후치환 vs 프롬프트 주입)(Q8; §9.1).
  - persona 생성 변형(expert/beginner, 논문당 최대 2벌) vs 뷰 프리셋(재생성 0, 클라이언트 렌더) 경계(Q9; §9.2).
  - **종단 상태(SummaryResponse union) 결정 규칙**(Q5; FR-11) — 성공/기권/비용저하/소스부재 경계, 기권 우선(날조 금지 최우선).
  - 근거화 verdict 매핑 규칙(통과→저장·노출, 실패→1회 재시도→기권)(Q4; US-S3).
  - C-2 추출 경계(검색된 단일 논문 내용만; 사용자 원고 생성 금지)·SEC-9 비노출·SEC-11 레이트리밋(게이트웨이)·fail-closed(SEC-15).
- [x] **PBT 속성 식별(QT-4 / blocking PBT-02·03·07·09 해당 범위)** — 테스트 가능 속성 명문화:
  - 캐시 키 결정성/멱등(동일 입력→동일 키→동일 산출물; immutable 라운드트립).
  - 정제 멱등(재정제 불변)·용어집 후치환 멱등(keep-as-is 용어 불변).
  - `SummaryResponse` DTO 라운드트립(4 종단 상태 직렬화 보존·내부 필드 비노출).
  - 앵커 검증 건전성(앵커가 가리킨 섹션/span이 정제 소스에 실재할 때만 통과).
- [x] **추적성 매트릭스** — U7 컴포넌트/규칙/속성 → 요구사항 ID(FR-12~14·NFR-P2·QT-5·C-2·SEC-8/9/11/15·US-S1..S6) 역추적(미커버 0 검증).
- [x] **공유 계약 정합 주석 + 설계 입력 흡수 맵** — `summarization-translation-pipeline.md` §2~§12 각 HOW 항목이 어느 FD 산출물 절로 흡수됐는지 매핑(설계 입력 문서의 추후 SUPERSEDED 전환 근거). 비용/관측 단일 권위(U6) 재인용.

---

## 3. 가정 (명시 — 잘못이면 §4 또는 별도 지적으로 정정 요청)

- **AS-1**: 본 단계는 코드 미생성. 산출물은 설계 문서뿐이며 기술 스택·수치 결정 없음.
- **AS-2**: 모델 식별자(Sonnet 4.6/Haiku 4.5)·Bedrock·S3/Redis·토큰 캡·TTFB·map-reduce 임계 등 **기술·수치**는 설계 입력 §12가 방향을 확정했어도 **NFR/Infra Design에서 고정**. FD는 "요약=고역량 모델·번역=경량 모델", "영구+핫 2단 캐시" 같은 **형태**만 흡수.
- **AS-3 (real-first 구현)**: U7이 의존하는 **LLM 게이트웨이·전문 소스·요약 스토어**는 포트/capability 추상 뒤에 있고, **첫 구현부터 실 프로덕션 어댑터**(Bedrock·S3·Redis)로 구현한다 — **mock/인메모리 대역 어댑터는 만들지 않는다.** 포트는 의존성 역전·테스트 경계·MR-4 계약 스왑 용도로만 유지. 단위 테스트가 불가피하게 필요로 하는 테스트 더블은 *출하 어댑터가 아닌 테스트 픽스처*에 한정(구체 테스트 전략은 NFR/Code-gen). FD 비즈니스 로직은 기술 무관.
- **AS-4**: 비용 누적/서킷 판정·관측성 수집은 **U6 소관**(`shared/ports`). U7 FD는 `get_budget_state` 소비(게이트 분기)·`emit*` 제출만 설계. 근거화는 **Q4 결정에 따라** U6 enforce 소비 또는 U7 고유 결정적 게이트로 갈린다(QT-5가 FD 검증을 명시한 지점).
- **AS-5**: QT-5 평가셋(요약/번역 케이스)의 **구축·구체 수치**는 OP/U6 산출물(QT-1 평가셋 확장). U7은 근거화 출력을 평가셋이 측정 가능한 **표면**(앵커·기권 결정)으로 제공할 책임만 진다.
- **AS-6**: U7 결과의 클라이언트 렌더(뷰 프리셋 전체/3줄/관점별)는 **U5 후속 연동**. U7 FD는 그 표시 변형을 **재생성 0의 같은 §3 JSON에서 파생**되도록 출력 계약을 충분히 풍부하게 정의할 책임만 진다(렌더 자체는 U5).

---

## 4. 명확화 질문 (Step 3 — `[Answer]:` 태그로 답변; 미답 시 진행 불가)

> 답변 방법: 각 질문의 `**[Answer]**:` 뒤에 **A/B/C/D** 중 하나(또는 **X) 기타: 직접 기술** — 마지막 옵션, 업스트림 question-format-guide 표준). 모호한 답("상황에 따라", "섞어서" 등)에는 후속 질문을 추가한다(규칙 Step 5). overconfidence-prevention 원칙에 따라 카테고리를 빠짐없이 질의한다. **설계 입력 §12에서 이미 *확정*한 항목도, 코드 대조나 FD 입도 관점에서 재확인이 필요하면 ⟲표시로 다시 묻는다**(요청사항).

### A. 비즈니스 로직 모델링 · 데이터 흐름

**Q1 — task별 소스 선택 + 전문 부재 폴백(§5/NFR-R2).** 요약=S3 전문, 번역=초록은 확정(§5). 전문이 없거나 OA 라이선스 미허용이면?
- A) **초록 폴백 + 명시 표기**: 요약도 초록 기반으로 생성하되 "전문 부재 — 초록 기반 요약" 메타 표기(NFR-R2 우아한 저하). (권장)
- B) **소스부재 기권**(`SourceUnavailableDTO`) — 전문 없으면 요약 거부, 번역만 허용.
- X) 기타.
- **권장**: A — NFR-R2(전문 부재 시 초록 폴백)가 설계 입력 §6 stage 2에 이미 명시. 단 초록 기반 요약은 "초록에 없는 디테일 도출"이라는 가치(§3)가 약화되므로 **메타 표기로 정직성 확보**. 종단 상태는 Q5와 연동.
- **[Answer]**: A

**Q2 — 구조 인지 정제 범위(§4).** `InputRefiner`가 전문에서 무엇을 제거/보존하나?
- A) **참고문헌/인용목록 제거 · 수식(LaTeX) 보존(번역 금지) · 표/그림 캡션 유지 · 제어문자 제거 + 본문 격리(injection 대비)**. (권장, §4/§6 stage 3 그대로)
- B) A + **추가 노이즈 제거(범위 한정)** — 제거 대상을 **Header/Footer · 페이지 번호 · 저작권 문구 · 저자 정보(소속)** 에 **한정**. **Table/Figure 캡션 · Appendix · Supplementary Results 등 실험 정보가 포함될 수 있는 콘텐츠는 제거하지 않는다(보존).**
- C) 최소 정제(제어문자만) — 정제는 프롬프트 지시에 위임.
- X) 기타.
- **권장(원안 A)는 보강 채택**: 팀 결정 = B(범위 한정). A의 보수적 보존 위에 **명백한 비실험 노이즈(머리말/꼬리말·페이지번호·저작권·저자정보)만** 추가 제거하고, **실험 정보 가능 콘텐츠(캡션·Appendix·Supplementary)는 절대 제거 금지**. 이는 §3 결과 수치 도출·Q6 앵커(캡션/섹션) 보존과 정합(과도 제거로 인한 결과 유실 방지).
- **[Answer]**: B — 추가 노이즈 제거는 Header/Footer·페이지번호·저작권·저자정보에 한정; Table/Figure 캡션·Appendix·Supplementary Results 등 실험 정보 콘텐츠는 보존.

**Q3 ⟲ — 길이 분기(map-reduce) 트리거 형태(§5 stage 5).** 단일 콜 vs map-reduce 분기를 FD에서 어떻게 모델링?
- A) **형태만 정의**: `LengthRouter`가 `tokenCount > 컨텍스트예산`이면 map-reduce(섹션 인지 청킹+오버랩→부분요약→통합), 아니면 단일 콜. **임계 수치·청크 크기·비동기 잡 전환점은 NFR/Infra**. (권장)
- B) FD에서 임계 토큰값까지 확정.
- X) 기타.
- **권장**: A — 기술 무관 원칙(AS-2). 설계 입력 §12는 "초장문만 map-reduce·비동기 잡"을 확정했으나 *수치*는 NFR. FD는 분기 **규칙과 결과 동등성**(map-reduce 통합 출력도 §3 동일 스키마)만 보장.
- **[Answer]**: A

### B. 도메인 모델 · 근거화 · 종단 상태 (핵심 결정)

**Q4 ⟲⭐ — 근거화 게이트: U6 `enforce` 재사용 vs U7 고유 결정적 게이트(QT-5, 코드 대조 불일치).** `enforce(candidate, retrieved: Sequence) → GroundingDecision`는 🔒FROZEN **검색 형상**(후보를 *검색 레코드 집합*에 매핑). U7 근거화(§7.1)는 *단일 논문 소스 텍스트 안*의 앵커 실재성·수치 일치·스키마 완전성을 **결정적 코드 체크**로 본다(§7.1이 이미 "LLM-judge 안 씀, 결정적 체크만" 확정). 두 형상이 다르다 →
- A) **U7 고유 결정적 근거화 게이트(`GroundingValidator`)**: 설계 입력 §7.1 그대로 — 앵커가 가리킨 섹션/표/span이 **정제 소스에 실재하나** + 수치 정규화 일치 + 스키마 완전. enforce(검색 형상)는 **U7에 재사용 안 함**(형상 불일치). U6는 *검색* 근거화 단일 권위로 유지, U7 근거화는 *문서-충실도*라는 **다른 종류의 검증**임을 FD에 명문화. 단일 권위 원칙은 "검색 근거화=U6"로 한정 해석. (권장)
- B) **U6 ports 확장**: U6 FD에 요약-근거화 메서드(예: `enforceDocumentFidelity(summary, sourceText)`)를 신설해 **단일 권위(U6) 원칙 유지**. ⇒ **U6 FD 변경 = 크로스 유닛 의존·@U6 사인오프** 필요(외부 의존).
- C) **enforce 강제 적합(input shaping)**: 단일 논문 전문/섹션을 `retrieved` 레코드 집합으로 정형해 frozen enforce에 통과. ⇒ 검색 게이트를 다른 문제에 억지 적용(시맨틱 어긋남 위험).
- X) 기타.
- **권장**: A — ① 설계 입력 §7.1이 이미 결정적 체크(LLM-judge 배제)를 확정했고, ② frozen enforce 시그니처가 검색 전용이며, ③ QT-5가 "FD에서 재사용 가부 검증"을 명시 → 검증 결론은 "형상 불일치, 그대로 재사용 불가". A는 U6를 건드리지 않아 트랙 독립성↑. **단 "단일 근거화 권위=U6" INV의 해석을 "검색 근거화 한정"으로 좁히는 데 대한 당신/@U6의 합의가 필요** — 이견이면 B(U6 확장, 사인오프 동반). C는 비권장(억지 적합).
- **[Answer]**: A

**Q5 — 종단 상태(`SummaryResponse` union) 결정 규칙(FR-11/US-S3/US-S5).** 응답 종단 상태를 어떻게 가르나?
- A) **성공**(근거화 통과 & 산출물 완전) · **기권**(근거화 실패·재시도 후도 실패, 또는 코퍼스 밖 정당한 abstain) · **비용저하**(get_budget_state OPEN/저하 → "AI 요약 일시 중단") · **소스부재**(전문/초록 모두 부재 — Q1=B 채택 시). **빈 성공 금지**(근거 없는 빈 산출물을 성공으로 표기하지 않음). 비용저하·소스부재와 무관하게 근거화 실패면 **기권 우선**. (권장)
- B) 단순화 — 성공/실패 2분기(실패 사유는 메시지 필드).
- X) 기타.
- **권장**: A — U2 union 패턴과 동형(US-D6/D7 분리 선례). FR-11 명시 상태 + 신뢰 UX. B는 비용저하 vs 근거화 기권의 운영 신호(RES-11)가 흐려짐.
- **[Answer]**: A

**Q6 ⟲⭐ — 근거 앵커 입도 + 섹션 구조 출처(US-S3, 코드 대조 불일치).** 설계 입력 §4는 "U1 `split_sections` 재사용"을 가정하나 코드에 부재(전문=raw text). 앵커(`Anchor{field,target,span}`)의 `target`을 무엇으로 보증하나?
- A) **U7이 정제 단계에서 섹션 구조 도출**: `InputRefiner`가 헤딩 패턴(예: "INTRODUCTION", "5.2", "Table 3", "Figure 2")을 인식해 섹션/표/그림 라벨 + **문자 offset span**을 부여. 앵커 검증(Q4)은 이 도출된 구조에 대해 실재성 확인. "출처 보기"는 span으로 원문 하이라이트. (권장)
- B) **span(문자 offset)만 보증, 섹션 라벨은 best-effort**: 라벨 매칭 실패해도 span 실재로 앵커 성립(라벨은 표시용 힌트).
- C) U1에 섹션 분해 capability 추가 요청(외부 의존, @U1).
- X) 기타.
- **권장**: A — 코드 현실(섹션 미영속)에 맞춰 U7이 자족적으로 도출, 근거화(Q4)의 "앵커 실재성" 결정성과 직결. AI/ML arXiv는 섹션 헤딩이 규칙적이라 패턴 인식 실효적. **단 도출 실패 항목은 span-only로 저하**(B의 안전망 흡수) — 라벨 못 잡아도 span 실재하면 앵커 유효, 라벨도 span도 없으면 해당 주장 기권. C는 U1 변경 비용이 커 비권장.
- **[Answer]**: A

### C. 비즈니스 규칙

**Q7 ⟲ — 캐시 키 필드 구성 + per-user 경계(§11/SEC-8).** immutable 키 `(paperId, version, task, targetLang, persona, glossaryVer, modelVer, promptVer)`를 FD 신원으로 확정?
- A) **그대로 확정**. 번역은 P2 개인 용어집이 결과를 바꾸므로 **`glossaryVer`가 사용자별 버전** → 같은 키 공간에서 개인화가 자연 분리(공유 기본=glossaryVer0, 개인 오버라이드=사용자 glossaryVerN). 요약은 persona가 신원에 포함(2벌). (권장)
- B) per-user 캐시를 위해 키에 `userId` 명시 추가.
- X) 기타.
- **권장**: A — 설계 입력 §11 확정 키 그대로. `glossaryVer`가 개인화 분기를 흡수(별도 userId 불필요·공유 기본 캐시 최대 재사용). 개인 용어집 upsert→`glossaryVer++`→해당 사용자 키 자연 갱신(§9.1). SEC-8 격리는 키 자체가 아니라 조회 권한(게이트웨이)에서. B는 공유 캐시 재사용을 깨 비용↑.
- **[Answer]**: A

**Q8 — 용어집 적용 메커니즘(§9.1).** P1 시드(미번역 keep-as-is) + P2 개인 오버라이드를 어떻게 적용?
- A) **핵심 용어 보존은 프롬프트 단계에서 강제하고, 후치환은 사용자 선호 용어에 한정하여 단순 명사를 교정한다.** 즉 (1) keep-as-is·핵심 용어 매핑은 **프롬프트에 강제 주입**(생성 시 일관·문맥 처리), (2) 사용자 선호 용어의 **단순 명사 교정**은 **캐시된 기본 번역에 결정적 후치환**(LLM 재호출 회피, 조사 안전한 단순 명사 한정). (권장)
- B) 전부 프롬프트 주입(후치환 없음) — 단순하나 개인 교정마다 재생성.
- C) 전부 후치환 — LLM 무관, 일관성·문맥 약함.
- X) 기타.
- **권장**: A — 설계 입력 §9.1 확정(저비용 교정). 핵심 용어 보존(keep-as-is)은 생성 품질에 영향이라 프롬프트 강제, 사용자 선호 단순 명사는 후치환으로 재호출 회피. 후치환 멱등은 PBT 속성(§2).
- **[Answer]**: A — 핵심 용어 보존은 프롬프트 단계에서 강제, 후치환은 사용자 선호 용어에 한정하여 단순 명사를 교정.

**Q9 ⟲ — persona 생성 변형 vs 뷰 프리셋 경계(§9.2/FR-14).** 무엇이 생성(캐시)이고 무엇이 뷰(재생성 0)인가?
- A) **생성 변형 = persona(expert/beginner) 2벌**(내용이 실제로 달라짐 → 캐시 키 포함); **뷰 프리셋(전체/3줄/관점별) = 같은 §3 JSON의 클라이언트 필드 선택 렌더**(추가 LLM·캐시 0). U7은 풍부한 §3 출력만 보장, 뷰 렌더는 U5. (권장)
- B) 뷰 프리셋도 서버에서 생성·캐시(styleVer).
- X) 기타.
- **권장**: A — 설계 입력 §9.2 확정(개인화 = persona 2벌 + 무료 뷰). 뷰를 서버 생성하면 캐시 폭발·비용↑(B 배제). U7 책임은 "뷰가 재생성 없이 파생 가능할 만큼 풍부한 출력"(AS-6).
- **[Answer]**: A

### D. 통합 지점 · 실배포 구현 · 에러 처리

**Q10 — LLM 게이트웨이 어댑터 구현 전략.** `LlmGatewayAdapter`(요약/번역, U6 게이트웨이 경유)를 어떻게?
- A) 포트 + 결정적 픽스처 mock 선행, 실 어댑터는 후속 교체.
- B) 실 Bedrock 준비까지 U7 보류.
- X) **기타 — real-first**: `LlmGatewayAdapter` 포트는 유지하되 **첫 구현부터 실 Production Gateway(Bedrock Sonnet/Haiku)** 로 구현. **Mock LLM Adapter는 구현하지 않는다.**
- **권장(원안 A)는 기각** — 실배포 기준 결정. 포트는 의존성 역전·테스트 경계·MR-4 계약 스왑용으로 유지하되 출하 구현은 실 Bedrock 어댑터 단일본. U6 게이트웨이 경유(SEC-11 레이트리밋·비용 일원화)는 그대로.
- **[Answer]**: X — 포트 유지 + 첫 구현부터 실 Bedrock 게이트웨이, Mock LLM Adapter 미구현.

**Q11 — 스토어 어댑터(S3 영구 + Redis 핫) 구현 전략.** `SummaryStoreAdapter`를 어떻게?
- A) 포트 + 인메모리 mock 선행, 실 S3/Redis는 후속 교체.
- B) 보류.
- X) **기타 — real-first**: `SummaryStoreAdapter` 포트는 유지하되 **첫 구현부터 실 저장소(S3 영구 + Redis 핫)** 로 구현. **인메모리 Mock Store는 구현하지 않는다.**
- **권장(원안 A)는 기각** — 실배포 기준 결정. 캐시 시맨틱(read-through Redis→S3, write-through, immutable `SummaryCacheKey`)은 FD 규칙, 구현은 실 S3+Redis 단일본.
- **[Answer]**: X — 포트 유지 + 첫 구현부터 실 S3+Redis, 인메모리 Mock Store 미구현.

**Q12 ⭐ — 스트리밍 ↔ 근거화 게이트 상호작용(NFR-P2 TTFB vs FR-5 날조 0).** 근거화 검증(§6 stage 7)은 생성 *후* 실행인데 스트리밍은 생성 *중* 노출이다. 충돌을 어떻게?
- A) **버퍼-검증-스트리밍(안전 우선)**: 생성은 스트리밍으로 받되 **근거화 통과 전까지 사용자 노출 보류**, 통과 후 점진 렌더(또는 통과분부터). 근거 없는 토큰이 사용자에게 새는 것 방지(FR-5 최우선). TTFB는 캐시 히트(대부분)로 관리, 첫 생성만 검증 지연 감수. (권장)
- B) **낙관적 스트리밍 + 사후 철회**: 즉시 스트리밍, 근거화 실패 시 "근거 부족"으로 교체(빠른 TTFB·날조 노출 위험).
- C) **하이브리드**: 결정적 1차 체크(앵커 실재·스키마) 일부를 스트리밍 중 점진 적용, 치명 위반 시 중단.
- X) 기타.
- **권장**: A — FR-5(날조 0·근거 없으면 노출 금지)가 QT-5 인수기준상 절대 우선. NFR-P2는 "캐시 히트 즉시"가 주 경로이고 첫 생성 TTFB는 보조 목표 → 안전 우선이 정합. B는 날조 토큰 노출로 신뢰 UX(US-S3) 훼손. 구체 TTFB 목표/버퍼 전략 수치는 NFR.
- **[Answer]**: A

**Q13 — 비용 게이트 배치 + 기권 표면(NFR-C1/US-S6/FR-11).** `get_budget_state()` 게이트는 어디서, 실패 시?
- A) **LLM 호출 직전 게이트**(캐시 MISS 후·생성 전): OPEN/저하 → `CostDegradedDTO` 기권("AI 요약 일시 중단", FR-11 명시 상태) + 비용 폭발 신호(RES-11a). 캐시 HIT는 게이트 우회(LLM 0콜이라 비용 없음). (권장)
- B) 모든 요청 게이트(캐시 HIT 포함).
- X) 기타.
- **권장**: A — 설계 입력 §6 stage 0→1 순서(캐시 먼저, 게이트는 LLM 비용 발생 직전). 캐시 HIT는 비용 0이라 게이트 불필요(가용성↑). U6 CostGuard 단일 권위 소비(재구현 없음, AS-4).
- **[Answer]**: A

### E. 설계 입력 §12 "확정안" 재확인 (팀 이견 가능 — 재개)

> `summarization-translation-pipeline.md` §12가 "측정 불필요·바로 확정"으로 적은 HOW 항목들이다. 단독 작성된 설계 문서의 확정이므로 **팀 이견 여지**가 있어, 흡수 전 명시 질문으로 재개한다(요청사항). 권장안은 설계 입력 입장이되 **얼마든지 override 가능**.
> **범위 주의**: 여기는 *설계 입력 문서의 HOW 확정*만 재확인한다. **요구사항 수준 합의**(INCEPTION Q1~Q7 팀 합의 — FR-12~14 편입·NFR-P2·QT-5·§12 P3/자유입력 제외)는 이미 승인된 사안이라 **재개하지 않는다**.

**Q14 ⟲ — 모델 선택 정책(§2/§12).** task가 모델 역량 등급을 자동 결정(번역=경량·요약=고역량), 사용자 선택기 비노출.
- A) **task별 역량 등급 자동 결정 + 선택기 비노출** — 번역=경량 모델·요약=고역량 모델. **구체 모델 식별자(Sonnet/Haiku)·비용은 NFR에서 바인딩**(FD는 정책 형태만). (권장)
- B) **단일 모델 통일**(요약·번역 동일 등급) — 캐시·운영 단순, 요약 품질 리스크.
- C) **사용자에게 품질/모델 선택기 노출** — 사용자 통제↑, 캐시 분할·혼란.
- X) 기타.
- **권장**: A — 난해 코퍼스 요약은 정밀 모델 필요(§2), 번역 품질은 모델보다 용어집(§9.1)이 좌우. 선택기 노출은 캐시 쪼개짐·대다수 사용자 이해난(§2). **이는 FD 비즈니스 규칙(형태)이고 구체 모델·금액은 NFR 단계.** 팀이 비용/단순화를 우선하면 B.
- **[Answer]**: A

**Q15 ⟲ — 품질 게이트 판정 방식(§7.1/§12).** 결정적 체크만 vs LLM-judge 추가.
- A) **결정적 체크만**(앵커 실재성·수치 정규화 일치·스키마 완전·잘림/빈출력) — **LLM-judge(NLI) 미사용**. 1차 실패→1회 재시도→기권. "그럴듯하나 미묘히 틀림"은 앵커("출처 보기")로 사용자 검증에 위임(정직한 한계). (권장)
- B) **결정적 + LLM-judge(NLI) 2단** — 미묘한 방법 왜곡까지 포착하나 **콜 2배·비용·지연**.
- X) 기타.
- **권장**: A — 설계 입력 §7.1 확정. 전건 LLM-judge는 콜 2배라 bounded 비용 원칙과 충돌. 단 팀이 "요약 충실도 > 비용"을 택하면 B(고위험 케이스만 선택적 judge도 변형). **Q4(근거화 게이트 소유)와 직결** — A 채택 시 U7 결정적 게이트로 자족.
- **[Answer]**: A

**Q16 ⟲ — 재현성 신호 추출 방식(§12).** `reproducibility` 필드(코드/데이터 공개 여부·링크)를 어떻게 뽑나?
- A) **정규식 힌트 + LLM 추출 병행** — 정규식(github.com·"code available"·"dataset" 등 high-precision 패턴) + LLM 문맥 추출(공개 뉘앙스). 둘 다 §3 `reproducibility`로 수렴, 근거화(Q4)가 날조 링크 차단. (권장)
- B) **LLM 추출만** — 단순하나 링크 정밀도·날조 위험.
- C) **정규식만** — 싸지만 문맥(부분 공개·요청 시 공개) 누락.
- X) 기타.
- **권장**: A — 설계 입력 §12 확정. 정규식=싸고 정확한 링크 포착, LLM=문맥. 페르소나 최우선 신호(재현성)라 둘 병행이 robust. 구체 패턴 목록은 business-rules.md에 명문화.
- **[Answer]**: A

**Q17 ⟲ — 동기/비동기 처리 정책(§12).** 응답을 동기 스트리밍으로? 초장문은?
- A) **기본 스트리밍 동기**(단일 콜) + **초장문(map-reduce)만 비동기 잡**(배포 ③). (권장)
- B) **전부 동기** — 초장문도 동기(장시간·타임아웃 위험).
- C) **전부 비동기 잡 + 폴링** — 일관 처리나 TTFB·복잡도↑, 대다수 짧은 작업엔 과함.
- X) 기타.
- **권장**: A — 대다수 논문은 단일 콜 스트리밍으로 충분(§2 ~13K토큰), 초장문만 잡으로 분리. **Q3(길이 분기)·Q12(스트리밍↔근거화)와 연동** — 비동기 잡 경로의 근거화·기권도 동일 규칙 적용(잡 결과를 STORE write-through 후 통지).
- **[Answer]**: A

---

## 5. 결정된 불변식 (질문 아님 — 명백한 정답, 투명성 위해 명시; 이견 시 지적)

- **INV-1 (C-2 추출 경계, FR-12/13)**: U7은 **검색돼 사용자가 선택한 단일 논문의 내용**만 요약/번역한다(요약=전문 구조화, 번역=초록). 사용자 본인 원고·문헌리뷰 산문 생성은 **금지**(C-2 §12 제외 유지). grounding 지시 + 기권 경로가 경계 강제(§10).
- **INV-2 (비용·관측 단일 권위 = U6, AS-4)**: U7은 `CostGuardCircuitBreaker`·`ObservabilityHub`를 **재구현하지 않는다**. `get_budget_state` 조회·`emit*` 제출만(`shared/ports`). 근거화는 Q4 결정 사항(검색 근거화는 U6 유지).
- **INV-3 (SEC-9 내부 필드 비노출)**: 응답 DTO는 요약/번역 산출물·앵커(섹션/span)만. raw LLM 메타·토큰·비용·내부 캐시 키·모델 식별자·프롬프트는 외부 DTO 비노출(텔레메트리는 U6 관측 경로로만).
- **INV-4 (fail-closed, SEC-15/FR-5/FR-11)**: 근거화 미통과·LLM 장애·비용 OPEN은 **기권**으로 수렴(날조·빈 화면·스택 비노출). 근거 없는 출력은 사용자에게 노출하지 않는다.
- **INV-5 (캐시 키 immutable, §11)**: 같은 키 = 항상 같은 산출물. 무효화는 키(modelVer/promptVer/glossaryVer/version) 변경에 의한 신규 객체 생성(수동 flush 불필요).

---

## 사후 결정 — Construction 이후 (`[Answer]` 태그)

**Q18 — 번역 입력·프롬프트·길이 정렬 (2026-06-23; P2).** 전문 번역(scope=full)은 프론트 정식 기능(`fullTrans`)이나 백엔드 번역은 **초록 전용 형태**(`translate(abstract)`·"초록 번역" 프롬프트·`<abstract>` 태그)라, 정제 안 한 전문을 욱여넣는다 — ① 정제 미적용(참고문헌 등 노이즈·새니타이즈 누락) ② 길이판정(`refined.token_count`)↔실제전송(`source.raw`) **불일치**(예산 초과·#135 청킹 어긋남) ③ 프롬프트 부정합. 어떻게 정렬하나?
- A) **번역 입력=`refined.body` 통일(요약과 대칭) + 프롬프트 scope별 분기(초록/본문) + 길이기준 일치.**
- B) scope=full만 정제(초록 현행) — 비대칭 부채.
- C) 번역=초록 전용 축소 — 전문번역 회수(기능 손실; 프론트 노출과 충돌).
- **[Answer]**: **A** — 요약/번역이 동일 정제·길이 경로를 타게 해 불일치를 근본 제거, 프롬프트만 scope로 분기. 초록 번역은 raw≈refined라 무해. **산출**: BR-S(추가) · `_run_translate`·번역 프롬프트 분기 · 테스트.

---

## 6. 다음 절차

1. `§4`의 `[Answer]:` 태그를 **17개 모두** 채운다(또는 채팅으로 A/B/C/D/E 회신). **모든 질문은 동등하게 열린 결정**이다 — 권장안(설계 입력 입장)은 참고일 뿐, 팀 이견으로 얼마든지 override한다. ⭐ **Q4·Q6·Q12**(코드 대조 불일치)와 **§E Q14~Q17**(설계 입력 §12 확정안 재개)은 특히 팀 합의가 갈릴 수 있는 지점. `§5` INV는 이견 시에만 지적.
2. 모호 답변 발견 시 후속 명확화 질문 추가(규칙 Step 5) — 해소 전 진행 불가.
3. 답변 확정 → `§2` 산출물 생성(`u7-summarization/functional-design/` 의 domain-entities·business-logic-model·business-rules + PBT 속성·추적성·설계입력 흡수 맵).
4. 완료 메시지 + 리뷰 게이트 → 승인 시 다음 단계(**U7 NFR Requirements** — 모델 식별자 Sonnet/Haiku·Bedrock·S3/Redis·토큰 캡·TTFB 등 기술/수치 확정).

> 본 계획·질문은 **리뷰 게이트**입니다. 답변 전까지 Functional Design 산출물을 생성하지 않으며, 아직 커밋하지 않았습니다.
