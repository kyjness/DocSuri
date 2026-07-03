# U13 Agent Chat Frontend — NFR Design Patterns

**Unit**: Agent Chat Frontend  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-07-01

## Transport Classifier Pattern

All mock and real backend responses pass through one classifier before reaching React components.

| Outcome | Pattern |
|---|---|
| `completed` | Append final agent message and mark session complete. |
| `degraded` | Preserve partial output, show degraded banner/detail, allow follow-up. |
| `failed` | Preserve draft if send failed; show retry path. |
| `retryable` | Render retry action without losing composer state. |

Components do not branch on mock vs real transport.

## Local Interaction Pattern

Drawer open/close, timeline expand/collapse, composer typing, and mode selection are local reducer/UI state. Backend calls run asynchronously and update state through reducer actions.

This keeps the UI responsive while long-running agent work is represented as loading, degraded, or failed state.

## Safe Error Mapping Pattern

User-facing errors are mapped to short non-technical messages. Internal stack traces, raw prompts, credentials, tokens, infrastructure details, and raw tool payloads are never rendered in timeline or error surfaces.

## Attachment Allowlist Pattern

Attachment validation runs before enqueueing a file for send.

| File kind | Allowed |
|---|---|
| PDF | Yes |
| Markdown | Yes |
| TXT | Yes |
| Other | No |

Rejected files remain outside the send queue and are displayed as drawer-local validation errors.

## Responsive and Accessibility Pattern

U13 reuses existing `AppHeader`, `BottomNav`, and `ViewModePreview` behavior. `/agent` uses CSS constraints for mobile and desktop rather than separate routes.

Drawer, timeline, mode picker, and composer controls must have:

- reachable keyboard focus,
- visible focus state,
- stable labels or accessible names,
- stable `data-testid` values for automation.

## Test Pattern

The test design uses three layers:

| Layer | Purpose |
|---|---|
| Reducer/helper property candidates | mode lock, event ordering, idempotency, allowlist, classifier normalization. |
| Example-based UI tests | route/nav entry, mode picker, drawer, composer preservation, timeline expand/collapse. |
| E2E tests | authenticated happy path and mobile/desktop navigation smoke checks once code exists. |

Q5 explicitly adds E2E tests to the recommended reducer/helper + UI example plan.
