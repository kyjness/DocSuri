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

## Search-Boost Application — Shadow Mode (US-P4, added 2026-07-01)

The decision path is now consumed by U2 discovery **in shadow** — measured, not applied. The
user-visible ranking is unchanged; only a metric is emitted.

- **BR-P8 clamp at the source** (`service.py` `_to_search_boosts`): `search_decision` now emits
  contract-compliant boosts (each ∈ [-0.1, +0.1], Σ|boost| ≤ 0.2) instead of raw [0,1] category
  weights. Consumers never re-clamp.
- **Relative-boost formula + top-30% rule** (`discovery/domain/ranker.py` `shadow_rerank_diff`,
  pure): boost is multiplicative and relative to each candidate's own score, applied only within
  the top 30% of ranked results, so it nudges rank without flipping the overall order. Returns a
  diff (`positions_changed`, `max_shift`, `boosted_count`) against the baseline; the baseline is
  what the caller keeps.
- **In-process wiring** (`backend/wiring.py`): the discovery orchestrator gets a `search_boosts`
  callable (default no-op) bound — via the existing `_event_publisher` patch idiom — to U9's read
  port with a per-request session. The search hot path reads only an existing cached profile
  (`cached_search_boosts`) and never lazily aggregates raw behavior events inline; PostgreSQL reads
  apply `PERSONALIZATION_DECISION_TIMEOUT_MS` via `statement_timeout`. Gated by
  `PERSONALIZATION_ENABLED`. Fail-open (BR-P13): any error / `disabled` / `no_profile` → empty
  boosts → today's exact baseline.
- **Metrics**: `personalization.rerank_shadow` (positions changed),
  `personalization.rerank_shadow.max_shift`, and
  `personalization.rerank_shadow.boosted_count`, each with dim `scope=search`, in the
  `DocSuri/Production` namespace.
- **Go-live**: replace `shadow_rerank_diff`'s `reordered` as the returned order (one line) after
  the shadow numbers confirm nudges-not-flips.
- **Deferred**: summary/translation defaults (US-P5), `keywordWeights` surfacing.

PR: #300 (branch `feature/u9-search-boost-shadow` → develop).

### Review Remediation (2026-07-01)

- BR-P8 total budget now remains within `Σ|boost| ≤ 0.2` after normalization; regression is
  covered by a Hypothesis invariant with the three-equal-category counterexample.
- Discovery shadow reads use `cached_search_boosts`, which reads only existing settings/profile
  rows and never performs lazy raw-event aggregation in the search request path.
- Shadow observability now emits positions changed, max shift, and boosted count.
- Verification: focused personalization/discovery tests passed, app-shell/orchestrator tests
  passed, backend+discovery sweep passed, touched-file Ruff passed, `git diff --check` passed,
  and `git merge-tree origin/develop HEAD` produced a clean merge tree.

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
