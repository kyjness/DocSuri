# Technical Environment Document — DocSuri

> **Artifact type**: Technical Environment Document (AI-DLC inception input, per
> upstream `awslabs/aidlc-workflows` `docs/writing-inputs/technical-environment-guide.md`).
> Technical counterpart to the Vision/requirements; binding reference for the
> Construction Phase. Consolidates the per-unit `nfr-requirements/tech-stack-decisions.md`
> ADRs into the single project-level input the workflow (and `tools/aidlc-designreview`)
> expects. **Date**: 2026-06-28.

## Project Technical Summary

- **Project Name**: DocSuri (AI/ML arXiv discovery, phone-only web)
- **Project Type**: Greenfield (cycle 2)
- **Primary Runtime Environment**: Cloud
- **Cloud Provider**: AWS (account `028317349537`, region `ap-northeast-2` / Seoul)
- **Target Deployment Model**: Containers (ECS Fargate behind ALB; CloudFront for frontend)
- **Team Size**: 5 (team-a)
- **Team Experience**: All-Korean team; Python/FastAPI + TypeScript/Next.js; AWS CDK.
  Docs are authored in English; persona/label content is Korean by design.

---

## Programming Languages

### Required Languages

| Language | Version | Purpose | Rationale |
|----------|---------|---------|-----------|
| Python | 3.11+ | `backend/`, `ingestion/`, `ops/`, `shared/python/` | Single backend runtime; Bedrock/OpenSearch SDKs; Hypothesis PBT |
| TypeScript | 5.x | `frontend/` (Next.js) | Type safety; organizational frontend standard |

### Permitted Languages

| Language | Conditions for Use |
|----------|-------------------|
| Bash | Ops/deploy glue and CI scripts only |

### Prohibited Languages

| Language | Reason |
|----------|--------|
| New backend languages (Go/Java/etc.) | Backend is a single-runtime modular monolith; no second runtime without sign-off |

---

## Frameworks and Libraries

### Required Frameworks

| Framework/Library | Version | Domain | Rationale |
|-------------------|---------|--------|-----------|
| FastAPI | latest | Backend API (modular monolith, single app-shell) | Async I/O for Bedrock+OpenSearch; Pydantic v2 DTOs; auto OpenAPI |
| Pydantic | v2 | DTO validation/serialization | Shared `shared/python` bindings already on v2 |
| Next.js | latest | Frontend (phone-only web) | Org standard; SSR/static |
| AWS CDK | v2 (via `npx`) | Infrastructure as Code | AWS deployment target |
| pytest + Hypothesis | latest | Backend unit + property-based tests | PBT is an opted-in AI-DLC extension |
| Vitest | latest | Frontend tests | CI `next build` + unit gate |

### Preferred Libraries

| Library | Purpose | Use When |
|---------|---------|----------|
| `opensearch-py` | OpenSearch k-NN + BM25 client | Hybrid retrieval (app-level RRF merge) |
| `boto3` | AWS SDK (Bedrock, S3, SQS, EventBridge) | All AWS service calls |
| `httpx` | Async HTTP client | Outbound calls (e.g. Google tokeninfo, Resend) |

### Library Approval Process

New runtime dependencies require track owner + CODEOWNERS sign-off; prefer a few
lines over a new dependency. Cost-bearing dependencies (LLM/embeddings) must fit the
$1600 budget cap.

---

## Cloud Environment

### Cloud Provider

AWS only (constraint **C-5**). Production account `028317349537`, `ap-northeast-2`.
Deploy profile `AdministratorAccess-028317349537`. Cross-account team access via the
`DocsuriCrossAccountDev` role (MFA, 4h) for 3 trusted team accounts.

### Service Allow List

| Service | Purpose |
|---------|---------|
| ECS Fargate + ECR + ALB | Backend/API + ingestion worker containers (linux/amd64) |
| CloudFront + S3 | Frontend hosting/CDN |
| Amazon OpenSearch Service **2.19** | Hybrid vector (k-NN/ANN, `on_disk`) + lexical (BM25) store |
| Amazon Bedrock | Cohere embeddings + Claude (Haiku) summarization |
| RDS PostgreSQL | Relational store (accounts, library, etc.) |
| S3 (SSE-KMS, public access blocked) | DocModel JSON + full-text artifacts (**SEC-9**) |
| SQS | Ingestion worker queue (at-least-once) |
| EventBridge | Domain event backbone (e.g. `AccountDeleted`) |
| CloudWatch (+ SNS, Budgets) | Metrics/alarms (namespace via `CLOUDWATCH_NAMESPACE`), cost alerts |
| Secrets Manager | Secrets by full ARN (e.g. `RESEND_API_KEY`) |

