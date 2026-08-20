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

### 커밋을 잘게 쪼개지 않는다

**기본은 한 작업 = 한 커밋**이다. 같은 작업의 **코드·테스트·도구·문서는 한 커밋에 함께** 간다
— 파일 종류나 변경 성격(fix/docs)은 분할 사유가 아니다.

나누는 것은 *정말 필요할 때*만이다:
- 서로 **무관한** 결함을 한 브랜치에서 같이 고쳤을 때
- 한쪽만 되돌려야 할 실질적 이유가 있을 때

커밋 전에 **"같은 종류의 자리를 전수로 확인했나"**를 묻는다. 세 곳 중 둘만 고치면 나머지
하나가 다음 커밋이 되고, 로그에는 같은 제목이 두 번 남는다. 그건 커밋 위생 문제가 아니라
**덜 된 걸 내보내고 고친 흔적**이다.

이 저장소는 squash가 아니라 **merge commit**으로 통합하므로 중간 커밋이 `develop`에 영구히
남는다. 커밋 하나하나가 단독으로 빌드·테스트를 통과해야 `git bisect`가 성립한다.

## PR

- **base는 `develop`** (릴리스 PR `develop → main` 제외).
- 제목은 커밋 제목과 **같은 형식 규칙**을 따른다 — `type(scope):` + 한국어 명사구.
- 절 이름은 [`.github/PULL_REQUEST_TEMPLATE.md`](.github/PULL_REQUEST_TEMPLATE.md)를 그대로
  쓴다: **Description · Related Issues · Changes Made · Screenshots or Video · Testing ·
  Checklist · Additional Notes**. 임의로 바꾸지 않는다. **해당 없는 절은 지운다** — 빈 절을
  남기면 템플릿이 잡음이 된다.
- **Description은 "왜"로 시작한다.** "무엇을 바꿨나"는 Changes Made와 diff가 말한다.
  결함 수정이라면 **재현 조건과 영향 범위**를 먼저 적는다.
- 검증 결과(테스트 수·정적 검사)를 Testing에 남긴다. 결함 수정이면 **그 테스트가 수정 전
  코드에서 실패하는 것을 확인했는지**도 적는다 — 통과만 보고한 테스트는 아무것도 증명하지
  않는다.
- 선행 조건이 있으면(다른 PR 머지·배포 등) Description 최상단에 경고로 둔다.

### 분량은 영향 범위에 비례한다

긴 본문이 항상 좋은 게 아니다. **작은 수정에 긴 본문은 오히려 판단력 부족으로 읽힌다.**

| PR 성격 | 적정 분량 |
|---|---|
| 오타·상수 변경 | 제목 한 줄. 본문 없어도 된다 |
| 일반 버그 수정 | Description 2~3줄 + Testing |
| 기능 추가 | 필요한 절만 쓰되 각각 짧게 |
| 아키텍처·마이그레이션·다건 결함 | 소제목·표를 동원한 긴 본문이 정당하다 |

## Version tags

- SemVer, `v` prefix, **annotated** tags on `main`: `v1.0.0`.
- Cut a tag when promoting `develop → main` for a release.
- `MAJOR.MINOR.PATCH`: bump **MINOR** for shipped features, **PATCH** for fixes,
  **MAJOR** for breaking API/contract changes.
