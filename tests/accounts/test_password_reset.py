"""FR-26 / BR-A8 — PasswordResetService.

Covers: enumeration-safe request (no raise / no email for unknown or inactive accounts),
single-use + expiring hashed token, BR-A1 re-validation on confirm, and all-session
invalidation on success (BR-A8).
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.models import AccountStatus, DomainException
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.password_reset import PasswordResetService, _hash_token


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _active_account(repo: CredentialRepository, session, email="user@docsuri.org"):
    acct = repo.create_account(email, get_password_hasher().hash("OldPw123!@x"))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    session.commit()
    return acct


def _emailed_token(email_client) -> str:
    return email_client.send_password_reset_email.call_args.kwargs["token"]


@pytest.mark.asyncio
async def test_request_reset_active_account_issues_hashed_token_and_emails(session):
    repo = CredentialRepository(session)
    _active_account(repo, session)
    email_client = AsyncMock()
    email_client.send_password_reset_email.return_value = True
    svc = PasswordResetService(repo, AsyncMock(), email_client)

    await svc.request_reset("USER@docsuri.org", "https://docsuri.org/reset-password")
    session.commit()

    email_client.send_password_reset_email.assert_awaited_once()
    token = _emailed_token(email_client)
    # stored as hash, retrievable by hash
    assert repo.get_reset_token(_hash_token(token)) is not None


@pytest.mark.asyncio
async def test_request_reset_unknown_or_inactive_is_noop(session):
    repo = CredentialRepository(session)
    email_client = AsyncMock()
    svc = PasswordResetService(repo, AsyncMock(), email_client)
    # unknown email: no raise, no email (enumeration-safe)
    await svc.request_reset("nobody@docsuri.org", "https://x/reset")
    email_client.send_password_reset_email.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_reset_updates_password_consumes_token_invalidates_sessions(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    email_client = AsyncMock()
    email_client.send_password_reset_email.return_value = True
    sm = AsyncMock()
    svc = PasswordResetService(repo, sm, email_client)

    await svc.request_reset("user@docsuri.org", "https://x/reset")
    session.commit()
    token = _emailed_token(email_client)
    old_hash = acct.password_hash

    await svc.confirm_reset(token, "BrandNewPw9!@")
    session.commit()

    assert repo.get_by_email("user@docsuri.org").password_hash != old_hash  # changed
    assert repo.get_reset_token(_hash_token(token)) is None  # single-use: consumed
    sm.invalidate_all_for_user.assert_awaited_once_with(acct.id)  # BR-A8
    # token reuse rejected
    with pytest.raises(DomainException):
        await svc.confirm_reset(token, "AnotherPw9!@")


@pytest.mark.asyncio
async def test_confirm_reset_rejects_weak_password(session):
    repo = CredentialRepository(session)
    _active_account(repo, session)
    email_client = AsyncMock()
    email_client.send_password_reset_email.return_value = True
    svc = PasswordResetService(repo, AsyncMock(), email_client)
    await svc.request_reset("user@docsuri.org", "https://x/reset")
    session.commit()
    token = _emailed_token(email_client)
    with pytest.raises(DomainException):
        await svc.confirm_reset(token, "weak")


@pytest.mark.asyncio
async def test_confirm_reset_invalid_token_raises(session):
    repo = CredentialRepository(session)
    svc = PasswordResetService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.confirm_reset("nonexistent-token", "BrandNewPw9!@")
