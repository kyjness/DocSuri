# Build Instructions — 통합 빌드 지침서

**단계**: CONSTRUCTION → Build and Test · **문서 언어**: 한국어/영어 혼용

## Scope

본 문서는 현재 생성된 백엔드 코드의 개발 및 통합 빌드 절차를 규정합니다.

- **U1 Ingestion 워커** (`ingestion/`) 및 `shared/python` 의존성 — Python 3.11+, `uv` 기반.
- **U3 Accounts 모듈** (`backend/modules/accounts/`) 을 포함하는 모듈형 모놀리스 백엔드 서비스 (U2 Discovery + app-shell 과 공존) — Python 3.12+, `pip` 기반.

생성되지 않은 나머지 애플리케이션 코드(U4-U6 등)는 본 지침 범위에 포함되지 않으며, 저장소 전역 빌드 명령은 현재 위 유닛과 공용 계약(shared contracts)만을 대상으로 합니다. 유닛별 절차는 아래 각 하위 섹션에 명시되어 있습니다.

---

# U11 Novelty Agent Build Instructions — 2026-06-30

## Prerequisites

- Python runtime available as `python`.
- Backend test dependencies installed from `backend/pyproject.toml`.
- Local source packages on `PYTHONPATH` for app-shell checks:

```powershell
$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src;backend/modules/summarization/src'
```

If the backend suite reports unsupported async tests, install the declared test plugin:

```powershell
python -m pip install "pytest-asyncio>=0.23"
```

## Build Steps

```powershell
python -m compileall backend/modules/novelty backend/wiring.py backend/app.py ops/cdk/stacks/novelty_stack.py ops/cdk/stacks/compute_stack.py ops/cdk/app.py
```

Expected result: compileall completes without syntax errors.

## CDK Synthesis

```powershell
cd ops/cdk
cdk synth
```

Verified result on 2026-06-30: `cdk synth` completed successfully and synthesized `Docsuri-Novelty` to `ops/cdk/cdk.out`. The CDK CLI emitted existing construct warnings for cross-stack reference strength, ECS `minHealthyPercent`, and security group egress.

---

## U1 Ingestion (`ingestion/`)

생성된 U1 Ingestion 워커와 그 `shared/python` 의존성을 대상으로 합니다.

### Prerequisites

- Build tool: Python 3.11 or newer, `uv` 0.11 or newer
- Runtime package manager: `pip` or `uv`
- Development tools: `pytest`, `hypothesis`, `ruff`
- Local packages:
  - `shared/python`
  - `ingestion`
- System requirements:
  - Windows PowerShell or POSIX shell
  - Network access for first dependency sync
  - Docker only when building the container image

### Environment Variables

Local fake-adapter validation does not require AWS credentials. Production runtime requires:

- `DOCSURI_ENV`
- `DOCSURI_AWS_REGION`
- `DOCSURI_S3_BUCKET`
- `DOCSURI_BEDROCK_MODEL_ID`
- `DOCSURI_OPENSEARCH_ENDPOINT`
- `DOCSURI_OPENSEARCH_INDEX`
- `DOCSURI_CONTROL_PLANE_DSN`
- `DOCSURI_SQS_QUEUE_URL`
- `DOCSURI_SQS_DLQ_URL`

### Build Steps

#### 1. Install Dependencies

PowerShell from the repository root:

```powershell
python -m pip install uv
cd ingestion
uv sync --all-groups
```

Fallback without `uv`:

```powershell
python -m pip install -e shared/python
python -m pip install -e ingestion
python -m pip install pytest hypothesis ruff
```

#### 2. Configure Local Environment

PowerShell from the repository root:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
```

#### 3. Build U1 Package

```powershell
cd ingestion
uv build
```

Fallback:

```powershell
python -m pip install build
python -m build ingestion
```

#### 4. Build Container Image

Run from the repository root because the Dockerfile copies both `shared/python` and
`ingestion`:

```powershell
docker build -f ingestion/Dockerfile -t docsuri-ingestion:<git-sha> .
```

Do not publish `latest` tags. Use immutable git SHA or release tags.

#### 5. Verify Build Success

Expected artifacts:

- Python package artifacts under `ingestion/dist/`
- Container image tagged `docsuri-ingestion:<git-sha>`
- Lockfile at `ingestion/uv.lock`

Acceptable warnings:

- Local editable path warnings for `docsuri-shared` during development.
- Missing AWS environment variables only when running local fake-adapter tests.

### Troubleshooting (U1)

#### Dependency Sync Fails

Cause: `uv` is missing or cannot resolve the local path dependency.

Solution:

1. Run commands from the repository root or `ingestion/` as shown above.
2. Confirm `shared/python/pyproject.toml` exists.
3. Re-run `uv lock` inside `ingestion/`.

#### Runtime Fails with Missing Settings

Cause: production mode is fail-closed when required `DOCSURI_*` settings are absent.

Solution:

1. Use `--local` for fake-adapter checks.
2. Provide all production settings before running `python -m docsuri_ingestion.worker`.

#### Docker Build Fails

Cause: build context is not the repository root.

Solution:

1. Run `docker build -f ingestion/Dockerfile -t docsuri-ingestion:<git-sha> .` from repo root.
2. Confirm both `shared/python` and `ingestion` are present in the build context.

---

## U3 Accounts (`backend/modules/accounts/`)

U3 Accounts 모듈을 포함하는 Python 3.12+ 백엔드 서비스(모듈형 모놀리스)의 개발 및 통합 빌드 절차를 규정합니다.

### 1. 사전 요구사항 (Prerequisites)

- **언어 및 런타임**: Python `3.12` 이상
- **패키지 매니저**: `pip` (Python Package Installer)
- **필수 의존성 목록**:
  - `fastapi>=0.110.0`
  - `uvicorn>=0.28.0`
  - `sqlalchemy>=2.0.28`
  - `redis>=5.0.3` (asyncio 지원 버전)
  - `argon2-cffi>=23.1.0`
  - `httpx>=0.27.0` (reCAPTCHA 비동기 호출용)
  - `boto3>=1.34.0` (Amazon SES 연동용)
- **개발/테스트 의존성**:
  - `pytest>=8.1.0`
  - `pytest-asyncio>=0.23.5`
  - `hypothesis>=6.98.0` (속성 기반 테스트용)
- **환경 변수**:
  - `ENV`: 작동 환경 (`local` \| `production`)
  - `RECAPTCHA_SECRET_KEY`: Google reCAPTCHA v3 비밀키 (비어있을 시 Fail-Closed 오작동 주의)
  - `SES_MOCK`: `true`로 설정 시 Amazon SES 실제 발송을 Mocking하여 stdout 로그로 인증 토큰 출력

### 2. 빌드 및 설치 단계 (Build Steps)

#### 2.1. 가상 환경 구성 및 의존성 설치
터미널에서 가상 환경을 생성하고 관련 패키지를 설치합니다.

```bash
# 1. 가상환경 생성
python3 -m venv .venv

