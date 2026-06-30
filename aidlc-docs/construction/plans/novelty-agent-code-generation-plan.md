# Novelty Agent — Code Generation 계획 + 승인 게이트

**단계**: CONSTRUCTION -> Code Generation  
**유닛**: Novelty Agent  
**일자**: 2026-06-30  
**근거**: `construction/novelty-agent/functional-design/`, `nfr-requirements/`, `nfr-design/`, `infrastructure-design/`

> 본 계획서는 승인 게이트다. 승인 전에는 앱 코드를 생성하지 않는다.

## 1. Part 1 Planning Checklist

- [x] Functional/NFR/Infrastructure design artifacts reviewed.
- [x] User stories reviewed: US-NV1..US-NV9.
- [x] Existing backend module, worker, migration, SQS/Fargate, RDS/S3, and U6 observability patterns reviewed.
- [x] Exact application code paths identified outside `aidlc-docs/`.
- [x] Code generation steps defined with story traceability.

## 2. 구현 범위

- Backend module: `backend/modules/novelty/`.
- Existing backend app-shell route mounting.
- Existing custom SQL migration runner.
- Existing RDS, S3, SQS, ECS/Fargate, CloudWatch/U6 patterns.
- New novelty SQS queue/DLQ and worker CDK mapping.
- SSE progress endpoint plus polling/status fallback.
- PDF/Markdown/TXT manuscript scope only; DOCX excluded.
- Notion export state and token encryption boundary, but no plaintext token in job payload.

## 3. 생성/수정 예정 경로

| Type | Path |
|---|---|
| New module | `backend/modules/novelty/` |
| Module files | `__init__.py`, `controller.py`, `models.py`, `repository.py`, `service.py`, `worker.py`, `adapters.py`, `validators.py`, `streaming.py`, `security.py` |
| Migration | `backend/modules/novelty/migrations/001_create_novelty_tables.sql` |
| Migration runner update | `backend/migrations/__main__.py` |
| App-shell wiring update | `backend/wiring.py` |
| Backend tests | `backend/tests/test_novelty.py`, `backend/tests/test_app_shell.py` |
| Infra CDK update | `ops/cdk/stacks/novelty_stack.py`, `ops/cdk/app.py` |
| Optional env wiring | Existing deploy/env files if required by current CDK pattern |
| Code summary docs | `aidlc-docs/construction/novelty-agent/code/summary.md` |

## 4. Dependencies and Interfaces

| Dependency | Use |
|---|---|
| U3 Accounts | Principal and owner-scoped user identity. |
| U6 Reliability/Ops | CostGuard, ObservabilityHub, gateway safety, incident signals. |
| U2 Discovery | Bounded `full` search. |
| EvidenceFormationPort | First-order evidence input; currently provisional, so implement behind adapter/fixture seam. |
| Shared DocModel/SourceRef | Anchor/source identity validation. |
| Agent-Browser | Server-side GitHub/dataset search. |
| Notion MCP/OAuth | Approval-gated export. |

## 5. Story Traceability

| Story | Planned implementation |
|---|---|
| US-NV1 | Natural language job creation, evidence adapter, U2 full fallback. |
| US-NV2 | PDF/Markdown/TXT manuscript job path and parse failure state. |
| US-NV3 | Similar work table artifact and source refs. |
| US-NV4 | GitHub/dataset external finding adapters with allowlist. |
| US-NV5 | Manuscript risk signal artifact shape. |
| US-NV6 | Novelty candidates and experiment plan artifacts with required fields. |
| US-NV7 | Progress events, SSE endpoint, degraded visibility. |
| US-NV8 | Internal result persistence and Notion preview/approval/export state. |
| US-NV9 | U6 telemetry, budget exceeded, source degraded, half-baked completion signals. |

## 6. Code Generation Steps

- [x] **Step 1 — Module skeleton**
  - Create `backend/modules/novelty/` and lightweight `__init__.py`.
  - Keep imports safe for app-shell mounting.

- [x] **Step 2 — Domain models and state machines**
  - Create `models.py`.
  - Define job request, progress event, artifacts, export state, degraded reason, validation result.

