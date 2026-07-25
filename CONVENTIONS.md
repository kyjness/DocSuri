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

## Commits

- Conventional-style 제목: `type(scope): 설명`. `type` ∈ `feat` / `fix` / `refactor` / `test` /
  `chore` / `docs` / `ci`, `scope`는 유닛(`u5` 등) 또는 `qa`.
- **커밋 제목·본문은 한국어로 작성한다.** `type(scope):` prefix만 영어로 유지한다.
  예: `feat(qa): 로컬 paper_asset 백필 스크립트`, `fix(u5): 디스플레이 수식 붕괴 방지`.
- 이미 푸시된 커밋의 메시지를 바꾸는 history rewrite(+force-push)는 SHA가 바뀌고 머지된
  이력에 영향을 주므로 지양한다 — 필요하면 명시적으로 합의한 뒤에만.

## Version tags

- SemVer, `v` prefix, **annotated** tags on `main`: `v1.0.0`.
- Cut a tag when promoting `develop → main` for a release.
- `MAJOR.MINOR.PATCH`: bump **MINOR** for shipped features, **PATCH** for fixes,
  **MAJOR** for breaking API/contract changes.
