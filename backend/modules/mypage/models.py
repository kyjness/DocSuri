"""U10 My Page — subscription domain entity (mock only, no real PG/billing).

Internal domain type, distinct from the wire DTO (``docsuri_shared.dtos.SubscriptionDTO``,
re-exported via ``schemas.py``). The mapping internal -> DTO lives in
``services/subscription.py``.

Authority note: ownership is NOT decided here — every repository method takes ``owner_id`` as a
required argument, the same data-layer backstop pattern U4 uses under U3's AuthorizationGuard
(SEC-8 single decision point).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .schemas import SubscriptionPlan, SubscriptionStatusValue

BILLING_PERIOD = timedelta(days=30)  # mock fixed-length period — no real billing cycle


class DomainException(Exception):
    """Base domain exception for the My Page module."""


@dataclass
class AccountProfile:
    """A user's account-derived profile for the My Page header (read-only).

    Backed by the REAL U3 accounts module: ``created_at`` is the account's signup time and
    ``login_provider`` is derived from the user's LINKED social identities (ORCID > GOOGLE >
    EMAIL). The mapping internal -> DTO lives in ``services/account.py``.
    """

    login_provider: str  # 'GOOGLE' | 'ORCID' | 'EMAIL'
    created_at: datetime


@dataclass
class Consents:
    """A user's consent flags (read-only for the two mandatory ones; nightly push is togglable).

    Backed by the REAL U3 accounts module's consent columns. Privacy-policy / terms-of-service
    are always True (rejecting them blocks signup), so only ``nightly_push_agreed`` ever toggles.
    """

    privacy_policy_agreed: bool
    terms_of_service_agreed: bool
    nightly_push_agreed: bool


@dataclass
class Subscription:
    """A user's mock subscription state (no real PG/billing behind plan/status changes).

    One row per owner. An owner with no row is equivalent to ``status=NONE`` (never
    subscribed) — services default to this rather than raising NotFound.
    """

    owner_id: str
    plan: SubscriptionPlan = SubscriptionPlan.FREE
    status: SubscriptionStatusValue = SubscriptionStatusValue.NONE
    started_at: datetime | None = None
    current_period_end: datetime | None = None
    canceled_at: datetime | None = None
