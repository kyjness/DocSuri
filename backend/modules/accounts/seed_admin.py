"""Idempotent admin seeding (BR-A7).

ADMIN accounts are NEVER created via public signup (privilege-escalation guard) — they are
provisioned only here. Run once per environment:

    DOCSURI_ADMIN_EMAIL=admin@docsuri.dev DOCSURI_ADMIN_PASSWORD='…' \\
        DATABASE_URL=postgresql+psycopg://… python -m backend.modules.accounts.seed_admin

Idempotent: an existing account with that email is promoted to ADMIN/ACTIVE (not duplicated);
its password is NOT overwritten. The admin enrolls TOTP MFA on first login (/auth/mfa/enroll)
before the admin control plane unlocks. The plaintext password is read from env once and is
never logged (SEC-3)."""

from __future__ import annotations

import logging
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .models import AccountStatus, DomainException, UserRole
from .password import PasswordPolicy, get_password_hasher
from .repository.credential import AccountTable, Base, CredentialRepository

logger = logging.getLogger(__name__)


def seed_admin(db_session, email: str, password: str) -> str:
    """Idempotent: 주어진 이메일의 계정을 ADMIN·ACTIVE로 보장하고 그 id를 반환한다.
    신규면 강도 정책 검증 후 해싱하여 생성하고, 기존이면 ADMIN·ACTIVE로 승격한다(비번 미변경)."""
    repo = CredentialRepository(db_session)
    account = repo.get_by_email(email)
    if account is None:
        PasswordPolicy.evaluate(password)  # 시드 관리자도 동일 강도 정책 (BR-A1)
        account = AccountTable(
            email=email,
            password_hash=get_password_hasher().hash(password),
            status=AccountStatus.ACTIVE.value,
            role=UserRole.ADMIN.value,
        )
        db_session.add(account)
        db_session.flush()
        logger.info("Seeded new ADMIN account.")
    else:
        # 멱등 재실행(이미 ADMIN)은 무변경 통과. 그러나 공개 가입 등으로 *먼저 존재하던* 비-ADMIN
        # 계정을 묻지도 않고 ADMIN으로 승격하면 권한 상승 위험이 있다(공격자가 시드 이메일을 선점
        # 가입 → 시드 실행 시 ADMIN 획득). 따라서 비-ADMIN 기존 계정 승격은 명시적 opt-in을 요구한다.
        already_admin = account.role == UserRole.ADMIN.value
        promote_opt_in = os.getenv("DOCSURI_ADMIN_PROMOTE_EXISTING", "").strip().lower() in {"1", "true", "yes", "on"}
        if not already_admin and not promote_opt_in:
            raise DomainException(
                "해당 이메일로 비-ADMIN 계정이 이미 존재합니다. 의도된 승격이라면 "
                "DOCSURI_ADMIN_PROMOTE_EXISTING=true 로 다시 실행하세요 (권한 상승 방지)."
            )
        account.role = UserRole.ADMIN.value
        account.status = AccountStatus.ACTIVE.value
        repo.update_account(account)
        logger.info("Promoted existing account to ADMIN/ACTIVE.")
    db_session.commit()
    return account.id


def main() -> int:
    email = os.getenv("DOCSURI_ADMIN_EMAIL", "").strip()
    password = os.getenv("DOCSURI_ADMIN_PASSWORD", "")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not email or not password or not database_url:
        logger.error("DOCSURI_ADMIN_EMAIL · DOCSURI_ADMIN_PASSWORD · DATABASE_URL 환경변수가 모두 필요합니다.")
        return 2
    engine = create_engine(database_url)
    # N5: create_all은 ORM 모델에서 테이블을 만들어 SQL 마이그레이션과 드리프트할 수 있다(프로덕션은
    # 마이그레이션이 선행). 로컬/초기 부트스트랩(ENV=local) 또는 명시 opt-in일 때만 수행한다.
    env = os.getenv("ENV", "local").strip().lower()
    create_all_optin = os.getenv("DOCSURI_SEED_CREATE_ALL", "").strip().lower() in {"1", "true", "yes", "on"}
    if env == "local" or create_all_optin:
        Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        account_id = seed_admin(session, email, password)
        logger.info("Admin seeding complete: %s", account_id)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
