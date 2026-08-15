# DocSuri Conventions

VCS conventions. AIDLC (`AGENTS.md`, `.aidlc-rule-details/`) governs the **document**
lifecycle; AIDLC is deliberately silent on git, so the git workflow is documented here.

> **Solo-fork mode (2026-07~).** The 4-person team and the upstream
> `80-hours-a-week/DocSuri` are retired; this fork is maintained solo. The PR-first rule
> below is relaxed accordingly — the rest (branch naming, commit style, tags) still applies.

## Branches (git-flow)

- **`main`** — production/release line. The docsuri.org deployment is retired (redeploy
  deferred); promote `develop`
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
- **제목은 명사구로 쓴다. 동사 종결(`~한다` / `~막는다`) 금지.** 목록에서 훑을 때 읽는 것은
  제목뿐이고, 명사구가 짧고 스캔하기 쉽다. 갈래가 여럿이면 em-dash로 잇는다.

  ```
  fix(u1): 크롭 프레이밍 수리 — 그림·표 본체 크롭 + 외부 소스 fetch 규약
  feat(u1): 자산 단계 감사 확장 — 유형별 판정 추가
  ```

- **본문은 갈래별로 나눈다.** 한 문단에 문제·원인·해법을 뭉치면 훑을 수가 없다. 굵은 소제목
  아래 관찰을 `-`로, 그 갈래의 해법을 `→` 한 줄로 적고, 숫자는 **실측** 블록에 따로 묶는다.

  ```
  **근거 판정의 두 구멍**
  - "회수가 상자를 안 움직임"을 "그래픽 없음"으로 읽었다. 상자가 이미 그래픽
    위에 있을 때도 회수는 안 움직인다 — 정반대의 뜻이다.
  - "Figure N" 라벨이 <head>에 있으면 캡션이 비어 보였다.
  → 판정 헬퍼를 회수와 공유하고, 스펙에 라벨을 실어 근거 셋을 다 본다.

  **실측** (30편 캐시)
  - 저장 1,107 → 1,108 — 오폐기됐던 진짜 표 크롭 복원
  - duplicate_region 3 → 2, 그 외 유형 전부 불변
  ```

- **PR 본문에도 같은 기준을 적용한다** — 템플릿 섹션 안에서 굵은 소제목 + 목록으로 나누고,
  근거가 되는 수치는 문장에 섞지 말고 표나 목록으로 뺀다.
- 이미 푸시된 커밋의 메시지를 바꾸는 history rewrite(+force-push)는 SHA가 바뀌고 머지된
  이력에 영향을 주므로 지양한다 — 필요하면 명시적으로 합의한 뒤에만.

## Version tags

- SemVer, `v` prefix, **annotated** tags on `main`: `v1.0.0`.
- Cut a tag when promoting `develop → main` for a release.
- `MAJOR.MINOR.PATCH`: bump **MINOR** for shipped features, **PATCH** for fixes,
  **MAJOR** for breaking API/contract changes.
