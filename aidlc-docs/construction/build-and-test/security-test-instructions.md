# Security Test Instructions

## Purpose

Validate U1 security controls required by the enabled Security Baseline.

## Static and Dependency Checks

Run from repository root:

```powershell
cd ingestion
uv export --all-groups --format requirements-txt > requirements.lock.txt
pip-audit -r requirements.lock.txt
syft packages dir:. -o spdx-json > sbom.spdx.json
trivy fs --scanners vuln,secret,misconfig .
```

If `pip-audit`, `syft`, or `trivy` are unavailable, install them through approved CI tooling
or run equivalent organization-standard SCA/SBOM scanners.

## Code Security Checks

### Secret Logging

- Verify `IngestionSettings.safe_log_dict` redacts endpoint, URL, and DSN-like values.
- Verify `sanitize_log_entry` redacts secret, password, token, and DSN-like keys.

Command:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests
```

### Fail-Closed Runtime Configuration

- Production runtime must call `settings.require_production`.
- Missing required `DOCSURI_*` values must stop startup before external calls.

Manual check:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m docsuri_ingestion.cli ingest-one --arxiv-ref 2401.00001v1
```

Expected result without production settings: startup fails closed.

### Input Validation

Covered inputs:

- arXiv reference normalization
- OA license validation
- metadata required fields
- queue payload shape
- embedding vector dimensions
- IndexRecord pydantic model validation

## AWS Security Checks

Run after Infrastructure Design:

- S3 bucket blocks public access.
- S3 uses SSE-S3 or SSE-KMS.
- OpenSearch endpoint uses TLS and authenticated access.
- SQS queue and DLQ are not public.
- IAM policies avoid wildcard resource grants except where explicitly justified.
- Worker role can access only U1-required S3 prefix, queue, DLQ, Bedrock model, OpenSearch index,
  and control-plane database secret.
# U9 Personalization Security Test Instructions — 2026-06-23

Run security-relevant U9 tests:

```powershell
python -m pytest backend/tests/test_personalization.py -q
```

Covered security/privacy checks:

- metadata allowlist rejects raw/free-form payloads
- owner isolation in aggregation
- direct raw-log delete removes active events from future decisions
- profile reset removes aggregate/default signals
- no `user_behavior_event_backup` table is created

Manual review checklist:

- Confirm telemetry carries counts/status only, not raw behavior metadata.
- Confirm future U2/U4/U7 integrations record events only after successful owner-scoped actions.
- Confirm CDK purge failure alarm is deployed with ops alert subscription configured.

---
