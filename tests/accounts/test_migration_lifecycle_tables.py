"""003 migration ↔ SQLAlchemy model parity for the FR-26/27/28 lifecycle tables.

Guards against the migration DDL drifting from the ORM models (a forgotten/renamed
column would let the app start then 500 at runtime). Runs the DDL on stdlib in-memory
SQLite (no new deps; 003 is pure CREATE TABLE/INDEX IF NOT EXISTS — SQLite-compatible).
"""

import sqlite3
from pathlib import Path

import pytest

from backend.modules.accounts.repository.credential import (
    AccountDeletionTable,
    EmailChangeRequestTable,
    PasswordResetTokenTable,
    SocialIdentityTable,
)

# 003은 라이프사이클 테이블을 만들고, 이후 additive 마이그레이션이 컬럼을 덧붙인다(006:
# social_identities에 orcid_* 추가, 007: email_change_requests에 revoke_token_hash 추가). 파리티
# 검사는 전부 적용해야 모델과 일치한다. (009/010은 DROP NOT NULL이라 SQLite 미지원·신규 컬럼 없음 → 제외.)
MIGRATIONS = [
    Path("backend/modules/accounts/migrations/003_create_lifecycle_tables.sql"),
    Path("backend/modules/accounts/migrations/006_add_orcid_columns_to_social_identities.sql"),
    Path("backend/modules/accounts/migrations/007_add_email_change_revoke_token.sql"),
    Path("backend/modules/accounts/migrations/011_add_purge_attempts.sql"),  # S2: account_deletions.purge_attempts
]


@pytest.mark.parametrize(
    "model",
    [
        PasswordResetTokenTable,
        SocialIdentityTable,
        EmailChangeRequestTable,
        AccountDeletionTable,
    ],
)
def test_migration_columns_cover_model(model):
    conn = sqlite3.connect(":memory:")
    try:
        for migration in MIGRATIONS:
            # SQLite는 `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`(Postgres)를 모르므로 IF NOT EXISTS만
            # 떼어 같은 컬럼을 추가한다(파리티 검사 목적상 동일). CREATE TABLE/INDEX IF NOT EXISTS는 OK.
            sql = migration.read_text(encoding="utf-8").replace(
                "ADD COLUMN IF NOT EXISTS", "ADD COLUMN"
            )
            conn.executescript(sql)
        created = {row[1] for row in conn.execute(f"PRAGMA table_info({model.__tablename__})")}
    finally:
        conn.close()
    expected = {c.name for c in model.__table__.columns}
    assert created, f"migration did not create table {model.__tablename__}"
    assert expected <= created, f"{model.__tablename__}: model columns missing from DDL: {expected - created}"
