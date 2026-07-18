# Novelty Agent v2 재설계 (U12) — Functional Design Plan + 질문 게이트

**단계**: CONSTRUCTION → Functional Design (재설계 라운드)
**일자**: 2026-07-17
**상태**: 🟡 답변 대기 — 아키텍처 질문지(2026-07-18 확정)에서 Q2·Q12 상속 완료. 잔여 `[Answer]:`를 채우면 산출물 생성을 진행한다.
**근거 SSOT**: `inception/requirements/requirements.md` FR-30~35 · NFR-P5/R3 · QT-10 [U12] · 유지보수 로드맵 ④~⑦(`operations/solo-roadmap.md`) · **아키텍처 결정** `inception/requirements/requirement-verification-questions-agent-rearchitecture.md`(2026-07-18 확정) · 현행 frozen 설계 `construction/novelty-agent/`(BR-NV1~19, PBT-NV1~7) · 공유 계약 `EvidenceFormationPort`/`SourceRef`(D5).

**상속된 아키텍처 결정** (재논의 없음):
- 최종형은 supervisor–서브 에이전트 구조이며, **본 유닛은 그 1단계 — novelty를 단일 자율 루프 에이전트로** (arch Q1=C, Q3=A).
- 코드 전략은 **모듈 내부 재작성** — 기존 파이프라인 위 개조가 아니라 새 루프 코어를 짜고 가치 있는 부품만 이식 (arch Q4=A).
- 단일 루프는 **프레임워크 없이 직접 구현** — LangGraph는 로드맵 ⑦ supervisor 단계에서 도입 (arch Q5=A).
- REST 계약·FE 화면 유지 + **결정 트레이스(도구·질의·종료 사유) 구조화 저장은 루프 도입과 동시 시작** (arch Q6=A).
- requirements.md는 소규모 개정 블록 — 델타 5건 (arch Q7=A → 본 문서 Q12).
- 이번 사이클 산출물은 설계 문서까지, 구현은 로드맵 ⑤ (arch Q8=A).

## 1. 유닛 컨텍스트

- **대상**: Novelty Agent v2 — 현행 novelty 모듈(고정 상태머신 QUEUED→…→EXPORTING_NOTION)의 **도구 호출 루프 기반 재설계** 목표 아키텍처.
- **명칭**: 유닛명·코드 경로 모두 **novelty 유지**. "research*" 계열 명칭은 로드맵 ⑦ supervisor 명명 후보로 예약 (`backend/modules/research/`는 문헌탐색·근거형성 Agent(U11)의 대화 표면 — 본 유닛과 무관).
- **책임**(불변 — FR-30~35·현행 기능 승계): 자연어 연구 의도 또는 업로드 원고에서 유사 연구·차별화 후보·실험 계획·원고 위험 신호·진행상태·선택적 Notion export를 제공한다.
- **문서 위치**: 설계 문서는 `construction/novelty-agent-v2/`에 둔다 (`construction/novelty-agent/`는 v1 frozen 기준선).
- **범위 경계 (로드맵 ④/⑤)**: 이번 라운드는 **설계 문서만** 산출한다. 코드 교체(에이전트 루프 → MCP 연동 → 세션 메모리 → 멀티모달)는 로드맵 ⑤ — 본 설계는 그 4단계 도입을 수용할 수 있어야 하되, 기존 API 계약·모듈 경로 유지가 ⑤의 제약이다.
- **v1 제외**(승계): 뉴스 검색, novelty 점수, "새로움 확정" 판정, 논문화 가능성 점수, 코드 skeleton/실행 스크립트 생성.

## 2. Functional Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/novelty-agent-v2/functional-design/`에 작성한다.

- [ ] `domain-entities.md`
- [ ] `business-logic-model.md`
- [ ] `business-rules.md`

`frontend-components.md`는 제외 — API 계약 유지가 기본값이라 FE 변경이 없다(Q2에서 계약이 바뀌는 답이 나오면 재결정). `infrastructure-design/`은 AWS 배포 은퇴·로컬 컨테이너 체제로 본 세트에서 제외.

## 3. 명확화 질문

아래 `[Answer]:`를 모두 채운 뒤 Functional Design 산출물 생성을 진행한다.

### A. 아키텍처 코어

#### Q1 — 에이전트 루프 형태
고정 상태머신을 무엇으로 교체하나?

