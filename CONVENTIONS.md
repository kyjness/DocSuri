# DocSuri Conventions

VCS conventions. AIDLC (`AGENTS.md`, `.aidlc-rule-details/`) governs the **document**
lifecycle; AIDLC is deliberately silent on git, so the git workflow is documented here.

> **Solo-fork mode (2026-07~).** The 4-person team and the upstream
> `80-hours-a-week/DocSuri` are retired; this fork is maintained solo. The PR-first rule
> below is relaxed accordingly — the rest (branch naming, commit style, tags) still applies.

## Branches (git-flow)

- **`main`** — production/release line. The docsuri.org deployment is retired (redeploy
  deferred — see `aidlc-docs/operations/solo-local-migration.md` §7); promote `develop`
  into `main` when cutting a release/portfolio snapshot.
- **`develop`** — integration target and default branch. **Direct commits and direct
  pushes to `develop` are allowed** (solo maintenance; a self-approved PR adds ceremony,
  not review — CI runs on `develop` pushes anyway).
- Working branches + PR are still preferred for larger or riskier work. Rule of thumb:
  work that fits one session and reverts cleanly → commit straight to `develop`; multi-day,
  structural, or experimental work (e.g. the novelty agent redesign) → branch + PR, which
  keeps unfinished work off `develop`, leaves a reviewable record, and enables PR-based
  deep review tooling.
- Working branches, when used, are short-lived and merge into `develop` through a PR.

### Branch naming

`<type>/<short-kebab-description>` — optionally encoding the AIDLC Unit of Work or story id.

| Type       | Use                                   | Example                          |
|------------|---------------------------------------|----------------------------------|
| `feature/` | new functionality (often a Unit)      | `feature/u8-export-pdf`          |
| `fix/`     | bug fix                               | `fix/u3-accounts-session`        |
| `ci/`      | CI/CD pipeline                        | `ci/branch-naming-convention`    |
| `chore/`   | maintenance, tooling                  | `chore/aidlc-github-sync`        |
| `docs/`    | documentation only                    | `docs/system-infrastructure-design` |
| `infra/`   | infrastructure / IaC                  | `infra/cdk-scaffold`             |

- **Standardized on `feature/`** (not `feat/`) — the historical split is resolved in favour of the longer form.
- Construction re-passes after a review-gate rejection take a `-vN` suffix: `feature/u7-v2`, `feature/u7-v3`.
- Enforced by `.github/workflows/branch-name-check.yml`, which fails any PR whose source branch
  doesn't match an approved prefix. `develop` is allowed only as the source of `develop → main` release PRs.

## Version tags

- SemVer, `v` prefix, **annotated** tags on `main`: `v1.0.0`.
- Cut a tag when promoting `develop → main` for a release.
- `MAJOR.MINOR.PATCH`: bump **MINOR** for shipped features, **PATCH** for fixes,
  **MAJOR** for breaking API/contract changes.
