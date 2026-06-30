# U11 차별화(novelty) 에이전트 — 요구사항 재스코핑 질문

- **단계**: INCEPTION → Requirements Analysis 재진입 / 기존 U11 산출물 개정
- **일자**: 2026-06-28
- **대상 유닛**: U11 Research Agent
- **개발 대상**: `차별화(novelty) 에이전트`
- **비대상**: `문헌탐색 & 근거형성 에이전트` 구현. 해당 에이전트는 U11 내 병렬 에이전트지만 별도 과정에서 개발한다.

## 전제 정정

본 작업은 신규 유닛을 새로 여는 작업이 아니다. U11은 이미 User Stories와 Functional Design까지 승인된 유닛이며, 기존 체인은 `1개 Research Agent + 2개 모드` 구조였다.

- 기존 모드 A: 문헌탐색 & 근거형성
- 기존 모드 B: novelty 비교 seam, 다음 사이클
- 기존 FD 엔티티: `EvidenceTable`, `PaperEvidence`, `EvidenceItem`, `Anchor`, `EvidenceRow`, `CrossCheckTag`

이번 질문지는 기존 U11 산출물을 `2개 병렬 에이전트 + novelty 에이전트 개발 우선` 구조로 재스코핑할지 확인한다. 따라서 답변 결과는 `requirements.md`, `stories.md`, U11 Functional Design의 개정 범위를 결정한다.

## 답변 방법

각 질문의 `[Answer]:` 뒤에 선택지 문자를 입력해 주세요. 답변이 비어 있으면 Recommended 옵션으로 진행합니다. 선택지가 맞지 않으면 마지막 `X) Other`를 선택하고 원하는 내용을 적어 주세요.

---

## Question 1
기존 U11 요구사항을 novelty 에이전트 기준으로 어떻게 재스코핑할까요?

A) FR-22는 문헌탐색&근거형성 에이전트로 분리하고, FR-23은 U11 novelty 에이전트 요구사항으로 개정한다. FR-24/25, NFR-P5, NFR-C1, QT-8은 두 에이전트의 공통 계약으로 유지한다. (Recommended)

B) 기존 FR-22~25를 유지하고 novelty 에이전트 요구사항을 신규 FR로 추가한다.

C) 기존 FR-22~25를 폐기하고 novelty 에이전트 요구사항으로 완전히 대체한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X — A의 구조(문헌탐색&근거형성 분리 + 공통 계약 유지) 채택. 단 FR-22~25는 PR #232에서 폐기되어(FR-21→FR-26 번호 공백 유지) 더 이상 존재하지 않으므로 "FR-23 개정"이 아니라 novelty 에이전트를 **신규 FR**(현재 상한 FR-29 → FR-30+)로 등재한다. 공통 계약(EvidenceBundle/source reference/비용/QT)은 A와 동일하게 두 에이전트가 공유.

## Question 2
논문 업로드가 있을 때 문헌탐색&근거형성 에이전트와 novelty 에이전트의 호출 관계는 어떻게 둘까요?

A) 공통 U11 orchestrator가 업로드 입력을 감지해 문헌탐색&근거형성 에이전트를 먼저 호출하고, novelty 에이전트는 그 산출물만 소비한다. novelty 에이전트는 해당 에이전트를 구현하지 않는다. (Recommended)

B) novelty 에이전트가 문헌탐색&근거형성 에이전트를 직접 sub-agent로 호출한다.

C) 업로드 입력이어도 novelty 에이전트만 실행하고 upstream 산출물은 사용하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
novelty 에이전트 v1의 입력은 무엇인가요?

A) 연구 의도 텍스트, 또는 공통 orchestrator가 생성한 upstream Evidence artifact 중 하나 이상을 입력으로 받는다. 원문 업로드 파싱은 novelty 에이전트 범위 밖이다. (Recommended)

B) 사용자의 논문 초안 파일을 novelty 에이전트가 직접 파싱한다.

