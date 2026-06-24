# u9-personalization-code-generation-plan.md — Code Generation 계획 + 승인 게이트

**단계**: CONSTRUCTION -> Code Generation (유닛별 루프)  
**유닛**: U9 Personalization  
**일자**: 2026-06-23  
**근거**: `construction/u9-personalization/functional-design/`, `nfr-requirements/`, `nfr-design/`, `infrastructure-design/`

> 본 계획서는 승인 게이트다. 승인 전에는 앱 코드를 생성하지 않는다.

## 1. Part 1 Planning Checklist

- [x] U9 functional/NFR/infrastructure design artifacts reviewed.
- [x] U9 story map reviewed: US-P1..US-P6 Owner=U9, US-P7 contribution to U6 observability.
- [x] Existing backend module, wiring, migration, and test patterns reviewed.
- [x] Exact application code paths identified outside `aidlc-docs/`.
- [x] Code generation steps defined with story traceability.

## 2. 구현 범위

- Backend only: `backend/modules/personalization/`.
- Existing backend app-shell/ECS API deployment reuse.
- Existing RDS PostgreSQL migration path reuse.
- Existing U6 observability reuse.
- No frontend settings UI in this unit; U5 can call the API later.
- No SQS queue, Redis cache, OpenSearch index, S3 bucket, Bedrock call, or separate ECS service.
- No `user_behavior_event_backup` table. User raw-log deletion directly deletes owner-scoped active rows.

## 3. 생성/수정 예정 경로

| Type | Path |
| --- | --- |
| New module | `backend/modules/personalization/` |
| Module files | `backend/modules/personalization/__init__.py`, `controller.py`, `models.py`, `repository.py`, `service.py`, `maintenance.py` |
| Migration | `backend/modules/personalization/migrations/001_create_personalization_tables.sql` |
| Migration runner update | `backend/migrations/__main__.py` |
| App-shell wiring update | `backend/wiring.py` |
| Backend tests | `backend/tests/test_personalization.py`, `backend/tests/test_app_shell.py` |
| Infra CDK update | `ops/cdk/stacks/compute_stack.py` |
| Code summary docs | `aidlc-docs/construction/u9-personalization/code/summary.md` |

## 4. Dependencies and Interfaces

| Dependency | Use |
| --- | --- |
| U3 Accounts | `Principal` and owner-scoped user identity. |
| U6 Reliability/Ops | Gateway path and operational telemetry without raw behavior payloads. |
| U2 Discovery | Calls search decision and emits `search_executed` / `paper_opened` after success. |
| U4 Library | Emits `library_added` / `library_removed` after owner-scoped success. |
| U7 Summarization | Calls summary/translation defaults and emits summary/glossary events. |
| U5 Frontend | Calls settings/delete/reset and frontend-only source-anchor event endpoint later. |

## 5. Story Traceability

| Story | Planned implementation |
| --- | --- |
| US-P1 | Event DTO, allowlist validation, dedupe, best-effort record endpoint/service. |
| US-P2 | Event types for library add/remove and source anchor; library removal captures paper subject before delete at caller integration point. |
| US-P3 | Lazy deterministic aggregation from active events into bounded profile. |
| US-P4 | Search decision endpoint/read port returning bounded boosts and fail-open default. |
| US-P5 | Summary/translation default decision endpoint/read port. |
| US-P6 | Settings toggle, raw event direct delete, profile reset endpoints. |
| US-P7 | U6 telemetry for record/aggregation/degraded decision/delete/reset/purge events. |

## 6. Code Generation Steps

- [x] **Step 1 — Module skeleton**
  - Create `backend/modules/personalization/`.
  - Add `__init__.py`.
  - Keep module import light so app-shell can graceful-skip only on real import failures.

- [x] **Step 2 — Domain models and policy**
  - Create `models.py`.
  - Define `BehaviorEvent`, event type literals/enums, subject metadata, settings, profile, decision DTOs.
  - Implement metadata allowlist policy with no raw paper text, no anchor-nearby source text, no credentials/tokens, no free-form click payload.

- [x] **Step 3 — Repository seam**
  - Create `repository.py`.
  - Provide in-memory repository for tests/local SQLite path.
  - Provide SQLAlchemy/PostgreSQL repository for production RDS.
  - Implement owner-scoped insert, dedupe lookup, active event list, direct user event delete, profile upsert/reset, settings read/write, and timestamp purge.

