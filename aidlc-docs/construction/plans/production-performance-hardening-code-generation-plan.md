# Production Performance Hardening Code Generation Plan

**Stage**: Construction / Code Generation
**Scope**: Production infrastructure performance and observability hardening.
**Request**: Load-test API/frontend, increase API/frontend capacity headroom, isolate bulk ingestion from user-triggered DocModel work, add queue-age alarms, fix summary-worker CloudWatch IAM, and document RDS encryption migration.

## Steps

- [x] Step 1: Append the user request and continuation to `aidlc-docs/audit.md`.
- [x] Step 2: Add ingestion worker queue-mode control so a service can poll bulk, DocModel, or both queues.
- [x] Step 3: Split the CDK ingestion topology into a bulk worker service and a DocModel-builder worker service.
- [x] Step 4: Increase API and frontend ECS task size and autoscaling headroom.
- [x] Step 5: Add CloudWatch queue-age alarms and fix summary-worker CloudWatch metric permissions.
- [x] Step 6: Add an API/frontend load-test artifact and update performance instructions.
- [x] Step 7: Add the RDS encrypted-storage migration runbook without replacing the live database from CDK.
- [x] Step 8: Run focused tests and CDK synth validation.

## Compliance Notes

- Security Baseline: Applicable. RDS encryption is handled by an explicit migration runbook because direct in-place CDK mutation is unsafe for the existing unencrypted DB.
- Resiliency Baseline: Applicable. Queue isolation, capacity headroom, alarms, and load-test instructions address the active production performance gaps.
- PBT Partial: N/A for CDK-only changes; the one runtime branch gets focused example coverage.
