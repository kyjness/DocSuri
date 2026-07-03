# U13 에이전트 채팅 프론트엔드 메서드

## View model

```text
AgentMode = "evidence" | "novelty"
AgentJobState = "idle" | "queued" | "running" | "completed" | "failed" | "degraded"
AttachmentKind = "pdf" | "markdown" | "text"
```

## 주요 메서드

| 소유자 | 메서드 | 목적 |
|---|---|---|
| AgentChatReducer | `startSession(mode)` | 새 세션을 만들고 모드를 고정한다. |
| AgentChatReducer | `appendUserMessage(content, attachments)` | 사용자 메시지와 첨부 참조를 추가한다. |
| AgentChatReducer | `applyAgentEvent(event)` | 메시지, timeline, job state를 정규화된 이벤트로 갱신한다. |
| AgentChatReducer | `markFailure(error)` | 실패 상태와 재시도 가능 여부를 반영한다. |
| AgentChatReducer | `markDegraded(reason)` | 부분 실패를 degraded 상태로 표시한다. |
| AgentTransport | `listSessions(mode?)` | 내 Agent 세션 목록을 조회한다. |
| AgentTransport | `loadSession(sessionId)` | 메시지와 timeline을 복원한다. |
| AgentTransport | `sendMessage(sessionId, request)` | mock 또는 real backend에 메시지를 전송한다. |
| AgentTransport | `deleteSession(sessionId)` | owner-scoped 세션 삭제를 요청한다. |
| AttachmentValidator | `classifyFile(file)` | PDF/Markdown/TXT만 허용한다. |
| ResponseClassifier | `classify(response)` | completed/failed/degraded를 화면 상태로 변환한다. |

## 테스트 후보

- mode는 세션 시작 후 바뀌지 않는다.
- timeline event는 입력 순서 또는 서버 sequence 순서를 보존한다.
- 첨부 allowlist 외 파일은 전송되지 않는다.
- mock/real 응답은 같은 view model로 정규화된다.
