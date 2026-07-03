# U13 에이전트 채팅 프론트엔드 컴포넌트

## 범위

U13은 `/agent` 단일 route에서 U11 문헌탐색·근거형성 Agent와 U12 novelty Agent를 선택해 대화하는 프론트엔드 셸이다. backend job 구현이나 신규 인프라는 포함하지 않는다.

## 컴포넌트

| 컴포넌트 | 책임 |
|---|---|
| AgentRouteShell | `/agent` page shell. `AppHeader`, `BottomNav`, route guard와 연결한다. |
| AgentChatScreen | 화면 최상위 client component. reducer 상태, drawer open 상태, transport 호출을 조정한다. |
| AgentModePicker | 새 세션에서 `문헌탐색&근거형성` 또는 `novelty` 모드를 선택한다. 선택 후 세션 모드는 고정된다. |
| AgentSessionDrawer | 과거 세션 목록, 새 채팅, 세션 삭제 진입을 제공한다. |
| AgentMessageList | 사용자/Agent 메시지와 메시지 사이 timeline을 렌더링한다. |
| AgentProgressTimeline | 단계 이벤트를 시간순으로 표시하고 상세를 접고 펼친다. |
| AgentComposer | 입력창, 전송 버튼, 왼쪽 `+` 첨부 버튼을 제공한다. |
| AgentAttachmentDrawer | PDF/Markdown/TXT 첨부 목록과 검증 오류를 표시한다. |
| AgentTransport | mock/real backend 호출을 같은 view model로 정규화한다. |
| AgentChatReducer | mode lock, 메시지, timeline, 첨부, loading/failed/degraded 상태 전이를 관리한다. |

## 설계 원칙

- 모바일은 `BottomNav`, 데스크톱은 `AppHeader`의 주 메뉴를 사용한다.
- 기존 `ViewModePreview` iframe 구조를 유지한다.
- mock과 real 응답은 화면에 도달하기 전에 같은 view model로 정규화한다.
- owner-scoped 세션 전제와 첨부 allowlist는 trust boundary로 다룬다.
