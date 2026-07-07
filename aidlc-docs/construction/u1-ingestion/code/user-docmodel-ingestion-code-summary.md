# User DocModel Ingestion Code Summary

Status: complete

## Summary

Implemented the ingestion-side consumer for the frozen user-uploaded PDF doc-model contract.

## Application Changes

- Added `JobKind.BUILD_USER_DOC_MODEL`.
- Extended `IngestionJob` with `objectKey`, `module`, `ownerId`, and `recordRef` payload fields.
- Added strict queue payload validation for user doc-model jobs:
  - `jobId` must use `userdoc-{uuid}`.
  - `paperId` must use `userdoc:{uuid}`.
  - `version` must be exactly `1`.
  - `recordRef` must exactly match `upload:{ownerId}:{jobId}:{attachmentId}`.
  - `module` must be `evidence` or `novelty`.
  - `arxivRef` is not accepted for this job kind.
- Added `UserDocumentSourcePort` and `S3UserDocumentSource`.
- Wired production runtime to read uploaded PDF bytes from the configured S3 bucket.
- Added `IngestionPipelineService.build_user_doc_model`.
- Routed `BUILD_USER_DOC_MODEL` through the existing worker dispatch and permanent-failure DLQ path.

## Parsing Behavior

- First PR is pdfplumber-only.
- Unparseable or empty PDF text is a permanent `PARSE_FAILURE`.
- Successful builds store the normal doc-model artifact at `doc-model/{paperId}/v{version}.json`.
- Produced doc-models use `SourceTier.pdf`; user-vs-arXiv origin remains encoded by the `userdoc:` namespace.

## Tests

- Focused ingestion tests: 35 passed.
- Full ingestion suite: 281 passed, 1 skipped.
- Ruff: clean.
- Compile check: clean.
- Diff whitespace check: clean.

## Extension Compliance

- Security: compliant for this slice. Queue input is validated before processing, S3 reads are scoped to the configured bucket/key, and the worker enforces a size cap.
- Resiliency: compliant for this slice. S3 reads use the existing dependency timeout/retry wrapper; permanent payload/parse failures go to the existing DLQ path.
- PBT partial mode: compliant for this slice. Added a domain-specific user doc-model job payload round-trip property.
