# 차별화(novelty) 형성 Agent — 요구사항 명확화 질문

**단계**: INCEPTION → Requirements Analysis
**일자**: 2026-06-29
**대상 기능**: 차별화(novelty) 형성 Agent
**연관 기능**: 문헌탐색·근거형성 Agent, U2 전문 Full 검색, Agent-Browser 외부 검색, Notion MCP 저장
**상태**: 확정 — `requirement-verification-questions-answer-1.md` 답변 반영

## 전제

이번 질문지는 차별화(novelty) 형성 Agent 구현 범위를 확정하기 위한 요구사항 질문지입니다.

입력은 두 갈래입니다.

1. 자연어 연구 의도: 사용자가 "~~~를 연구하고 싶다" 유형의 자연어를 입력합니다.
2. 작성 중인 논문 문서류: 사용자가 초안, 원고, 실험 계획 문서 등을 업로드합니다.

두 경로 모두 내부 corpus retrieval과 U2 전문 Full 검색 기능을 활용하며, GitHub/뉴스/데이터셋 검색은 Agent-Browser 기반 외부 탐색으로 다룹니다. 문헌탐색·근거형성 Agent와의 공유계약은 `EvidenceFormationPort`/`SourceRef` 계약을 준수합니다.

## 답변 방법

각 질문의 `[Answer]:` 뒤에 선택지 문자를 입력해 주세요. 선택지가 맞지 않으면 마지막 `X) Other`를 선택하고 원하는 내용을 적어 주세요.

---

## Question 1
이번 사이클에서 유닛 경계는 어떻게 둘까요?

A) 문헌탐색·근거형성 Agent와 차별화(novelty) Agent를 별도 유닛으로 두고, novelty Agent는 공유계약(`EvidenceFormationPort`, `SourceRef`)을 통해 upstream 근거만 소비한다. (권장)

B) 두 에이전트를 하나의 Research Agent 유닛 안에 두고 내부 모드만 나눈다.

C) novelty Agent가 문헌탐색·근거형성 Agent의 내부 구현까지 직접 호출한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 2
자연어 입력 경로에서 문헌탐색·근거형성 Agent를 언제 호출할까요?

A) 자연어 입력도 먼저 `EvidenceFormationPort.form_evidence`를 호출해 근거 묶음을 만든 뒤 novelty Agent가 소비한다. (권장)

B) 자연어 입력은 novelty Agent가 U2 Full 검색과 외부 검색을 직접 수행하고, 문헌탐색·근거형성 Agent는 문서 업로드 경로에서만 사용한다.

C) 자연어 입력은 내부 corpus retrieval만 사용하고 외부 검색은 생략한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 3
논문 문서 업로드 경로에서 문서 파싱 책임은 어디에 둘까요?

A) 문헌탐색·근거형성 Agent 또는 공통 ingestion/doc-model 파이프라인이 업로드 문서를 파싱하고, novelty Agent는 파싱된 Evidence/SourceRef만 소비한다. (권장)

B) novelty Agent가 업로드 문서 파싱, 청킹, 근거 추출까지 직접 수행한다.

C) v1에서는 문서 업로드를 텍스트 추출만으로 처리하고 doc-model 파싱은 제외한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 4
업로드 문서 형식은 v1에서 어디까지 지원할까요?

A) PDF, DOCX, Markdown, TXT를 지원하고, 실패 시 사용자에게 파싱 실패 사유를 노출한다. (권장)

B) PDF만 지원한다.

C) Markdown/TXT만 지원하고 PDF/DOCX는 다음 사이클로 미룬다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — DOCX 파서는 신규 의존성 비용이 있으나, 원고 형식 사용성을 위해 v1에 포함한다.

## Question 5
업로드 문서 청킹은 어떤 기준으로 검색 질의를 만들까요?

A) 제목/초록/문제정의/방법/실험/결론 섹션을 우선 추출하고, 각 섹션 요약 질의와 핵심 키워드 질의를 함께 만든다. (권장)

