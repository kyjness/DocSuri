---
name: aidlc-unit-review
description: Per-unit code review for DocSuri AI-DLC units (u1-ingestion, u2-discovery, u3-accounts, u4-library, u5-frontend, u6-reliability-ops, u7-summarization, u7-summarization-frontend, u8-citation-graph, u9-personalization). Reviews a unit's changes against THAT unit's own functional design, NFR design, requirements, and constraints — not generic linting. FastAPI/Python-aware; emphasizes injection (SQL/param binding), authz/ACL gaps, and contract adherence. Use before merging a unit's branch.
---

# AI-DLC Per-Unit Code Review

Review one unit's changes against **its own spec**, not a generic checklist. Take the unit id as input (e.g. `u3-accounts`).

## Load the unit's context first

Before reading any code, load that unit's spec so the review is grounded:

- `aidlc-docs/construction/u{N}-{name}/` — functional design, NFR design for the unit
- `aidlc-docs/construction/plans/u{N}-*-plan.md` — the code-generation / design plans
- `aidlc-docs/inception/requirements/requirements.md` — the FR/NFR/constraint IDs this unit must satisfy
- `.aidlc-rule-details/extensions/{security,resiliency,testing}/` — opt-in extension rules that apply

> u7 spans two directories — `u7-summarization/` and `u7-summarization-frontend/`. For a u7 review, load both.

The review's job is: **does the diff satisfy this unit's requirements and violate none of its constraints?** Cite requirement IDs (FR-N / NFR-… / C-N) in findings.

## Always check these (canonical AI-DLC bug classes)

These two slipped through generic review in real AI-DLC projects — check them every time:

1. **Injection / parameter binding** — every DB query uses parameterized binding, never string interpolation. SQLAlchemy: bound params, not f-strings. Flag any user-derived value reaching a query/command unescaped.
2. **Authz / ACL gaps** — every route and request-parsing path enforces the access control its requirements specify. Flag any endpoint that parses a request but never checks ownership/permission (the classic "ACL processing gap").

## FastAPI/Python checklist (this stack)

- Pydantic models validate at the boundary; no `dict`-passing around validation.
- `async` routes don't call blocking I/O; DB sessions scoped/closed correctly.
- Errors follow `.aidlc-rule-details/common/error-handling.md`; no swallowed exceptions / bare `except`.
- Contract adherence: the unit's public API matches what dependent units expect (check `shared/` and consumers). A changed contract is a **blocking** finding — it affects other units.
- Tests exist per `aidlc-docs/construction/build-and-test/unit-test-instructions.md`; `ruff` clean.

## Output

Findings table: **severity · requirement/rule ref · file:line · issue · fix**. Severity = blocking / should-fix / nit. End with a verdict: **APPROVE** or **CHANGES REQUESTED**, and never approve with an open blocking finding (contract break, injection, or missing authz).

<!-- ponytail: one parameterized skill instead of 8 per-unit copies — loads the target unit's spec at runtime. Add a unit-specific skill only if one unit needs rules the others don't. -->