C) upstream Evidence artifact만 입력으로 받는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4
upstream 산출물과 기존 U11 FD 엔티티의 관계는 어떻게 정할까요?

A) 신규 `EvidenceBundle`은 기존 `EvidenceTable`, `PaperEvidence`, `EvidenceItem`, `Anchor`를 감싸는 공통 wrapper로 정의한다. 기존 엔티티는 재사용하고 필요한 필드만 승격한다. (Recommended)

B) `EvidenceBundle`을 완전히 신규 DTO로 만들고 기존 FD 엔티티와 별도로 둔다.

C) 신규 DTO 없이 기존 `EvidenceTable`만 그대로 넘긴다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 단 EvidenceBundle은 novelty 단독 정의가 아니라 문헌탐색&근거형성 유닛(페이즈 4)과 공동 동결한다(차터 D5/§4.1; 해당 유닛 Q1~Q3가 evidence DTO를 잠금).

## Question 5
공통 source reference 계약은 어느 수준이어야 하나요?

A) 모든 근거는 `sourceId`, `sourceType`, `title`, `url`, `retrievedAt`, `snippet`, 내부 corpus `paperId/version/blockRefs`, doc-model `StructuredLocator` 중 가능한 값을 포함한다. (Recommended)

B) URL과 제목만 있으면 충분하다.

C) 내부 corpus 근거만 source reference로 인정한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6
novelty 에이전트의 제품 약속은 무엇인가요?

A) "새롭다/아니다" 판정은 하지 않고, 유사 연구·겹치는 점·차별화 가능한 지점·불확실성을 근거와 함께 제시한다. (Recommended)

B) novelty 점수와 "논문화 가능성" 판정을 제공한다.

C) 유사 논문 목록만 제공하고 차별화 지점은 사용자가 판단한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 7
내부 corpus retrieval은 novelty 에이전트에서 어떤 역할인가요?

A) 1차 비교 근거다. U1 Corpus / U2 Discovery 인덱스를 먼저 검색하고, 외부 검색은 보강으로 사용한다. (Recommended)

B) 외부 검색과 동등한 여러 소스 중 하나다.

C) 내부 corpus는 사용하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 8
GitHub, 최신 뉴스, 데이터셋 검색은 기존 U11 범위를 넘어서는 신규 외부 source 확장이다. v1에서 어디까지 승인할까요?

A) GitHub, 최신 뉴스, 관련 데이터셋 검색을 모두 v1에 포함한다. 단, FR-23/§12/C-6의 novelty 한정 외부 source 카브아웃으로 명시하고 source별 budget·grounding·degraded 상태를 둔다.

B) GitHub 검색과 데이터셋 검색만 v1에 포함하고, 뉴스는 다음 사이클로 둔다. (Recommended)

C) 외부 탐색은 모두 다음 사이클로 두고 내부 corpus만 사용한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: B — GitHub·데이터셋만 v1, 뉴스는 다음 사이클. (이 선택이 Q11을 C로 강제한다.)

## Question 9
Agent-Browser 사용 방식은 어떻게 제한할까요?

A) 서버 측 U11 novelty Agent Worker에서만 실행하고, 결과 URL·타임스탬프·스니펫·근거만 저장한다. 사용자 원문/EvidenceBundle 전체는 외부 사이트에 보내지 않는다. (Recommended)

B) 품질을 위해 사용자 원문/EvidenceBundle 전체를 외부 사이트 검색 질의에 사용할 수 있다.

C) Agent-Browser는 PoC에서만 사용하고 프로덕션은 공식 API로 대체한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 10
GitHub 검색 결과는 novelty 분석에서 어떻게 사용할까요?

A) 관련 구현체·baseline 코드·벤치마크 코드·재현 단서를 찾되, "재현 가능" 판정은 하지 않고 사실 추출만 한다. (Recommended)

B) repository star/fork/license 기준으로 구현체 품질 점수까지 산출한다.

C) 참고 링크로만 표시하고 novelty 분석에는 반영하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 11
최신 뉴스 검색 결과는 novelty 분석에서 어떻게 사용할까요?

