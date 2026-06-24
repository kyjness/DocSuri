# DocSuri Conventions

Team VCS conventions. AIDLC (`AGENTS.md`, `.aidlc-rule-details/`) governs the **document**
lifecycle; AIDLC is deliberately silent on git, so the git workflow is documented here.

## Branches (git-flow)

- **`main`** — production. What's deployed at https://docsuri.org. Advanced only by promoting `develop`.
- **`develop`** — integration target. All work merges here first, via GitHub PR.
- Working branches are short-lived and merge into `develop` through a PR.

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
