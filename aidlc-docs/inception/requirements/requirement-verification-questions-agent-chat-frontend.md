# Agent Chat Frontend — Requirement Verification Questions

**Stage**: INCEPTION / Requirements Analysis
**Date**: 2026-06-30
**Scope**: 프론트엔드 Agent 채팅 진입점, 세션 목록, 멀티턴 채팅, 파일 첨부, 탐구 프로세스 표시

## Fixed Input From User

- 내비게이션 바 가운데에 Agent 진입점을 추가한다.
- Agent 화면은 멀티턴 채팅을 지원한다.
- 채팅 시작 시 `문헌탐색&근거형성` 또는 `novelty` 중 하나를 선택한다.
- 선택한 agent mode는 이후 변경할 수 없다.
- 화면 왼쪽 위에 메뉴바를 만들어 과거 세션을 로딩한다.
- 파일 추가 버튼은 채팅바 왼쪽 `+` 버튼으로 둔다.
- 에이전트의 탐구 프로세스 과정이 프론트에 출력되어야 한다.

## Question 1
Agent 진입점의 라벨은 무엇으로 표시할까요?

A) `에이전트`로 표시한다. 하단 내비게이션의 검색/에이전트/마이페이지 3탭 구조로 둔다. (Recommended)

B) `AI 연구`로 표시한다. 기능 범위를 넓게 보이게 한다.

C) `채팅`으로 표시한다. 사용자에게 가장 익숙한 대화 진입점으로 둔다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 라벨은 추후 변경 가능성을 열어두되, v1은 검색/에이전트/마이페이지 3탭 구조로 둔다.

## Question 2
Agent 화면의 기본 route는 무엇으로 둘까요?

A) `/agent` 단일 route를 만들고 내부에서 mode 선택 및 세션 로딩을 처리한다. (Recommended)

B) `/agent/evidence`와 `/agent/novelty`를 별도 route로 나눈다. 단, 최초 선택 후 다른 mode route 이동은 막는다.

C) `/chat` 단일 route로 둔다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — `/agent` 단일 route에서 mode 선택과 세션 로딩을 처리한다. 세션 도중 mode 간 전환은 막는다.

## Question 3
새 채팅 시작 시 mode 선택 화면은 어떤 방식이 좋을까요?

A) 빈 채팅 첫 화면 중앙에 두 개의 큰 선택 버튼을 표시하고, 선택 직후 채팅 입력창을 활성화한다. (Recommended)

B) 첫 메시지 입력 전 작은 segmented control로 선택하게 한다.

C) 첫 메시지를 보내는 순간 modal로 선택하게 한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X — 챗봇의 채팅창처럼 모드를 선택할 수 있게 한다. 둘 중 하나를 선택한 직후 채팅 입력창을 활성화한다.

## Question 4
mode 선택 후 변경 불가를 UI에서 어떻게 표현할까요?

A) 채팅 상단에 고정 badge로 mode를 표시하고 변경 버튼은 제공하지 않는다. (Recommended)

B) mode badge를 클릭하면 "이 채팅에서는 변경할 수 없음" 안내만 보여준다.

C) 변경 버튼을 보여주되 누르면 새 세션 생성으로 유도한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: C — 변경 버튼을 보여주되 누르면 현재 세션의 mode를 바꾸지 않고 새 세션 생성으로 유도한다.

## Question 5
과거 세션 메뉴는 어떤 범위까지 구현할까요?

A) 왼쪽 위 메뉴 버튼을 누르면 세션 drawer를 열고, 세션 목록/새 채팅/삭제를 제공한다. (Recommended)

B) 세션 drawer에는 세션 목록/새 채팅만 제공하고 삭제는 후속으로 둔다.

C) 세션 drawer에는 최근 세션 목록만 표시하고 관리는 마이페이지로 넘긴다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — ChatGPT/Gemini와 유사한 왼쪽 drawer 방식으로 세션 목록, 새 채팅, 삭제를 제공한다.

## Question 6
세션 목록의 표시 정보는 무엇이 적합할까요?

A) 제목, agent mode, 마지막 업데이트 시간, 최종 상태를 표시한다. (Recommended)

B) 제목과 마지막 메시지만 표시한다.

C) 제목 없이 날짜별 세션만 표시한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 제목, agent mode, 마지막 업데이트 시간, 최종 상태를 표시한다.

## Question 7
멀티턴 채팅에서 backend API 연결 범위는 어디까지로 둘까요?

A) 프론트 mock transport를 먼저 만들고, 실제 API는 기존 `/api/novelty/*`와 향후 evidence agent API 계약에 맞춰 seam만 둔다. (Recommended)

B) novelty는 실제 `/api/novelty/*`에 연결하고, 문헌탐색&근거형성은 mock으로 둔다.

