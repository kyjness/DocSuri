# 에이전트 채팅 프론트엔드 NFR Requirements 계획

## 입력

- `aidlc-docs/construction/agent-chat-frontend/functional-design/`
- `aidlc-docs/inception/requirements/requirements.md`의 NFR-P7, QT-11

## 산출 계획

- [x] `aidlc-docs/construction/agent-chat-frontend/nfr-requirements/nfr-requirements.md`를 생성한다.
- [x] `aidlc-docs/construction/agent-chat-frontend/nfr-requirements/tech-stack-decisions.md`를 생성한다.

## NFR Requirements 질문

### 질문 1
성능 기준은 어떻게 둘까요?

A) mode 선택, drawer open/close, timeline expand/collapse, composer typing은 클라이언트 즉시 반응을 목표로 하고, backend 지연은 loading/degraded 상태로 분리한다. (권장)

B) 전체 Agent 응답 완료 시간만 성능 기준으로 둔다.

C) 성능 기준은 Code Generation 이후 측정으로 미룬다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 2
보안 경계는 어디까지 NFR로 고정할까요?

A) 인증 사용자 전용 route, owner-scoped session, 첨부 allowlist, 민감 내부 로그/stack trace 비노출을 NFR로 고정한다. (권장)

B) backend가 처리하므로 frontend NFR에서는 제외한다.

C) 첨부 allowlist만 NFR로 둔다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 3
resiliency 기준은 어떻게 둘까요?

A) mock/real transport 모두 failed/degraded/retryable을 정규화하고, 실패 시 입력 보존과 재시도 경로를 제공한다. (권장)

B) 네트워크 실패만 처리하고 degraded는 표시하지 않는다.

C) 실패 시 새로고침 안내만 제공한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 4
접근성과 responsive 기준은 어떻게 둘까요?

A) 기존 AppHeader/BottomNav/ViewModePreview 패턴을 유지하고, drawer/composer/timeline은 keyboard focus와 모바일/데스크톱 레이아웃을 모두 지원한다. (권장)

B) 모바일만 우선 지원하고 데스크톱은 이후 조정한다.

C) 데스크톱만 우선 지원한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

### 질문 5
테스트 NFR은 어떻게 둘까요?

A) reducer/helper는 PBT 후보로 두고, route/nav/drawer/composer/timeline rendering은 예시 기반 Vitest로 둔다. (권장)

B) 모든 테스트를 예시 기반으로만 둔다.

C) 테스트 기준은 Code Generation에서만 정한다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A

## Extension 준수 요약

- **Security Baseline**: 인증, owner scope, 첨부 allowlist, 정보 노출 방지를 NFR로 고정한다.
- **Resiliency Baseline**: failed/degraded/retryable, 입력 보존, 재시도 경로를 NFR로 고정한다.
- **Property-Based Testing**: reducer/helper 불변식은 PBT 후보로 유지한다.