- **A) 완전 자율 tool-loop** — LLM이 매 턴 도구를 선택하고, 필수 산출물 완성(Q4) 또는 예산 소진(Q9)이 종료 조건. 로드맵 ⑤의 명시 목표("도구 호출 루프 기반 에이전트")와 일치. *유연성 최대 / 안전은 Q8·Q9 게이트에 의존.* (권장)
- **B) 거시 페이즈 골격 유지 + 페이즈 내 도구 선택만 자율** — 탐색→분석→계획 3페이즈는 고정, 각 페이즈 안에서만 루프. *예측 가능성↑ / 상태머신의 경직성 절반 잔존.*
- **C) plan-then-execute** — LLM이 먼저 도구 호출 계획을 산출하고 결정론 실행기가 수행. *감사 용이 / 중간 발견에 따른 경로 수정 불가(재계획 필요).*
- **X) 기타**

[Answer]:

#### Q2 — 진행상태 계약 (FR-35 state enum과 동적 루프의 조화)
FR-35가 고정한 진행상태 enum(`queued`~`exporting_notion`)을 어떻게 다루나?

- **A) enum 유지 + 투영 매핑** — 루프의 도구 활동을 기존 state로 투영하는 매핑 레이어(예: U2/evidence 도구 실행 중 = `retrieving_corpus`). API·FE timelineDetail 계약 무변경. *⑤ 제약("기존 API 계약 유지")과 정합.* (권장)
- **B) 세밀 이벤트 스트림 신설 + enum은 요약 투영으로 병존** — 도구 호출 단위 이벤트 계약을 추가하고 기존 enum은 하위호환 요약으로 유지. *표현력↑ / FE 작업·계약 이원화.*
- **C) enum 교체** — 루프에 맞는 새 상태 체계로 대체. *⑤ 제약과 정면 충돌 → 사실상 기각 후보.*
- **X) 기타**

[Answer]: A — 아키텍처 질문지 Q6=A 상속. 조건: 결정 트레이스(선택 도구·질의·종료 사유)를 루프 도입 시점부터 서버에 구조화 저장(`ToolCallRecord` — §4 참조). enum 투영은 사용자 표시용일 뿐, 감사·디버깅·재현성은 트레이스가 담당. FE 노출은 별도 결정.

#### Q3 — v1 도구 집합 (루프에 노출할 도구)
에이전트가 자율 호출할 수 있는 도구를 무엇으로 하나?

- **A) 보수적 코어** — U2 full 검색 · `EvidenceFormationPort`(U11) · GitHub/데이터셋 검색(기존 어댑터 경로) · figure 조회(Q7) · 산출물 저장. **arXiv MCP(외부 arXiv 검색)는 ⑤ 2단계(MCP 연동)로 이월**, **Notion은 루프 밖**(BR-NV17: 미리보기·승인 후 별도 경로 — 에이전트 자율 export 금지). (권장)
- **B) A + arXiv MCP를 v1 설계에 포함** — owned corpus 밖 최신 논문 커버리지↑. *트레이드오프: U11 Q5=A(owned corpus 근거 충실) 원칙과 긴장 — 외부 결과는 DocModel 앵커가 없어 grounding 검증 불가, 별도 근거 등급 필요.*
- **C) A + Notion도 루프 도구로** — *BR-NV17(승인 없는 export 금지)과 충돌 → 기각 후보.*
- **X) 기타**

[Answer]:

#### Q4 — 산출물 계약
현행 ArtifactKind 세트(EVIDENCE, SIMILAR_WORKS, EXTERNAL_FINDINGS, RISK_SIGNALS, NOVELTY_CANDIDATES, EXPERIMENT_PLAN, EXPORT_STATUS)를 어떻게 다루나?

- **A) 전부 유지 + 루프의 필수 완성 조건으로 승격** — 입력 유형별 필수 산출물(자연어: EVIDENCE·SIMILAR_WORKS·NOVELTY_CANDIDATES·EXPERIMENT_PLAN / 원고: +RISK_SIGNALS)을 채워야 정상 종료. 기존 결과 API 무변경. (권장)
- **B) 필수는 NOVELTY_CANDIDATES·EXPERIMENT_PLAN만** — 나머지는 에이전트 재량. *유연 / FE 결과 화면·QT-10 검증 대상 약화.*
- **C) 산출물 자유화** — 계약 없는 자유 출력. *API 계약 파괴 → 기각 후보.*
- **X) 기타**

[Answer]:

### B. 로드맵 ⑤ 단계 수용

