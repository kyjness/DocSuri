# U13 Agent Chat Frontend — Domain Entities

## AgentSession

- `id`: session id
- `mode`: `evidence` 또는 `novelty`
- `title`: 세션 목록 표시용 제목
- `state`: `idle`, `queued`, `running`, `completed`, `failed`, `degraded`
- `createdAt`, `updatedAt`

규칙: `mode`는 세션 생성 후 변경하지 않는다.

## AgentMessage

- `id`
- `role`: `user` 또는 `agent`
- `content`
- `attachments`
- `createdAt`
- `status`: `pending`, `sent`, `failed`

규칙: 전송 실패 시 사용자 입력과 첨부 선택은 보존한다.

## AgentTimelineEvent

- `id`
- `sessionId`
- `sequence?`
- `stage`
- `label`
- `detail?`
- `source?`
- `state`: `running`, `completed`, `failed`, `degraded`

규칙: `sequence`가 있으면 우선 정렬하고, 없으면 수신 순서로 append한다. 같은 `id`는 멱등 처리한다.

## AgentAttachment

- `id`
- `name`
- `kind`: `pdf`, `markdown`, `text`
- `sizeBytes`
- `status`: `ready`, `rejected`, `uploading`, `failed`
- `error?`

규칙: PDF, Markdown, TXT 외 파일은 전송 큐에 넣지 않는다.

## AgentResponseOutcome

- `kind`: `completed`, `failed`, `degraded`
- `message?`
- `events`
- `retryable`

규칙: 최종 산출물이 없거나 재시도 없이는 계속할 수 없으면 `failed`, 부분 산출물이 있으면 `degraded`다.
