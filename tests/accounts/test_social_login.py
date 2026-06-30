"""FR-27 / BR-A9 — SocialLoginService.reconcile (identity reconciliation core).

Covers the H1 pre-hijacking defense and the auto-link / new-account / unverified rules.
The OIDC transport (Google discovery/token/JWKS) is deliberately out of scope here — this
exercises the security-critical decision logic against verified claims.
"""

import pytest
from backend.modules.accounts.controller import _principal_for_social_account
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
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


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


def test_existing_pending_confirmation_link_requires_explicit_confirmation_on_replay(repo):
    acct = repo.create_account("user@docsuri.org", get_password_hasher().hash("RealPw123!@x"))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    svc = SocialLoginService(repo)

    with pytest.raises(SocialLinkConfirmationRequired):
        svc.reconcile(OidcProvider.GOOGLE, _claims())
    with pytest.raises(SocialLinkConfirmationRequired):
        svc.reconcile(OidcProvider.GOOGLE, _claims())

    assert repo.get_social_identity("GOOGLE", "goog-sub-1").status == "PENDING_CONFIRMATION"


def test_unverified_email_rejected(repo):
    with pytest.raises(DomainException):
        SocialLoginService(repo).reconcile(OidcProvider.GOOGLE, _claims(verified=False))


# ── BR-A13: 이메일을 제공하지 않는 프로바이더(ORCID) ─────────────────────────────
def _orcid_claims(subject="0000-0002-1825-0097", name="Josiah Carberry"):
    return OidcClaims(subject=subject, email=None, email_verified=False, name=name)


def test_orcid_emailless_creates_active_account_with_null_email(repo):
    acct_id = SocialLoginService(repo).reconcile(OidcProvider.ORCID, _orcid_claims())
    acct = repo.get_by_id(acct_id)
    assert acct.status == AccountStatus.ACTIVE.value
    assert acct.email is None  # BR-A13: 이메일 미제공 → NULL
    assert acct.password_hash == SOCIAL_NO_PASSWORD_HASH  # 비밀번호 로그인 불가
    assert repo.get_social_identity("ORCID", "0000-0002-1825-0097").status == "LINKED"


def test_orcid_existing_link_is_idempotent(repo):
    svc = SocialLoginService(repo)
    first = svc.reconcile(OidcProvider.ORCID, _orcid_claims())
    second = svc.reconcile(OidcProvider.ORCID, _orcid_claims())  # 동일 (ORCID, subject)
    assert first == second


def test_orcid_does_not_merge_into_password_account_same_absence_of_email(repo):
    # 이메일 가입 계정이 있어도 ORCID는 이메일이 없어 자동 병합/H1 경로를 타지 않는다(BR-A13).
    repo.create_account("user@docsuri.org", get_password_hasher().hash("RealPw123!@x"))
    acct_id = SocialLoginService(repo).reconcile(OidcProvider.ORCID, _orcid_claims())
    acct = repo.get_by_id(acct_id)
    assert acct.email is None  # 별개의 ORCID 계정 — 이메일 계정과 무관
    assert repo.get_social_identity("ORCID", "0000-0002-1825-0097").status == "LINKED"


def test_orcid_profile_cache_update(repo):
    acct_id = SocialLoginService(repo).reconcile(OidcProvider.ORCID, _orcid_claims())
    repo.update_orcid_profile("0000-0002-1825-0097", "Josiah Carberry", "Brown University")
    ident = repo.get_orcid_identity(acct_id)
    assert ident.orcid_name == "Josiah Carberry"
    assert ident.orcid_affiliation == "Brown University"
    assert ident.orcid_synced_at is not None


def test_social_session_principal_requires_active_account(repo):
    acct = repo.create_social_account(None)
    acct.status = AccountStatus.DEACTIVATED.value
    repo.update_account(acct)

    with pytest.raises(HTTPException) as exc:
        _principal_for_social_account(acct.id, repo)

    assert exc.value.status_code == 401
