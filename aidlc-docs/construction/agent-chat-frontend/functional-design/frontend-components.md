# U13 Agent Chat Frontend — Frontend Components

## Component Tree

```text
/agent page
  AgentRouteShell
    AppHeader
    AgentChatScreen
      AgentSessionDrawer
      AgentModePicker
      AgentMessageList
        AgentProgressTimeline
      AgentComposer
        AgentAttachmentDrawer
    BottomNav
```

## Component Responsibilities

| Component | Props/State | Responsibility |
|---|---|---|
| AgentChatScreen | reducer state, drawer open, selected session | 화면 orchestration, transport 호출, retry |
| AgentModePicker | selected mode, onSelect | 새 세션 mode 선택 |
| AgentSessionDrawer | sessions, current session, onLoad, onNew, onDelete | 과거 세션 로딩과 관리 |
| AgentMessageList | messages, timeline events | 메시지와 timeline 표시 |
| AgentProgressTimeline | events, expanded ids | 진행 단계 접기/펼치기 |
| AgentComposer | draft, attachments, submitting | 입력, `+` 첨부, 전송 |
| AgentAttachmentDrawer | attachments, errors | 첨부 검증 결과와 삭제 |

## Interaction Flow

1. 사용자가 `/agent`에 진입한다.
2. 기존 세션을 선택하거나 새 채팅 mode를 고른다.
3. composer에 메시지를 입력하고 필요하면 첨부를 추가한다.
4. 전송하면 메시지와 timeline이 진행 상태를 표시한다.
5. 성공 시 composer를 비우고, 실패 시 입력을 보존한다.

## Test Candidates

- reducer: mode lock, timeline idempotency, failed/degraded classifier.
- helper: attachment allowlist, mock/real response normalization.
- UI: nav entry, drawer, mode picker, composer preservation, timeline expand/collapse.