#### Q5 — MCP 통합 위치
⑤ 2단계 MCP(arXiv/GitHub/Notion) 연동을 아키텍처 어디에 두나?

- **A) 포트 뒤 어댑터** — MCP는 기존 헥사고날 포트(external search port 등)의 어댑터 구현 디테일. 도메인·루프 코어는 MCP를 모른다. *기존 아키텍처 원칙(어댑터 추가, 도메인 불변)·conditional mounting과 정합.* (권장)
- **B) 루프 코어에 MCP 클라이언트 직결** — 도구 목록을 MCP 서버에서 동적 발견. *확장 용이 / 도구 통제·프라이버시 경계(Q11)·테스트 대역 구성이 어려워짐.*
- **X) 기타**

[Answer]:

#### Q6 — 세션 메모리 범위 (⑤ 3단계)
"세션 메모리"가 무엇을 뜻하는지 목표 아키텍처에서 정의한다.

- **A) 잡 내 멀티턴만** — 실행 중/완료 후 사용자 채팅이 루프를 스티어링(추가 지시·방향 수정). 잡 간 메모리는 범위 밖.
- **B) 잡 간 사용자 메모리만** — 새 잡이 이전 잡의 산출물·선호를 참조. 잡 내 스티어링은 없음.
- **C) 둘 다 목표 아키텍처에 정의, 단계 도입** — ⑤ 3단계에서 잡 내 멀티턴 먼저, 잡 간 메모리는 그 뒤. 기존 `NoveltyChatMessage`는 잡 내 멀티턴의 영속 모델로 승계. (권장)
- **X) 기타**

[Answer]:

#### Q7 — 멀티모달 입력 편입 (⑤ 4단계)
u1이 생성한 figure/formula crop(WebP, S3)을 LLM 컨텍스트에 어떻게 편입하나?

- **A) 온디맨드 도구(`view_figure`)** — 에이전트가 필요 판단 시 특정 논문의 특정 figure만 조회. *비용 통제·컨텍스트 절약.* (권장)
- **B) 근거 논문 선정 시 자동 첨부** — 상위 근거 논문의 주요 figure를 일괄 컨텍스트 편입. *발견 가능성↑ / 토큰 비용·노이즈↑.*
- **X) 기타**

[Answer]:

### C. 안전·비용 (C-2 fail-closed 유지)

#### Q8 — 그라운딩 게이트 위치
자율 루프에서 날조 금지(C-2, BR-NV9~11)를 어디서 강제하나?

- **A) 산출물 저장 시점 결정론 검증** — 에이전트가 산출물 저장 도구를 호출할 때마다 SourceRef 실재성·필수 필드·bounded 후보 규칙을 결정론(LLM-judge 없음)으로 검사, 위반 시 저장 거부 + 오류를 에이전트에 반환(재시도 기회). U7 결정론 게이트 원칙과 동형. (권장)
- **B) 루프 출구 일괄 검증** — 종료 시점에 전 산출물 검사. *구현 단순 / 위반 발견이 늦어 예산 낭비, 부분 실패 처리 복잡.*
- **C) LLM-judge 검증** — *U7 결정론 원칙·눈금 고정 정신과 상충 → 기각 후보.*
- **X) 기타**

[Answer]:

#### Q9 — 루프 예산 정책
루프 폭주를 무엇으로 막나? (수치 임계는 NFR Requirements로 이월 — 여기선 정책만)

- **A) 3중 한도** — 최대 반복 수 + 도구 호출 수(도구별 상한 포함) + 토큰/비용 한도(U6 `get_budget_state()` 단일 권위 유지). 소진 시 지금까지 검증된 산출물로 `degraded` 종료(BR-NV16 승계). (권장)
- **B) 토큰 한도만** — *단순 / 무한 저비용 루프(같은 검색 반복 등)를 못 막음.*
- **C) 무제한** — *기각 후보.*
- **X) 기타**

[Answer]:

#### Q10 — 취소·재개 시맨틱
루프 중 취소와 재개를 어떻게 정의하나?

- **A) 협조적 취소 + v1 재개 미지원** — 취소 신호 시 현재 도구 호출 완료 후 루프 탈출, 저장·검증된 산출물은 유지(CANCELLED 상태). 재개는 새 잡으로(세션 메모리가 이전 산출물 참조 — Q6). (권장)
- **B) 체크포인트 재개 지원** — 루프 상태(대화 이력·도구 결과)를 영속해 이어서 실행. *가치 / 상태 영속·버전 관리 복잡도↑.*
- **C) 즉시 강제 종료** — *진행 중 도구 호출 유실·정합성 위험.*
- **X) 기타**

