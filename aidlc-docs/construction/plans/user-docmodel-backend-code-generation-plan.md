# User DocModel Backend Code Generation Plan

Status: complete — PR #391 review fixes applied

Scope: PR2 backend producer and bounded consumer path for the frozen user-uploaded PDF doc-model contract.

## Unit Context

- Units: U11 evidence/research backend and U12 novelty backend.
- Contract source: `aidlc-docs/construction/plans/user-docmodel-contract.md`.
- Upload artifact: PDF bytes stored in the configured user-document S3 bucket.
- Queue payload: `BUILD_USER_DOC_MODEL` on `DOCSURI_DOCMODEL_BUILD_QUEUE_URL`.
- Identity contract: `paperId=userdoc:{uuid}` and `recordRef=upload:{ownerId}:{jobId}:{attachmentId}`.
- Failure UX: evidence notice and novelty `manuscript_pdf_parse_unavailable` degraded reason.

## Execution Steps

- [x] Step 1: Create the stacked backend PR2 branch from the merged PR0/PR1 contract base.
- [x] Step 2: Add a shared backend user-docmodel coordinator for upload, enqueue, and bounded polling.
- [x] Step 3: Wire evidence and research PDF attachment upload routes and attachment doc-model polling.
- [x] Step 4: Wire novelty PDF manuscript upload, user-docmodel enqueue, and PDF similarity doc-model polling.
- [x] Step 5: Add regression coverage for queue payload shape, upload response shape, polling, degradation, and no arXiv URL fabrication for `userdoc:` sources.
- [x] Step 6: Run focused and broad backend verification gates.
- [x] Step 7: Update code summary and AI-DLC state/audit.
- [x] Step 8: Harden evidence/research attachment doc-model consumption so client-supplied `objectKey` is bound to the authenticated owner, module, and attachment scope before enqueue or polling.
- [x] Step 9: Convert malformed user-docmodel attachment identities into client validation errors instead of unhandled server errors.
- [x] Step 10: Add regression coverage for forged object keys and invalid attachment metadata, then rerun focused backend verification.

## Compliance Notes

- Security: uploaded PDFs are size/type checked before S3 write; re-used evidence/research attachment object keys are owner/module/attachment scoped before enqueue or polling; generated source references do not invent arXiv URLs for user uploads.
- Resiliency: enqueue is best-effort; bounded polling degrades instead of failing the evidence or novelty workflow; malformed attachment identity metadata returns 422 instead of leaking as a server error.
- PBT partial mode: no new general property is required for this slice; contract-specific regression coverage exercises payload identity and source-reference invariants, including forged object-key rejection.
