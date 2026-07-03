# U13 에이전트 채팅 프론트엔드 서비스

## AgentChatUiService

- `AgentChatScreen` 내부의 화면 오케스트레이션 책임이다.
- reducer dispatch, drawer 상태, transport 호출, retry 흐름을 연결한다.
- 전역 Context는 만들지 않는다. `/agent` 화면 안에서 필요한 상태만 보유한다.

## AgentTransportService

- 기존 `frontend/lib/api` 패턴을 따른다.
- `NEXT_PUBLIC_DOCSURI_REAL_API` 설정 여부와 기존 BFF transport 패턴에 맞춰 mock/real 호출을 숨긴다.
- novelty API는 `/api/novelty/*` seam을 우선 사용한다.
- evidence API는 향후 U11 API가 준비될 때 같은 view model 계약으로 붙인다.

## AgentSessionService

- 세션 목록, 세션 로딩, 새 채팅, 삭제 동작의 프론트 view model을 관리한다.
- 실제 영속성은 backend transport가 담당한다.
- 세션은 owner-scoped 전제를 가진다.

## AgentAttachmentService

- 첨부 파일 종류를 검증하고 화면 표시용 attachment view model을 만든다.
- v1 허용 형식은 PDF, Markdown, TXT다.
- 첨부 실패는 내부 오류 없이 사용자 메시지와 삭제/재시도 경로만 노출한다.

## AgentProgressService

- backend event 또는 mock event를 timeline item으로 정규화한다.
- 검색/근거 정리/외부 탐색/아이디어 형성/실험 계획 등 단계 이벤트를 시간순으로 표시한다.
- source별 부분 실패는 전체 실패가 아니라 degraded로 표현할 수 있다.
