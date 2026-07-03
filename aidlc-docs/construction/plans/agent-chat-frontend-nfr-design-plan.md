# 에이전트 채팅 프론트엔드 NFR Design 계획

## 입력

- `aidlc-docs/construction/agent-chat-frontend/nfr-requirements/nfr-requirements.md`
- `aidlc-docs/construction/agent-chat-frontend/nfr-requirements/tech-stack-decisions.md`
- `aidlc-docs/construction/agent-chat-frontend/functional-design/`

## 산출 계획

- [x] `aidlc-docs/construction/agent-chat-frontend/nfr-design/nfr-design-patterns.md`를 생성한다.
- [x] `aidlc-docs/construction/agent-chat-frontend/nfr-design/logical-components.md`를 생성한다.

## NFR Design 질문

### 질문 1
resilience pattern은 어떻게 설계할까요?

A) transport response classifier를 단일 경계로 두고, retryable/failed/degraded를 reducer action으로 정규화한다. (권장)

B) 각 컴포넌트에서 오류를 직접 처리한다.

C) 실패는 전역 error boundary에만 맡긴다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 2
성능 pattern은 어떻게 설계할까요?

A) drawer, timeline, composer는 local state/reducer로 처리하고 backend 호출은 비동기 transition으로 분리한다. (권장)

B) 모든 상태를 backend 응답 이후에만 갱신한다.

C) 성능 최적화는 Code Generation 이후로 미룬다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 3
보안 pattern은 어떻게 설계할까요?

A) route guard, owner-scoped transport assumption, client allowlist, user-safe error mapping을 별도 logical component로 둔다. (권장)

B) backend 보안에만 의존하고 frontend pattern은 두지 않는다.

C) 첨부 allowlist만 logical component로 둔다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 4
responsive/accessibility pattern은 어떻게 설계할까요?

A) 기존 AppHeader/BottomNav/ViewModePreview 구조를 유지하고, drawer/timeline/composer는 keyboard focus와 CSS responsive constraint를 명시한다. (권장)

B) 모바일 UI만 먼저 설계한다.

C) 데스크톱 UI만 먼저 설계한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 5
테스트 logical component는 어떻게 둘까요?

A) reducer/helper property 후보와 UI 예시 테스트 후보를 logical component별로 매핑한다. (권장)

B) 테스트 logical component는 만들지 않는다.

C) 모든 테스트를 E2E 중심으로 설계한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: X) A + E2E 테스트

## Extension 준수 요약

- **Security Baseline**: route guard, owner scope, allowlist, safe error mapping pattern을 설계한다.
- **Resiliency Baseline**: classifier, retry, degraded state, draft preservation pattern을 설계한다.
- **Property-Based Testing**: reducer/helper 불변식을 NFR Design logical component에 연결한다.
