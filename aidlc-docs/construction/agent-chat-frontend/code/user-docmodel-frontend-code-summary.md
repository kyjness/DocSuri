# User DocModel Frontend Code Summary

Status: complete

## Summary

Implemented frontend binary upload wiring for user-uploaded PDFs in the agent chat flows.

## Application Changes

- Added a binary request-body envelope to the frontend transport interface.
- Updated the browser RouteHandler transport, server Http transport, and Next.js BFF proxy so `application/pdf` bodies are forwarded as raw bytes instead of JSON.
- Extended agent attachments with backend upload metadata (`objectKey`, `paperId`, `recordRef`) and a temporary browser-local `sourceFile` blob.
- Ensured `sourceFile` is stripped from all JSON job/message payloads.
- Evidence/research PDF attachments now upload to `/api/research/attachments` first, then send returned metadata in the normal job payload.
- Novelty PDF manuscripts now create the manuscript job first, then upload the PDF to `/api/novelty/jobs/{jobId}/manuscript?fileName=...`.
- md/txt manuscript attachments continue to use the existing `contentText` JSON upload behavior.
- Mock transport now supports the research attachment upload endpoint for local preview.

## Tests

- Added API client regression coverage for:
  - research PDF upload before job creation,
  - job payload metadata-only attachment shape,
  - novelty PDF raw manuscript upload after job creation.

## Verification

- `node_modules/.bin/tsc --noEmit` from `frontend/` -> passed.
- `node_modules/.bin/vitest run test/apiClient.test.ts test/agentChatReducer.test.ts test/agentChatScreen.test.tsx` from `frontend/` -> 34 passed.
- `node_modules/.bin/vitest run` from `frontend/` -> 248 passed.
- `node_modules/.bin/next build` from `frontend/` -> passed.
- Initial `pnpm --dir frontend test -- apiClient.test.ts` was blocked by the local Corepack pnpm version mismatch (`packageManager` pins pnpm 9.15.9; Corepack exposed pnpm 11.9.0), so verification used the checked-in frontend `node_modules/.bin` binaries without changing package metadata.

## Extension Compliance

- Security: compliant for this slice. PDF bytes travel through same-origin/BFF transport and are never included in JSON payloads.
- Resiliency: compliant for this slice. Upload failures use the existing normalized API error path; backend degradation semantics remain unchanged.
- PBT partial mode: N/A for new mandatory properties; deterministic tests cover the contract-critical request sequence and payload shape.
