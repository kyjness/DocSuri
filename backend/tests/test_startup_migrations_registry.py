"""마이그레이션 목록 드리프트 가드.

`_apply_startup_migrations`의 명시 목록은 저장소 관례다("이 이미지의 모듈만") —
다만 `_INTEGRATIONS`와의 결합이 암묵이라, 마운트되는 모듈이 migrations/를 갖고도
목록에 빠지면 **첫 Postgres 부팅에서야** 터진다. 이 저장소에서 두 번 있었던 일이다
(research 잔재를 가리키던 채 evidence가 빠져 evidence 테이블이 적용된 적이 없었다).
드리프트를 CI 시점의 소음으로 바꾼다.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "backend" / "app.py"
MODULES = REPO / "backend" / "modules"


def _declared_migration_dirs() -> set[str]:
    """`_apply_startup_migrations`가 넘기는 경로 리터럴."""
    tree = ast.parse(APP.read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("backend/modules/") and node.value.endswith("/migrations"):
                out.add(node.value)
    return out


def _mounted_module_names() -> set[str]:
    """wiring `_INTEGRATIONS`의 `_mount_*` 이름들."""
    tree = ast.parse((REPO / "backend" / "wiring.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "_INTEGRATIONS" in targets and isinstance(node.value, ast.Tuple | ast.List):
                return {
                    element.id.removeprefix("_mount_")
                    for element in node.value.elts
                    if isinstance(element, ast.Name)
                }
    raise AssertionError("_INTEGRATIONS not found in backend/wiring.py")


def test_every_mounted_module_with_migrations_is_in_the_startup_list():
    declared = _declared_migration_dirs()
    missing = []
    for name in _mounted_module_names():
        migrations = MODULES / name / "migrations"
        if migrations.is_dir() and f"backend/modules/{name}/migrations" not in declared:
            missing.append(name)
    assert not missing, (
        f"마운트되는 모듈 {missing}에 migrations/가 있는데 _apply_startup_migrations "
        "목록에 없다 — 첫 Postgres 부팅에서 스키마 없이 서빙된다(backend/app.py)."
    )


def test_declared_migration_dirs_exist():
    """반대 방향 — 목록이 삭제된 모듈(research 사례)을 가리키지 않는지."""
    ghosts = [d for d in _declared_migration_dirs() if not (REPO / d).is_dir()]
    assert not ghosts, f"마이그레이션 목록이 존재하지 않는 디렉터리를 가리킨다: {ghosts}"
