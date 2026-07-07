# DocSuri — 요구사항

**단계**: INCEPTION → 요구사항 분석(Requirements Analysis) · **깊이**: Comprehensive · **일자**: 2026-06-15
**사이클**: AI-DLC 재시작(cycle 2) · **단일 진실 공급원(SSOT)**: 본 문서 + `aidlc-state.md` + `audit.md`

> **개정 (2026-06-18) — 신규 유닛 U7(요약/번역) 편입**: U1~U6 빌드·배포 완료 후 신규 기능을 Requirements Analysis 재진입으로 등재. 명확화 질문 `requirement-verification-questions-u7.md` Q1~Q7 전부 A(설계 초안 권장안, **팀 합의 2026-06-18**) → **FR-12~14·NFR-P2·QT-5·NFR-C1 보강·C-2 경계·§12 제외 추가**. 설계 입력: `summarization-translation-pipeline.md`. 본 개정으로 §2 단일 임무(디스커버리)에 **검색된 논문의 추출 요약/번역**이 보조 기능으로 추가된다(생성 글쓰기 C-2 경계는 유지).

> **개정 (2026-06-19) — 신규 유닛 U8(인용 그래프/각주 트리) 편입**: 명확화 질문 `requirement-verification-questions-citation-graph.md` Q1~Q22 답변 확정(Q3/Q10=X, Q4/Q14=B, 나머지 권장안) → **FR-15~16·NFR-P3·QT-6·§12 카브아웃** 등재. 논문 상세보기 페이지의 보조 액션으로 각주 트리를 제공하되, v1은 **backward references만** 표시하고 FE 구현은 별도 분기 산출물에 위임한다.

> **개정 (2026-06-22) — 멀티모달 표시(그림·도표) 부분 편입**: 정규화 시 그림·도표를 이미지 자산으로 추출·저장해 상세보기/전문뷰어에 표시하는 기능을 Requirements Analysis 재진입으로 등재. 명확화 `requirement-verification-questions-multimodal-display.md` Q1~Q7(**Q2=C 혼합 추출, 나머지 A**, 2026-06-22) → **FR-17 등재 + FR-12 앵커 자산 연결 보강 + §12 "그림·도표" 제외를 "비전 추론만 제외"로 한정**. 요약/번역 LLM 입력은 **텍스트+캡션 유지**(이미지 비전 추론은 차기 사이클). 영향 유닛: U1(자산 추출·저장)·공유계약(`shared/dtos`)·U7(통과 + 기존 백/프론트 정합 갭 3건 흡수)·U5(렌더).

