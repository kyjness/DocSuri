# U9 Personalization — Code Summary

**Unit**: U9 Personalization  
**Stage**: CONSTRUCTION -> Code Generation  
**Date**: 2026-06-23

## Generated Application Code

| Path | Purpose |
| --- | --- |
| `backend/modules/personalization/__init__.py` | Module export. |
| `backend/modules/personalization/models.py` | Event/profile/settings/decision DTOs and metadata allowlist. |
| `backend/modules/personalization/repository.py` | In-memory and SQL repositories, active event/profile/settings persistence. |
| `backend/modules/personalization/service.py` | Event recorder, lazy aggregator, decision read port, settings/delete/reset service. |
| `backend/modules/personalization/controller.py` | FastAPI routes under `/api/personalization`. |
| `backend/modules/personalization/maintenance.py` | Idempotent retention purge command. |
| `backend/modules/personalization/migrations/001_create_personalization_tables.sql` | RDS tables and indexes. |

## Modified Application Code

| Path | Change |
| --- | --- |
| `backend/app.py` | Added U9 migrations to startup migration list. |
| `backend/migrations/__main__.py` | Added U9 migration directory to migration CLI. |
| `backend/wiring.py` | Mounted U9 module and injected SQL/in-memory repository. |
| `backend/tests/test_app_shell.py` | Added `personalization` to module registry expectations. |
| `ops/cdk/stacks/compute_stack.py` | Added U9 env defaults, daily EventBridge ECS cleanup task, and purge failure alarm. |

## Endpoints

| Route | Behavior |
| --- | --- |
| `POST /api/personalization/events` | Records an allowlisted meaningful behavior event, best-effort. |
| `GET /api/personalization/decision/search` | Returns bounded search boosts or fail-open default. |
| `GET /api/personalization/decision/summary-defaults` | Returns summary/translation defaults or fail-open default. |
| `GET /api/personalization/settings` | Returns the current user's personalization settings. |
| `PATCH /api/personalization/settings` | Enables/disables personalization. |
| `POST /api/personalization/delete-events` | Directly deletes owner-scoped active raw events. |
| `POST /api/personalization/reset-profile` | Clears aggregate profile/defaults. |

All routes are gated by `PERSONALIZATION_ENABLED`; CDK deploy default is enabled.

## Tables

Created by `backend/modules/personalization/migrations/001_create_personalization_tables.sql`:

- `user_behavior_events`
- `user_interest_profiles`
- `personalization_settings`

No `user_behavior_event_backup` table is created.

## Retention Cleanup

`python -m backend.modules.personalization.maintenance` deletes `user_behavior_events` older than `PERSONALIZATION_RAW_EVENT_RETENTION_DAYS` (default `90`). The command is timestamp-predicate based and idempotent. CDK wires it as a daily EventBridge scheduled ECS task using the existing backend image.

## Verification

Passed:

- `python -m pytest backend/tests/test_personalization.py -q` -> 11 passed
- `$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'; python -m pytest backend/tests/test_personalization.py backend/tests/test_app_shell.py -q` -> 25 passed
- `$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'; python -m pytest backend/tests -q` -> 57 passed, 1 skipped
- `python -m ruff check backend/modules/personalization backend/wiring.py backend/app.py backend/migrations/__main__.py backend/tests/test_personalization.py backend/tests/test_app_shell.py ops/cdk/stacks/compute_stack.py` -> pass
- `python -m compileall backend/modules/personalization backend/wiring.py backend/app.py ops/cdk/stacks/compute_stack.py` -> pass
- `python -m pip install -r ops/cdk/requirements.txt` -> pass
- `$env:JSII_NODE="$env:USERPROFILE\scoop\apps\nodejs-lts\current\node.exe"; cdk synth` from `ops/cdk` -> pass; synthesized to `ops/cdk/cdk.out`
