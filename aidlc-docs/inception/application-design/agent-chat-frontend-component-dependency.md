# U13 에이전트 채팅 프론트엔드 의존성

## 의존성 요약

| 컴포넌트 | 의존 대상 | 이유 |
|---|---|---|
| AgentRouteShell | AppHeader, BottomNav, RouteGuard | 기존 인증/네비 패턴 재사용 |
| AgentChatScreen | AgentChatReducer, AgentTransportService | 화면 상태와 backend 호출 조정 |
| AgentSessionDrawer | AgentSessionService | 세션 목록/삭제/새 채팅 |
| AgentMessageList | AgentProgressTimeline | 메시지 사이 진행 과정 표시 |
| AgentComposer | AgentAttachmentDrawer, AttachmentValidator | 입력과 첨부 검증 |
| AgentTransportService | `frontend/lib/api` transport | mock/real 호출 경계 재사용 |
| AgentProgressService | ResponseClassifier | 상태와 timeline 정규화 |

## 데이터 흐름

```text
/agent page
  -> AgentRouteShell
  -> AgentChatScreen
  -> AgentChatReducer
  -> AgentTransportService
  -> mock transport 또는 BFF/real API
  -> ResponseClassifier
  -> AgentChatReducer
  -> MessageList + ProgressTimeline
```

## 경계

- U13은 U11/U12 backend 내부 orchestration을 알지 않는다.
- U13은 화면 view model과 transport seam만 소유한다.
- 신규 infrastructure는 만들지 않는다.
- 데스크톱/모바일 차이는 route 분리가 아니라 CSS와 기존 preview iframe 구조로 처리한다.