B) 고정 토큰 길이로만 청킹해 각 chunk를 검색 질의로 사용한다.

C) 사용자가 직접 검색 키워드를 지정하게 하고 자동 청킹 질의는 만들지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 6
U2 전문 Full 검색 기능은 novelty Agent에서 어떻게 사용할까요?

A) U2의 기존 검색 API/포트를 재사용하고, novelty Agent는 별도 검색 인덱스나 랭킹 로직을 만들지 않는다. (권장)

B) novelty Agent 전용 retrieval adapter를 만들되 U2 인덱스만 공유한다.

C) novelty Agent 전용 인덱스를 새로 만든다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 7
U2 검색 결과와 `EvidenceFormationPort` 결과가 모두 있을 때 우선순위는 어떻게 둘까요?

A) EvidenceFormationPort 결과를 1차 근거로 삼고, U2 Full 검색은 누락 보강과 유사 논문 확장에 사용한다. (권장)

B) U2 Full 검색 결과를 1차 근거로 삼고, EvidenceFormationPort 결과는 보조 설명으로만 사용한다.

C) 둘을 같은 가중치로 합치고 중복 제거만 수행한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 8
외부 검색 범위는 v1에서 어디까지 포함할까요?

A) GitHub 검색, 최신 뉴스 검색, 관련 데이터셋 검색을 모두 v1에 포함한다. (권장)

B) GitHub 검색과 데이터셋 검색만 v1에 포함하고 뉴스는 다음 사이클로 둔다.

C) 외부 검색은 모두 다음 사이클로 두고 내부 corpus만 사용한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: B — GitHub·데이터셋만 v1에 포함하고, 뉴스는 다음 사이클로 둔다.

## Question 9
Agent-Browser는 어떤 실행 경계에서 사용할까요?

A) 서버 측 Agent Worker에서만 실행하고, 사용자 원문 전체를 외부 사이트에 보내지 않으며 검색 키워드/익명화 요약만 사용한다. (권장)

B) 품질을 위해 사용자 원문 또는 Evidence 전체를 외부 검색 질의로 사용할 수 있다.

C) Agent-Browser는 개발/PoC에서만 사용하고 프로덕션은 공식 API로 대체한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 10
GitHub 검색 결과는 어떤 역할로 사용할까요?

A) 관련 구현체, baseline 코드, benchmark 코드, reproduction 단서, license 정보를 추출하되 품질 점수나 재현 가능 판정은 하지 않는다. (권장)

B) stars/forks/issues/license를 기반으로 구현체 품질 점수까지 산출한다.

C) 참고 링크로만 보여주고 novelty 분석에는 반영하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 11
최신 뉴스 검색 결과는 어떤 역할로 사용할까요?

A) 최근 동향, 산업 적용, 제품 출시, 정책/규제 변화 보강 근거로만 사용하고 학술 novelty 근거는 논문/코드/데이터셋을 우선한다. (권장)

B) 뉴스도 논문과 같은 수준의 novelty 근거로 사용한다.

C) 뉴스 검색은 v1에서 제외한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A — v1 뉴스 검색은 제외하지만, 다음 사이클에 포함될 경우 보강 근거로만 사용한다.

## Question 12
관련 데이터셋 검색 결과는 어떤 출력에 반영할까요?

A) 실험 아이디어와 실험 계획에 데이터셋 이름, 출처 URL, 라이선스/접근성, 태스크, metric 후보를 반영한다. (권장)

B) 데이터셋 이름과 링크만 표시한다.

C) 데이터셋 검색은 수동 참고 자료로만 저장하고 분석 출력에는 반영하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 13
"기존에 완료된 유사 아이디어 논문 정리" 출력은 어떤 형태가 좋을까요?

A) 유사 논문별 문제정의, 방법, 데이터셋, 결과, 한계, 내 아이디어와 겹치는 점, 근거 SourceRef를 표로 제공한다. (권장)

