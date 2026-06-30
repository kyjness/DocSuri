"""FR-28 / BR-A10 — AccountManagementService.

Covers: password change (re-auth current, BR-A1 on new, all-session invalidation),
email change request (verification to new + M2 notice to old, enumeration-safe no-op for
in-use addresses), and email-change confirm (delayed apply, single-use token).
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.models import AccountStatus, DomainException
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.account_management import AccountManagementService, _hash_token


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _active_account(repo: CredentialRepository, session, email="user@docsuri.org", pw="OldPw123!@x"):
    acct = repo.create_account(email, get_password_hasher().hash(pw))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    session.commit()
    return acct


def _change_token(email_client) -> str:
    # send_email_change_verification_email(new_email, token, confirm_link) — token is positional[1].
    return email_client.send_email_change_verification_email.call_args.args[1]


# ── change_password ──────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_change_password_success_rehashes_and_invalidates(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    old_hash = acct.password_hash
    sm = AsyncMock()
    svc = AccountManagementService(repo, sm, AsyncMock())

    await svc.change_password(acct.id, "OldPw123!@x", "BrandNewPw9!@")
    session.commit()

    assert repo.get_by_id(acct.id).password_hash != old_hash
    sm.invalidate_all_for_user.assert_awaited_once_with(acct.id)  # BR-A10 §7.1


@pytest.mark.asyncio
async def test_change_password_wrong_current_rejected(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountManagementService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.change_password(acct.id, "WrongPw1!@x", "BrandNewPw9!@")


@pytest.mark.asyncio
async def test_change_password_weak_new_rejected(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountManagementService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.change_password(acct.id, "OldPw123!@x", "weak")


# ── request_email_change ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_request_email_change_sends_verification_and_notice(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    email_client = AsyncMock()
    email_client.send_email_change_verification_email.return_value = True
    email_client.send_email_change_notice_email.return_value = True
    svc = AccountManagementService(repo, AsyncMock(), email_client)

    await svc.request_email_change(
        acct.id, "New@docsuri.org", "https://docsuri.org/email-change/confirm",
        current_password="OldPw123!@x", revoke_link_base="https://docsuri.org/email-change/revoke",
    )
    session.commit()

    email_client.send_email_change_verification_email.assert_awaited_once()
    email_client.send_email_change_notice_email.assert_awaited_once()  # M2 notice to current email
    token = _change_token(email_client)
    assert repo.get_email_change_request(_hash_token(token)) is not None


@pytest.mark.asyncio
async def test_request_email_change_for_null_email_account_skips_old_address_notice(session):
    repo = CredentialRepository(session)
    acct = repo.create_social_account(None)
    session.commit()
    email_client = AsyncMock()
    svc = AccountManagementService(repo, AsyncMock(), email_client)

    await svc.request_email_change(acct.id, "new@docsuri.org", "https://x/confirm")
    session.commit()

    email_client.send_email_change_verification_email.assert_awaited_once()
    email_client.send_email_change_notice_email.assert_not_awaited()
    token = _change_token(email_client)
    assert repo.get_email_change_request(_hash_token(token)) is not None


@pytest.mark.asyncio
async def test_request_email_change_in_use_is_noop(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    _active_account(repo, session, email="taken@docsuri.org")
    email_client = AsyncMock()
    svc = AccountManagementService(repo, AsyncMock(), email_client)

    await svc.request_email_change(
        acct.id, "taken@docsuri.org", "https://x/confirm", current_password="OldPw123!@x"
    )
    email_client.send_email_change_verification_email.assert_not_awaited()  # enumeration-safe (SEC-BR-2)


@pytest.mark.asyncio
async def test_request_email_change_same_email_rejected(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountManagementService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.request_email_change(
            acct.id, "user@docsuri.org", "https://x/confirm", current_password="OldPw123!@x"
        )


# ── confirm_email_change ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_confirm_email_change_applies_and_consumes(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    email_client = AsyncMock()
    email_client.send_email_change_verification_email.return_value = True
    email_client.send_email_change_notice_email.return_value = True
    svc = AccountManagementService(repo, AsyncMock(), email_client)

    await svc.request_email_change(
        acct.id, "new@docsuri.org", "https://x/confirm",
        current_password="OldPw123!@x", revoke_link_base="https://x/revoke",
    )
    session.commit()
    token = _change_token(email_client)

    await svc.confirm_email_change(token)
    session.commit()

    assert repo.get_by_id(acct.id).email == "new@docsuri.org"  # delayed apply now committed
    assert repo.get_email_change_request(_hash_token(token)) is None  # single-use consumed
    with pytest.raises(DomainException):
        await svc.confirm_email_change(token)  # reuse rejected


@pytest.mark.asyncio
async def test_confirm_email_change_invalid_token_rejected(session):
    repo = CredentialRepository(session)
    svc = AccountManagementService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.confirm_email_change("nonexistent-token")


# ── re-auth (H7) + session invalidation (H5) + revoke (H5) ─────────────────────
def _revoke_token(email_client) -> str:
    # send_email_change_notice_email(email, new_email, revoke_link) — revoke_link is positional[2].
    link = email_client.send_email_change_notice_email.call_args.args[2]
    return link.split("token=")[1]


@pytest.mark.asyncio
async def test_request_email_change_requires_correct_password(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountManagementService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.request_email_change(
            acct.id, "new@docsuri.org", "https://x/confirm", current_password="WrongPw1!@x"
        )
    with pytest.raises(DomainException):
        await svc.request_email_change(acct.id, "new@docsuri.org", "https://x/confirm")  # 비번 미제공


@pytest.mark.asyncio
async def test_confirm_email_change_invalidates_all_sessions(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    sm = AsyncMock()
    email_client = AsyncMock()
    svc = AccountManagementService(repo, sm, email_client)
    await svc.request_email_change(
        acct.id, "new2@docsuri.org", "https://x/confirm",
        current_password="OldPw123!@x", revoke_link_base="https://x/revoke",
    )
    session.commit()
    token = _change_token(email_client)

    await svc.confirm_email_change(token)
    session.commit()

    sm.invalidate_all_for_user.assert_awaited_once_with(acct.id)  # H5: 식별자 변경 시 전 세션 무효화


@pytest.mark.asyncio
async def test_revoke_email_change_cancels_pending(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    email_client = AsyncMock()
    svc = AccountManagementService(repo, AsyncMock(), email_client)
    await svc.request_email_change(
        acct.id, "new@docsuri.org", "https://x/confirm",
        current_password="OldPw123!@x", revoke_link_base="https://x/revoke",
    )
    session.commit()
    confirm_token = _change_token(email_client)
    revoke_token = _revoke_token(email_client)

    await svc.revoke_email_change(revoke_token)  # 현 주소 소유자가 취소(세션 불필요)
    session.commit()

    assert repo.get_email_change_request(_hash_token(confirm_token)) is None  # 요청 폐기
    with pytest.raises(DomainException):
        await svc.confirm_email_change(confirm_token)  # 확인 토큰도 무효
    assert repo.get_by_id(acct.id).email == "user@docsuri.org"  # 이메일 미변경
