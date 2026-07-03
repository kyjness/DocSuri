# U13 Agent Chat Frontend — Business Rules

## BR-AG-1 Mode Lock

세션 mode는 생성 후 변경할 수 없다. UI는 변경 버튼을 제공하지 않고, 새 채팅 생성만 안내한다. reducer와 transport request 생성 양쪽에서 mode lock을 검증한다.

## BR-AG-2 Owner Scope

세션 목록, 세션 로딩, 삭제는 현재 로그인 사용자 scope 안에서만 동작해야 한다. 프론트는 다른 사용자 세션 id를 추측하거나 표시하지 않는다.

## BR-AG-3 Attachment Allowlist

허용 첨부는 PDF, Markdown, TXT뿐이다. 거부된 파일은 전송 큐에 들어가지 않으며 오류는 첨부 drawer 안에 표시한다.

## BR-AG-4 Timeline Idempotency

같은 event id가 다시 들어오면 중복 렌더링하지 않는다. sequence가 있으면 sequence 우선, 없으면 수신 순서로 처리한다.

## BR-AG-5 Failed vs Degraded

최종 산출물이 없거나 재시도 없이는 계속할 수 없으면 `failed`다. 일부 source/tool 실패에도 부분 산출물이 있으면 `degraded`다.

## BR-AG-6 Mock/Real Normalization

mock transport와 real transport는 같은 view model을 반환해야 한다. 화면 컴포넌트는 mock/real 여부를 직접 분기하지 않는다.

## BR-AG-7 Sensitive Detail Suppression

timeline과 오류 메시지는 내부 stack trace, raw prompt, credential, 민감 source payload를 노출하지 않는다.

## BR-AG-8 Composer Preservation

전송 실패 시 입력과 첨부 선택을 보존한다. 성공 시에만 composer를 비운다.
