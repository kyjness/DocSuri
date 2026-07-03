# 에이전트 채팅 프론트엔드 Code Generation 계획 + 승인 게이트

**단계**: CONSTRUCTION -> Code Generation  
**유닛**: Agent Chat Frontend  
**일자**: 2026-07-01  
**근거**: `construction/agent-chat-frontend/functional-design/`, `nfr-requirements/`, `nfr-design/`

> 본 계획서는 승인 게이트다. 승인 전에는 앱 코드를 생성하지 않는다.

## 1. Part 1 Planning Checklist

- [x] Functional/NFR design artifacts reviewed.
- [x] User stories reviewed: US-AG1..US-AG7.
- [x] Existing frontend route, nav, API transport, mock, and test patterns reviewed.
- [x] Infrastructure Design skipped: existing frontend deployment is reused.
- [x] Exact application code paths identified outside `aidlc-docs/`.
- [x] Code generation steps defined with story traceability.

## 2. 구현 범위

- New `/agent` frontend route.
- Mobile `BottomNav` and desktop `AppHeader` entry.
- Agent chat UI components.
- Local reducer/helper state model.
- Mock/real transport seam using existing frontend API patterns.
- Attachment allowlist and user-safe error mapping.
- Unit/UI tests plus E2E smoke tests.

## 3. 생성/수정 예정 경로

| Type | Path |
|---|---|
| New route | `frontend/app/agent/page.tsx` |
| Route styles | `frontend/app/agent/agent.module.css` |
| New components | `frontend/components/agent/` |
| New helpers | `frontend/lib/agentChat/` |
| API integration | `frontend/lib/api/` and/or existing `ApiClient` pattern |
| Mock integration | `frontend/lib/api/mockTransport.ts` or adjacent mock fixture path |
| Nav update | `frontend/components/AppHeader.tsx`, `frontend/components/BottomNav.tsx` |
| Tests | `frontend/test/agentChat*.test.ts(x)` |
| E2E smoke | `frontend/e2e/agent-chat.spec.ts` |
| Code summary docs | `aidlc-docs/construction/agent-chat-frontend/code/summary.md` |

## 4. Dependencies and Interfaces

| Dependency | Use |
|---|---|
| U3 Accounts | Authenticated route/session behavior. |
| U11 Evidence Agent | Future evidence API transport target; v1 may use mock seam until real API is available. |
| U12 Novelty Agent | `/api/novelty/*` transport target where available. |
| U5 Frontend Shell | Existing AppHeader, BottomNav, ViewModePreview, page/module CSS patterns. |

## 5. Story Traceability

| Story | Planned implementation |
|---|---|
| US-AG1 | `/agent` route and mobile/desktop nav entries. |
| US-AG2 | Mode picker and reducer/transport mode lock. |
| US-AG3 | Session drawer, new chat, session load/delete mock/transport seam. |
| US-AG4 | Progress timeline rendering and expand/collapse. |
| US-AG5 | Composer `+` attachment drawer and allowlist validation. |
| US-AG6 | Mock/real transport normalization and failed/degraded UX. |
| US-AG7 | Reducer/helper, UI, and E2E test coverage. |

## 6. Code Generation Steps

- [x] **Step 1 — Agent route shell**
  - Create `/agent` page.
  - Reuse existing screen layout, `AppHeader`, route guard pattern, and `BottomNav`.

- [x] **Step 2 — Navigation entries**
  - Add `에이전트` to desktop `AppHeader` nav.
  - Add centered `에이전트` tab to mobile `BottomNav`.

- [x] **Step 3 — Domain helpers and reducer**
  - Create `frontend/lib/agentChat/` helper/reducer files.
  - Implement mode lock, event ordering, attachment allowlist, and classifier helpers.

- [x] **Step 4 — Transport seam and mocks**
  - Add mock session/message/timeline fixtures.
  - Add normalized send/list/load/delete functions following existing API patterns.

- [x] **Step 5 — UI components**
  - Create `AgentChatScreen`, `AgentModePicker`, `AgentSessionDrawer`, `AgentMessageList`, `AgentProgressTimeline`, `AgentComposer`, `AgentAttachmentDrawer`.
  - Add stable `data-testid` values for interactive elements.

- [x] **Step 6 — Unit and UI tests**
  - Add reducer/helper tests.
  - Add UI tests for route/nav, mode picker, drawer, composer, timeline.

- [x] **Step 7 — E2E smoke tests**
  - Add authenticated `/agent` navigation smoke.
  - Cover desktop/mobile or preview-relevant path at smoke level.

- [x] **Step 8 — Code summary**
  - Create `aidlc-docs/construction/agent-chat-frontend/code/summary.md`.

## 7. Approval Question

코드 생성을 진행할까요?

A) 승인합니다. 이 계획대로 Code Generation을 진행합니다. (권장)

B) 아직 진행하지 않습니다. 계획을 수정한 뒤 다시 확인합니다.

X) 기타. 아래 [Answer]: 태그 뒤에 설명해 주세요.

[Answer]: A
