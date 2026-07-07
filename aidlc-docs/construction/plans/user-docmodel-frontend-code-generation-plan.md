# User DocModel Frontend Code Generation Plan

Status: complete

Scope: PR3 frontend binary-upload wiring for the frozen user-uploaded PDF doc-model contract.

## Unit Context

- Unit: Agent Chat Frontend.
- Contract source: `aidlc-docs/construction/plans/user-docmodel-contract.md`.
- Backend dependency: PR2 upload endpoints on `feature/pr2-userdoc-docmodel-backend`.
- Evidence/research path: upload raw PDF to `POST /api/research/attachments`, then send returned `objectKey`/`paperId`/`recordRef` in the normal job payload.
- Novelty path: create manuscript job, then upload raw PDF to `POST /api/novelty/jobs/{jobId}/manuscript?fileName=...`.
- Existing md/txt path: preserve `contentText` JSON upload behavior.

## Execution Steps

- [x] Step 1: Create the stacked frontend PR3 branch from the updated PR2 backend branch.
- [x] Step 2: Add binary request-body support to the shared frontend transport seam and BFF proxy.
- [x] Step 3: Preserve browser-local PDF blobs in attachment state without sending them in JSON payloads.
- [x] Step 4: Upload evidence/research PDFs before job creation and send only backend metadata afterward.
- [x] Step 5: Upload novelty PDF manuscripts as raw `application/pdf` bodies after manuscript job creation.
- [x] Step 6: Keep md/txt manuscript `contentText` behavior unchanged.
- [x] Step 7: Add frontend regression coverage for research PDF upload order and novelty PDF raw upload dispatch.
- [x] Step 8: Run frontend compile and targeted test gates.
- [x] Step 9: Update code summary and AI-DLC state/audit.

## Compliance Notes

- Security: PDF bytes remain in same-origin/BFF transport and are not serialized into JSON or persisted in frontend state beyond the live send.
- Resiliency: failed upload responses are normalized through the existing `ApiClient` user-facing error path; backend fail-soft behavior remains owned by PR2.
- PBT partial mode: N/A for new mandatory properties in this slice; deterministic regression tests lock the contract-critical request order and payload shape.
