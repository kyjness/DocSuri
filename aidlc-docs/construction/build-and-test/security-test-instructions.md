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

# U11 Novelty Agent Security Test Instructions — 2026-06-30

Run security-relevant U11 tests:

```powershell
python -m pytest backend/tests/test_novelty.py -q
```

Covered security/privacy checks:

- owner isolation blocks cross-owner job reads
- supported outputs cannot claim evidence without `sourceRefs`
- external URLs require HTTPS and reject localhost/private-style IP targets
- query minimization strips whitespace/newlines before external search
- Notion export requires explicit preview approval before completion
- unsupported manuscript types are rejected at the API boundary

Manual review checklist:

- Confirm deploy env keeps `NOVELTY_AGENT_ENABLED=true`.
- Confirm API task can send only to the novelty queue and read/write only the `novelty/` S3 prefix.
- Confirm no plaintext Notion token is stored in novelty job payloads.
- Confirm real external adapters preserve the allowlist and timeout/degraded behavior.

---

# Agent Chat Frontend Security Test Instructions — 2026-07-01

Run security-relevant frontend checks:

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- vitest run test/agentChatScreen.test.tsx --reporter=dot
corepack pnpm@9.15.9 --dir frontend exec -- playwright test e2e/agent-chat.spec.ts --reporter=line
```

Covered security/privacy checks:

- `/agent` remains behind the existing `RouteGuard`.
- unsupported attachment types are rejected before send.
- attachment UI stores browser metadata only in this mock-first slice.
- user-facing errors are generic and do not expose raw transport internals.
- no new local secret storage or backend credential path is introduced.

Manual review checklist:

- Confirm future real upload path keeps server-side MIME, size, and owner checks.
- Confirm future backend session APIs enforce owner-scoped session access.
- Confirm external adapter results do not render untrusted HTML in chat messages.

---
