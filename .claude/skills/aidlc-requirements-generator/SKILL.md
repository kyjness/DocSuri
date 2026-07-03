---
name: aidlc-requirements-generator
description: Convert informal source documents (Figma exports, PDFs, slides, persona notes, meeting notes) into a structured DocSuri requirements spec — FR-N functional requirements, NFR-{cat}N non-functional requirements, and C-N constraints — written under aidlc-docs/inception/requirements/. Use during the INCEPTION phase when turning raw inputs into a reviewable requirements document.
---

# AI-DLC Requirements Generator

Turn unstructured inputs into a structured, ID'd requirements spec. This skill runs in the **INCEPTION phase**, Requirements Analysis stage.

## Hard rule: only extract what is stated

Derive requirements **only** from information explicitly present in the source documents. Never invent, assume, or "fill in" a sensible default. Anything the sources do not cover goes into a **`## Open Questions`** section as an explicit gap — do not silently resolve it.

## Inputs

Point the skill at source material: Figma frames/exports, PDFs, slide decks, persona docs, or meeting notes (e.g. the team's wiki dailies). Read every source before writing anything.

## ID scheme (matches existing DocSuri convention)

- `FR-{n}` — functional requirement (sequential: FR-1, FR-2, …)
- `NFR-{cat}{n}` — non-functional, grouped by category letter already in use (e.g. `NFR-A1` availability, `NFR-C1` capacity, `NFR-P1` performance …). Reuse an existing category before minting a new one — check `aidlc-docs/inception/requirements/requirements.md` first.
- `C-{n}` — constraint (single flat series; continue the `C-1…` sequence already in `requirements.md` §9). Record the kind — technical / business / legal-compliance — in the **Kind** column, not in the ID. Do **not** introduce `TC-`/`BC-`/`LC-` prefixes: there is no such convention here, and `LC-` is already taken (it means "Logical Component" in `aidlc-docs/construction/u5-frontend/nfr-design/`).

Each requirement is one row: **ID · statement · source ref · (FR only) acceptance criterion**. Trace every item back to the document it came from.

## Output

Write to `aidlc-docs/inception/requirements/requirements.md` (append/merge — never clobber existing IDs; continue the sequence). If the input is a distinct feature track, write a sibling file like `requirements/<feature>.md` and cross-link, matching the existing per-feature files there.

Structure:

```
## Functional Requirements
| ID | Requirement | Source | Acceptance |
| FR-40 | ... | personas.md §2 | ... |

## Non-Functional Requirements
| ID | Requirement | Source |

## Constraints
| ID | Kind | Constraint | Source |

## Open Questions
- [ ] <gap the sources did not answer> — needs a human decision
```

## After writing

Summarize: counts (N functional, N non-functional, N constraints, N open questions) and the highest ID in each series. Do **not** proceed to user stories or design — stop at the human approval gate. Open Questions must be resolved by the team before CONSTRUCTION.

<!-- ponytail: appends to the existing requirements.md ID series rather than introducing a parallel format. -->
