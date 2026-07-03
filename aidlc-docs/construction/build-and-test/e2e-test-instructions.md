# E2E Test Instructions — Agent Chat Frontend

**Stage**: CONSTRUCTION → Build and Test
**Unit**: Agent Chat Frontend
**Date**: 2026-07-01

## Prerequisites

Install the local Playwright WebKit browser if it is not already present:

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- playwright install webkit
```

## Command

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- playwright test e2e/agent-chat.spec.ts --reporter=line
```

## Observed Result

- 1 Playwright test passed.

## Coverage

- authenticated mock session opens `/agent`
- `Novelty` mode can be selected once at session start
- user message can be sent through the mock transport
- assistant response and exploration timeline render in the chat surface

## Note

The E2E test injects the mock session through `localStorage` because the purpose of
this slice is Agent Chat behavior, not authentication form coverage.
