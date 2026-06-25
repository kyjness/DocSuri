"""FR-27 / BR-A9 — SocialLoginService.reconcile (identity reconciliation core).

Covers the H1 pre-hijacking defense and the auto-link / new-account / unverified rules.
The OIDC transport (Google discovery/token/JWKS) is deliberately out of scope here — this
exercises the security-critical decision logic against verified claims.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.models import (
    AccountStatus,
    DomainException,
    OidcProvider,
    SocialLinkConfirmationRequired,
)
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import (
    SOCIAL_NO_PASSWORD_HASH,
    Base,
    CredentialRepository,
)
from backend.modules.accounts.services.social_login import OidcClaims, SocialLoginService


@pytest.fixture
def repo():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield CredentialRepository(s)
    s.close()


def _claims(email="user@docsuri.org", verified=True, subject="goog-sub-1"):
    return OidcClaims(subject=subject, email=email, email_verified=verified)


def test_new_email_creates_active_social_account(repo):
    acct_id = SocialLoginService(repo).reconcile(OidcProvider.GOOGLE, _claims())
    acct = repo.get_by_email("user@docsuri.org")
    assert acct.id == acct_id
    assert acct.status == AccountStatus.ACTIVE.value  # PENDING bypassed (provider-verified)
    assert acct.password_hash == SOCIAL_NO_PASSWORD_HASH  # no usable password
    assert repo.get_social_identity("GOOGLE", "goog-sub-1").status == "LINKED"


def test_existing_link_is_idempotent(repo):
    svc = SocialLoginService(repo)
    first = svc.reconcile(OidcProvider.GOOGLE, _claims())
    second = svc.reconcile(OidcProvider.GOOGLE, _claims())  # same (provider, subject)
    assert first == second


def test_social_only_account_same_email_auto_links(repo):
    svc = SocialLoginService(repo)
    acct_id = svc.reconcile(OidcProvider.GOOGLE, _claims(subject="sub-A"))
    # different subject, same verified email, account has no password -> auto-link
    again = svc.reconcile(OidcProvider.GOOGLE, _claims(subject="sub-B"))
    assert again == acct_id
    assert repo.get_social_identity("GOOGLE", "sub-B").status == "LINKED"


def test_existing_password_account_requires_explicit_link_H1(repo):
    # A password account pre-exists for the email (attacker pre-registration scenario).
    acct = repo.create_account("user@docsuri.org", get_password_hasher().hash("RealPw123!@x"))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    with pytest.raises(SocialLinkConfirmationRequired):
        SocialLoginService(repo).reconcile(OidcProvider.GOOGLE, _claims())
    # H1: a PENDING_CONFIRMATION identity is recorded — NOT auto-linked.
    link = repo.get_social_identity("GOOGLE", "goog-sub-1")
    assert link is not None
    assert link.status == "PENDING_CONFIRMATION"


def test_unverified_email_rejected(repo):
    with pytest.raises(DomainException):
        SocialLoginService(repo).reconcile(OidcProvider.GOOGLE, _claims(verified=False))
