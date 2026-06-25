"""U10 My Page — in-memory subscription repository (mock-first default, mirrors U4 D10).

The default adapter: the app-shell mounts U10 with it so the module serves with NO live
database, and the test suite runs green without infra. The production ``SqlSubscriptionRepository``
(``sql.py``) swaps in behind the same port.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..models import AccountProfile, Consents, Subscription


class InMemorySubscriptionRepository:
    def __init__(self) -> None:
        self._by_owner: dict[str, Subscription] = {}

    def get(self, owner_id: str) -> Subscription | None:
        return self._by_owner.get(owner_id)

    def upsert(self, item: Subscription) -> Subscription:
        self._by_owner[item.owner_id] = item
        return item


class InMemoryAccountRepository:
    """Mock-first default for the account-backed profile + consents port (mirrors the
    in-memory subscription repo). Seedable so tests and the app-shell default can populate
    accounts without live infra; an unseeded user_id reads as a missing account (-> None ->
    404 at the controller)."""

    def __init__(self) -> None:
        self._profiles: dict[str, AccountProfile] = {}
        self._consents: dict[str, Consents] = {}

    def seed(
        self,
        user_id: str,
        *,
        login_provider: str = "EMAIL",
        created_at: datetime | None = None,
        privacy_policy_agreed: bool = True,
        terms_of_service_agreed: bool = True,
        nightly_push_agreed: bool = False,
    ) -> None:
        self._profiles[user_id] = AccountProfile(
            login_provider=login_provider,
            created_at=created_at or datetime.now(UTC),
        )
        self._consents[user_id] = Consents(
            privacy_policy_agreed=privacy_policy_agreed,
            terms_of_service_agreed=terms_of_service_agreed,
            nightly_push_agreed=nightly_push_agreed,
        )

    def get_profile(self, user_id: str) -> AccountProfile | None:
        return self._profiles.get(user_id)

    def get_consents(self, user_id: str) -> Consents | None:
        return self._consents.get(user_id)

    def set_nightly_push(self, user_id: str, agreed: bool) -> Consents | None:
        existing = self._consents.get(user_id)
        if existing is None:
            return None
        existing.nightly_push_agreed = agreed
        return existing