B) 유사 논문 목록과 한 줄 요약만 제공한다.

C) 가장 유사한 3편만 상세 정리한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 14
차별점이 추가된 실험 아이디어 추천은 어디까지 허용할까요?

A) 기존 연구 한계와 데이터셋/코드 근거를 바탕으로 bounded 실험 아이디어 후보를 제안하되, "새로움 확정" 판정은 하지 않는다. (권장)

B) novelty 점수와 논문화 가능성 판정을 제공한다.

C) 실험 아이디어 생성은 제외하고 유사 연구 비교만 제공한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 15
실험 계획 산출물의 최소 필드는 무엇으로 둘까요?

A) 가설, 차별화 포인트, baseline, 데이터셋, metric, 실험 절차, 리스크, 필요한 구현/리소스, 근거 링크를 포함한다. (권장)

B) 간단한 bullet list와 TODO만 포함한다.

C) 코드 skeleton과 실행 스크립트까지 생성한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 16
문서 업로드 경로의 표절/문장 유사도 검사는 어디까지 제공할까요?

A) 내부 corpus와 업로드 문서 간 문장/문단 유사도 경고를 제공하되, 법적 표절 판정이 아니라 검토 필요 신호로 표시한다. (권장)

B) 외부 웹 전체까지 검색해 표절률을 산출한다.

C) 표절/문장 유사도 검사는 v1에서 제외한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 17
AI 어투 검사는 어떤 제품 약속으로 제공할까요?

A) 확정 판정이 아니라 문체 위험 신호와 수정 권고만 제공하고, false positive 가능성을 UI에 명시한다. (권장)

B) AI 작성 확률 점수를 제공하고 임계치 이상이면 경고한다.

C) AI 어투 검사는 v1에서 제외한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 18
표절/AI 어투 경고는 novelty 산출물과 어떻게 연결할까요?

A) 별도 "원고 위험 신호" 섹션으로 분리하고, novelty 아이디어 추천/실험 계획 생성을 막지 않는다. (권장)

B) 위험 신호가 높으면 novelty 추천을 중단한다.

C) 위험 신호를 novelty 점수에 직접 반영한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 19
에이전트 탐구 프로세스는 프론트에 어떤 수준으로 출력할까요?

A) 단계별 진행 상태, 현재 tool, 검색 질의, 발견한 출처 수, 부분 결과, 실패/저하 상태를 스트리밍 또는 폴링으로 표시한다. (권장)

B) 전체 작업 완료 후 최종 결과만 표시한다.

C) 내부 tool 실행 로그를 거의 그대로 표시한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 20
프론트 진행상태 이벤트 계약은 어떻게 둘까요?

A) `queued`, `retrieving_corpus`, `searching_external`, `summarizing_prior_work`, `checking_similarity`, `forming_ideas`, `planning_experiment`, `exporting_notion`, `completed`, `failed`, `degraded` 같은 상태 enum을 둔다. (권장)

B) 자유 텍스트 로그만 스트리밍한다.

C) 퍼센트 진행률만 제공한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 21
실행 방식은 어떻게 둘까요?

A) API는 job 생성/상태 조회/취소만 담당하고, 별도 Agent Worker가 U2 검색, Agent-Browser, LLM, Notion MCP 호출을 처리한다. (권장)

B) API 요청 안에서 동기적으로 전체 agent loop를 처리한다.

C) 전부 클라이언트에서 직접 tool을 호출한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 22
Notion 저장은 어떤 방식으로 제공할까요?

A) DocSuri 내부에 owner-scoped 결과를 먼저 저장하고, 사용자가 미리보기 후 승인하면 Notion MCP로 선택 export한다. (권장)

B) 분석이 끝나면 자동으로 Notion에 저장한다.

C) v1에서는 Notion 저장을 제외하고 Markdown export만 제공한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 23
Notion 인증/권한은 어떻게 처리할까요?

