# U13 Agent Chat Frontend — Logical Components

**Unit**: Agent Chat Frontend  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-07-01

## Components

| Component | Responsibility |
|---|---|
| `AgentRouteGuard` | Reuse existing authenticated-route behavior for `/agent`. |
| `AgentChatReducer` | Local state transitions for mode lock, messages, timeline, attachments, and outcomes. |
| `AgentTransportClassifier` | Convert mock/real responses into completed/failed/degraded/retryable outcomes. |
| `AgentAttachmentValidator` | Enforce PDF/Markdown/TXT client allowlist before send queue entry. |
| `AgentSafeErrorMapper` | Map transport/tool errors to user-safe messages. |
| `AgentResponsiveShell` | Keep AppHeader/BottomNav/ViewModePreview-compatible layout. |
| `AgentA11yControls` | Keyboard/focus behavior for drawer, timeline, composer, and mode picker. |
| `AgentFrontendTestHarness` | Reducer/helper tests, UI examples, and E2E smoke tests. |

## Data Flow

```text
User action
  -> AgentChatReducer
  -> AgentTransport
  -> AgentTransportClassifier
  -> AgentSafeErrorMapper
  -> AgentChatReducer
  -> UI render
```

## Test Mapping

| Requirement | Test Component |
|---|---|
| Mode lock | Reducer/helper property candidate |
| Timeline event ordering | Reducer/helper property candidate |
| Attachment allowlist | Helper property candidate + UI example |
| Failed/degraded classifier | Helper example/property candidate |
| Drawer/composer/timeline UI | Vitest/RTL example tests |
| Desktop/mobile smoke | E2E tests after implementation |

## Non-Goals

- New deployment.
- New backend API implementation.
- New global state library.
- Separate mobile route.
