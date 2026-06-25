"""FR-27 H1 social link-confirm + FR-28 EventBridge AccountDeleted publisher.

- confirm_pending_links: a password account with a PENDING_CONFIRMATION social identity is
  promoted to LINKED once the owner proves ownership (password session), after which social
  login reconciles straight to that account.
- EventBridgeAccountDeletedPublisher: builds the correct put_events entry and propagates
  failures (so purge_job retries). boto3 client is mocked — no AWS contact.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.models import AccountStatus, OidcProvider, SocialLinkConfirmationRequired
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.account_deletion import (
    EventBridgeAccountDeletedPublisher,
    LoggingAccountDeletedPublisher,
    build_account_deleted_publisher,
)
from backend.modules.accounts.services.social_login import OidcClaims, SocialLoginService


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _password_account(repo, session, email="u@docsuri.org"):
    acct = repo.create_account(email, get_password_hasher().hash("OldPw123!@x"))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    session.commit()
    return acct


# ── FR-27 H1 link-confirm ────────────────────────────────────────────────────
def test_confirm_pending_link_promotes_then_login_reconciles(session):
    repo = CredentialRepository(session)
    acct = _password_account(repo, session)
    svc = SocialLoginService(repo)
    claims = OidcClaims(subject="g-1", email="u@docsuri.org", email_verified=True)

    # H1: existing password account → PENDING_CONFIRMATION recorded + raises (no auto-merge).
    with pytest.raises(SocialLinkConfirmationRequired):
        svc.reconcile(OidcProvider.GOOGLE, claims)
    session.commit()
    assert repo.get_social_identity("GOOGLE", "g-1").status == "PENDING_CONFIRMATION"

    # Owner proves ownership (password session) and confirms the link.
    assert svc.confirm_pending_links(acct.id) == 1
    session.commit()
    assert repo.get_social_identity("GOOGLE", "g-1").status == "LINKED"

    # Subsequent social login now reconciles straight to the linked account (idempotent).
    assert svc.reconcile(OidcProvider.GOOGLE, claims) == acct.id


def test_confirm_no_pending_is_zero(session):
    repo = CredentialRepository(session)
    acct = _password_account(repo, session)
    assert SocialLoginService(repo).confirm_pending_links(acct.id) == 0


# ── FR-28 EventBridge publisher ──────────────────────────────────────────────
@pytest.mark.asyncio
async def test_eventbridge_publish_builds_entry():
    pub = EventBridgeAccountDeletedPublisher(event_bus_name="docsuri-events")
    client = MagicMock()
    client.put_events.return_value = {"FailedEntryCount": 0, "Entries": [{"EventId": "e"}]}
    pub._client = client  # bypass boto3
    await pub.publish("acct-1", datetime.now(UTC), "evt-1")
    entry = client.put_events.call_args.kwargs["Entries"][0]
    assert entry["DetailType"] == "AccountDeleted"
    assert entry["EventBusName"] == "docsuri-events"
    assert '"accountId": "acct-1"' in entry["Detail"]


@pytest.mark.asyncio
async def test_eventbridge_publish_failure_raises():
    pub = EventBridgeAccountDeletedPublisher(event_bus_name="docsuri-events")
    client = MagicMock()
    client.put_events.return_value = {"FailedEntryCount": 1, "Entries": [{"ErrorCode": "Throttled"}]}
    pub._client = client
    with pytest.raises(RuntimeError):
        await pub.publish("acct-1", datetime.now(UTC), "evt-1")  # purge_job retries next run


def test_build_publisher_switches_on_env(monkeypatch):
    monkeypatch.delenv("ACCOUNT_EVENTS_BUS", raising=False)
    assert isinstance(build_account_deleted_publisher(), LoggingAccountDeletedPublisher)
    monkeypatch.setenv("ACCOUNT_EVENTS_BUS", "docsuri-events")
    assert isinstance(build_account_deleted_publisher(), EventBridgeAccountDeletedPublisher)