A) 최근 동향·산업 적용·출시·정책 보강 근거로만 사용하고, 학술 novelty 근거는 논문/데이터셋/코드를 우선한다. (Recommended)

B) 뉴스도 논문과 같은 수준의 novelty 근거로 사용한다.

C) 뉴스 검색은 v1에서 제외한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: C — Q8=B로 뉴스가 다음 사이클이므로 v1 제외. (Q8을 A로 바꿔 뉴스를 v1에 포함하면 Q11=A로 전환.)

## Question 12
관련 데이터셋 검색 결과는 어떤 출력에 반영할까요?

A) 실험 아이디어와 실험 계획에 반영한다: 데이터셋 이름, 출처 URL, 라이선스/접근성, 평가 가능 태스크를 추출한다. (Recommended)

B) 데이터셋 이름과 링크만 표시한다.

C) 데이터셋 검색은 수동 참고 자료로만 저장하고 출력에는 반영하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 13
기존 한계 분석의 출력 범위는 무엇인가요?

A) 검색된 논문/코드/데이터셋 근거에서 추출 가능한 한계만 표로 정리하고, 근거 없는 한계는 기권한다. (Recommended)

B) LLM이 일반 지식으로 가능한 한계를 추론해 추가한다.

C) 한계 분석은 실험 아이디어 뒤의 부록으로만 제공한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 14
실험 아이디어 생성은 기존 U11 FD에 없던 신규 산출물이다. C-2 경계 안에서 어디까지 허용할까요?

A) 기존 연구 한계와 데이터셋/코드 근거를 바탕으로 bounded 실험 아이디어 후보만 생성한다. 논문 문장·문헌리뷰 산문·연구 갭 산문은 생성하지 않는다. (Recommended)

B) contribution 문장, related work 문단, 연구 갭 산문 초안까지 생성한다.

C) 실험 아이디어 생성은 제외하고 유사 연구 비교만 제공한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 15
실험 계획도 기존 U11 FD에 없던 신규 산출물이다. 최소 산출물은 무엇인가요?

A) 가설, 비교 baseline, 데이터셋, metric, 실험 절차, 예상 리스크, 필요한 구현/리소스, 근거 링크를 포함한다. 코드 skeleton은 생성하지 않는다. (Recommended)

B) 간단한 bullet list 수준의 실험 아이디어와 TODO만 포함한다.

C) 재현 가능한 코드 skeleton까지 생성한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 16
Notion 저장은 신규 외부 통합이다. 어떤 보안/운영 계약으로 제공할까요?

A) 사용자 OAuth 연결 또는 명시적 Notion token 연결을 사용하고, 토큰은 Secrets/암호화 저장한다. 저장 전 미리보기·사용자 승인·재시도 실패 표시·연결 해제/삭제를 제공한다. (Recommended)

B) 분석 완료 후 자동으로 Notion에 저장하고 실패는 내부 로그만 남긴다.

C) Notion 저장은 v1에서 제외하고 Markdown export만 제공한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — Notion을 v1에 포함할 경우의 보안 계약. (Notion이 하드 v1 요건이 아니면 C(다음 사이클·Markdown export만)도 수용 가능.)

## Question 17
DocSuri 내부 저장과 Notion 저장의 관계는 어떻게 둘까요?

A) 내부 DB/S3에 owner-scoped 세션과 결과를 저장하고, Notion은 선택적 외부 export로 둔다. (Recommended)

B) Notion에만 저장하고 DocSuri에는 저장하지 않는다.

C) 세션 중에만 유지하고 저장하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 18
U11 novelty 에이전트 실행 방식은 무엇이 적합한가요?

A) API는 job 생성/상태 조회만 담당하고, 별도 U11 Agent Worker가 SQS job을 처리한다. MCP/Agent-Browser/Notion tool은 worker 내부 sidecar 또는 internal gateway로만 접근한다. (Recommended)

B) Backend API 컨테이너 안에서 동기 요청으로 모두 처리한다.

