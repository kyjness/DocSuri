"""CLI: python -m backend.migrations [--check | --apply]

--check: list pending migrations (exit 1 if any pending)
--apply: apply all pending migrations
"""

from __future__ import annotations

import os
import sys

from backend.app import STARTUP_MIGRATION_DIRS

from . import apply_migrations, pending_migrations

# 부팅 자가 적용과 같은 목록(backend/app.py) — 여기만 따로 두면 갈린다(실제로 갈렸다).
_DEFAULT_PATHS = list(STARTUP_MIGRATION_DIRS)


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("ERROR: DATABASE_URL environment variable is required", file=sys.stderr)
        return 1

    paths = _DEFAULT_PATHS
    mode = sys.argv[1] if len(sys.argv) > 1 else "--apply"

    if mode == "--check":
        pending = pending_migrations(dsn, paths)
        if pending:
            print(f"{len(pending)} pending migration(s):")
            for p in pending:
                print(f"  - {p}")
            return 1
        print("All migrations applied.")
        return 0

    if mode == "--apply":
        applied = apply_migrations(dsn, paths)
        if applied:
            print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
        else:
            print("No pending migrations.")
        return 0

    print(f"Unknown mode: {mode}. Use --check or --apply.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
