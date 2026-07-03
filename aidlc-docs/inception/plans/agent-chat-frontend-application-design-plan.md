# 에이전트 채팅 프론트엔드 Application Design 계획

## 입력

- `aidlc-docs/inception/requirements/requirements.md`의 FR-40~43, NFR-P7, QT-11
- `aidlc-docs/inception/user-stories/stories.md`의 에픽 11, US-AG1..AG7
- 기존 frontend 패턴:
  - `frontend/app/*/page.tsx`
  - `frontend/components/AppHeader.tsx`
  - `frontend/components/BottomNav.tsx`
  - `frontend/components/ViewModePreview.tsx`
  - `frontend/lib/api/*`

## 설계 산출 계획

- [x] `aidlc-docs/inception/application-design/agent-chat-frontend-components.md`를 생성한다.
- [x] `aidlc-docs/inception/application-design/agent-chat-frontend-component-methods.md`를 생성한다.
- [x] `aidlc-docs/inception/application-design/agent-chat-frontend-services.md`를 생성한다.
- [x] `aidlc-docs/inception/application-design/agent-chat-frontend-component-dependency.md`를 생성한다.
- [x] 기존 application-design 요약 문서에 U13 링크를 추가한다.

## Application Design 질문

### 질문 1
에이전트 채팅 화면의 컴포넌트 경계는 어떻게 나눌까요?

A) `/agent` route shell 아래에 `AgentChatScreen`, `AgentModePicker`, `AgentSessionDrawer`, `AgentMessageList`, `AgentProgressTimeline`, `AgentComposer`, `AgentAttachmentDrawer`로 나눈다. (권장)

B) 큰 `AgentChatScreen` 하나에 대부분의 UI와 상태를 둔다.

C) U11/U12 모드별로 별도 화면 컴포넌트를 만든다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 2
채팅 상태 관리는 어디에 둘까요?

A) `useReducer` 기반 local state와 순수 helper를 `frontend/lib/agentChat/`에 둔다. 세션 영속은 transport가 담당한다. (권장)

B) React Context로 전역 상태를 만든다.

C) URL query와 localStorage 중심으로 관리한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 3
mock/real backend 전송 경계는 어떻게 설계할까요?

A) `frontend/lib/api`의 기존 transport 패턴을 따르고, Agent 전용 normalizer/classifier만 추가한다. mock과 real은 같은 view model을 반환한다. (권장)

B) 화면 컴포넌트에서 mock과 real 호출을 직접 분기한다.

C) novelty와 evidence 전송 계층을 완전히 분리해 서로 다른 view model을 둔다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 4
데스크톱/모바일 preview 대응은 어떻게 할까요?

A) 기존 responsive CSS와 `ViewModePreview` iframe 구조를 그대로 사용하고, `/agent` 화면은 viewport별 CSS만 둔다. (권장)

B) 데스크톱과 모바일을 별도 route로 나눈다.

C) 모바일 preview에서는 일부 기능을 숨긴다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 5
Application Design에서 테스트 경계는 어디까지 고정할까요?

A) 컴포넌트별 책임과 함께 reducer/helper PBT 후보, UI 예시 테스트 후보, transport classifier 테스트 후보까지만 고정한다. (권장)

B) 구체적인 test file 이름과 모든 케이스를 이 단계에서 확정한다.

C) 테스트는 Functional Design 이후로 전부 미룬다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

## Extension 준수 요약

- **Security Baseline**: 적용 대상. 인증된 사용자, owner-scoped 세션, 첨부 검증, 민감 로그 비노출을 설계에 반영해야 한다.
- **Resiliency Baseline**: 적용 대상. 실패/저하 상태, 재시도, 입력 보존, mock/real 응답 정규화를 설계에 반영해야 한다.
- **Property-Based Testing**: 적용 대상. 모드 고정, event ordering, 첨부 allowlist, response classifier는 PBT 후보로 유지한다.