C) Lambda 중심으로 agent loop와 tool call을 처리한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 19
성능/응답 UX는 어떻게 잡을까요?

A) U7/U8처럼 온디맨드 비동기 작업으로 둔다. 진행 상태, 부분 결과, 실패 소스 표시, 재시도/취소, 재접속 후 상태 조회를 제공한다. (Recommended)

B) 검색과 동일하게 P50 3초 내 전체 결과를 반환해야 한다.

C) 결과가 완성될 때까지 화면을 blocking 상태로 둔다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 20
비용과 사용량 제한은 어떻게 둘까요?

A) 기존 NFR-C1 안에서 U6 CostGuard와 rate limit을 재사용하고, 외부 검색/LLM/tool call 횟수에 per-job budget을 둔다. 초과 시 부분 결과와 기권을 반환한다. (Recommended)

B) U11 전용 월 예산을 새로 신설한다.

C) v1에서는 비용 제한 없이 품질을 우선한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 21
품질 게이트(QT)는 어떻게 나눌까요?

A) QT-8을 공통 산출물 게이트와 novelty 자체 게이트로 분리한다. 공통 게이트는 EvidenceBundle/source reference 무결성, novelty 게이트는 유사 연구 적중·차별화 후보 근거·tool 장애 저하·Notion 저장 무결성을 본다. (Recommended)

B) 기존 QT-8을 그대로 사용한다.

C) 수동 QA만 수행하고 자동 품질 게이트는 두지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X — A 구조(공통 산출물 게이트 + novelty 자체 게이트) 채택. 단 QT-8은 PR #232에서 폐기되어(QT-9까지 생존, QT-8 공백) 존재하지 않으므로 "QT-8 분리"가 아니라 **신규 QT**(QT-9 → QT-10)로 등재한다.

## Question 22
upstream EvidenceBundle과 외부 tool 호출의 프라이버시 경계는 어떻게 둘까요?

A) 원문/EvidenceBundle은 DocSuri 내부 저장소/LLM 입력에만 사용하고, 외부 웹 검색에는 최소 질의어·키워드·익명화된 요약만 보낸다. 사용자 삭제/초기화 기능을 제공한다. (Recommended)

B) 품질을 위해 원문/EvidenceBundle 전체를 외부 검색/tool provider에 보낼 수 있다.

C) 원문/EvidenceBundle은 저장하지 않고 처리 직후 삭제한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 23
Security Extensions
Should security extension rules be enforced for U11 novelty agent?

A) Yes — enforce all SECURITY rules as blocking constraints. (Recommended)

B) No — skip all SECURITY rules for U11 novelty agent.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 24
Resiliency Extensions
Should the resiliency baseline be applied to U11 novelty agent?

A) Yes — apply the existing project setting: Resiliency Baseline Full, all 15 rules as blocking constraints. (Recommended)

B) No — skip the resiliency baseline for U11 novelty agent.

C) Change U11 resiliency mode from Full blocking to directional guidance only.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 25
Property-Based Testing Extension
Should property-based testing rules be enforced for U11 novelty agent?

A) Yes — enforce PBT rules as blocking constraints for U11 business logic and serialization/state invariants.

B) Partial — enforce PBT only for pure functions, DTO round-trips, session state invariants, EvidenceBundle/source reference invariants, and tool-result normalization. (Recommended)

C) No — skip PBT rules for U11 novelty agent.

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 26
이번 사이클의 산출물 범위는 어디까지인가요?

A) Requirements만 개정한다.

B) Requirements와 User Stories를 개정한다.

C) Requirements, User Stories, 기존 U11 Functional Design 개정 계획까지 진행한다. (Recommended)

D) Construction 코드 구현까지 바로 진행한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: C — Requirements + User Stories + U11 FD 개정 계획. 단 FD 개정은 모놀리식 U11 FD 패치가 아니라 페이즈 4(문헌탐색&근거형성) + 페이즈 5(novelty) FD로의 분해다.
