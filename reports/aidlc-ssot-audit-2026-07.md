# Audit — Can `aidlc-docs/` be the single source of truth?

**Date:** 2026-07-08
**Scope:** Whether the `aidlc-docs/` tree (303 markdown files, incl. `aidlc-state.md`,
`audit.md`, `technical-environment.md`) can serve as the project's single source of truth (SSOT).
**Method:** structure map + drift probes cross-checked against **live code/CDK** (not just memory).

---

## Verdict

**No — not as one undifferentiated SSOT, and it already isn't.**

`aidlc-docs/` is a **sound SSOT for the slow-changing layer** — requirements, design
intent, business rules — and a **structurally unreliable SSOT for the fast-changing
layer** — deployed model/alias, `EMAIL_PROVIDER`, deploy/health status. The project
already declares it the SSOT (`sync-stories.yml` header; `aidlc-state.md`: "본 절이 현재
상태의 단일 진실"), so this audits a *standing claim* — and the claim is overbroad.

---

## What SSOT requires, and how the docs score

One canonical place · no competing authority per fact · kept current by a *mechanism* ·
queryable for "what is true **now**."

| Criterion | Result |
|---|---|
| No literal duplication of code | ✅ `code/` dirs hold `*-code-summary.md` prose, not copies of `backend/`. |
| Single authority per fact | ❌ Runtime facts are authoritative in CDK env / task-defs / live AWS and *copied* (stale) into docs. |
| Kept current by a mechanism | ❌ Only `sync-stories.yml` auto-syncs, and only `stories.md`→issues. No code→doc or live→doc guard. |
| Queryable "current state" | ❌ Current state lives in two append-only ledgers (`aidlc-state.md` 161 KB, `audit.md` 392 KB); the canonical value has no fixed address. |
| Fresh | ❌ Newest `aidlc-state.md` entry = 2026-07-02; audit run 2026-07-08. Freshest state artifact in the repo is `reports/roadmap-2026-07.md`, **not** an aidlc-doc. |

---

## Evidence — two hard drifts, confirmed against live code

| Fact | `aidlc-docs` said | Live code says | Verdict |
|---|---|---|---|
| Email provider | `EMAIL_PROVIDER=resend`, "SES 폐기" — `technical-environment.md:102` | default `"ses"` — `email.py` (`getenv("EMAIL_PROVIDER","ses")`), `compute_stack.py` (`"EMAIL_PROVIDER":"ses"`) | **docs were wrong** |
| Embedding (reader) | v4 `embed-multilingual-v4.0`, alias `docsuri-corpus`/`-v2` — `technical-environment.md:131`, `construction/v4-migration/*` | `cohere.embed-multilingual-v3` → alias `docsuri-corpus-c3ml` — `ops/cdk/stacks/compute_stack.py` (`DOCSURI_BEDROCK_MODEL_ID` / `DOCSURI_OPENSEARCH_INDEX`, ~L254 on develop) | **docs were wrong** |

**Bonus finding (not fixed — see below):** the live code is *itself* internally
inconsistent, because a re-embed migration is in flight:

- reader (`compute_stack.py`) → `cohere.embed-multilingual-v3` / `docsuri-corpus-c3ml`
- ingestion (`ingestion_stack.py`) → `cohere.embed-multilingual-v3` / `docsuri-corpus-v2`
- novelty (`novelty_stack.py`) → `global.cohere.embed-v4:0`

The runtime truth is split across three stacks and changing. **No prose snapshot can
track this** — which is exactly why it must be a pointer to the stacks, not a copy.

---

## Root causes (not symptoms)

1. **No enforcement on the prose.** CI's `tools/generate.py --check` drift guard covers
   *DTO/type contracts* in `shared/`. Nothing asserts a value written in doc prose still
   matches code. Drift stays invisible until a human notices — which is why the live
   truth had migrated into out-of-band memory notes, not the docs.
2. **Append-only ledgers, not a state table.** Answering "what's the live email provider?"
   means reading the *newest* entry across 550 KB of chronological prose. A log is a poor
   SSOT: the canonical value has no fixed address.
3. **Fast-changing facts were copied, not pointed at.** `technical-environment.md`
   hard-coded `EMAIL_PROVIDER=resend` and `1024-dim v4`. A copy drifts; a pointer
   ("`EMAIL_PROVIDER` → `compute_stack.py` env") can't. The docs even self-admit deferral
   ("라이브 배포는 리포지토리 대조 불가 → AWS 콘솔 확인 필요") — an SSOT that defers to
   another authority for the answer is not the SSOT for that fact.

---

## The clean split

**Keep as SSOT** (slow, no competing authority, already works): requirements (FR/NFR/C),
user stories (already synced to issues), business rules (BR-*), per-unit functional/NFR
design intent, constraints, architecture rationale, and the frozen `construction/shared/`
contracts (which *are* enforced by the CI drift guard).

**Stop treating as SSOT** (fast, authoritative elsewhere, unsynced): deployed embedding
model/dims/alias, `EMAIL_PROVIDER`, deploy/health status, test counts (docs already carry
a standing "테스트 수 드리프트" disclaimer), task-def revisions. Authority = code / CDK /
live AWS — read live.

---

## Fixes applied in this change

1. **This report** — `reports/aidlc-ssot-audit-2026-07.md`.
2. **`technical-environment.md`** — corrected both drifts and rewrote them as **pointers
   to the authoritative code** (email provider → `compute_stack.py` env; embedding
   model/alias → `*_stack.py` env + frozen `shared/vector-spec`), with a dated snapshot
   labelled non-authoritative. Removed the now-false "SES disallowed / Resend live" row;
   added SES to the service allow list. Added a header de-drift note.
3. **`aidlc-state.md`** — added a top-of-file **SSOT-scope banner**: docs own
   requirements/design intent; runtime/config truth lives in code/CDK/live AWS.
4. **`sync-stories.yml`** — narrowed the "source of truth" header comment to
   requirements/design/stories.

## Deliberately NOT done (and why)

- **A CI guard that parses doc prose to assert values match code** — *skipped.* Once the
  fast-changing values are pointers (fix #2) there is nothing left to drift, so the guard
  would be brittle Korean-prose parsing guarding a problem that no longer exists. Pointers
  are enforcement by construction. (Ponytail: take the higher rung; don't build what the
  higher-rung fix eliminates.)
- **"Fixing" the three-stack model/alias inconsistency** — *left alone.* It is a live
  in-flight re-embed migration, plausibly intentional (novelty on v4, reader on v3ml). It
  belongs to the migration owner, not a docs audit. Flagged above; the doc now says "read
  the stacks."

## If you want more later (not required)

Collapse the two append-only ledgers into one short **current-state table** at the top of
`aidlc-state.md` — one row per fast-changing fact, each a *pointer* to its authority. That
turns "read the newest of 550 KB" into an O(1) lookup. Deferred: the pointer fixes above
already remove the drift; this is ergonomics, not correctness.