- [x] **Step 3 — Repositories and storage seams**
  - Create `repository.py`.
  - Implement owner-scoped job/event/artifact/export repository seams.
  - Include S3 artifact store interface and in-memory test implementation.

- [x] **Step 4 — Output validators**
  - Create `validators.py`.
  - Implement schema/source_ref/abstain/anchor checks.
  - Do not call or clone U6 GroundingEnforcementHook.

- [x] **Step 5 — Security and egress guard**
  - Create `security.py`.
  - Implement external query minimization, allowlist checks, and SSRF guard seam for fetched URLs.

- [x] **Step 6 — Service orchestration**
  - Create `service.py`.
  - Implement job creation, cancel, stage snapshot persistence, degraded handling, and export approval.

- [x] **Step 7 — Adapters**
  - Create `adapters.py`.
  - Add seams for EvidenceFormationPort, U2 full search, Agent-Browser, LLM, shared parser/evidence output, Notion export, U6 telemetry/cost.

- [x] **Step 8 — Worker**
  - Create `worker.py`.
  - Implement SQS payload handling, stage loop, bounded retry/degraded behavior, cancel checks, and progress emission.

- [x] **Step 9 — API controller and SSE**
  - Create `controller.py` and `streaming.py`.
  - Add job create/status/result/cancel/SSE/export preview/export approval routes.
  - SSE uses persisted progress events and polling fallback; no Last-Event-ID replay in v1.

- [x] **Step 10 — RDS migration**
  - Create `backend/modules/novelty/migrations/001_create_novelty_tables.sql`.
  - Add `novelty_jobs`, `novelty_progress_events`, `novelty_artifacts`, `novelty_exports`, `notion_connections`.
  - Use custom SQL runner; do not introduce Alembic.

- [x] **Step 11 — Migration runner and app-shell wiring**
  - Update `backend/migrations/__main__.py`.
  - Update `backend/wiring.py` with `_mount_novelty`.
  - Set deployment activation flag default to enabled (`NOVELTY_AGENT_ENABLED=true`).

- [x] **Step 12 — Backend tests**
  - Create `backend/tests/test_novelty.py`.
  - Cover DTO roundtrip, source normalization idempotency, job state transition, owner isolation, export approval invariant, validator abstain behavior, SSRF guard, cancel, SSE read model.
  - Update `backend/tests/test_app_shell.py`.

- [x] **Step 13 — Infrastructure CDK**
  - Add `ops/cdk/stacks/novelty_stack.py`.
  - Add SQS queue/DLQ, Fargate worker, IAM, S3 prefix permissions, env vars, CloudWatch alarms.
  - Register the stack in `ops/cdk/app.py`.

- [x] **Step 14 — Code summary document**
  - Create `aidlc-docs/construction/novelty-agent/code/summary.md`.
  - Summarize generated files, routes, tables, worker, CDK, tests, and known deferred items.

- [x] **Step 15 — Verification commands**
  - Run the smallest relevant checks:
    - `python -m pytest backend/tests/test_novelty.py backend/tests/test_app_shell.py -q`
    - `python -m ruff check backend/modules/novelty backend/wiring.py backend/tests/test_novelty.py backend/tests/test_app_shell.py`
    - `python -m compileall backend/modules/novelty backend/wiring.py`
  - If CDK changes are made, run the repo's existing CDK synth command if locally available.

## 7. Non-Goals

- No DOCX upload support in v1.
- No news search.
- No novelty score or "newness proven" judgment.
- No paper prose generation.
- No code skeleton generation for the user's research project.
- No separate novelty microservice.
- No separate search index or ranking model.
- No Last-Event-ID replay store.

## 8. Content Validation

- Mermaid diagram: 없음.
- ASCII diagram: 없음.
- Markdown tables and lists: CommonMark compatible.
- Application code paths are outside `aidlc-docs/`; documentation summaries stay under `aidlc-docs/`.

## 9. 승인 질문

Code Generation Part 2를 시작할까요?

A) 계획대로 Novelty Agent backend/worker/infra 코드를 생성한다. (권장)

B) 코드 생성 전에 계획을 수정한다.

X) 기타 (아래 [Answer]: 태그 뒤에 설명해 주세요)

[Answer]: A
