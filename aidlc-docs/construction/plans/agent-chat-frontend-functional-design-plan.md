# 에이전트 채팅 프론트엔드 Functional Design 계획

## 입력

- `aidlc-docs/inception/application-design/agent-chat-frontend-components.md`
- `aidlc-docs/inception/application-design/agent-chat-frontend-component-methods.md`
- `aidlc-docs/inception/user-stories/stories.md`의 US-AG1..US-AG7

## 산출 계획

- [x] `aidlc-docs/construction/agent-chat-frontend/functional-design/domain-entities.md`를 생성한다.
- [x] `aidlc-docs/construction/agent-chat-frontend/functional-design/business-logic-model.md`를 생성한다.
- [x] `aidlc-docs/construction/agent-chat-frontend/functional-design/business-rules.md`를 생성한다.
- [x] `aidlc-docs/construction/agent-chat-frontend/functional-design/frontend-components.md`를 생성한다.

## Functional Design 질문

### 질문 1
세션 mode lock 규칙은 어디까지 강제할까요?

A) reducer와 transport 요청 생성 양쪽에서 강제한다. UI는 변경 버튼 대신 새 채팅 생성만 제공한다. (권장)

B) UI에서만 막고 reducer/transport는 신뢰한다.

C) backend 응답에만 맡긴다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 2
timeline event ordering은 어떤 기준으로 처리할까요?

A) 서버 sequence가 있으면 sequence 우선, 없으면 수신 순서로 append한다. 같은 event id는 멱등 처리한다. (권장)

B) 항상 클라이언트 수신 시간 기준으로 정렬한다.

C) 단계 이름의 고정 순서로 정렬한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 3
첨부 검증 실패는 어떻게 다룰까요?

A) 파일 선택 즉시 allowlist를 검증하고, 거부된 파일은 전송 큐에 넣지 않는다. 오류는 첨부 drawer 안에 표시한다. (권장)

B) 전송 시점에만 검증한다.

C) backend 검증 실패 응답만 표시한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 4
failed와 degraded 상태는 어떻게 구분할까요?

A) 최종 산출물이 없거나 재시도 없이는 계속할 수 없으면 failed, 일부 source/tool 실패에도 부분 산출물이 있으면 degraded로 분류한다. (권장)

B) 하나라도 실패가 있으면 failed로 분류한다.

C) 사용자에게는 completed/failed만 보여주고 degraded는 숨긴다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 5
mock transport는 어느 수준까지 구현할까요?

A) mode 선택, 세션 목록, 메시지 전송, timeline, completed/degraded/failed 샘플을 모두 같은 view model로 제공한다. (권장)

B) 메시지 전송 성공 happy path만 제공한다.

C) mock은 만들지 않고 실제 API만 연결한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 6
채팅 입력 보존은 어떻게 처리할까요?

A) 전송 실패 시 입력과 첨부 선택을 보존하고 재시도/삭제를 제공한다. 성공 시에만 composer를 비운다. (권장)

B) 전송 버튼을 누르면 성공/실패와 무관하게 입력을 비운다.

C) browser localStorage에 draft를 항상 저장한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

## Extension 준수 요약

- **Security Baseline**: 첨부 allowlist, owner-scoped session, 민감 내부 로그 비노출을 business rule로 고정한다.
- **Resiliency Baseline**: failed/degraded 분류, 입력 보존, 재시도 경로를 business rule로 고정한다.
- **Property-Based Testing**: mode lock, event ordering, 첨부 allowlist, response classifier, mock/real normalization은 PBT 후보로 유지한다.
