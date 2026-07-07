from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.mypage import controller
from backend.modules.mypage.repository.memory import (
    InMemoryAccountRepository,
    InMemorySubscriptionRepository,
)


def _client(
    monkeypatch,
    *,
    principal: Principal | None = None,
    repo=None,
    account_repo=None,
) -> TestClient:
    app = create_app(Settings(env="test", database_url="sqlite://"))
    if principal is not None:
        app.dependency_overrides[controller.get_principal] = lambda: principal
    if repo is not None:
        app.dependency_overrides[controller.get_subscription_repo] = lambda: repo
    if account_repo is not None:
        app.dependency_overrides[controller.get_account_repo] = lambda: account_repo
    return TestClient(app)


def _principal() -> Principal:
    return Principal(user_id=str(uuid4()), role=UserRole.USER)


def test_orcid_profile_404_when_not_orcid_user(monkeypatch) -> None:
    # 비-ORCID 계정(시드 없음) → 404.
    client = _client(monkeypatch, principal=_principal(), account_repo=InMemoryAccountRepository())
    resp = client.get("/mypage/orcid-profile")
    assert resp.status_code == 404


def test_orcid_profile_returns_cached_identity_plus_live_works(monkeypatch) -> None:
    async def _fake_record(orcid_id, **kw):
        return {"affiliation": "ignored-uses-cache", "works": [{"title": "Paper A", "year": 2020}]}

    monkeypatch.setattr(controller, "fetch_orcid_public_record", _fake_record)
    principal = _principal()
    account_repo = InMemoryAccountRepository()
    account_repo.seed_orcid(
        principal.user_id,
        orcid_id="0000-0002-1825-0097",
        name="Josiah Carberry",
        affiliation="Brown",
    )
    client = _client(monkeypatch, principal=principal, account_repo=account_repo)
    resp = client.get("/mypage/orcid-profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["orcidId"] == "0000-0002-1825-0097"
    assert body["name"] == "Josiah Carberry"
    assert body["affiliation"] == "Brown"  # 캐시 값 사용
    assert body["works"] == [{"title": "Paper A", "year": 2020}]  # 라이브 fetch


def test_get_subscription_defaults_to_none_when_never_subscribed(monkeypatch) -> None:
    resp = _client(monkeypatch, principal=_principal()).get("/mypage/subscription")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"] == "FREE"
    assert body["status"] == "NONE"
    assert "startedAt" not in body or body["startedAt"] is None


def test_subscribe_activates_premium_with_period_end(monkeypatch) -> None:
    client = _client(monkeypatch, principal=_principal())
    resp = client.post("/mypage/subscription")
    assert resp.status_code == 201
    body = resp.json()
    assert body["plan"] == "PREMIUM"
    assert body["status"] == "ACTIVE"
    assert body["startedAt"] is not None
    assert body["currentPeriodEnd"] is not None
    assert body["canceledAt"] is None


def test_subscribe_is_idempotent_when_already_active(monkeypatch) -> None:
    repo = InMemorySubscriptionRepository()
    client = _client(monkeypatch, principal=_principal(), repo=repo)
    first = client.post("/mypage/subscription").json()
    second = client.post("/mypage/subscription").json()
    assert first["startedAt"] == second["startedAt"]
    assert second["status"] == "ACTIVE"


def test_cancel_retains_benefit_through_current_period_end(monkeypatch) -> None:
    repo = InMemorySubscriptionRepository()
    client = _client(monkeypatch, principal=_principal(), repo=repo)
    subscribed = client.post("/mypage/subscription").json()

    resp = client.post("/mypage/subscription/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CANCELED"
    assert body["canceledAt"] is not None
    # Q11: cancellation does not cut access immediately — period end is unchanged.
    assert body["currentPeriodEnd"] == subscribed["currentPeriodEnd"]


def test_cancel_without_active_subscription_is_a_no_op(monkeypatch) -> None:
    resp = _client(monkeypatch, principal=_principal()).post("/mypage/subscription/cancel")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NONE"


def test_subscription_endpoints_require_authentication(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/mypage/subscription")
    assert resp.status_code == 401


@pytest.mark.parametrize("owner_a, owner_b", [(str(uuid4()), str(uuid4()))])
def test_subscriptions_are_owner_scoped(monkeypatch, owner_a, owner_b) -> None:
    repo = InMemorySubscriptionRepository()
    client_a = _client(
        monkeypatch, principal=Principal(user_id=owner_a, role=UserRole.USER), repo=repo
    )
    client_b = _client(
        monkeypatch, principal=Principal(user_id=owner_b, role=UserRole.USER), repo=repo
    )

    client_a.post("/mypage/subscription")
    b_status = client_b.get("/mypage/subscription").json()
    assert b_status["status"] == "NONE"


# ── account-profile + consents (REAL U3 accounts data via AccountRepository) ──
def _seeded_account_repo(
    user_id: str,
    *,
    login_provider: str = "GOOGLE",
    nightly_push_agreed: bool = False,
) -> InMemoryAccountRepository:
    repo = InMemoryAccountRepository()
    repo.seed(
        user_id,
        login_provider=login_provider,
        created_at=datetime(2026, 3, 2, tzinfo=UTC),
        nightly_push_agreed=nightly_push_agreed,
    )
    return repo


def test_account_profile_returns_login_provider_and_created_at(monkeypatch) -> None:
    principal = _principal()
    account_repo = _seeded_account_repo(principal.user_id, login_provider="ORCID")
    resp = _client(monkeypatch, principal=principal, account_repo=account_repo).get(
        "/mypage/account-profile"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["loginProvider"] == "ORCID"
    assert body["createdAt"].startswith("2026-03-02")


def test_account_profile_requires_authentication(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/mypage/account-profile")
    assert resp.status_code == 401


def test_account_profile_404_when_account_absent(monkeypatch) -> None:
    # Principal present but no seeded account row → repo returns None → 404.
    resp = _client(
        monkeypatch, principal=_principal(), account_repo=InMemoryAccountRepository()
    ).get("/mypage/account-profile")
    assert resp.status_code == 404


def test_consents_get_returns_the_three_flags(monkeypatch) -> None:
    principal = _principal()
    account_repo = _seeded_account_repo(principal.user_id)
    resp = _client(monkeypatch, principal=principal, account_repo=account_repo).get(
        "/mypage/consents"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "privacyPolicyAgreed": True,
        "termsOfServiceAgreed": True,
        "nightlyPushAgreed": False,
    }


def test_consents_post_toggles_nightly_push_and_persists(monkeypatch) -> None:
    principal = _principal()
    account_repo = _seeded_account_repo(principal.user_id, nightly_push_agreed=False)
    client = _client(monkeypatch, principal=principal, account_repo=account_repo)

    resp = client.post("/mypage/consents", json={"nightlyPushAgreed": True})
    assert resp.status_code == 200
    assert resp.json()["nightlyPushAgreed"] is True
    # The change persists — a subsequent GET reflects it.
    assert client.get("/mypage/consents").json()["nightlyPushAgreed"] is True


def test_consents_require_authentication(monkeypatch) -> None:
    resp = _client(monkeypatch).get("/mypage/consents")
    assert resp.status_code == 401