[Answer]:

#### Q11 — 외부·MCP 프라이버시 경계
BR-NV6(외부 검색에 원문·Evidence 전문·원고 전문 금지)을 MCP 시대에 어떻게 확장하나?

- **A) 승계 + 서버별 payload allowlist** — 외부로 나가는 도구(GitHub/데이터셋/arXiv MCP)마다 허용 payload(topic·키워드·익명화 요약·논문 제목·기술명)를 규칙으로 명시. 에이전트가 도구 인자를 자유 구성하더라도 어댑터가 결정론 sanitize/차단. (권장)
- **B) MCP 서버를 신뢰 경계 내부로 간주** — 제한 없음. *셀프호스트여도 프롬프트 인젝션 경유 유출 경로가 열림 → 기각 후보.*
- **X) 기타**

[Answer]:

### D. 문서·경계

#### Q12 — 요구사항 앵커
FR 레벨 개정이 필요한가?

- **A) FR-30~35 유지 + FD 문서가 재설계 근거를 명시** — 유닛의 약속(입력·출력·진행표시·export)은 불변, 바뀌는 것은 오케스트레이션 방식이므로 FR 개정 없이 FD 헤더에 로드맵 ⑤를 재설계 근거로 인용. (권장)
- **B) requirements.md 개정판 선행** — 세션 메모리·멀티모달을 신규 FR로 등재 후 FD 진행. *엄밀 / 이번 범위(④=문서)에 인셉션 라운드가 추가됨.*
- **X) 기타**

[Answer]: X — 아키텍처 질문지 Q7=A 상속: **소규모 개정 블록 선행**(기존 개정 관례 형식). 델타 5건 — ① 외부 탐색 메커니즘 중립화(FR-31 Agent-Browser → 외부 탐색 어댑터, MCP 포함) ② 세션 메모리 신규 FR ③ 진행상태 enum 재해석 각주(FR-35) ④ 루프 예산·반복 상한 FR ⑤ 결정 추적성 FR. 이번 범위는 문서만.

#### Q13 — 기존 BR-NV 규칙 승계 방식
`business-rules.md`를 어떻게 쓰나?

- **A) 승계 표 + 델타 중심** — BR-NV1~19 각각에 유지/개정/폐기 판정 표를 두고, 루프 신설 규칙(BR-RA-*)만 상세 기술. *리뷰 가능성↑·⑤ 구현 시 대조 용이.* (권장)
- **B) 전면 재작성** — 새 규칙 체계로 처음부터. *일관성 / 현행 대비 무엇이 바뀌었는지 추적 어려움.*
- **X) 기타**

[Answer]:

#### Q14 — U11 evidence 의존의 위치
BR-NV2(Evidence First — 자연어 경로는 `form_evidence` 선행)를 루프에서 어떻게 다루나?

- **A) 선행 강제 유지** — 자연어 잡은 루프 시작 전(또는 첫 도구로) evidence 형성을 강제. BR-NV2 그대로, 근거 없는 탐색 방지. (권장)
- **B) 루프 자율 + 산출물 게이트로 간접 강제** — 호출 시점은 에이전트 재량, 단 EVIDENCE 산출물 없이는 NOVELTY_CANDIDATES 저장이 거부됨(Q8 게이트). *자율성↑ / 근거 없이 외부 검색부터 도는 경로 허용.*
- **X) 기타**

[Answer]:

## 4. 답변 후 생성할 산출물 요약

- `domain-entities.md`: NoveltyJob(승계) · AgentLoopRun · ToolCallRecord · SessionMemory(Q6) · ArtifactRef(승계) · ProgressEvent 투영 모델(Q2) · 루프 예산 모델(Q9) — 기존 엔티티 승계/신설 구분 명시
- `business-logic-model.md`: 루프 수명주기(시작→도구 선택→검증 저장→종료 조건), 진행상태 투영, 취소, 예산 소진, degraded 경로, ⑤ 4단계(루프→MCP→메모리→멀티모달) 단계별 도입 지도
- `business-rules.md`: BR-NV1~19 승계/개정/폐기 표(Q13) + 루프 신설 규칙(그라운딩 게이트, 예산, 프라이버시 allowlist, Notion 루프 밖 경계) + PBT 속성 + 추적성 매트릭스(FR-30~35·QT-10 미커버 0)
