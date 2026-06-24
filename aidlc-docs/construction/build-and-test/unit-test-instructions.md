# Unit Test Execution — 단위 테스트 실행 지침서

**단계**: CONSTRUCTION → Build and Test · **유닛**: U1 Ingestion · U3 Accounts · **일자**: 2026-06-16
**문서 언어**: 한국어 (영문 명령어/식별자 병기)

본 문서는 Code Generation 단계에서 구현된 단위 테스트의 실행 방법과 품질 관리 요건을 수립합니다.
유닛별로 다음 두 모듈을 다룹니다.

- **U1 Ingestion**: 도메인 규칙, 처리 컴포넌트, 로컬 어댑터, 오케스트레이션 경계.
- **U3 Accounts**: 핵심 단위 테스트 및 속성 기반 테스트(PBT).

---

## 1. 테스트 실행 도구 (Testing Tools)

- **테스트 프레임워크**: `pytest`
- **비동기 테스트 지원**: `pytest-asyncio` (FastAPI 및 aioredis 비동기 I/O 매핑 검증 — U3)
- **속성 기반 테스트 (PBT)**: `hypothesis`
- **린트**: `ruff` (U1)

---

## 2. 테스트 실행 절차

### 2.1. U1 Ingestion

#### Scope

Unit tests cover U1 domain rules, processing components, local adapters, and orchestration
boundaries implemented during Code Generation.

#### 1. Execute All U1 Tests

PowerShell from the repository root:

```powershell
$env:PYTHONPATH="ingestion/src;shared/python/src"
python -m pytest ingestion/tests
```

With `uv`:

```powershell
cd ingestion
uv run pytest
```

#### 2. Expected Results

- Total tests: 21
- Expected result: 21 passed, 0 failures
- Property-based tests: included in `ingestion/tests/test_properties.py`
- Report location: terminal output unless CI config writes JUnit XML

#### 3. Test Groups

- Domain unit tests: `ingestion/tests/test_domain_units.py`
- Property-based tests: `ingestion/tests/test_properties.py`
- Orchestration and fault-injection tests: `ingestion/tests/test_orchestration.py`

#### 4. Fix Failing Tests

If tests fail:

1. Inspect the first failing test and traceback.
2. Fix the smallest affected code path.
3. Re-run the same test module.
4. Re-run `python -m pytest ingestion/tests`.
5. Re-run `python -m ruff check ingestion`.

#### Current Known Result

Last local execution during Code Generation:

```text
21 passed
```

### 2.2. U3 Accounts

가상 환경이 활성화된 상태에서 아래 명령어를 실행하여 단위 테스트를 전체 수행합니다.

#### 1. 전체 단위 테스트 실행

```bash
# tests/accounts 디렉터리 내의 모든 테스트 코드를 수행합니다.
pytest tests/accounts -v
```

#### 2. 속성 기반 테스트 (PBT) 단독 실행

비밀번호 강도 정책 및 해싱 연산의 멱등/상수시간 성질을 검증하는 PBT 스펙만 독립적으로 실행합니다.

```bash
# 1. 비밀번호 정책 PBT 실행 (PBT-U3-1)
pytest tests/accounts/test_password_pbt.py -v

# 2. Argon2id 해싱 일관성 PBT 실행 (PBT-U3-2)
pytest tests/accounts/test_hash_pbt.py -v
```

---

## 3. 테스트 성공 기준 및 보고 (Success Criteria)

### 3.1. 공통 기준

- **성공률**: **100% Pass** (실패 테스트 0건)
- 보고 위치: 터미널 출력 (CI 설정이 JUnit XML을 기록하지 않는 한).

### 3.2. U3 Accounts 추가 요건

- **테스트 커버리지 요건**: U3 Accounts 핵심 서비스 및 도메인 레이어 커버리지 **85% 이상** 권장.
- **Hypothesis 기본 설정**:
  - 각 PBT 함수는 기본적으로 `100`가지의 임의 무작위 시나리오 케이스를 생성하여 평가합니다.
  - 만약 반례(Counter-example)가 발견되면, Hypothesis가 입력을 최소화(Shrinking)하여 콘솔 터미널에 실패 원인 입력 패턴을 상세 출력합니다. 이 패턴을 참조하여 `password.py` 또는 `models.py`를 보정해야 합니다.
# U9 Personalization Unit Test Instructions — 2026-06-23

Run U9 unit tests:

```powershell
python -m pytest backend/tests/test_personalization.py -q
```

Observed result:

- 11 passed

Coverage focus:

- event DTO roundtrip
- metadata allowlist rejection
- dedupe
- owner isolation
- deterministic aggregation
- direct raw-log delete
- profile reset
- fail-open decision behavior
- idempotent retention purge

---
