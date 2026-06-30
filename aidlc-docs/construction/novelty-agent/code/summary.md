# Novelty Agent Code Summary

**Stage**: CONSTRUCTION / Code Generation
**Unit**: Novelty Agent
**Date**: 2026-06-30

## Generated Backend Code

- `backend/modules/novelty/models.py`: job state machine, progress events, artifacts, export states, manuscript scope validation.
- `backend/modules/novelty/repository.py`: owner-scoped in-memory and SQL repositories plus artifact-store seam.
- `backend/modules/novelty/service.py`: job creation, status/result, cancel, artifact validation, Notion preview/approval/export invariant.
- `backend/modules/novelty/controller.py`: `/api/novelty` routes for job create/status/result/cancel, SSE progress snapshot, and Notion approval flow.
- `backend/modules/novelty/worker.py`: SQS polling/ack loop, SQS payload parser, stage progress emission, degraded no-op adapter behavior.
- `backend/modules/novelty/adapters.py`: seams for U2 full search, external browser search, similarity check, and Notion export.
- `backend/modules/novelty/validators.py`: source-key normalization, source-ref requirements for supported outputs, experiment-plan shape validation.
- `backend/modules/novelty/security.py`: external query minimization and SSRF/egress URL guard.
- `backend/modules/novelty/streaming.py`: persisted progress events encoded as SSE snapshots.

## Routes

- `POST /api/novelty/jobs`
- `GET /api/novelty/jobs/{job_id}`
- `GET /api/novelty/jobs/{job_id}/result`
- `GET /api/novelty/jobs/{job_id}/events`
- `POST /api/novelty/jobs/{job_id}/cancel`
- `POST /api/novelty/jobs/{job_id}/notion/preview`
- `POST /api/novelty/jobs/{job_id}/notion/approve`

## Persistence

- Added migration `backend/modules/novelty/migrations/001_create_novelty_tables.sql`.
- Tables: `novelty_jobs`, `novelty_progress_events`, `novelty_artifacts`, `novelty_notion_exports`.
- Startup migrations now include novelty migrations.
- CLI migration defaults now include novelty migrations.

## App Shell and Deployment

- Added `_mount_novelty` in `backend/wiring.py`.
- Updated app-shell registry tests for the new `novelty` module.
- Added `ops/cdk/stacks/novelty_stack.py` with SQS queue/DLQ, Fargate worker, S3 prefix permissions, Bedrock invoke permission, RDS access, and DLQ alarm.
- Registered `Docsuri-Novelty` in `ops/cdk/app.py`.
- Novelty worker RDS endpoint/port/security group/secret are passed as stack props from CDK context instead of being fixed inside the stack.
- Updated API task deploy env in `ops/cdk/stacks/compute_stack.py`:
  - `NOVELTY_AGENT_ENABLED=true`
  - `DOCSURI_NOVELTY_JOB_QUEUE_URL`
  - `DOCSURI_NOVELTY_ARTIFACT_BUCKET`
  - `DOCSURI_NOVELTY_ARTIFACT_PREFIX`
- API task role can send novelty jobs and read/write `s3://docsuri-papers-fulltext-*/novelty/*`.

## Tests and Verification

- Added `backend/tests/test_novelty.py`.
- Covered source-key normalization, source-ref validation, owner isolation, state transition guard, Notion approval invariant, SSRF guard, worker completion/failure ack paths, manuscript degraded path, SSE encoding, API create/status/cancel, and unsupported manuscript rejection.

Commands run:

- `python -m pytest backend/tests/test_novelty.py -q` -> 15 passed
- `python -m pytest backend/tests/test_novelty.py backend/tests/test_app_shell.py -q` -> novelty tests passed; existing app-shell assertions failed because this local shell lacks `docsuri_shared`, `docsuri_ops`, and discovery dependencies.
- `python -m ruff check backend/modules/novelty backend/wiring.py backend/app.py backend/migrations/__main__.py backend/tests/test_novelty.py backend/tests/test_app_shell.py ops/cdk/stacks/novelty_stack.py ops/cdk/stacks/compute_stack.py ops/cdk/app.py` -> passed
- `python -m compileall backend/modules/novelty backend/wiring.py ops/cdk/stacks/novelty_stack.py ops/cdk/app.py` -> passed
- `cd ops/cdk; cdk synth` -> passed with existing CDK warnings; synthesized `Docsuri-Novelty`.

## Deferred Items

- Real U2 full-search, Agent-Browser, similarity, and Notion clients are adapter seams in this code pass.
- News search remains out of v1 scope.
- DOCX upload remains out of v1 scope.
- No novelty score or "newness proven" judgment is generated.