### Service Disallow List

| Service | Reason / Alternative |
|---------|----------------------|
| Amazon SES (production send) | SES production access delayed → **Resend** is the live email channel (`EMAIL_PROVIDER=resend`) |
| Bedrock Knowledge Bases / S3 Vectors | Evaluated in spike; not the production path — self-managed OpenSearch index is authoritative |

### Service Approval Process

New AWS services require Infra-design review and a cost estimate against the $1600 cap;
RETAIN-policy resources (RDS, S3, OpenSearch) need an explicit teardown plan.

---

## Preferred Technologies and Patterns

### Architecture Patterns

- Backend = **modular monolith**, single FastAPI app-shell, units U1–U11 as modules.
- Corpus index: **single writer** (U1) / single logical reader path (U2) with
  blue/green **index generations + atomic alias cutover**; lexical-only degradation
  on cost-circuit OPEN.

### API Design Standards

- REST + auto-generated OpenAPI; DTOs validated via Pydantic v2; additive (backward-
  compatible) contract evolution only. Shared contracts live in `aidlc-docs/construction/shared/`
  (SSOT) and several are 🔒 FROZEN (`events.md`, `ports.md`, `vector-spec.md`, `dtos.md`, `docmodel.md`).

### Data Patterns

- Embeddings: **Cohere Embed Multilingual (Bedrock), 1024-dim, cosine**; writer
  `search_document` / reader `search_query` asymmetry; writer↔reader same-space
  invariant (`assert_same_space`). v3→v4 migration completed 2026-06-24
  (alias `docsuri-corpus`). Strict **Open Access (OA)** licensing only.

### Messaging and Events

- EventBridge + SQS; **at-least-once** delivery; consumers must be idempotent
  (e.g. `DeduplicationGuard`). Event schemas frozen in `shared/events.md`.

### Frontend Patterns

- Phone-only responsive web; Next.js; talks to the FastAPI gateway.

---

## Security Requirements

### Authentication and Authorization

- Session-based auth with **Secure cookies**; social login via **OIDC (Google)**
  (`httpx` tokeninfo). Admin/Ops endpoints require admin authz + **MFA** (SEC-8/SEC-12).
- Single authorization authority per concern: U3 owns authn/z; U6 owns search grounding.

### Data Protection

- S3 SSE-KMS, public access blocked (SEC-9). PII never logged; reset/verification
  tokens are plaintext-link single-use, non-logged (SEC-BR-1).

### Secrets Management

- AWS Secrets Manager, referenced by **full ARN**. No secrets in design docs or code.

### Compliance Requirements

- GDPR-style account lifecycle: soft-delete + grace purge, `AccountDeleted` cascade
  to subscriber units.

### Dependency Security

- GitHub CI runs lint + tests per unit; OIDC for deploy (no long-lived keys).

---

## Testing Requirements

### Test Strategy Overview

- Unit (pytest / vitest), property-based (Hypothesis, opted-in extension),
  integration, contract, performance per the build-and-test docs.

### CI/CD Testing Gates

- `ci.yml` — 7 jobs: per-unit lint (`ruff` **check only**, `format` not enforced) +
  pytest/vitest + SSOT/type-drift check + `next build`.
- `cd.yml` — push to `main` → ECR/ECS deploy (units ①②④) via OIDC.
- `branch-name-check.yml` — branch names must match `feature/` (+`fix/ci/chore/docs/infra`).
- `sync-stories.yml`, `CODEOWNERS` — story sync + per-track/unit ownership.

---

## How This Document Feeds Into AI-DLC

- **Construction (NFR/Infra/Code-gen)**: binds language/framework/service choices so
  stages don't re-ask or assume. Per-unit `tech-stack-decisions.md` ADRs refine, but
  must not contradict, this document.
- **`tools/aidlc-designreview`**: this file is classified `TECHNICAL_ENVIRONMENT` and
  supplies tech context to the critique/gap/alternatives agents (previously absent →
  see `operations/code-reviews/2026-06-28/designreview-audit.md`).