> **개정 (2026-06-23) — 신규 유닛 U9(개인화 / 행동 지능) 편입**: 사용자 행동 로그를 기록하고 분석해 개인화 맞춤 서비스를 제공하는 기능을 Requirements Analysis 재진입으로 등재. 명확화 `requirement-verification-questions-u9-personalization.md` Q1~Q20(**Q13=B, 나머지 A**, 2026-06-23) → **FR-39(행동 이벤트 기록)·FR-19(관심사 프로필 집계)·FR-20(개인화 적용)·NFR-P4·QT-7 등재**(행동 이벤트 기록은 본래 FR-18이었으나 같은 날 doc-model **자체 리치뷰**가 FR-18을 선점 → **신규 FR-39로 재번호**, 2026-06-30 정합 정정 — `aidlc-suite-review` PR #280. **FR-22~25는 폐기된 구 research-agent 초안 ID**[`aidlc-state.md` 2026-06-28 분리 refactor]라 재사용을 피하고 신규 번호 부여). v1은 **검색 rerank + 요약/번역 기본값 개인화**까지 포함하고, 별도 추천 목록·전체 클릭스트림·실시간 ML 추천 파이프라인은 제외한다. U6 운영 텔레메트리와 분리된 owner-scoped 사용자 데이터로 관리한다.
>
> **개정 (2026-06-24) — doc-model 실데이터·비동기 (PR-1)**: doc-model 생성·요약을 **비동기**로 완성(구현 — FD/BR/NFR back-sync). 리치뷰(자체 리치뷰) 첫 열람 시 **lazy 빌드를 백그라운드 잡**으로 트리거하고 "준비 중"(building) 표시·폴링; 긴 논문 요약(FR-12)은 **map-reduce를 백그라운드 잡**으로 처리하고 진행(pending) 표시·폴링(게이트웨이 타임아웃 회피), **초극단(>입력상한)은 거절**. 게이트 기본 OFF(라이브 무변경). 상세 = `construction/plans/docmodel-foundation-pivot-plan.md` PR-1 절·BR-S6/S12·BR-30.
> **개정 (2026-06-24) — 구조화 번역 (PR-2)**: 본문 번역(FR-13, scope=full) 출력을 평문 한 덩어리 → **본문과 동일한 구조화 형식(번역본 doc-model)** 으로 전환해 원본 본문과 **같은 리치 뷰어**로 렌더. 표 셀·수식·코드는 원어 보존(D8), 섹션 제목·문단·캡션·리스트만 번역. 긴 본문은 **섹션별 map-only**(reduce 없음)로 처리하고 요약 잡 큐·워커 재사용(`task=translate`)으로 **비동기**(pending·폴링), 초극단은 거절. 계약 변경: `summarization.schema.json` `TranslationDraft`가 `docmodel.schema.json#/$defs/DocModel`을 크로스파일 `$ref`. 상세 = `construction/plans/docmodel-foundation-pivot-plan.md` PR-2 절·BR-S18·BR-S6/S12.
>
> **개정 (2026-06-23) — doc-model 기반 전환**: 요약/번역 입력을 평문(`.txt`) → **구조화 doc-model**(arXiv HTML 결정적 파싱; 표=데이터·수식=LaTeX·그림=webp 참조)로 전환하고, "전문뷰어 표시"를 **자체 리치뷰(FR-18) 1급**으로 격상한다. 명확화 `requirement-verification-questions-docmodel.md` Q1~Q7(**전부 게이트 권장안 D1~D8 + 리치뷰=신규 FR-18**, 2026-06-23) → **FR-12 개정(입력=doc-model·앵커=doc-model id) + FR-17 개정(그림=이미지·표=데이터) + FR-18 신설(자체 리치뷰) + §12 PDF 미저장(D3)·비전 추론 제외 유지(D5) + QT-5 앵커 보강**. 생성·근거화·캐시 **로직 불변**(입력 업그레이드). 게이트 SSOT `construction/plans/docmodel-foundation-pivot-plan.md`(D1~D8) · 스키마 `shared/dtos/docmodel.schema.json`. 영향 유닛: U1(doc-model 생산·캐시)·공유계약·U7(입력 교체)·U5/U7-frontend(리치뷰).
> **개정 (2026-06-23) — Cohere Embed v4.0 마이그레이션 편입**: 명확화 질문 `requirement-verification-questions-v4-migration.md` Q1~Q4 전수 답변(A) 반영 → **FR-21(듀얼 라이트)·NFR-M2(Blue/Green 마이그레이션)·NFR-S2(v4 모델 컷오버)** 등재. 기존 v3 인덱스와의 비호환성을 무중단으로 해결하기 위해 신규 인덱스 백필, 듀얼 라이트, 그리고 Instant Cutover 전략을 확정한다. (FR-18은 develop의 자체 리치뷰가 선점 → 본 요구사항은 FR-21로 재번호.)

> **개정 (2026-06-26) — 재인셉션 페이즈 1 / U1 Corpus 완성형 편입**: PR #220의 재인셉션 차터 D6과 `requirement-verification-questions-u1-corpus.md` Q1~Q12 답변(**전부 A**)을 반영해 **FR-6을 멀티소스 Corpus 생성 파이프라인으로 전면 개정**한다. 범위는 arXiv(HTML 우선→PDF) → Semantic Scholar(PDF→GROBID) → OpenAlex(PDF→GROBID), cross-source dedup, FullText 추출, **수집 시점 eager DocModel 완성형 생성**, DocModel(Block) 기반 청킹/임베딩/OpenSearch 인덱싱, S3 저장, source별 watermark incremental update, scheduler/retry/DLQ, `(paperId, version)` 버전 정합이다. 이 결정은 구 doc-model 피벗 Q7의 **lazy on-demand 기본 결정**을 U1 phase-1 Corpus 범위에서는 대체한다. lazy 빌드 큐는 누락분·재빌드·백필 보강 역할로 축소한다.

> **개정 (2026-06-29 / 번호 정정 2026-06-30) — 신규 유닛 U11(문헌탐색·근거형성 Agent) 편입**: 재인셉션 차터 페이즈 4와 `requirement-verification-questions-literature-evidence-agent.md` Q1~Q10 답변 확정(전수 화랑님, 2026-06-29)을 반영해 **FR-36~38·NFR-P6·QT-8 등재**. _(번호 정정: 본 에이전트는 본래 requirements 초안에서 `[U4]`로 태깅됐으나 **U4는 Library 유닛이 선점** — 설계 레이어 `unit-of-work.md`·`application-design.md`·`services.md` 및 코드 `backend/modules/evidence_agent/`가 일관되게 **U11**로 번호 확정 → requirements/stories의 `[U4]` 태그를 **`[U11]`로 back-sync**, 2026-06-30 — `aidlc-suite-review` PR #280.)_ 근거 출력 계약(EvidenceItem·EvidenceFormationPort)은 `shared/dtos/evidence.schema.json`·`shared/ports/README.md`에 동결(D5 계약 게이트 — 페이즈 5 병렬 잠금 해제). 로그인 필수 온디맨드 대화형 다논문 문헌탐색·근거형성 에이전트(그린필드): 사용자 질의/첨부에 대해 여러 논문을 교차확인해 **핵심 주장·방법·결과 수치·한계**를 논문 비교형+쟁점 오버레이로 정리하고 근거 없으면 기권(FR-5). 세션·결과 owner-scoped 영속·전용 네비 재열람. 연구아이디어 유닛(U12, 페이즈 5)의 하부 Tool(D2·D5).

> **개정 (2026-06-29) — 재인셉션 페이즈 2 / U2 검색 정합·안정화 편입**: 재인셉션 차터 페이즈 2와 `requirement-verification-questions-u2-discovery.md` Q1~Q9 답변(**전부 A**)을 반영한다. PR #236(검색 lite/full 분기·`scope` 계약·멀티소스 TEI 구조화·section 케이싱 정규화)이 develop에 머지된 기정선 위에서: **FR-2 개정**(lite/full scope·DocModel(Block)·멀티소스 인덱스 소비) · **FR-4 개정**(결과 카드에 소스 표기 + 소스 중립 resolvable URL — Q2) · **FR-5 개정**(근거 실재 링크 검증을 arXiv 단일 → 소스 중립으로 일반화 — Q2). **NFR-P1 보강**(LITE=검색 SLA 대상 / FULL=비-SLA 에이전트 프로파일 — Q6). **경계 이월**: DocModel Block 앵커(`blockRefs`)의 검색 외부 노출(Q3)은 페이즈 3·4 계약 동결로, Grounding(Search)는 **U6 단일권위 enforce 유지**·도메인 Validator 레지스트리(Search/Summary/Agent) 재조정은 페이즈 3(D3)으로, reranker·LTR·query expansion 고도화는 페이즈 7로 이월한다. 소스 중립 카드·근거 계약(`search.schema.json` 외부 투영)은 FROZEN 변경이므로 U6 사인오프 동반. 영향 유닛: U2(`discovery`) 핵심·공유계약(`shared/dtos/search.schema.json`·`shared/vector-spec`)·U6(GroundingEnforcementHook·사인오프)·U1(인덱스 생산자).

> **개정 (2026-07-06) — 재인셉션 페이즈 7 / 검색 품질(Cross-Encoder Reranker) 편입**: 재인셉션 차터 페이즈 7(검색 품질 개선)의 실채택 스코프를 **재랭킹 1건**으로 확정한다(경량 경로 — 스코프가 명확해 정식 verification-questions 생략). **FR-3 개정**: retrieve→융합 상위 M 후보를 cross-encoder 재랭킹 모델로 재정렬(순서 품질). rerank는 순서만 바꾸는 SUPPLY 단계로 `Candidate.ranking_score`만 공급하고 정렬은 ranker 단독(공급↔정렬 분리). **NFR-C1 예산 저하(RERANK_OFF/LEXICAL_ONLY) 또는 어댑터 실패 시 융합점수(RRF) 베이스라인으로 fail-soft**(재랭킹은 순위 품질 향상일 뿐 하드 의존이 아니며 응답을 막거나 저하 모드로 만들지 않음). **적용=lite·full 둘 다**(예산 게이트 보호). **재랭킹 폭 M은 보수적 시작값**(retrieve 폭 150은 불변)으로 두고 정량 신호 확보 후 조정한다. **평가 방침(2026-07-06 결정)**: 검색 품질의 **정량 평가(nDCG/MRR/Precision·라벨셋)는 클릭 로그 또는 별도 라벨 데이터가 확보된 이후 수행**한다. 현 단계에서는 **기능 검증(fail-soft·예산 게이트·타임아웃)과 대표 질의 기반의 정성 평가(육안 baseline vs rerank 비교)만** 수행한다(QT-2 정량 게이트는 데이터 확보 시 적용). **명시적 제외(차기 사이클)**: LTR·피드백학습·클릭로그 계측·query expansion 고도화·chunk 전략·embedding 교체 — 사유: 클릭 로그 부재(LTR 선결 데이터 없음)·생성형 LLM 비용/지연·결정성(query expansion). 계약 무변경(내부 랭킹만 — `search.schema.json`·`ranking_score` 등 내부 필드는 SEC-9 비노출). 영향 유닛: U2(`discovery`) 단독.

> **개정 (2026-06-29 / 번호 부여 2026-06-30) — 차별화(novelty) 형성 Agent 요구사항 편입 [U12]**: `requirement-verification-questions-novelty-agent.md`(확정)와 재스코핑 질문지 `requirement-verification-questions-u11-novelty-agent.md`의 답변을 반영한다. _(원답변 파일 `requirement-verification-questions-answer-1.md`은 미커밋 임시 입력으로, 그 답변은 본 개정 본문·위 두 질문지·FR-30~35 정의에 인라인 반영됨 — 끊긴 참조 정정 2026-06-30, `aidlc-suite-review` PR #280.)_ novelty Agent는 설계 레이어에서 **U12(연구아이디어/차별화 유닛)**로 번호 확정(구현 산출물 `construction/novelty-agent/`)이며, 문헌탐색·근거형성 Agent(U11)와 별도 유닛으로 두고, `EvidenceFormationPort`/`SourceRef` 공유계약만 소비한다(Q1~Q3=A). 자연어 입력과 원고 업로드 입력을 모두 지원하며, U2 `full` 검색은 누락 보강/유사 논문 확장에 재사용한다(Q6~Q7=A). v1 외부 검색은 **GitHub + 데이터셋**으로 제한하고 뉴스는 다음 사이클로 둔다(Q8=B, Q11=A는 차기 뉴스 편입 시 보강 근거 역할). 출력은 유사 연구 정리, bounded 실험 아이디어, 실험 계획, 원고 위험 신호, 프론트 진행상태, 선택적 Notion export까지 포함한다(FR-30~35, NFR-P5, QT-10). Security/Resiliency는 적용, PBT는 Partial 적용(Q30=A, Q31=A, Q32=B).

> **개정 (2026-07-01) — Agent Chat Frontend 요구사항 편입 [U13]**: `requirement-verification-questions-agent-chat-frontend.md`와 `requirement-question-answer.md`를 반영해 **FR-40~43·NFR-P7·QT-11 등재**. 프론트 v1은 `/agent` 단일 route와 하단 네비 `에이전트` 탭을 제공하고, 새 채팅에서 `문헌탐색&근거형성` 또는 `novelty` mode를 선택한 뒤 해당 세션에서는 mode 변경을 막는다. 왼쪽 drawer로 과거 세션 목록/새 채팅/삭제를 제공하고, 메시지 사이에 접을 수 있는 탐구 과정 timeline을 표시한다. 파일 첨부는 `+` 버튼과 별도 drawer로 관리하며 PDF/Markdown/TXT만 허용한다. Notion export UI는 v1 제외. Security/Resiliency 적용, PBT는 frontend 로직에도 Full 적용(Q14=A, Q15=A, Q16=B).

> 정량 목표는 **(제안)** 으로 표기 — 리뷰 게이트에서 확정/조정한다. 요구사항 ID는 고정이며 후속 단계에서 참조된다.

---

## 1. 의도 분석 (Intent Analysis)
- **사용자 요청(Prompt 1)**: "Using AI-DLC, our team want to build an application that supports researchers and postgraduates do their research."
- **요청 유형**: 신규 프로젝트(그린필드 재시작)
- **범위 추정**: 시스템 전반(풀스택: 인제스천 파이프라인 + 검색 서비스 + 모바일 웹 프런트엔드 + 계정)
- **복잡도**: 높음(High)
- **명확도(2차 명확화 후)**: 해소됨 — **디스커버리를 핵심 앵커로 하는 풀스택 MVP**로 확정(앵커=디스커버리, 단 계정·인제스천·운영 포함 — "단일 앵커"는 기능 초점이지 범위 축소가 아님; Construction 사이징은 6 유닛 기준)
- **한 줄 요약**: AI 기반·폰 우선의 **연구 논문 디스커버리** 앱 — 자연어 연구 의도를 입력하면 가장 관련성 높은 AI/ML arXiv 논문을 수초 내에, 엄격히 근거화(grounded)된 형태로 제시한다.

## 2. 제품 비전 & MVP 범위
DocSuri v1은 **프로덕션 수준의, 공개 이용 가능한 모바일 웹 앱**으로, 단일 임무는 **AI/ML 연구자를 위한 문헌 디스커버리**다. **핵심 흐름("매직 모먼트")**: 사용자가 자연어 연구 의도(예: "diffusion models for protein structure prediction")를 입력하면 수초 내에 가장 관련성 높은 arXiv 논문 목록을 받으며, 각 결과는 실재하고 인용 가능한 레코드다. 계정으로 검색 저장과 개인 라이브러리 구축이 가능하며, 연구 라이프사이클의 그 외 단계는 v1 범위에서 명시적으로 제외한다(§12).

**앵커**: 디스커버리 & 검색(Q3=A). 합성 Q&A·레퍼런스 관리·작성은 **아님** — 모두 보류.

## 3. 페르소나
- **P1 — 주(Primary): 현역 AI/ML 연구자 / 박사과정.** 특정 세부 분야를 추적하며 깊이·전문 용어·폭·최신성이 필요하다. 성공 = 몰랐던 관련·최신 논문을 폰에서 빠르게 발견.
    - 28세 AI대학원 박사과정 박지훈. 졸업논문을 써야 하는데 이미 엄청나게 많은 논문들과 하루에도 수백 건 이상의 논문들이 쏟아지는 상황에서 자신이 쓰려는 주제가 이미 있는 건지 알 수 없고 방대한 양으로 다 읽어 트랜드를 파악할 수 없다. 주 10시간 이상 연구 문헌을 조사하지만 겨우 찾은 논문조차 재현이 불가능해 실제 실험이나 논문 작성에 투자할 시간이 부족하다.
- **P2 — 부(Secondary): 대학원생 / 박사과정 초기.** 초기 문헌 리뷰 중이며, 동일한 디스커버리 흐름을 더 가벼운 프레이밍으로 활용. v1에서 별도 최적화는 하지 않음.
- **OP — 운영자/유지보수자(비최종 사용자).** 비용 상한/서킷 브레이커 모니터링, AI 인시던트(비용 폭발·할루시네이션·반쪽짜리 결과) 트리아지(RES-11), 인제스천 파이프라인 건강도 관리, 관리자 MFA 보유(SEC-12)·감사 로그 검토(SEC-14)·운영 대시보드 소비(NFR-O1). **근거화/관련도 평가셋(QT-1/QT-2) 구축·관리 책임자.** 성공 = 인시던트가 신호·경보로 탐지되고, 우아하게 저하되며, 지출이 상한을 넘지 않음.

## 4. 기능 요구사항 (Functional Requirements)

| ID | 요구사항 | 인수 기준 |
|---|---|---|
| **FR-1** | 자유 텍스트 자연어 연구 의도를 주 입력으로 받는다. | 단일 질의 입력란; 최대 길이(제안: 500자)까지 허용·검증. |
| **FR-2** | 의도를 해석/확장하여 공유 AI/ML **멀티소스**(arXiv·Semantic Scholar·OpenAlex) **DocModel(Block) 기반** 벡터 인덱스에 대해 **시맨틱 검색**을 수행한다(하이브리드 lexical+vector 허용) *(2026-06-29 개정 — 페이즈 2)*. **검색 폭(scope)**: `lite`(기본·사람 검색창 — 제목+초록 BM25 + 초록 chunk k-NN·저지연) / `full`(에이전트 심층 — 본문 chunk 포함 고recall). | 대표 질의 세트에서 관련 논문이 상위 결과에 등장(평가셋으로 검증 — QT-2); lite는 NFR-P1 SLA 대상, full은 비-SLA(Q6). |
| **FR-3** | 관련도순으로 정렬해 상위 N건을 빠르게 반환한다. *(2026-07-06 개정 — 페이즈 7)* 융합 상위 M 후보를 cross-encoder 재랭킹으로 재정렬해 순서 품질을 높인다. | 상위 N건(제안: 20) 반환, 문서화된 관련도 점수순 정렬. **재랭킹**: 예산 저하/어댑터 실패 시 융합점수(RRF) 순서로 fail-soft(응답 비차단). 정량 품질 평가(nDCG/MRR/라벨셋)는 클릭로그·라벨 데이터 확보 후 수행; 현 단계=기능 검증 + 대표 질의 정성 비교. M은 보수적 시작값. |
| **FR-4** | 각 결과를 **폰 화면**에 최적화해 제시: 제목, 저자, 연도, 식별자, 초록 스니펫, 관련도 신호, **소스 표기(sourceName) + 소스 중립 resolvable 링크** *(2026-06-29 개정 — 페이즈 2/Q2; arXiv=arXiv 링크, 비-arXiv=sourceUrl/DOI 링크)*. | 360–430px 너비에서 가로 스크롤 없이 완전히 가독·조작 가능; 비-arXiv 결과도 실재 링크로 연결(FR-5). |
| **FR-5** | **엄격한 근거화(strict grounding)** *(2026-06-29 개정 — 페이즈 2; 페이즈 3 D3 통합 확정)*: 노출되는 모든 논문은 인덱스의 실재 레코드; AI 생성 텍스트(관련도 설명/요약)는 검색된 논문에서만 도출; 근거가 없으면 날조 대신 **기권(abstain)**("관련 논문 없음"). 실재 링크 검증은 **소스 중립**(arXiv=arxivUrl, 비-arXiv=sourceUrl/DOI; Q2). **Grounding Framework 통합(D3 — 페이즈 3 Q2 확정)**: 단일 철학(fail-closed·기권≠빈결과·날조0·verdict={pass/block/abstain})과 **공유 추상 Validator 인터페이스 + 레지스트리**(Search/Summary/Agent) 아래, **검증 로직은 도메인별**이다 — `GroundingEnforcementHook.enforce`(candidate↔retrieved record set)는 **검색 한정 U6 단일권위(FROZEN, 시그니처 무변경)**, **요약은 U7 자체 결정론 Validator**(요약↔단일 논문 refined source = 문서충실도 검증; 검증 종류가 달라 별도), Agent Validator는 페이즈 4 자리만 확보. enforce 호출 지점은 각 도메인 seam 유지(검색=U6 게이트웨이, 요약=U7 오케스트레이터). DocModel Block 앵커(`blockRefs`)는 근거 매칭에 **내부 활용**하되 검색 결과 외부 노출은 페이즈 3·4로 이월(Q3). | 평가셋 전반에서 날조 논문/인용 0건; 코퍼스 밖 질의에 기권 경로 동작; 비-arXiv 결과도 소스별 실재 링크로 검증. (QT-1) "단일권위"의 의미는 **검색 grounding 한정**으로 명문화(`shared/ports.md`); 도메인 Validator 추상·레지스트리는 shared 계약 PR + U6 사인오프. |
| **FR-6** | **Corpus 생성 파이프라인 [U1]**: AI/ML 논문을 멀티소스로 수집하고, 소스 우선순위 기반 중복 제거 후 FullText→DocModel 완성형→Chunk→Embedding→OpenSearch/S3 저장까지 자동 구축한다. 수집 우선순위는 **arXiv(HTML 우선, 없으면 PDF) → Semantic Scholar(PDF→GROBID) → OpenAlex(PDF→GROBID)** 이며, dedup 키는 **DOI → arXiv id → 정규화(title+1저자+연도)** 순으로 판정하고 상위 소스/품질 좋은 전문을 승자로 삼는다. DocModel은 Section/Block·표(rows/cols)·수식(LaTeX/MathML)·그림 AssetRef·Provenance/SourceTier를 포함하는 구조 완성형이며, 비전 추론은 제외한다. | 초기 코퍼스는 **최근 AI/ML 1년·OA/인덱싱 허용 라이선스·eager 비용 상한 내**로 구축한다. 수집 시점에 `(paperId, version)`별 DocModel을 eager 생성하고, **DocModel(Block) 기반 청킹**(Block 경계 존중+길이 상한+섹션 컨텍스트)으로 Cohere Embed v4/specVersion v2 임베딩을 생성한다. DocModel 기반 신규 index generation/alias를 블루/그린으로 만들고 컷오버한다. source별 watermark로 incremental update하고, scheduler·단계별 retry·DLQ·재처리 경로·ObservabilityHub `emitMetric`/`emitLog` 실패 신호를 제공한다. |
| **FR-7** | **사용자 계정**: 공개 셀프 가입, 로그인, 로그아웃, 인증 세션. | 신규 사용자가 셀프 가입·로그인·세션 유지 가능; 자격증명은 SEC-12 준수. |
| **FR-8** | **검색 저장**: 질의 저장, 목록, 재실행, 삭제(사용자별 비공개). | 저장 검색이 세션 간 지속, 소유자에게만 노출(SEC-8). |
| **FR-9** | **라이브러리 저장**: 논문을 개인 라이브러리에 추가/삭제·목록. | 라이브러리가 사용자별 지속·비공개(SEC-8). |
| **FR-10** | 사용자별 **검색 이력**. | 최근 질의가 목록·재실행 가능, 사용자에게 비공개. |
| **FR-11** | **빈 결과 & 실패 UX**: 빈 검색, 업스트림(arXiv/LLM/인덱스) 장애, 저하(degraded) 모드에 대한 명확한 구분 상태. | 각 상태가 구체적·비기술적 메시지 표시; 빈 화면·스택 트레이스 없음; 오류 시 fail closed·일반화된 프로덕션 에러(SEC-9, SEC-15, NFR-R1). |
| **FR-12** | **AI 요약(요약 액션) [U7]** *(2026-06-29 앵커 입도 정정 — 페이즈 3/Q4)*: 검색 결과 카드에서 선택한 **단일 논문의 구조화 doc-model**(전문을 arXiv HTML 결정적 파싱한 섹션/블록·표=데이터·수식=LaTeX·그림 참조; 평문 아님 — 2026-06-23 개정)을 페르소나 질문 기반 **구조화 요약**(핵심주장·기여·방법·결과·한계·재현성)으로 생성. 요약 *수준* 선택(전문가용/입문자용). 각 항목에 원문 근거 **앵커** 부기 — 현행 앵커 계약은 `{field, target∈{section\|table\|figure}, span(원문 인용), label(예: "Section 3.1")}`이며 **검증 통과 앵커(kept_anchors)만 노출**. (DocModel **block-level id** 정밀 앵커는 페이즈 4 evidence 계약과 함께 — 후속 이월.) | 선택 논문 1편에 구조화 요약 반환; 입력은 doc-model(표 숫자·수식이 요약·근거화에 가시); 각 주장에 검증 가능한 원문 앵커("출처 보기" → target/label 실재성, FR-18 리치뷰로 점프); 근거 없으면 날조 대신 기권(FR-5·QT-5); 수준(전문/입문) 선택이 출력에 반영. 온디맨드(NFR-P2)·캐시+S3 영구저장. 생성·근거화·캐시 로직 불변(입력만 업그레이드). |
| **FR-13** | **한국어 번역(번역 액션) [U7]** *(2026-06-24 본문 번역 구조화, PR-2; 2026-06-29 정합 확인 — 페이즈 3/Q6)*: 선택한 논문의 **초록 번역**(scope=abstract, 기본 — Metadata Abstract 사용) 또는 **전문(全文) 번역**(scope=full — DocModel(v1) 사용)을 한국어로 번역. 전문 번역의 출력은 **source와 동일한 구조화 형식**(번역본 doc-model — 섹션 트리·문단·표/그림 캡션 단위 번역; 표 셀·수식 LaTeX·코드·block/section id·그림 assetRef는 원어/원본 보존)으로, 원본 본문과 **동일한 리치 뷰어**로 렌더. 도메인 용어집(미번역 리스트 포함) 적용으로 전문용어 일관. | 초록/전문 한국어 번역 반환; 전문 번역은 구조화(DocModel(v1) 미러·동일 구조/id 재조립)되어 동일 뷰어로 표시(BR-S18); 용어집의 미번역 용어(모델명·약어)는 영어 유지; 표 숫자·수식은 번역하지 않고 보존(D8); 긴 본문은 섹션별 map-only로 처리하고 진행(pending) 표시·폴링(게이트웨이 타임아웃 회피), 초극단(>입력상한)은 거절; 사용자 용어 선호 저장 시 이후 일관 적용(SEC-8). **온디맨드**(버튼 클릭 시 eager s3 doc-model 번역; NFR-P2)이며 **번역본은 S3 영구저장+Redis 캐시**(immutable key, 동일 키 재사용) — 요약·초록번역·전문번역 3종 모두 동일. |
| **FR-14** | **요약/번역 개인화 [U7]** *(2026-06-29 개정 — 페이즈 3/Q9; 뷰 프리셋·커뮤니티 용어집 폐기)*: persona 생성 변형(전문가용/입문자용)·용어집(P1 도메인 시드 + P2 개인 오버라이드). **용어집 적용**: 기본은 번역 출력 위 **결정론적 post-substitution 덮어쓰기**(LLM 재호출 없음·전체단어·긴것우선·한국어 조사 보존·멱등; `prompt_enforced=False`), 옵션으로 LLM 프롬프트 강제(`prompt_enforced=True`). | persona는 **요약 전용** 논문당 최대 2벌(전문/입문) 생성(번역은 persona-agnostic 단일); 개인 용어 선호가 사용자별 지속(SEC-8), 개인 용어집 조회 실패 시 seed-only로 저하(전체 기권 안 함). **뷰 프리셋(코드 부재)·커뮤니티 공유 용어집(P3)은 폐기**, 자유입력 per-user는 범위 제외(§12). |
| **FR-15** | **각주 트리 / 인용 그래프 [U8]**: 논문 상세보기 페이지에서 선택 논문의 backward references(이 논문이 인용한 논문)를 트리로 표시한다. 기본 1-hop, 사용자 펼침 시 최대 2-hop, 화면당 최대 50노드. | 논문 상세보기 페이지에 요약·초록 번역·전문 번역·각주 트리 4개 액션 중 각주 트리 진입점이 존재한다(상세보기 FE 자체는 별도 분기 책임). 각 노드는 제목·연도·인용수를 표시한다. 중복 노드는 "이미 표시됨"으로 접고, unresolved 항목은 확정 노드로 승격하지 않는다. |
| **FR-16** | **인용 노드 저장/연동 [U8]**: 각주 트리 노드는 라이브러리 저장 액션과 연결된다. 전체 인용 그래프 기능은 로그인 필수이며 U3/U6 인증·인가 경로를 통과한다. | 모든 표시 노드에서 "라이브러리에 저장" 가능; 저장 시 U4 `LibraryItemMeta` 스냅샷을 재사용한다. 외부 인용 API 장애 시 캐시된 snapshot을 우선 표시하고, 없으면 루트 논문은 유지한 채 "인용 정보를 불러올 수 없음" 상태를 보여준다. |
| **FR-17** | **그림·표 표시 (멀티모달) [U1/U7/U5]** *(2026-06-23 개정 — 표=데이터)*: 인제스천/doc-model 생성 시 **그림은 이미지 자산(webp)으로 추출·저장**(arXiv 소스 가용성 혼합 — 소스 있으면 구조화 추출, 없으면 PDF 페이지 크롭 폴백)하고, **표는 크롭 이미지가 아니라 구조화 데이터(rows/cols)로 doc-model에 싣는다**(D8 — 표 숫자가 요약·근거·에이전트에 가시; 텍스트 에이전트 깜깜이 해소). 비-HTML(~9%) 폴백 시에만 표 크롭 이미지. 자체 리치뷰(FR-18)·상세보기에 표시. 이미지 **비전 추론은 본 범위 제외**(차기 사이클·에이전트 on-demand, D5). | 원문에서 추출된 **실재 자산만** 표시(생성·합성 금지 — FR-5 정신); 표는 데이터로 렌더(표 컴포넌트, FR-18); OA 미허용 논문은 자산/리치뷰 미노출 + arXiv 링크아웃(BR-SF-11); 그림 자산은 **단기 만료 서명 URL**로 서빙(SEC-9/12 — doc-model엔 `assetId` 참조만, 픽셀·키 비노출); 표·그림 앵커("출처 보기")는 doc-model id로 연결(FR-12/18); 이미지는 lazy-load·플레이스홀더·치수 예약 렌더(모바일 성능, 검색 SLA NFR-P1 무관). 온디맨드 표시. |
| **FR-18** | **자체 리치뷰 (doc-model 렌더) [U1/U7/U5]** *(2026-06-23 신규 — D4; 2026-06-26 U1 Corpus D6 정정)*: 논문 **doc-model**을 앱 안에서 콘텐츠 충실하게 재렌더하는 **목적지 표면**(요약/번역/주석/에이전트 통합 + 로그수집·개인화 표면). 섹션 **목차(TOC)·앵커 점프**, **수식 KaTeX/MathJax(LaTeX)**, **표 구조화 컴포넌트(rows/cols)**, **그림 webp**(FR-17 자산 재사용). **PDF.js 픽셀 재현 아님**(arXiv HTML/GROBID 기반 콘텐츠 재렌더). U1 phase-1 Corpus에 편입된 논문은 **수집 시점 eager 생성 + `(paperId, version)` 캐시**가 기본이며, lazy/on-demand 빌드는 누락분·재빌드·백필·phase-1 밖 논문 보강 경로로만 남긴다. | phase-1 코퍼스 논문은 첫 열람 전 DocModel이 준비되어야 하며, 누락 시 빌드 큐로 보강하고 `building`/재시도 상태를 노출한다. version 변경 시 DocModel·청크·인덱스·S3를 같은 버전으로 재빌드/재색인한다. 리치뷰가 목차·수식·표·그림·앵커를 렌더; 요약 출처 앵커(doc-model id) 클릭 시 해당 위치로 스크롤·하이라이트; **라이선스 미허용 → 리치뷰 미제공 + 원문 링크아웃**(BR-SF-11); 외부 콘텐츠 이스케이프·신뢰 렌더러(KaTeX·표 컴포넌트) 경유(원시 HTML 주입 금지, SEC-5); PDF 원문 저장·다운로드 없음(§12, D3). |
| **FR-19** | **개인 관심사 프로필 집계 [U9]**: 행동 이벤트를 기반으로 사용자별 관심 arXiv 카테고리, 키워드 가중치, 저장/반복 조회 논문, 요약 persona 선호, 번역 scope 선호, 용어집 버전을 집계한다. | 원본 행동 이벤트는 기본 90일 보관 후 삭제하고, 집계 프로필만 유지한다. 사용자는 개인화 켜기/끄기, 행동 로그 삭제, 개인화 프로필 초기화를 할 수 있다. 프로필 갱신은 가벼운 온디맨드/배치 집계로 수행하며 실시간 ML 파이프라인은 만들지 않는다. |
| **FR-20** | **개인화 적용 [U9]**: 기존 검색 관련도 점수는 유지하고 사용자 관심사 기반 작은 boost로 rerank한다. 요약/번역은 최근 선택을 기본값으로 기억하되 사용자가 매번 바꿀 수 있게 한다. | 검색 결과에 과도한 순위 변경 없이 개인화 boost를 적용하고, "내 관심 주제 반영" 정도의 짧은 표시와 개인화 끄기 토글을 제공한다. v1은 별도 추천 논문 목록을 만들지 않는다. 개인화 저장/분석 실패 시 기본 검색·요약·번역으로 저하한다. |
| **FR-21** | **인제스천 파이프라인 v4 듀얼 라이트 (마이그레이션) [U1]** *(구 FR-18 — develop 리치뷰와 충돌로 재번호)*: 마이그레이션 기간 동안 신규 문서는 기존 v3 인덱스(`docsuri-corpus-v1`)와 신규 v4 인덱스(`docsuri-corpus-v2`) 양쪽에 모두 기록(dual-write)된다. | 마이그레이션 완료 시점까지 두 인덱스 모두 최신 상태 유지. |
| **FR-39** | **행동 이벤트 기록 [U9]** *(2026-06-23 신규 — 본래 FR-18; doc-model 자체 리치뷰가 FR-18 선점으로 2026-06-30 **신규 FR-39** 재번호; FR-22~25는 폐기된 구 research-agent 초안 ID라 회피)*: 의미 있는 사용자 행동(검색 실행, 결과 클릭, 라이브러리 저장/해제, 요약/번역 액션, persona/scope 선택)을 owner-scoped 행동 이벤트로 **비차단 기록**한다. 단순 hover·scroll·체류시간·임의 클릭은 기록하지 않는다(§12 U9 제외). | 행동 이벤트는 사용자별 비공개(SEC-8)·기본 90일 보관 후 삭제(집계 프로필만 유지, FR-19); 이벤트 기록 저장소 실패는 본 기능 요청 실패로 승격하지 않고 비개인화 경로로 저하(NFR-P4·NFR-R*); 이벤트 DTO 라운드트립·dedupe key 안정성 자동 테스트(QT-7). |
| **FR-26** | **비밀번호 재설정(분실 복구) [U3]** *(2026-06-24 신규 — 계정 프로덕션화 Q1-A/Q6-A)*: 로그인 불가 사용자가 이메일로 비밀번호를 자가 재설정한다. | 재설정 요청 시 **Resend** 이메일로 **단일 사용·30분 만료** 토큰 링크 발송; 토큰 검증 후 새 비밀번호 설정(BR-A1 정책 재적용); 성공 시 **해당 계정 전 세션 무효화**(BR-A8); **계정 열거 방지** — 가입/상태와 무관하게 항상 동일 일반 응답(SEC-9); 요청에 레이트 리밋(SEC-11); 사용·만료 토큰 재사용 거부. _↪ 토큰 저장·만료 메커니즘 = Functional/NFR Design._ |
| **FR-27** | **소셜 로그인 (OIDC) [U3]** *(2026-06-24 신규 — Q1-B/Q3=Google/Q4-A · 2026-06-30 개정 — ORCID 추가, `requirement-verification-questions-orcid-login.md`)*: 외부 신원공급자로 가입/로그인한다. **프로바이더 = Google · ORCID**(GitHub·Apple 차기 사이클). | OIDC Authorization Code 흐름 — **`state`/`nonce`로 CSRF·replay 방어**(SEC-5/SEC-12); **(이메일 제공 프로바이더, 예: Google)** 프로바이더 **검증된 이메일**을 정규화해 기존 계정에 **자동 연결**, 미존재 시 **ACTIVE 계정 신규 생성**(이메일 PENDING 우회, BR-A9); 프로바이더 **미검증** 이메일은 자동 연결 금지(BR-A9 — 계정 탈취 방어); **(이메일 미제공 프로바이더, 예: ORCID — OIDC가 이메일 클레임을 반환하지 않음)** `(provider, subject)` 신원으로 **ACTIVE 계정 신규 생성**(`accounts.email` NULL 허용·자동 연결/병합 없음, BR-A13), id_token은 **로컬 JWKS/RS256** 검증(tokeninfo 엔드포인트 부재); 성공 시 기존 로그인과 **동일한 secure/httpOnly/sameSite 세션 쿠키** 발급(SEC-12); 부여 권한은 항상 **USER**(권한상승 금지); 프로바이더 장애 시 명시적 에러(NFR-R1). 연구자 ORCID iD는 마이페이지(U10)에 실표시(`GET /mypage/orcid-profile`). _↪ OIDC 라이브러리·연결 테이블(provider/subject)·이메일 nullable 마이그레이션·시크릿 보관 = Functional/NFR/Infra Design._ |
| **FR-28** | **계정 라이프사이클 (자가 관리) [U3]** *(2026-06-24 신규 — Q1-C/Q5-A)*: 로그인 사용자가 ① 비밀번호 변경 ② 이메일 변경 ③ 계정 삭제(탈퇴)를 수행한다. | ① **비번 변경** = **현 비밀번호 재인증** 후 신 비번(BR-A1) + 전 세션 무효화; ② **이메일 변경** = **신 주소 재검증(PENDING 링크) 완료 전 로그인 식별자에 미반영**(BR-A10) + 중복 이메일 거부; ③ **계정 삭제** = **소프트 삭제(즉시 비활성·전 세션 무효화) + 유예 N일 후 비동기 영구 파기**(BR-A11) + **owner-scoped 데이터 캐스케이드 파기**(U4 라이브러리/저장검색·U2 이력, SEC-8); 모든 작업 감사 로그(SEC-14)·일반화 에러(SEC-9); 비동기 파기 잡은 멱등·재시도·DLQ(RES). _↪ 캐스케이드·유예 잡·DB 마이그레이션 = Functional/Infra Design._ |
| **FR-36** | **대화형 문헌탐색·근거형성 세션 [U11]** *(2026-06-29 신규)*: 로그인 필수 사용자가 채팅 형식으로 연구 질문을 입력하면 에이전트가 다논문 교차확인을 수행해 근거를 비교 정리한다. 하단 네비 전용 진입·세션 리스트·세션 내 멀티턴(이전 턴 근거·대상 논문 맥락 누적)을 지원한다. | 로그인 필수(SEC-8). 채팅 진입 시 문헌탐색·근거형성 모드 선택 가능. 후속 질문("그 중 한계가 가장 적은 건?")에 이전 맥락을 유지한 응답 반환. 하단 네비에서 전용 진입, 세션 리스트에서 기존 세션 재열람 가능. |
| **FR-37** | **다논문 근거형성 — 추출·비교·기권 [U11]** *(2026-06-29 신규)*: 사용자 질문·명시 paper 집합·첨부 문서를 대상으로 다논문 교차확인 후 **핵심 주장·방법·결과 수치·한계**를 추출(C-2 경계: 논문 원문 기반 추출만, 생성 산문 금지)하고 **논문 비교형 + 쟁점 오버레이**(일치/상충 표시)로 정리한다. 근거 없으면 날조 대신 **기권**(FR-5). 결과는 `EvidenceItem{ statement, supporting[], conflicting[] }` 계약으로 반환하며 연구아이디어 유닛(U12)이 Tool로 소비한다(D5). | scope=auto(자동 검색)·explicit(명시 paper 집합)·mixed(혼합) 지원. 첨부는 doc-model 파이프라인 재사용(형식/크기 한도는 FD 이월). 코퍼스는 owned arXiv AI/ML 인덱스만(v1). confidence 제외(FR-5 그라운딩·환각 위험). conflicting[] 비어 있어도 성공 응답 가능. 근거 0건·범위 밖: state=abstain + 비기술 abstainReason(SEC-9, 내부 위반 상세 비노출). 긴 다논문 분석은 비동기 잡 오프로드 + 진행 상태 폴링(NFR-P6). 계약 SSOT: `shared/dtos/evidence.schema.json`. |
| **FR-38** | **근거형성 결과·세션 영속 및 사용자 제어 [U11]** *(2026-06-29 신규)*: 대화·결과·첨부 원본을 owner-scoped로 영속하고 전용 네비 메뉴·세션 리스트 재열람을 제공한다. 사용자는 세션 삭제·전체 초기화를 직접 제어할 수 있다. | 세션·결과·첨부는 로그인 사용자별 비공개(SEC-8). 세션 리스트에서 기존 세션 재열람 가능. 사용자가 세션 삭제·전체 초기화 수행 가능. 계정 삭제 시 owner-scoped 데이터 캐스케이드 파기(U3 AccountDeleted 구독, FR-28 준용). 보관 기간 수치·파기 잡 상세는 NFR/Infra Design 이월. |
| **FR-29** | **인증 입력 계약 견고화 & 에러 표면화 [U3/U5]** *(2026-06-24 신규 — Q1-D/Q7-A; 현 로그인 장애 근인 해소)*: 공개 인증 엔드포인트의 입력 계약 취약성으로 인한 전면 로그인 장애를 제거한다. | 공개 인증 엔드포인트(login/signup/reset 등)는 **알 수 없는 추가 바디 필드를 거부(422)하지 않고 무시**(필수 필드만 강제, BR-A12) → 프런트/백 버전 스큐가 로그인을 **전면 차단하지 못함**; 프런트는 4xx/422를 **구체·비기술적 메시지**로 표면화(빈 화면·원시 JSON·옵스큐어 generic 금지, SEC-15·NFR-R1·FR-11 정신); 인증 메일 재발송 UX 제공; 자격증명 비노출(SEC-12) 유지. _↪ SSOT 스키마 `additionalProperties` 변경·재생성(§5-B) = Construction._ |
| **FR-30** | **차별화(novelty) 형성 Agent 입력·오케스트레이션 [U12]**: 자연어 연구 의도와 업로드 원고(PDF/Markdown/TXT)를 입력으로 받는다. 문헌탐색·근거형성 Agent와는 별도 유닛이며, novelty Agent는 upstream `EvidenceFormationPort` 결과와 `SourceRef`만 소비한다. | 자연어 입력도 `form_evidence`를 선행 호출한다. 업로드 문서는 공통 ingestion/doc-model 파이프라인 또는 문헌탐색·근거형성 Agent가 파싱하고, novelty Agent가 직접 파서/근거형성 로직을 재구현하지 않는다. DOCX는 신규 파서 의존성이 필요하므로 v1에서 제외하고 차기 사이클 후보로 둔다. |
| **FR-31** | **novelty 검색·외부 탐색 [U12]**: U2 `full` 검색을 재사용해 내부 Corpus 유사 연구를 확장 검색하고, v1 외부 탐색은 Agent-Browser 기반 GitHub 검색과 관련 데이터셋 검색으로 제한한다. | EvidenceFormationPort 결과를 1차 근거로 삼고 U2 `full` 검색은 누락 보강/유사 논문 확장에 사용한다. novelty 전용 인덱스나 별도 랭킹 로직을 만들지 않는다. GitHub는 구현체·baseline·benchmark·license 단서만 추출하고 품질 점수/재현 가능 판정은 하지 않는다. 데이터셋은 이름·URL·라이선스·접근성·태스크·metric 후보를 산출한다. 뉴스 검색은 v1 제외. |
| **FR-32** | **유사 연구 정리와 bounded 차별화 아이디어 [U12]**: 기존에 완료된 유사 아이디어 논문을 표로 정리하고, 근거 기반 차별화 실험 아이디어 후보를 제안한다. | 유사 논문별 문제정의·방법·데이터셋·결과·한계·겹치는 점·SourceRef를 제공한다. "새로움 확정", novelty 점수, 논문화 가능성 판정은 하지 않는다. 아이디어는 기존 연구 한계와 코드/데이터셋 근거 안에서 bounded 제안으로 제한한다. |
| **FR-33** | **실험 계획 작성 [U12]**: 선택된 차별화 후보에 대해 실험 계획을 작성한다. | 실험 계획은 가설, 차별화 포인트, baseline, 데이터셋, metric, 실험 절차, 리스크, 필요한 구현/리소스, 근거 링크를 포함한다. 코드 skeleton이나 실행 스크립트 생성은 v1 범위 밖이다. |
| **FR-34** | **원고 위험 신호 [U12]**: 업로드 문서 경로에서 내부 Corpus 대비 문장/문단 유사도와 AI 어투 위험 신호를 표시한다. | 법적 표절 판정이나 AI 작성 확률 확정 판정이 아니라 검토 필요 신호로 표시한다. false positive 가능성을 UI에 명시한다. 위험 신호는 별도 "원고 위험 신호" 섹션으로 분리하며 novelty 추천/실험 계획 생성을 차단하지 않는다. |
| **FR-35** | **novelty Agent 진행상태·저장·Notion export [U12]**: 에이전트 탐구 과정을 프론트에 단계별로 출력하고, 결과를 owner-scoped로 내부 저장한 뒤 사용자 승인 시 Notion으로 export한다. | 진행상태 enum은 `queued`, `retrieving_corpus`, `searching_external`, `summarizing_prior_work`, `checking_similarity`, `forming_ideas`, `planning_experiment`, `exporting_notion`, `completed`, `failed`, `degraded`를 포함한다. UI는 현재 tool, 검색 질의, 발견 출처 수, 부분 결과, 실패/저하 상태를 스트리밍 또는 폴링으로 표시한다. 내부 DB/S3에 세션·입력 참조·단계 이벤트·최종 결과·export 상태를 저장하고 삭제/초기화를 제공한다. Notion은 사용자별 OAuth/명시 연결, 토큰 암호화 저장, 미리보기 후 승인 export, 연결 해제/삭제를 제공한다. |
| **FR-40** | **Agent Chat Frontend 진입·모드 선택 [U13]** *(2026-07-01 신규)*: 하단 네비 가운데 `에이전트` 탭을 추가하고 `/agent` 단일 route에서 새 채팅을 시작한다. 채팅 시작 시 `문헌탐색&근거형성` 또는 `novelty` 중 하나를 선택하며, 선택 직후 채팅 입력창을 활성화한다. | route는 `/agent` 하나로 유지한다. 선택된 mode는 세션에 고정되며, 변경 버튼을 누르면 현재 세션 변경이 아니라 새 세션 생성으로 유도한다. 모바일/데스크톱 레이아웃은 기존 responsive + phone preview 구조와 충돌하지 않는다. |
| **FR-41** | **Agent 세션 drawer와 멀티턴 채팅 [U13]**: 화면 왼쪽 위 메뉴 버튼으로 세션 drawer를 열어 세션 목록, 새 채팅, 삭제를 제공한다. 세션 목록에는 제목, agent mode, 마지막 업데이트 시간, 최종 상태를 표시한다. | 과거 세션을 선택하면 해당 대화와 mode를 로딩한다. 사용자와 assistant 메시지는 멀티턴으로 유지된다. 프론트 v1은 mock transport를 먼저 제공하고, 실제 API는 `/api/novelty/*`와 evidence agent API seam에 맞춘다. |
| **FR-42** | **탐구 과정 timeline 표시 [U13]**: 에이전트의 탐구 과정을 채팅 메시지 사이에 접을 수 있는 step timeline 블록으로 표시한다. | timeline은 단계, tool call 입력/출력 요약, source 종류, 검색 질의 요약, 발견 수, degraded/failed 사용자용 사유를 표시한다. 내부 원문 payload, 민감 로그, 자격/토큰/내부 오류 상세는 노출하지 않는다(SEC-9/15). |
| **FR-43** | **Agent 채팅 파일 첨부와 상태 UX [U13]**: 채팅 입력바 왼쪽 `+` 버튼으로 별도 첨부 drawer를 열고 PDF, Markdown, TXT 파일을 관리한다. 실패와 저하 상태는 명확히 표시하고 재시도 경로를 제공한다. | 전송 전 첨부 삭제가 가능하다. 지원하지 않는 파일 형식은 클라이언트에서 차단하고 사용자용 메시지를 표시한다. 실패는 상태 화면과 재시도/새 채팅 버튼, degraded는 부분 결과 상단의 출처별 저하 banner로 표시한다. Notion export UI는 v1에서 제외한다. |

## 5. 비기능 요구사항 (Non-Functional Requirements)

**성능(Performance)**
- **NFR-P1** 검색 지연: **P50 < 3s, P95 < 8s** 종단(질의 → 정렬 결과). *(제안)* LLM 인-루프/콜드 스타트 영향으로 공격적일 수 있어 NFR Requirements에서 워밍·동시성 가정과 함께 **검증 대상**(콜드 스타트 포함/제외 명시). **[페이즈 2 보강 — Q6]** SLA 대상은 **`lite` scope(사람 검색창 기본)** 이며, **`full` scope(에이전트 심층 검색)는 비-SLA**(요약/에이전트 온디맨드 프로파일에 준함). lite/full 분기는 #236에서 랜딩.
- **NFR-P2 [U7]** 요약/번역(FR-12/13)은 **온디맨드 액션**으로 검색 SLA(NFR-P1) **대상이 아니다**. 캐시 히트는 즉시 응답; 첫 생성은 **스트리밍(빠른 TTFB)** 으로 체감 관리(초장문 map-reduce만 비동기 잡). *(제안 — 구체 TTFB 지표는 NFR Requirements에서 확정.)*
- **NFR-P3 [U8]** 각주 트리(FR-15/16)는 **온디맨드 액션**으로 검색 SLA(NFR-P1) 대상이 아니다. 캐시 히트는 P50<500ms(제안), 첫 외부 조회는 명시적 로딩/부분 결과를 허용한다.
- **NFR-P4 [U9]** 개인화 기록·집계는 검색/요약 핵심 응답을 지연시키지 않는다. 행동 이벤트 기록 실패는 사용자 요청 실패로 승격하지 않고 기본 비개인화 경로로 저하한다.
- **NFR-P5 [U12]** novelty Agent는 온디맨드 비동기 작업으로 처리한다. API는 job 생성/상태 조회/취소만 담당하고, 별도 Agent Worker가 U2 `full` 검색, Agent-Browser, LLM, Notion MCP 호출을 수행한다. 검색 SLA(NFR-P1) 대상이 아니며, 재접속 후 상태 조회·취소·부분 결과 표시를 제공한다.
- **NFR-P6 [U11]** 근거형성(FR-37)은 **온디맨드 액션**으로 검색 SLA(NFR-P1) **대상이 아니다**. 짧은 질의는 **스트리밍 우선**(빠른 TTFB)으로 체감 응답 제공; 긴 다논문 분석은 **비동기 잡**(U7 잡 패턴 재사용) + 진행 상태·부분 결과 폴링으로 타임아웃을 방지한다. *(제안 — 구체 TTFB·잡 전환 임계는 NFR Requirements에서 확정.)*
- **NFR-P7 [U13]** Agent Chat Frontend는 채팅 입력, mode 선택, 세션 drawer, timeline expand/collapse가 즉시 반응해야 한다. backend가 mock/real 어느 쪽이든 로딩·실패·degraded 상태는 화면 전환 없이 표시하고, 긴 작업은 polling/streaming seam으로 부분 진행을 갱신한다.
**확장성 & 비용(Scalability & Cost)**
- **NFR-S1** 근시일 규모: 등록 사용자 수백 명 내외(제안: ~3,000 상한), 동시 수십 명(제안: ~50); 아키텍처는 재설계 없이 **저(低)천 명대까지 확장** 가능해야 함. *(제안)* 확장 헤드룸은 **아키텍처 요건**이며, NFR-C1 비용 상한은 **현재 티어 기준 근시일 가드레일**로 규모 증가 시 재설정한다(상한을 그대로 유지하지 않음).
- **NFR-S2** 임베딩 모델 v4 컷오버: 검색 및 인제스천에 사용하는 임베딩 모델을 `embed-multilingual-v3.0`에서 `embed-multilingual-v4.0`(차원: 1024)로 업그레이드한다. U2 검색 API는 신규 인덱스 준비 완료 시 A/B 테스트 없이 즉각 컷오버(Instant Cutover)된다.
- **NFR-C1** **월 비용 상한(hard cap) (제안: $300/월)**. **준실시간 지출/사용량 텔레메트리 + 임계 경보(제안: 80% 도달 시 경보)** 로 상한 초과 **이전에** 우아하게 저하하는 서킷 브레이커(제안: 100% 도달 전 LLM 리랭킹 비활성화 → lexical 검색 폴백). 이 텔레메트리/경보가 **RES-11(a) 비용 폭발 탐지 신호**를 제공한다(월 단위 청구가 아닌 인트라데이 폭주 포착). 이전 사이클의 CostGuard 패턴 계승. **[U1 Corpus 보강]** eager DocModel·GROBID·임베딩·OpenSearch/S3 저장은 사용량 비례가 아니라 코퍼스 전량 비용이므로, phase-1은 **최근 AI/ML 1년·OA/인덱싱 허용 라이선스·명시적 빌드 예산**으로 제한하고, 비용 임계치 도달 시 수집 우선순위(최신성/인용·팀 지정 seed) 밖 작업은 보류·DLQ/백필 큐로 이월한다. GROBID/임베딩/OpenSearch bulk/S3 저장 사용량은 U1 별도 비용 라인으로 계상한다. **[U7 보강]** 요약(FR-12)은 Sonnet 호출로 비용표에 없던 신규 라인(건당 ≈$0.1~0.2)이나, 온디맨드+영구저장으로 "distinct 논문×1회"만 과금되어 bounded → **기존 $1,600 상한 내 흡수**하되 U7 비용을 텔레메트리 **별도 라인으로 계상**하고 U6 CostGuard 게이트(예산 초과 시 요약 일시 기권, FR-11) 적용. **[U8 보강]** citation API는 U6 레이트리밋/CostGuard 신호와 U8 전용 쿼터 카운터를 사용하며, 임계 초과 시 캐시만 제공하거나 일시 기권한다. Infrastructure Design 비용표에 U1/U7/U8 라인 추가.
  - **[novelty Agent 보강]** U6 CostGuard와 rate limit을 재사용하고, U2 `full` 검색·LLM·tool call·Agent-Browser·Notion MCP에 per-job budget을 둔다. 초과 시 전체 실패가 아니라 부분 결과와 `degraded` 상태를 반환한다. novelty Agent 전용 CostGuard는 만들지 않는다.

**가용성 & 신뢰성(Availability & Reliability)** *(주 품질 속성: Q14=C)*
- **NFR-A1** 가용성 목표 **~99.5%**, 단일 리전 멀티 AZ. *(제안)*
- **NFR-R1** **조용한 오답 금지(no silent wrong answers)**: 모든 실패는 명시적 상태로 표면화; 시스템은 fail closed(SEC-15).
- **NFR-R2** 업스트림 장애(arXiv API, LLM, 벡터 스토어) 시 우아한 저하: 명시적 타임아웃, 폴백 경로, 저하 모드 메시지(RES-10).
- **NFR-R3 [U12]** novelty Agent 외부 의존성(U2 `full`, EvidenceFormationPort, Agent-Browser, GitHub, 데이터셋 사이트, Notion MCP, LLM)은 source별 실패/저하를 분리한다. 한 source 실패가 전체 job 실패로 전파되지 않으며, 성공한 source만으로 부분 산출물을 제공한다.

**사용성(Usability)**
- **NFR-U1** **폰 우선 모바일 웹**: 폰 뷰포트가 유일한 1급 레이아웃; 모든 흐름이 폰에서 한 손 사용 가능.
- **NFR-U2** 데스크톱/태블릿에서는 앱을 **폰 목업 프레임 안에 중앙 배치**해 렌더링(데스크톱 리플로우 레이아웃 아님). *(SEC-4 자기-프레이밍 유의사항 참조.)*

**접근성(Accessibility)** *(부차)*
- **NFR-X1** 핵심 흐름에 대해 가능 범위에서 WCAG 2.1 AA 지향; v1 차단 게이트는 아님(NFR-R* 우선으로 후순위).

**관측성 & 유지보수성(Observability & Maintainability)**
- **NFR-O1** 메트릭·구조화 로그·트레이스 + 운영 대시보드(RES-5).
- **NFR-M1** 모듈형 아키텍처, 문서화된 컴포넌트; 기술 스택은 Construction에서 선정.
- **NFR-M2** 무중단 데이터 마이그레이션 (Blue/Green): 기존 인덱스(`docsuri-corpus-v1`)는 유지한 채 신규 인덱스(`docsuri-corpus-v2`)를 생성 및 백필(re-embed)한 후, 완료 시점에 alias를 스위칭하여 검색 중단 시간(downtime) 없이 v4로 마이그레이션한다.

## 6. 보안 요구사항 *(Security 베이스라인 활성 — 15개 규칙 전부 차단성)*

| ID | 요구사항(규칙) |
|---|---|
| **SEC-1** | 모든 데이터 저장소(계정, 검색 저장/라이브러리, 벡터 인덱스, 오브젝트 스토리지)에 저장 시 암호화 + 전송 시 TLS 1.2+. (SECURITY-01) |
| **SEC-2** | 모든 네트워크 중간자(LB/API 게이트웨이/CDN)에 액세스 로깅. (SECURITY-02) |
| **SEC-3** | 애플리케이션 레벨 구조화 로깅(타임스탬프, 요청 ID, 레벨); **로그에 PII/시크릿 금지**. (SECURITY-03) |
| **SEC-4** | HTTP 보안 헤더 + 제한적 CSP. **자기-프레이밍 예외**: 데스크톱에서 앱이 폰 목업 안에 스스로를 프레이밍하므로 `X-Frame-Options`/`frame-ancestors`는 동일 출처 자기-프레이밍을 허용해야 함(전면 `DENY` 아님). 단, 이 카브아웃은 `frame-ancestors`/`X-Frame-Options`에만 적용되며 `script-src`/`connect-src`/`default-src` 등 나머지 제한적 CSP와 SEC-13 SRI는 그대로 유지. (SECURITY-04) |
| **SEC-5** | 모든 API 파라미터 입력 검증(타입, 길이, 형식, 새니타이즈, 파라미터화 질의). (SECURITY-05) |
| **SEC-6** | 최소 권한 IAM(문서화된 예외 없이는 와일드카드 액션/리소스 금지). (SECURITY-06) |
| **SEC-7** | 기본 거부(deny-by-default) 네트워크 구성; 공개 인그레스는 80/443만. (SECURITY-07) |
| **SEC-8** | 애플리케이션 레벨 인가: 기본 거부 라우트, 사용자 데이터(검색 저장/라이브러리/이력)에 **객체 단위 소유권**, 서버측 토큰 검증, 제한적 CORS. (SECURITY-08) |
| **SEC-9** | 하드닝: 기본 자격증명 금지, 일반화된 프로덕션 에러, 공개 오브젝트 스토리지 차단. (SECURITY-09) |
| **SEC-10** | 공급망: 락파일, 의존성 취약점 스캔, SBOM, 핀 고정 이미지(`latest` 금지). (SECURITY-10) |
| **SEC-11** | 시큐어 디자인: 인증 로직 격리; **공개 가입 + 검색 엔드포인트에 레이트 리미팅**, **계정 생성 남용 방어(봇/대량 가입 스로틀링·봇 완화)** 포함(공개 서비스의 남용 + 비용 통제; SEC-12 로그인 무차별 대입 방어와 별개). (SECURITY-11) |
| **SEC-12** | 인증: 비밀번호 정책 + 유출 검사, 적응형 해싱, secure/httpOnly/sameSite 세션, 무차별 대입 방어, 관리자 MFA. (SECURITY-12) |
| **SEC-13** | 소프트웨어/데이터 무결성: 안전한 역직렬화, 외부 스크립트 SRI, 핵심 데이터 변경 감사 가능. (SECURITY-13) |
| **SEC-14** | 경보 + 모니터링; **추가 전용(append-only) 감사 로그**, 90일+ 보존. (SECURITY-14) |
| **SEC-15** | 페일세이프 예외 처리: 모든 외부 호출 처리, fail closed, 전역 에러 핸들러, 일반화된 사용자 에러. (SECURITY-15) |

## 7. 복원력 요구사항 *(Resiliency 베이스라인 활성 — 15개 규칙 전부 차단성)*

| ID | 요구사항(규칙) |
|---|---|
| **RES-1** | 워크로드 중요도 분류 및 비즈니스 영향 + 의존성 맵 문서화(arXiv API, LLM/임베딩, 벡터 스토어). (RESILIENCY-01) |
| **RES-2** | **RTO/RPO + DR (CQ4=E)**: 단일 리전, 멀티 AZ; **교차 리전 DR 없음**. 자동 암호화 DB 백업; **계정/검색 저장 메타데이터**에 대해 RPO ~24h 이내 허용, RTO는 IaC 재배포 + 복원으로 수 시간. **공유 Corpus 벡터/DocModel 인덱스는 FR-6 인제스천 파이프라인에서 재생성 가능(rebuildable) 자산으로 취급 — RTO는 재구축 시간(제안: 수 시간~수일, phase 크기에 따름), RPO는 마지막 source별 watermark 성공 시점**(별도 백업 불요, 재구축 런북 문서화). AZ 장애에 대한 정적 안정성. (RESILIENCY-02/08/12) |
| **RES-3** | **변경 관리(CQ5=A)**: 기존 프로세스 준수 — **GitHub PR 리뷰 + git-flow(feature → develop → main) + GitHub Projects**. 새로 만들지 않음. (RESILIENCY-03) |
| **RES-4** | CI/CD, 롤백 메커니즘, 배포 방식 — **NFR Design으로 보류**(RESILIENCY-04). |
| **RES-5** | 메트릭/로그/트레이스 모니터링 + 운영 대시보드. (RESILIENCY-05) |
| **RES-6** | 얕은(shallow) + 깊은(deep) 헬스 체크와 라우팅 연동; 공개 엔드포인트 합성 모니터링. (RESILIENCY-06) |
| **RES-7** | 복원력 모니터링 + 경보(예: 인제스천 갱신 실패, source별 watermark 지연, GROBID/DocModel/Embedding 단계 실패, DLQ 적체, 단일 AZ 운영, 용량). (RESILIENCY-07) |
| **RES-8** | 오토스케일링 / 서버리스 동시성 한도 + 클라우드 서비스 쿼터 인지(arXiv·Semantic Scholar·OpenAlex 레이트 한도, GROBID 처리량, LLM/임베딩 처리량). (RESILIENCY-09) |
| **RES-9** | 의존성 격리: 명시적 타임아웃, 서킷 브레이커, arXiv/Semantic Scholar/OpenAlex/GROBID/LLM/벡터 스토어 장애에 대한 **정의된 저하 모드 동작**. (RESILIENCY-10) |
| **RES-10** | DR 전략 문서화(Backup & Restore, RES-2 기준): **교차 리전 페일오버 없음** — AZ 수준 복원 + 백업/인덱스 재구축 복구 절차(복원·재구축 런북). (RESILIENCY-11/13) |
| **RES-11** | **장애 대응(CQ6=B+)**: **경량 장애 대응 + 오류 교정(COE)** 프로세스 제안; RES-5 경보를 연동. 장애 분류 체계는 **AI/에이전트 특화 클래스**를 명시적으로 포함하며 각각 탐지 신호·경보·COE 후속을 가져야 함: **(a) 비용 폭발** — 폭주하는 LLM/API 비용(→ NFR-C1 비용 상한 서킷 브레이커, SEC-11 레이트 리미팅); **(b) 할루시네이션** — 날조된 논문/인용/주장(→ FR-5 / QT-1 엄격 근거화); **(c) 반쪽짜리 결과(partial/half-baked)** — 불완전·은밀히 저하된 답변(→ NFR-R1/R2, FR-11). (RESILIENCY-15) |
| **RES-12** | 복원력 테스트 방식 — **NFR Design으로 보류**(RESILIENCY-14). |

## 8. 품질 & 테스트 요구사항 *(Property-Based Testing 활성 — **Partial**: PBT-02/03/07/08/09만 차단성, 나머지(01/04/05/06/10) 권고)*

- **QT-1 — 엄격 근거화 인수**: 보류된 평가셋 전반에서 날조 논문/인용 0건; 코퍼스 밖 질의에 올바른 기권 동작. 평가셋(제안: in-corpus 질의 ≥30건, 의도적 코퍼스 밖/적대적 질의 ≥10건에 100% 기권; 동결·held-out). **평가셋 구축은 Functional Design 산출물이며 소유자는 OP/팀.** (Q13=A)
- **QT-2 — 관련도 평가셋**: 기대 관련 논문이 있는 보류 질의셋; 평가셋 대비 디스커버리 품질 측정(부팅 여부를 넘는 테스트 가능성 게이트). **지표(제안): 대표 질의 N건에서 Recall@10 ≥ 0.7.** FR-2/FR-3가 이 게이트를 참조. *(Q14=C 신뢰성과 보완)*
- **QT-3 — 신뢰성/우아한 저하 인수**: 모든 업스트림 장애·빈 결과 경로에 정의·테스트된 동작. (Q14=C, NFR-R*)
- **QT-4 — Property-Based Testing**: Functional Design에서 테스트 가능 속성 식별(PBT-01); 라운드트립(질의/결과 DTO·arXiv 메타데이터 직렬화), 불변식(랭킹 순서, 디덥 멱등성, 결과셋 크기/원소 보존), 도메인 제너레이터·shrinking·시드 재현성 적용; 프레임워크는 NFR Requirements에서 선정(Python→Hypothesis / TS→fast-check), 예시 기반 테스트와 보완. **Partial 모드**: PBT-02/03/07/08/09 차단성, PBT-01/04/05/06/10 권고(기술 스택 확정 후 재평가). (PBT-02/03/07/08/09 blocking)
- **QT-5 — 요약/번역 근거화 인수 [U7]** *(2026-06-29 개정 — 페이즈 3/Q2·Q3·Q4)*: U7 요약/번역(FR-12/13) 출력도 엄격 근거화 적용 — 보류 평가셋에서 날조 주장/인용 **0건**; 원문에 근거 없는 항목은 **기권**. **검증은 U7 자체 결정론 Validator**(D3 — U6 검색 enforce 재사용 아님으로 확정; 문서충실도 검증은 검색 candidate↔record set과 종류가 달라 별도, 공유 추상 인터페이스/레지스트리 아래 등재): ① **앵커 존재**(SOFT — 검증 불가 앵커는 드롭, 본문+검증 통과 앵커는 노출), ② **수치 일치**(HARD), ③ **스키마 완전성**(HARD), ④ **빈/절단**(HARD). 1차 실패→1회 재시도→재실패→기권(fail-closed). LLM-judge 미사용. **앵커 계약**: `{field, target∈{section\|table\|figure}, span, label}`(block-level id 정밀 앵커는 페이즈 4 이월; Q4). **수치 임계 재보정(Q3 — 실질 갭)**: 현행 수치 가드는 fraction-based 임계 `0.5`(결과 수치의 50% 초과가 원문 부재 시에만 기권)인데 이는 **충실도 평가셋 없이 정한 추정값**(matcher 노이즈—반올림·단위·표 재렌더—를 임계로 덮음). → **QT-1 충실도 평가셋 신설(grounded/날조 라벨 케이스 + `run_eval_set` 구현)·matcher 정밀화(반올림·단위 정규화)·임계 strict 재보정(false-abstain↔false-pass 곡선 기반)** 을 **페이즈 3 산출물**로 한다. **QT-1 평가셋에 요약/번역 케이스 추가.** (FR-12/13/18, FR-5와 일관.)
- **QT-6 — 인용 엣지 정확도 + 그래프 불변식 [U8]**: 날조 인용 0건. 해소 가능한 ID가 있는 엣지만 확정 표시하고, ID 해소 실패 항목은 unresolved로 분리한다. 그래프 불변식(깊이≤2, 화면당 노드≤50, 중복 접기, 순환 방지, DTO 라운드트립)을 PBT 또는 동등한 자동 테스트로 검증한다.
- **QT-7 — 개인화 이벤트/프로필 불변식 [U9]**: 행동 이벤트 DTO 라운드트립, 이벤트 dedupe key 안정성, owner-scoped 접근, raw event 90일 보관 정책, 프로필 집계 불변식(동일 입력 이벤트 집합 → 동일 프로필, 삭제/초기화 후 개인화 신호 제거)을 자동 테스트한다. PBT는 기존 Partial 모드(PBT-02/03/07/08/09)를 유지한다.
- **QT-8 — 근거형성 근거화·불변식 [U11]** *(2026-06-29 신규)*: 근거 출력에 날조 주장·인용 **0건**(논문 원문에 없는 statement 생성 금지, C-2·FR-5); 근거 0건·범위 밖 질의에서 **state=abstain 경로 동작**(날조 없이 기권); `EvidenceItem` DTO 라운드트립(schema.json 일치); conflicting[] 배열 상충 표현 정확성; owner-scoped 접근 불변식(다른 사용자 세션 접근 불가, SEC-8); 멀티턴 맥락 누적 불변식(이전 턴 근거 재참조 가능). **QT-1 평가셋에 문헌탐색 케이스 추가.** PBT Partial 모드(PBT-02/03/07/08/09 차단성) 유지.
- **QT-9 — U1 Corpus 품질/불변식 [U1]**: 멀티소스 dedup 멱등성(DOI→arXiv id→정규화 title/author/year), source별 watermark 단조 증가, `(paperId, version)`별 DocModel·청크·인덱스·S3 참조 정합, DocModel schema roundtrip/negative validation, 모든 인덱스 record의 DocModel Block id 실재성, retry/DLQ 재처리 멱등성, 라이선스 미허용 원문/원시 PDF 미저장 불변식을 자동 테스트한다. PBT Partial 모드에서 PBT-02/03/07/08/09는 차단성으로 적용하고 Python 구현은 Hypothesis 기반 generator/shrinking/seed 재현성을 사용한다.
- **QT-10 — novelty Agent 품질/불변식 [U12]**: `EvidenceFormationPort`/`SourceRef` 무결성, U2 `full` 검색 결과의 SourceRef 정합, 유사 논문 적중, GitHub/데이터셋 출처 보존, 원고 유사도/AI 어투 경고의 false positive 관리, 실험 계획 필수 필드, job state transition, Notion export 무결성을 자동 테스트한다. PBT는 Partial 적용(Q32=B)으로 pure function, DTO round-trip, source normalization, job-state invariant에 한정한다.
- **QT-11 — Agent Chat Frontend 품질/불변식 [U13]**: mode는 세션 생성 후 변경되지 않음, 세션 목록 정렬/상태 표시, timeline event ordering, 첨부 형식 allowlist, failure/degraded classifier, mock/real transport response normalization을 자동 테스트한다. Q16=B에 따라 frontend pure helper와 상태 reducer에는 fast-check 기반 Full PBT를 적용하고, UI rendering은 예시 기반 테스트로 보완한다.

## 9. 제약 (Constraints)
- **C-1** 콘텐츠: **오픈액세스/인덱싱 허용 라이선스 전용**(phase-1은 arXiv·Semantic Scholar·OpenAlex의 최근 AI/ML 1년). OA 전문만 저장. (Q12=A) **[개정 2026-06-25 — U1 리뷰, 커밋 `86ade36` 추인]** 인덱싱 허용 라이선스 = CC-BY/CC-BY-SA/CC0 **+ arXiv 비독점 배포 라이선스**(`arxiv.org/licenses/nonexclusive-distrib`). 근거: 디스커버리 용도(원문 링크백 + 초록 스니펫 표시)는 **대량 재배포가 아니며** arXiv 공개 열람과 동등 → arXiv 인덱스 가능 코퍼스를 CC 전용에서 사실상 전 arXiv로 확장. **[U1 Corpus 2026-06-26]** Semantic Scholar/OpenAlex PDF는 OA/라이선스 허용 신호가 확인되는 경우에만 transient fetch→GROBID 추출에 사용하고, 원시 PDF는 저장·다운로드하지 않는다. 저장 대상은 정규화 FullText/DocModel/자산/인덱스 record와 source provenance이며, 재배포 금지·미표기·불명 라이선스는 계속 NON_OA 배제(BR-1). 전문 S3 보관은 공개 차단 유지(SEC-9, BR-20).
- **C-2** 이번 사이클에서 **AI 생성 글쓰기(원고·문헌리뷰 산문 작성/합성)는 범위 제외**(Q11=D). v1의 AI 텍스트는 **검색된 레코드에서 도출된 근거 기반 관련도 신호/추출 요약**(FR-5)으로 한정하며, 사용자 본인 글을 위한 생성·합성 산문은 만들지 않는다. (§2·§12와 동일 정의 적용.) **[U7 경계 — Q1=A]** 요약/번역(FR-12/13)은 **검색돼 사용자가 선택한 단일 논문의 추출**(요약=전문 구조화, 번역=초록 번역)에 해당하여 본 추출 경계 **안**이다 → 허용. **[novelty Agent 경계 — Q14/Q15=A]** bounded 실험 아이디어와 실험 계획은 근거 기반 연구 보조 산출물로 허용하되, 원고 문단·문헌리뷰 산문·"새로움 확정" 판정·논문화 가능성 점수·코드 skeleton 생성은 제외한다.
- **C-3** **폰 전용 모바일 웹**(Q8/CQ3); 데스크톱 = 폰 목업 프레임. 네이티브 앱·PWA 설치 없음(v1).
- **C-4** **단일 리전, 멀티 AZ** 배포(CQ4=E).
- **C-5** AWS 지향(팀 경험 + 이전 사이클)이나 구체적 기술 스택은 Construction 전까지 **미확정**.
- **C-6** v1 분야 범위는 **AI/ML 전용**(Q5=A).

## 10. 가정 & 조정 (Assumptions & Reconciliations)
- **A-1 (CQ1)**: "프로덕션 출시" + "공개 셀프 가입"을 중간 비용 티어와 조정 → **공개 프로덕션, 단계적 규모** — 프로덕션 수준으로 구축하되 근시일 수백 명, 강한 비용 가드레일.
- **A-2 (CQ2)**: 벡터 스토어는 모두가 검색하는 **공유 AI/ML 학술 Corpus 인덱스**다. phase-1은 arXiv 중심에서 Semantic Scholar/OpenAlex OA PDF 보강까지 확장하되, 사용자별 데이터는 검색 저장/라이브러리/이력으로 한정한다. 사용자별 문서 코퍼스 아님(개인 코퍼스 RAG는 §12 로드맵 후보).
- **A-3 (CQ3)**: 플랫폼은 **모바일 웹 앱**("폰 전용 + 데스크톱 폰 목업" 해석).
- **A-4**: 정량 NFR 목표(P1/A1/S1/C1)는 이전 사이클을 따른 **제안**이며 확정 대상.
- **A-5**: arXiv 전문은 arXiv 약관 내에서 인덱싱/검색에 대해 오픈액세스·재배포 가능으로 취급.

## 11. 성공 기준 / 인수 (Success Criteria)
1. 첫 방문자가 셀프 가입 후 폰에서 자연어 AI/ML 의도를 입력하면 **< 3s(P50)** 내 관련 arXiv 논문을 받는다 — 매직 모먼트. (FR-1..4, NFR-P1)
2. **날조 논문/인용 0건**; 관련 결과가 없으면 깔끔히 기권. (FR-5, QT-1)
3. 검색 저장 + 라이브러리가 계정별로 비공개 지속. (FR-7..9, SEC-8)
4. 모든 업스트림/빈 실패가 명시적·우아한 상태로 — 조용한 오답 없음. (NFR-R*, QT-3)
5. 활성 확장 베이스라인(Security/Resiliency/PBT) 전부가 각 게이트에서 준수 또는 정당화된 N/A 보고.
6. 개인화는 기본 검색 품질을 해치지 않고, 사용자가 끄거나 삭제/초기화할 수 있으며, 실패 시 기본 검색·요약·번역으로 저하한다. (FR-39·FR-19·FR-20, NFR-P4, QT-7)
7. 사용자가 **비밀번호를 분실해도 이메일로 자가 재설정**(전 세션 무효화·열거 방지)하고, **Google 소셜 로그인(OIDC)** 으로 가입/로그인(검증 이메일 자동 연결)하며, **비밀번호·이메일 변경·계정 삭제(소프트+유예 비동기 파기·owner-scoped 캐스케이드)** 를 자가 수행한다. 공개 인증 엔드포인트는 추가 필드 스큐로 **전면 차단되지 않고**, 인증 실패는 **명확한 메시지**로 표면화된다. (FR-26..29, SEC-9/11/12, NFR-R1) *(계정 프로덕션화 — 2026-06-24.)*
8. 최근 AI/ML 1년 phase-1 Corpus가 source별 watermark 기반으로 증분 구축되고, 모든 검색/요약/에이전트 입력은 DocModel(Block) 기반 인덱스와 `(paperId, version)` 정합을 만족한다. 비용 상한 도달 시 새 작업은 보류·DLQ/백필로 이월되고 기존 검색/열람은 명시적 저하 상태로 유지된다. (FR-6, FR-18, NFR-C1, QT-9)
9. novelty Agent는 자연어 또는 업로드 원고 입력에서 공유 Evidence 계약과 U2 `full` 검색을 사용해 유사 연구·차별화 후보·실험 계획을 생성하고, 탐구 과정을 프론트에 단계별로 표시하며, Notion export는 사용자 승인 후에만 수행한다. 외부 source 실패는 `degraded` 부분 결과로 표면화된다. (FR-30..35, NFR-P5/R3, QT-10)
10. 사용자가 연구 질문을 채팅으로 입력하면 관련 논문들에서 **핵심 주장·방법·결과·한계를 추출·비교 정리**해 받고, 근거가 없으면 날조 없이 기권한다. 세션이 owner-scoped로 영속되어 재열람 가능하다. (FR-36~38, NFR-P6, QT-8)
11. 사용자가 하단 네비의 `에이전트` 탭에서 mode를 선택해 멀티턴 채팅을 시작하고, 과거 세션을 drawer에서 다시 열며, agent 탐구 과정을 timeline으로 확인할 수 있다. 실패/저하/첨부 제한은 명확한 사용자 메시지와 재시도 경로로 처리된다. (FR-40~43, NFR-P7, QT-11)

## 12. 범위 제외 (v1)
근거 합성 Q&A; 라이브러리 저장을 넘는 레퍼런스 관리; forward citations 기반 trace 내비게이션; AI 생성 글쓰기/작성; 비(非)AI/ML 분야; 비(非)오픈액세스/유료 콘텐츠; 멀티 리전 DR; 네이티브 모바일 앱; 협업/공유(랩, 지도교수-학생); 오프라인 사용.

> **[U7 제외 — Q6=A; 2026-06-29 개정 — 페이즈 3/Q9]** 요약/번역(FR-12~14)을 편입하되, 그중 **커뮤니티 공유 용어집(P3)**(UGC → 모더레이션·콘텐츠 삽입 방어 필요)과 **자유입력 per-user "내 연구노트 관련성"**(사용자마다 유일 → 비용이 사용자 수에 비례하는 진짜 per-user)은 v1 범위 **제외**(이후 사이클 후보). 편입 범위는 persona(전문/입문) 생성·용어집 P1 시드+P2 개인 오버라이드로 한정. **뷰 프리셋은 폐기**(코드 부재 확인 — 페이즈 3/Q9), **커뮤니티 용어집(P3)도 폐기**(이월 아닌 제거). **후속 이월(페이즈 3 제외)**: 표 셀 번역·각주 블록·DocModel block-level id 정밀 앵커(페이즈 4 evidence와 함께)·요약 grounding LLM-judge·다국어 번역(Q10).

> **[U8 카브아웃 — 2026-06-19]** 인용 그래프/"trace" 내비게이션 제외를 일부 해제한다. v1 편입 범위는 **논문 상세보기 페이지의 backward references 각주 트리**로 한정한다. forward citations, 3-hop 이상 탐색, 문헌리뷰 생성, 그래프 기반 추천 산문, 상세보기 FE 구현은 제외한다.

> **[멀티모달 카브아웃 — 2026-06-22]** "그림·도표(멀티모달)" 보류 트랙(`aidlc-state.md`)을 부분 해제한다. v1.x 편입 범위는 **그림·도표 자산의 추출·저장·표시(표시 전용, FR-17)** 로 한정한다. **이미지에 대한 비전 LLM 추론**(도표를 읽어 요약·근거에 반영)은 v1 범위 **제외 유지**(차기 사이클 후보). 명확화: `requirement-verification-questions-multimodal-display.md` Q1~Q7(2026-06-22; Q2=C 혼합 추출, 나머지 A).

> **[U9 제외 — 2026-06-23]** 개인화 기능은 **도메인 의미가 있는 행동 이벤트 + 관심사 프로필 + 검색 rerank + 요약/번역 기본값**으로 한정한다. v1에서 **전체 클릭스트림 수집, hover/scroll 추적, 별도 추천 논문 목록, 강한 추천 점수로 검색 순서 대폭 변경, 실시간 ML 추천 파이프라인, U6 운영 텔레메트리와 사용자 행동 데이터 통합**은 제외한다.
> **[doc-model 카브아웃 — 2026-06-23 / U1 Corpus 정정 2026-06-26]** 요약/번역 입력·전문뷰어를 doc-model 기반(FR-12/17/18)으로 전환하되, 다음은 v1 범위 **제외**: ① **PDF 원문 저장·다운로드**(D3 — 자산/doc-model 추출용 transient fetch만; 다운로드 버튼 없음; arXiv 재취득 가능). Semantic Scholar/OpenAlex PDF도 OA/허용 라이선스 확인 후 transient GROBID 입력으로만 사용하고 원시 PDF는 저장하지 않는다. ② **이미지 비전 LLM 추론**(D5 — 멀티모달 카브아웃과 동일, 그림 webp는 보존해 차기 에이전트 on-demand 비전 입력으로 재사용). ③ **phase-1 밖 외부소스 일괄 원문 캐시**. 재인셉션 D6에 따라 phase-1 Corpus에 편입된 논문은 **수집 시점 eager DocModel 생성**이 기본이며, lazy 빌드는 누락분·재빌드·백필·phase-1 밖 보강 경로로 제한한다. 명확화: `requirement-verification-questions-docmodel.md` Q1~Q7(2026-06-23; 전부 게이트 권장안 D1~D8 + 리치뷰=신규 FR-18), `requirement-verification-questions-u1-corpus.md` Q1~Q12(2026-06-26; 전부 A).
> **[novelty Agent 카브아웃 — 2026-06-29]** v1은 GitHub·데이터셋 외부 탐색까지만 포함하고, **최신 뉴스 검색은 다음 사이클**로 둔다(Q8=B). 외부 웹 검색에는 사용자 원문/Evidence 전체를 보내지 않고 최소 질의·익명화 요약만 사용한다(Q9/Q25=A). 표절/AI 어투 검사는 법적 판정이나 AI 작성 확률 판정이 아니라 검토 신호로만 제공한다(Q16/Q17=A). 코드 skeleton·실행 스크립트 생성은 제외한다(Q15=A). Notion 저장은 자동 저장이 아니라 내부 저장 후 사용자 승인 export만 허용한다(Q22=A).

> **[U11 제외 — 2026-06-29]** 문헌탐색·근거형성 에이전트는 **추출·비교·기권만** 수행한다. v1에서 **재현성 판정·정량 confidence 산출·생성 산문(문헌리뷰 작성)·연구아이디어 생성·전 분야 커버리지 확장**은 제외한다. 재현성 판정은 합성 판단으로 FR-5와 긴장(Q1=A 근거). confidence가 필요하면 페이즈 5(연구아이디어 유닛)가 자체 로직으로 산출한다. 연구아이디어 생성은 페이즈 5 별개 유닛(D2).

> **비고**: 폐기된 사이클 1(U1·U2·U4 데모; 인용 그래프 포함, git `ba3b6a9`)의 산출물·PR은 본 그린필드 사이클의 권위 있는 범위가 **아니다**. 인용 그래프의 v1 제외는 의도된 결정이며 이전 사이클과의 "충돌"이 아니다.

> **로드맵**: **개인 코퍼스 RAG**("내 라이브러리 전체에 질문", Round-1 Q7=C)는 v1 범위 제외이나(CQ2=A로 공유 인덱스 확정) **이후 사이클 후보로 기록** — 공유 arXiv 인덱스에서 사용자별 개인 문서 코퍼스로 확장(신규 데이터 모델·유닛 수반).

## 13. 추적성 (Traceability)

| 요구사항 | 출처 |
|---|---|
| §2, FR-1..5 (디스커버리, 매직 모먼트, 근거화) | Q3=A, Q4=A, Q13=A |
| §3 페르소나 | Q2=B |
| FR-6, C-1, C-6 (U1 Corpus 멀티소스 인제스천, OA/허용 라이선스, AI/ML) | Q5=A, Q6=B, Q12=A, CQ2=A; U1 Corpus Q1~Q12=A (2026-06-26); `requirement-verification-questions-u1-corpus.md`; `reinception-2026-06-charter.md` D6 |
| FR-2 + A-2 (공유 인덱스) | Q7=C, CQ2=A |
| FR-2/4/5 개정·NFR-P1 (U2 검색 정합·멀티소스 카드·근거 소스중립·lite/full SLA·Grounding(Search) 단일권위) [U2] | U2 Discovery Q1~Q9=A (2026-06-29); `requirement-verification-questions-u2-discovery.md`; `reinception-2026-06-charter.md` 페이즈 2·D3; PR #236 |
| FR-5/12/13/14 개정·NFR-C1[U7]·NFR-P2·QT-5 (U7 요약/전문번역 정합·Grounding Framework 통합 D3·앵커 입도·QT-1 충실도 평가셋 신설·온디맨드/영구저장·비용 게이트 80%·뷰프리셋·P3 폐기) [U7] | U7 Summarization Q1~Q10=A (2026-06-29); `requirement-verification-questions-u7-summarization.md`; `reinception-2026-06-charter.md` 페이즈 3·D3·D6·§5-3; 코드 베이스라인 §2 페이즈 3·§4-1 |
| FR-7..10, SEC-8/12 (계정) | Q9=B, Q10=C |
| FR-26..29, BR-A8..A12 (계정 프로덕션화: 재설정·소셜 OIDC·라이프사이클·입력 견고화) | 계정 프로덕션화 Q1=ABCD, Q2=A, Q3=Google, Q4=A, Q5=A, Q6=A, Q7=A, Q8=A (2026-06-24); `requirement-verification-questions-account-production.md` |
| NFR-S1/C1, A-1 (규모 + 비용) | Q1=C, Q10=C, Q15=B, CQ1=A |
| NFR-U1/U2, C-3 (폰 전용) | Q8=C, 채팅 오버라이드, CQ3=A |
| NFR-A1/R1/R2, RES-2 (신뢰성·우아한 저하·DR) | Q14=C, CQ4=E |
| NFR-P1 (성능 P50/P95) | 성능 목표(제안), 이전 사이클 P50<3s |
| NFR-O1/M1 (관측성·유지보수) | Resiliency/관측 베이스라인, RES-5 |
| NFR-X1 (접근성, 부차) | 품질 결정(Q14=C 신뢰성 우선) |
| FR-11 (빈/실패 UX) | Q14=C, NFR-R*, SEC-9/SEC-15 |
| C-2 (작성 범위 제외) | Q11=D |
| §6 SEC-* | Security 옵트인 = Yes(전체) |
| §7 RES-*, RES-3/RES-11 | Resiliency 옵트인 = Yes; CQ4=E, CQ5=A, CQ6=B+ (AI 인시던트 분류: 비용/할루시네이션/반쪽짜리 결과) |
| QT-1 (엄격 근거화) | Q13=A |
| QT-2 (관련도 평가셋) | Q14=C |
| QT-3 (신뢰성/저하 인수) | Q14=C, NFR-R* |
| §8 QT-4 (PBT) | PBT 옵트인 = Yes |
| FR-12/13/14 (요약·번역·개인화) [U7] | U7 명확화 Q1/Q2/Q6=A (2026-06-18, 팀 합의); `summarization-translation-pipeline.md` |
| NFR-P2 (온디맨드 응답) [U7] | U7 Q3=A |
| NFR-C1 U7 비용 라인 보강 [U7] | U7 Q4=A |
| QT-5 (요약/번역 근거화) [U7] | U7 Q5=A, FR-5/QT-1 일관 |
| C-2 U7 추출 경계 [U7] | U7 Q1=A |
| §12 U7 제외(P3·자유입력) [U7] | U7 Q6=A |
| FR-15/16 (각주 트리·노드 저장) [U8] | 인용 그래프 명확화 Q1/Q2=A, Q3=X, Q4=B, Q10=X, Q13=A, Q14=B (2026-06-19) |
| NFR-P3 (각주 트리 온디맨드 응답) [U8] | 인용 그래프 Q15=A |
| NFR-C1 U8 citation API 쿼터 게이트 [U8] | 인용 그래프 Q16=A |
| QT-6 (인용 엣지 정확도·그래프 불변식) [U8] | 인용 그래프 Q11=A, Q20=A |
| §12 U8 카브아웃 [U8] | 인용 그래프 Q1=A, Q4=B |
| FR-17 (그림·도표 표시 — 표시 전용) [U1/U7/U5] | 멀티모달 명확화 Q1=A·Q2=C·Q3~Q7=A (2026-06-22); `summarization-translation-pipeline.md`, aidlc-state 보류 트랙 |
| FR-12 앵커 자산 연결 보강 | 멀티모달 Q5=A |
| §12 멀티모달 카브아웃(비전 추론 제외 유지) | 멀티모달 Q1=A |
| 백/프론트 정합 갭 3건 U7 흡수(SSOT·상태매핑) | 멀티모달 Q6=A |
| FR-19 (개인 관심사 프로필 집계) [U9] | U9 Q7/Q8/Q9/Q10/Q11=A |
| FR-20 (개인화 적용) [U9] | U9 Q1/Q12/Q13=B/Q14/Q15/Q16=A |
| NFR-P4 (개인화 비차단 저하) [U9] | U9 Q6/Q16=A |
| QT-7 (이벤트·프로필 불변식) [U9] | U9 Q20=A |
| §12 U9 제외(추천 목록·전체 클릭스트림·실시간 ML) [U9] | U9 Q3=A, Q10=A, Q13=B |
| FR-12 개정(요약 입력 = doc-model·앵커 = doc-model id) [U7] | doc-model 명확화 Q1/Q6 = A (2026-06-23); 게이트 D2; `docmodel-foundation-pivot-plan.md` |
| FR-17 개정(그림=이미지·표=구조화 데이터) [U1/U7/U5] | doc-model 명확화 Q3=A; 게이트 D8 |
| FR-18 신설(자체 리치뷰 — doc-model 렌더 1급) [U1/U7/U5] | doc-model 명확화 Q2=A; 게이트 D4 |
| §12 doc-model 카브아웃(PDF 미저장·비전 제외 유지·phase-1 밖 외부소스 일괄 원문 캐시 제외) | doc-model 명확화 Q4/Q5 = A; 게이트 D3/D5/D7; U1 Corpus Q3/Q5/Q12=A |
| QT-5 앵커 보강(doc-model id 실재성·결정적) [U7] | doc-model 명확화 Q6=A; 게이트 Q3 스키마 |
| doc-model 생성 eager+캐시 / lazy 보강 경로 정정 [U1] | U1 Corpus Q5=A, Q9=A, Q12=A (2026-06-26); `reinception-2026-06-charter.md` D6. 구 doc-model Q7=A(lazy)는 phase-1 Corpus 범위에서 대체됨 |
| FR-13 개정(본문 번역 = 구조화 번역본 doc-model; 긴 번역 map-only·비동기) [U7] | PR-2 게이트 (2026-06-24); `docmodel-foundation-pivot-plan.md` PR-2 절·BR-S18 |
| FR-21 듀얼 라이트 (v4 마이그레이션, 구 FR-18) [U1] | v4 마이그레이션 Q3=A |
| NFR-M2 Blue/Green 마이그레이션 전략 | v4 마이그레이션 Q1=A |
| NFR-S2 v4 컷오버 및 모델 설정 | v4 마이그레이션 Q2=A, Q4=A |
| DocModel(Block) 기반 인덱싱 / index generation·alias 전환 [U1/U2] | U1 Corpus Q6/Q7/Q8=A (2026-06-26) |
| NFR-C1 U1 Corpus eager 비용 게이트 [U1] | U1 Corpus Q5/Q8/Q12=A (2026-06-26) |
| QT-9 U1 Corpus 품질/불변식 [U1] | U1 Corpus Q2/Q6/Q7/Q9/Q10/Q11=A (2026-06-26); PBT Partial PBT-02/03/07/08/09 |
| RES-7 U1 Scheduler/Retry/DLQ/watermark 실패 신호 [U1/U6] | U1 Corpus Q10/Q11=A (2026-06-26) |
| FR-30..35, NFR-P5/R3, QT-10 (novelty Agent 입력·검색·아이디어·실험계획·원고위험·진행상태·Notion export) [U12] | Novelty Agent Q1~Q7=A, Q8=B, Q9~Q28=A, Q29=C, Q30=A, Q31=A, Q32=B (2026-06-29); `requirement-verification-questions-novelty-agent.md`; `requirement-verification-questions-u11-novelty-agent.md`(재스코핑); 원답변 `…-answer-1.md`은 미커밋 임시 입력(인라인 반영); `EvidenceFormationPort`/`SourceRef` 공유계약; 구현 `construction/novelty-agent/` |
| FR-36~38 (문헌탐색·근거형성 세션·추출·영속) [U11] | U11 질문지 Q1~Q10 전수 확정 (2026-06-29); `requirement-verification-questions-literature-evidence-agent.md`; `reinception-2026-06-charter.md` 페이즈 4·D2·D5 |
| NFR-P6 (근거형성 응답 성능 — 스트리밍+비동기 잡) [U11] | U11 Q9=A |
| QT-8 (근거형성 근거화·불변식) [U11] | U11 Q1~Q3=A/B; FR-5·C-2 일관 |
| D5 계약 게이트 (EvidenceItem·EvidenceFormationPort 동결) [U11→U12] | `shared/dtos/evidence.schema.json`·`shared/ports/README.md` (2026-06-29); `reinception-2026-06-charter.md` D5 |
| §12 U11 제외 (재현성 판정·confidence·생성 산문·연구아이디어·전 분야) [U11] | U11 Q1=A (재현성 제외), Q3=B (confidence 제외), C-2, D2 |
| FR-40~43, NFR-P7, QT-11 (Agent Chat Frontend 진입·mode lock·세션 drawer·timeline·첨부·상태 UX) [U13] | Agent Chat Frontend Q1~Q16 확정 (2026-07-01); `requirement-verification-questions-agent-chat-frontend.md`; `requirement-question-answer.md` |