# 2. 가상환경 활성화 (macOS)
source .venv/bin/activate

# 3. pip 최신화 및 의존성 설치
pip install --upgrade pip
pip install fastapi uvicorn sqlalchemy redis argon2-cffi httpx boto3 pytest pytest-asyncio hypothesis
```

#### 2.2. 환경 변수 설정
로컬 디버깅용 환경 변수를 구성합니다.

```bash
export ENV=local
export SES_MOCK=true
export RECAPTCHA_SECRET_KEY=dummy_recaptcha_key_for_testing
```

#### 2.3. 애플리케이션 실행 테스트 (app shell 스텁 구동)
모듈형 모놀리스 진입점 구동 여부를 간이 확인합니다.

```bash
# 디렉터리 내 controller.py 임포트 확인 테스트 실행
python3 -c "from backend.modules.accounts.controller import router; print('Router import success!')"
```

### 3. 트러블슈팅 (Troubleshooting)

#### 3.1. Argon2 CFFI 컴파일 에러
- **원인**: C 컴파일러 및 개발 라이브러리가 머신에 설치되어 있지 않아 CFFI 바인딩 빌드가 실패하는 경우.
- **해결책**:
  - macOS: `xcode-select --install`을 실행하여 빌드 도구를 수립한 후 다시 `pip install argon2-cffi`를 시도합니다.

#### 3.2. Redis-py 비동기 모듈 Import 실패
- **원인**: 구버전 `redis` 패키지가 설치되어 `redis.asyncio`가 노출되지 않는 경우.
- **해결책**: `pip install --upgrade redis`를 실행하여 redis 패키지 버전을 5.0 이상으로 수집 및 동기화해 주십시오.
# U9 Personalization Build Instructions — 2026-06-23

## Prerequisites

- Python runtime available as `python`.
- Existing local source packages on `PYTHONPATH` for app-shell tests:

```powershell
$env:PYTHONPATH='shared/python/src;ops/src;backend/modules/discovery/src'
```

## Build Steps

```powershell
python -m compileall backend/modules/personalization backend/wiring.py backend/app.py ops/cdk/stacks/compute_stack.py
```

Expected result: compileall completes without syntax errors.

## CDK Build Note

CDK synth requires the Python dependencies from `ops/cdk/requirements.txt` and a Node runtime usable by `jsii`.

```powershell
cd ops/cdk
python -m pip install -r requirements.txt
$env:JSII_NODE="$env:USERPROFILE\scoop\apps\nodejs-lts\current\node.exe"
cdk synth
```

Verified result on 2026-06-23: `cdk synth` completed successfully and synthesized templates to `ops/cdk/cdk.out`. The CDK CLI emitted existing construct warnings for cross-stack reference strength, ECS `minHealthyPercent`, and security group egress; no U9 synth blocker remained.

---

# Agent Chat Frontend Build Instructions — 2026-07-01

## Prerequisites

- Node and Corepack available.
- Frontend dependencies installed from `frontend/pnpm-lock.yaml`.
- Playwright WebKit installed for local E2E:

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- playwright install webkit
```

## Build Steps

```powershell
corepack pnpm@9.15.9 --dir frontend exec -- tsc --noEmit
corepack pnpm@9.15.9 --dir frontend build
```

Expected result:

- TypeScript completes with no errors.
- Next.js production build completes and includes `/agent` in the route table.

Observed result on 2026-07-01:

- `tsc --noEmit`: PASS.
- `next build`: PASS; `/agent` route size `6.18 kB`, first-load JS `131 kB`.

## E2E Server Note

Playwright uses the configured `webServer` command in `frontend/playwright.config.ts`.
For this local E2E pass, `scripts/prepare-standalone-assets.mjs` copies `.next/static`
and `public/` into `.next/standalone` before `node .next/standalone/server.js` starts.
This keeps E2E aligned with the configured standalone output while serving static chunks.

---
