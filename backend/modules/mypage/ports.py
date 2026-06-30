"""U10 My Page — port interface (typing.Protocol seam).

Mirrors U4's port-decoupling pattern: the in-memory adapter is the mock-first default (the
app-shell mounts U10 with no live infra), and the SQL adapter swaps in through the same
interface. ``owner_id`` is a required argument on every method, so an adapter structurally
cannot return another owner's row.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import AccountProfile, Consents, OrcidIdentity, Subscription


@runtime_checkable
class SubscriptionRepository(Protocol):
    def get(self, owner_id: str) -> Subscription | None: ...
    def upsert(self, item: Subscription) -> Subscription: ...


@runtime_checkable
class AccountRepository(Protocol):
    """Account-backed read/write port for the My Page profile + consents.

    Mirrors ``SubscriptionRepository``: ``user_id`` is required on every method so an adapter
    structurally cannot return another account's row. The production adapter wraps U3's real
    ``CredentialRepository``; the in-memory adapter is the mock-first default. Methods return
    ``None`` when the account does not exist (controller maps to 404)."""

    def get_profile(self, user_id: str) -> AccountProfile | None: ...
    def get_consents(self, user_id: str) -> Consents | None: ...
    def set_nightly_push(self, user_id: str, agreed: bool) -> Consents | None: ...
    def get_orcid_identity(self, user_id: str) -> OrcidIdentity | None: ...
