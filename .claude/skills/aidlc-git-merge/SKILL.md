---
name: aidlc-git-merge
description: Resolve merge conflicts that arise from parallel unit development in DocSuri. Auto-merges AI-DLC state files (aidlc-docs/aidlc-state.md and aidlc-docs/audit.md) by combining each unit's progress records; classifies code conflicts as additive / overlapping / dependency-changing across units u1-ingestion … u8-citation-graph and proposes a resolution for each. Use when a git merge or rebase across unit branches conflicts.
---

# AI-DLC Git Merge

Resolve conflicts from concurrent unit work. Two conflict classes, handled differently.

## 1. AI-DLC state files → auto-merge

`aidlc-docs/aidlc-state.md` and `aidlc-docs/audit.md` are append-style progress logs. When both sides changed them, **do not pick a side** — union them: keep every unit's progress/audit entries from both branches, ordered by unit id (u1…u8) then timestamp. These files almost never have a *true* conflict; the conflict is just two units appending. Resolve automatically and report what was combined.

## 2. Code files → classify, then resolve

For each conflicting code hunk, classify it:

| Class | What it is | Resolution |
|---|---|---|
| **Additive** | Both sides *added* independent code (new functions/routes/files), no overlap | Keep both. Auto-resolve. |
| **Overlapping** | The *same* lines were edited differently on each side | Reconstruct intent from both unit plans, propose a merged version, **ask the human to confirm**. |
| **Dependency-changing** | A shared contract changed — `shared/`, a cross-unit API, a DB schema, a Pydantic model both units consume | **Stop.** This needs a design decision, not a merge. Surface both versions, name the units affected, escalate to the human. |

Read the relevant unit plans under `aidlc-docs/construction/u*/` and `aidlc-docs/construction/plans/` to recover intent before proposing any overlapping/dependency resolution. Never guess across a contract boundary.

## Process

1. List conflicted files; bucket into state-files vs code.
2. Auto-merge state files (union by unit/timestamp).
3. Classify each code conflict; auto-resolve additive, propose overlapping, escalate dependency-changing.
4. Print a summary table: file · class · action taken / decision needed.
5. **Do not commit.** Leave the merge staged for human review and let them run the build/tests.

## Guardrails

- Anything touching `shared/` or a cross-unit contract is dependency-changing by default — when unsure, escalate, don't merge.
- Re-run `pytest` + `ruff` after resolution (or tell the human to); a clean merge that breaks tests is not resolved.

<!-- ponytail: union-merge for append-only state files; everything semantic goes to a human gate. No clever auto-resolve across contracts. -->
