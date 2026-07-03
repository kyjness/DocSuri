# U13 Agent Chat Frontend — Tech Stack Decisions

**Unit**: Agent Chat Frontend  
**Stage**: CONSTRUCTION -> NFR Requirements  
**Date**: 2026-07-01

## Decisions

| ID | Decision | Rationale |
|---|---|---|
| TD-AG-1 | Reuse the existing Next.js frontend app and `/agent` App Router route. | Avoids a new app or deployment for one UI surface. |
| TD-AG-2 | Reuse `AppHeader`, `BottomNav`, and `ViewModePreview` layout patterns. | Keeps desktop/mobile behavior consistent with current develop. |
| TD-AG-3 | Use local `useReducer` plus pure helpers for chat state. | Smallest state boundary; no app-wide Context until another screen needs it. |
| TD-AG-4 | Put agent chat helpers under `frontend/lib/agentChat/`. | Keeps reducer/classifier/normalizer testable outside React. |
| TD-AG-5 | Reuse existing `frontend/lib/api` transport conventions for mock/real calls. | Prevents screen components from branching on backend mode. |
| TD-AG-6 | Do not add a new frontend dependency for v1 state management. | React and existing test stack are enough. |
| TD-AG-7 | Treat TypeScript PBT as a candidate for reducer/helper invariants; add dependency only if Code Generation needs it and repo policy accepts it. | Avoids speculative dependency while preserving QT-11 intent. |
| TD-AG-8 | Use example-based Vitest/React Testing Library for rendered UI states. | Existing frontend tests already use this pattern. |
| TD-AG-9 | Keep attachment validation client-side as a UX guard, with backend validation still required by API owners. | Frontend guard improves UX but is not a security boundary by itself. |

## Deferred

- New global state library.
- New route split for evidence vs novelty.
- Dedicated frontend deployment.
- Real backend API implementation.
- E2E browser automation as a required gate before code exists.