C) 두 agent 모두 실제 backend API가 완성될 때까지 프론트 구현을 보류한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 프론트 mock transport를 먼저 만들고, 실제 API는 `/api/novelty/*`와 evidence agent API 계약에 맞춰 seam을 둔다.

## Question 8
채팅 메시지와 agent 진행 이벤트는 화면에서 어떻게 배치할까요?

A) 채팅 메시지 사이에 "탐구 과정" step timeline을 접을 수 있는 블록으로 표시한다. (Recommended)

B) 화면 오른쪽/하단 별도 패널에 탐구 과정을 항상 표시한다.

C) assistant 답변 bubble 안에 단계별 진행 로그를 모두 누적 표시한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 채팅 메시지 사이에 "탐구 과정" step timeline을 접을 수 있는 블록으로 표시한다.

## Question 9
탐구 프로세스에서 사용자에게 노출할 정보 수준은 어디까지가 좋을까요?

A) 현재 단계, 사용한 source 종류, 검색 질의 요약, 발견 수, degraded/failed 이유의 사용자용 메시지만 표시한다. 내부 로그와 원문 payload는 숨긴다. (Recommended)

B) 각 tool call의 입력/출력 요약을 더 자세히 보여준다.

C) 최종 답변 전에는 단계 이름과 로딩 상태만 보여준다.

X) Other (please describe after [Answer]: tag below)

[Answer]: B — 각 tool call의 입력/출력 요약을 더 자세히 보여준다. v1에서는 사용자에게 불필요한 내부 원문 payload와 민감한 내부 로그는 숨긴다.

## Question 10
파일 첨부 `+` 버튼은 v1에서 어떤 파일을 허용할까요?

A) novelty 원고 입력 계약과 맞춰 PDF, Markdown, TXT만 허용한다. 문헌탐색&근거형성도 같은 제한을 사용한다. (Recommended)

B) PDF만 허용한다.

C) PDF, Markdown, TXT에 DOCX까지 허용한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — novelty 원고 입력 계약과 맞춰 PDF, Markdown, TXT만 허용한다. 문헌탐색&근거형성도 같은 제한을 사용한다.

## Question 11
첨부 파일은 어떤 UX로 표시할까요?

A) 채팅 입력창 위에 첨부 chip 목록을 표시하고, 전송 전 삭제할 수 있게 한다. (Recommended)

B) `+` 버튼을 누르면 별도 첨부 drawer에서 관리한다.

C) 첨부 완료 후 첫 사용자 메시지 bubble 안에만 표시한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: B — `+` 버튼을 누르면 별도 첨부 drawer에서 파일을 관리한다.

## Question 12
실패/저하 상태는 어떻게 표시할까요?

A) 실패는 명확한 상태 화면과 재시도/새 채팅 버튼을 제공하고, degraded는 부분 결과 상단에 출처별 저하 banner를 표시한다. (Recommended)

B) 실패/degraded 모두 assistant 메시지 안의 짧은 경고로만 표시한다.

C) 실패 시 세션을 종료하고 새 채팅으로만 유도한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 실패는 명확한 상태 화면과 재시도/새 채팅 버튼을 제공하고, degraded는 부분 결과 상단에 출처별 저하 banner를 표시한다. 재시도 로직도 포함한다.

## Question 13
Notion export는 Agent 채팅 프론트 v1에 포함할까요?

A) novelty 결과 화면에서 preview/approve 버튼만 제공하고 실제 export 상태는 기존 backend 계약을 따른다. (Recommended)

B) Notion export UI는 이번 프론트 v1에서 제외한다.

C) 두 agent 모두 Notion export UI를 제공한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: B — Notion export UI는 이번 프론트 v1에서 제외한다.

## Question 14
Security extension rules should be enforced for this frontend change?

A) Yes — enforce all SECURITY rules as blocking constraints. Existing project security baseline remains active. (Recommended)

B) No — skip SECURITY rules for this frontend change.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 기존 프로젝트 보안 baseline을 유지하고 이번 frontend 변경에도 blocking constraints로 적용한다.

## Question 15
Should the resiliency baseline be applied to this frontend change?

A) Yes — apply the resiliency baseline as design-time guidance. Existing project resiliency baseline remains active. (Recommended)

B) No — skip the resiliency baseline for this frontend change.

X) Other (please describe after [Answer]: tag below)

[Answer]: A — 기존 프로젝트 resiliency baseline을 이번 frontend 변경에도 design-time guidance로 적용한다.

## Question 16
Should property-based testing rules be enforced for this frontend change?

A) Partial — apply PBT only to pure helpers such as session normalization, event ordering, and response classifiers. UI rendering uses example-based tests. (Recommended)

B) Yes — enforce full PBT rules for all frontend logic.

C) No — skip PBT rules for this frontend change.

X) Other (please describe after [Answer]: tag below)

[Answer]: B — frontend 로직에도 full PBT rules를 적용한다.
