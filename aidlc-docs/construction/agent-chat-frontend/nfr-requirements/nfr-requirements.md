# U13 Agent Chat Frontend — NFR Requirements

**Unit**: Agent Chat Frontend  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-07-01

## Scope

U13 adds the `/agent` frontend shell for U11 evidence and U12 novelty conversations. It reuses the existing Next.js frontend, responsive desktop/mobile layout, `ViewModePreview`, `AppHeader`, `BottomNav`, and frontend API transport patterns. It does not add backend APIs, a new deployment, or infrastructure.

## Performance

| ID | Requirement |
|---|---|
| NFR-AG-P1 | Mode selection, drawer open/close, timeline expand/collapse, and composer typing must be client-local and immediately responsive. |
| NFR-AG-P2 | Backend latency must be represented as loading, failed, or degraded state without blocking local navigation or typing. |
| NFR-AG-P3 | Timeline updates must append/update without full screen remounts. |

## Security and Privacy

| ID | Requirement |
|---|---|
| NFR-AG-SEC1 | `/agent` is authenticated-only and follows existing route guard/session patterns. |
| NFR-AG-SEC2 | Session list/load/delete actions assume owner-scoped backend access and never display another user's session. |
| NFR-AG-SEC3 | Attachments are allowlisted to PDF, Markdown, and TXT before entering the send queue. |
| NFR-AG-SEC4 | User-facing errors and timeline details must not expose stack traces, raw internal prompts, credentials, tokens, or infrastructure details. |

## Resiliency

| ID | Requirement |
|---|---|
| NFR-AG-R1 | Mock and real transports both normalize completed, failed, degraded, and retryable outcomes into the same view model. |
| NFR-AG-R2 | Failed sends preserve the draft message and selected valid attachments. |
| NFR-AG-R3 | Degraded states are shown when partial output remains useful after source/tool failure. |
| NFR-AG-R4 | Retry must reuse the preserved draft rather than forcing re-entry. |

## Accessibility and Responsive UX

| ID | Requirement |
|---|---|
| NFR-AG-U1 | Existing `AppHeader`, `BottomNav`, and `ViewModePreview` behavior remains intact. |
| NFR-AG-U2 | Drawer, composer, mode picker, and timeline controls support keyboard focus and visible focus states. |
| NFR-AG-U3 | `/agent` supports both mobile viewport and desktop responsive layout; mobile preview uses the existing iframe path. |

## Test Requirements

| ID | Requirement |
|---|---|
| QT-11.1 | Reducer/helper tests cover mode lock, event idempotency, event ordering, attachment allowlist, failed/degraded classifier, and mock/real normalization. |
| QT-11.2 | PBT candidates exist for pure reducer/helper invariants. |
| QT-11.3 | Example-based UI tests cover route/nav entry, mode picker, drawer, composer preservation, and timeline expand/collapse. |
| QT-11.4 | Tests must not require real backend agent execution for frontend preview behavior. |

## Traceability

| Source | Covered By |
|---|---|
| FR-40 | NFR-AG-P1, NFR-AG-U1..U3, QT-11.1 |
| FR-41 | NFR-AG-R1..R4, NFR-AG-SEC1..SEC2 |
| FR-42 | NFR-AG-P2..P3, NFR-AG-R1..R3 |
| FR-43 | NFR-AG-SEC3..SEC4, NFR-AG-R2 |
| NFR-P7 | NFR-AG-P1..P3, NFR-AG-R1..R4 |
| QT-11 | QT-11.1..QT-11.4 |
