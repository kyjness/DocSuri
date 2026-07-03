# U13 Agent Chat Frontend — Business Logic Model

## 새 세션 시작

1. 사용자가 `/agent`에 진입한다.
2. `AgentModePicker`가 `evidence` 또는 `novelty`를 받는다.
3. reducer가 `AgentSession.mode`를 고정한다.
4. composer를 활성화한다.

## 메시지 전송

1. 사용자가 메시지와 첨부를 작성한다.
2. 첨부 allowlist를 즉시 검증한다.
3. reducer가 사용자 메시지를 `pending`으로 추가한다.
4. transport request 생성 시 session mode를 다시 확인한다.
5. mock 또는 real transport가 정규화된 event/message/outcome을 반환한다.
6. reducer가 timeline과 job state를 갱신한다.

## Timeline 처리

1. event id가 이미 있으면 기존 event를 갱신한다.
2. event에 `sequence`가 있으면 sequence 기준으로 배치한다.
3. sequence가 없으면 수신 순서로 append한다.
4. source/tool 일부 실패는 산출물이 있으면 `degraded`로 표시한다.

## 실패/저하 분류

- `failed`: 최종 산출물이 없거나 재시도 없이는 진행할 수 없음.
- `degraded`: 일부 source/tool 실패가 있지만 부분 산출물이 있음.
- `completed`: 최종 산출물이 있고 알려진 저하가 없음.

## 입력 보존

- 성공 시 composer를 비운다.
- 실패 시 입력과 첨부 선택을 보존한다.
- 사용자는 재시도하거나 첨부를 삭제할 수 있다.
