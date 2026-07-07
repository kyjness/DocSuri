# User DocModel Ingestion Code Generation Plan

Status: in progress

Scope: PR1 ingestion-only consumer for the frozen user-uploaded PDF doc-model contract.

## Unit Context

- Unit: U1 ingestion
- Contract source: `aidlc-docs/construction/plans/user-docmodel-contract.md`
- New queue kind: `BUILD_USER_DOC_MODEL`
- Input source: uploaded PDF bytes already in S3, addressed by `objectKey`
- Output artifact: `doc-model/{paperId}/v{version}.json`
- First PR parsing mode: pdfplumber-only

## Execution Steps

- [x] Step 1: Add user-docmodel job fields and payload validation.
- [x] Step 2: Add S3 user-document source port and production wiring.
- [x] Step 3: Add ingestion pipeline branch that reads S3 PDF bytes, extracts text with pdfplumber, and writes a normal DocModel.
- [x] Step 4: Route `BUILD_USER_DOC_MODEL` through the worker and existing permanent-failure DLQ path.
- [x] Step 5: Add focused unit and property-based regression tests for the new payload and worker path.
- [x] Step 6: Run focused ingestion verification and update code summary.
- [x] Step 7: Tighten frozen identity-contract validation after PR #390 contract review.

## Compliance Notes

- Security: validates queue payload fields before processing; does not synthesize arXiv URLs; reads only the configured S3 bucket/key.
- Resiliency: uses existing dependency timeout/retry wrapper and existing worker DLQ isolation for permanent parse/payload failures.
- PBT: includes a domain payload round-trip property for the new job payload.