- [x] **Step 4 — Business services**
  - Create `service.py`.
  - Implement `BehaviorEventRecorder`, `ProfileAggregator`, `PersonalizationReadPort`, and `PersonalizationSettingsService`.
  - Ensure U9 read/record failures fail open for caller feature paths.

- [x] **Step 5 — API controller**
  - Create `controller.py`.
  - Add routes:
    - `POST /api/personalization/events`
    - `GET /api/personalization/decision/search`
    - `GET /api/personalization/decision/summary-defaults`
    - `PATCH /api/personalization/settings`
    - `POST /api/personalization/delete-events`
    - `POST /api/personalization/reset-profile`
  - Gate routes with `PERSONALIZATION_ENABLED`.
  - Use existing `Principal` dependency pattern.

- [x] **Step 6 — Maintenance command**
  - Create `maintenance.py`.
  - Add idempotent retention purge command for `PERSONALIZATION_RAW_EVENT_RETENTION_DAYS` default `90`.
  - Emit U6 success/failure telemetry with row count/status only.

- [x] **Step 7 — RDS migration**
  - Create `backend/modules/personalization/migrations/001_create_personalization_tables.sql`.
  - Add only:
    - `user_behavior_events`
    - `user_interest_profiles`
    - `personalization_settings`
  - Do not add `user_behavior_event_backup`.
  - Add owner/time/dedupe indexes needed for owner isolation, dedupe, aggregation, and purge.

- [x] **Step 8 — Migration runner integration**
  - Update `backend/migrations/__main__.py` to include `backend/modules/personalization/migrations`.
  - Keep existing migration behavior unchanged.

- [x] **Step 9 — App-shell wiring**
  - Update `backend/wiring.py` with `_mount_personalization`.
  - Reuse existing DB engine/session factory when PostgreSQL is configured.
  - Inject U6 observability from `app.state.observability`.
  - Register module in `_INTEGRATIONS`.

- [x] **Step 10 — Backend tests**
  - Create `backend/tests/test_personalization.py`.
  - Cover event DTO roundtrip, allowlist rejection, dedupe, owner isolation, deterministic aggregation, direct raw-log delete, profile reset, fail-open decision behavior, and idempotent purge.
  - Use existing pytest/Hypothesis stack where suitable.

- [x] **Step 11 — App-shell tests**
  - Update `backend/tests/test_app_shell.py`.
  - Add `personalization` to module registry expectations.
  - Assert feature flag default behavior does not expose active endpoints unexpectedly.

- [x] **Step 12 — Infrastructure wiring for cleanup**
  - Update `ops/cdk/stacks/compute_stack.py`.
  - Add EventBridge scheduled ECS RunTask for the backend maintenance command.
  - Add IAM/EventBridge permission required to run the task.
  - Add CloudWatch alarm path for purge failure metric.

- [x] **Step 13 — Code summary document**
  - Create `aidlc-docs/construction/u9-personalization/code/summary.md`.
  - Summarize generated files, endpoints, tables, cleanup behavior, telemetry, and test commands.

- [x] **Step 14 — Verification commands**
  - Run the smallest relevant checks:
    - `python -m pytest backend/tests/test_personalization.py backend/tests/test_app_shell.py -q`
    - `python -m ruff check backend/modules/personalization backend/wiring.py backend/tests/test_personalization.py backend/tests/test_app_shell.py`
    - `python -m compileall backend/modules/personalization backend/wiring.py`
  - If CDK is changed, run the existing CDK synth/test command used by the repo, if locally available.

## 7. Non-Goals

- No frontend settings UI.
- No recommendation feed.
- No full clickstream SDK.
- No realtime ML pipeline.
- No backup table for deleted behavior events.
- No new always-on service or queue.

## 8. Content Validation

- Mermaid diagram: 없음.
- ASCII diagram: 없음.
- Markdown tables and lists: CommonMark compatible.
- Code paths are outside `aidlc-docs/` except markdown summary.

## 9. 승인 질문

Code Generation Part 2를 시작할까요?

A) **계획대로 U9 backend-only 코드를 생성한다.** (권장)

B) 코드 생성 전에 계획을 수정한다.

X) 기타.

[Answer]: A