A) 사용자별 Notion OAuth 또는 명시적 연결을 사용하고, 토큰은 암호화 저장하며 연결 해제/삭제를 제공한다. (권장)

B) 서버 공용 Notion token 하나로 저장한다.

C) 사용자가 매번 임시 token을 붙여 넣는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 24
결과 저장 정책은 어떻게 둘까요?

A) DocSuri 내부 DB/S3에 owner-scoped 세션, 입력 참조, 단계 이벤트, 최종 결과, export 상태를 저장하고 삭제/초기화를 제공한다. (권장)

B) Notion에만 저장하고 DocSuri에는 저장하지 않는다.

C) 세션 중에만 유지하고 저장하지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 25
외부 검색과 MCP 호출의 프라이버시 경계는 어떻게 둘까요?

A) 원문/Evidence 전체는 내부 처리와 LLM 입력에만 사용하고, 외부 검색/Notion에는 사용자가 승인한 최소 질의·결과만 보낸다. (권장)

B) 품질을 위해 원문/Evidence 전체를 외부 검색과 Notion MCP에 보낼 수 있다.

C) 외부 검색 결과는 저장하지 않고 최종 요약만 저장한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 26
비용과 사용량 제한은 어떻게 둘까요?

A) U6 CostGuard와 rate limit을 재사용하고, U2 검색/LLM/tool call/Agent-Browser/Notion MCP에 per-job budget을 둔다. 초과 시 부분 결과와 `degraded` 상태를 반환한다. (권장)

B) novelty Agent 전용 월 예산과 별도 CostGuard를 새로 만든다.

C) v1에서는 비용 제한 없이 품질을 우선한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 27
실패/저하 처리는 어떻게 보여줄까요?

A) 실패한 source별로 `degraded`를 표시하고, 성공한 내부 corpus/외부 source 결과만으로 부분 산출물을 제공한다. (권장)

B) 하나라도 실패하면 전체 job을 실패 처리한다.

C) 실패 source는 숨기고 최종 결과만 제공한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 28
품질 게이트는 무엇을 검증해야 할까요?

A) SourceRef 무결성, 유사 논문 적중, 외부 source 출처 보존, 표절/AI 어투 경고 false positive 관리, 실험 계획 필수 필드, Notion export 무결성을 검증한다. (권장)

B) 최종 결과가 생성되는지만 검증한다.

C) 수동 QA만 수행하고 자동 품질 게이트는 두지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 29
이번 AI-DLC 사이클의 산출물 범위는 어디까지로 둘까요?

A) Requirements 질문지 작성까지만 진행한다.

B) Requirements와 User Stories까지 진행한다.

C) Requirements, User Stories, Functional Design 계획까지 진행한다. (권장)

D) Construction 코드 구현까지 바로 진행한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: C — Requirements + User Stories + Functional Design 계획까지 진행한다.

## Question 30
보안 확장
이 novelty Agent 작업에 보안 확장 규칙을 적용할까요?

A) 예 — 모든 SECURITY 규칙을 blocking constraint로 적용한다. (권장)

B) 아니요 — 모든 SECURITY 규칙을 건너뛴다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 31
복원력 확장
이 novelty Agent 작업에 resiliency baseline을 적용할까요?

A) 예 — resiliency baseline을 설계 시점의 방향성 있는 best practice와 guidance로 적용한다. (권장)

B) 아니요 — resiliency baseline을 건너뛴다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A

## Question 32
Property-Based Testing 확장
이 novelty Agent 작업에 property-based testing 규칙을 적용할까요?

A) 예 — 모든 PBT 규칙을 blocking constraint로 적용한다.

B) 부분 적용 — pure function, DTO round-trip, source normalization, job state invariant에만 PBT 규칙을 적용한다. (권장)

C) 아니요 — 모든 PBT 규칙을 건너뛴다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: B
