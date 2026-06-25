"""U10 My Page — SQLAlchemy subscription repository (production adapter, mirrors U4 D10).

Swaps in behind the same port as the in-memory default (tests/app-shell run on in-memory;
production injects this against the U3-inherited RDS PostgreSQL). Table maps 1:1 to
``migrations/001_create_mypage_subscriptions.sql``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from backend.modules.accounts.repository.credential import CredentialRepository

from ..models import AccountProfile, Consents, Subscription
from ..schemas import SubscriptionPlan, SubscriptionStatusValue


class Base(DeclarativeBase):
    pass


class SubscriptionTable(Base):
    __tablename__ = "mypage_subscriptions"

    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def _to_domain(row: SubscriptionTable) -> Subscription:
    return Subscription(
        owner_id=row.owner_id,
        plan=SubscriptionPlan(row.plan),
        status=SubscriptionStatusValue(row.status),
        started_at=row.started_at,
        current_period_end=row.current_period_end,
        canceled_at=row.canceled_at,
    )


class SqlSubscriptionRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def get(self, owner_id: str) -> Subscription | None:
        row = (
            self._s.query(SubscriptionTable)
            .filter(SubscriptionTable.owner_id == owner_id)
            .first()
        )
        return _to_domain(row) if row else None

    def upsert(self, item: Subscription) -> Subscription:
        row = (
            self._s.query(SubscriptionTable)
            .filter(SubscriptionTable.owner_id == item.owner_id)
            .first()
        )
        if row is None:
            row = SubscriptionTable(owner_id=item.owner_id)
            self._s.add(row)
        row.plan = item.plan.value
        row.status = item.status.value
        row.started_at = item.started_at
        row.current_period_end = item.current_period_end
        row.canceled_at = item.canceled_at
        self._s.flush()
        return item


def _login_provider(repo: CredentialRepository, account_id: str) -> str:
    """LINKED 소셜 신원에서 로그인 경로를 도출한다: ORCID > GOOGLE > EMAIL(소셜 미연동).
    provider 문자열 비교는 대소문자 무시 (저장 규약은 'GOOGLE'/'ORCID' 대문자)."""
    providers = {
        identity.provider.upper()
        for identity in repo.list_social_identities(account_id)
        if identity.status == "LINKED"
    }
    if "ORCID" in providers:
        return "ORCID"
    if "GOOGLE" in providers:
        return "GOOGLE"
    return "EMAIL"


class SqlAccountRepository:
    """Production account-backed adapter (mirrors ``SqlSubscriptionRepository``): wraps U3's real
    ``CredentialRepository`` so the My Page profile/consents read straight from the accounts
    tables. ``None`` when the account is absent (-> 404 at the controller)."""

    def __init__(self, session: Session) -> None:
        self._repo = CredentialRepository(session)

    def get_profile(self, user_id: str) -> AccountProfile | None:
        account = self._repo.get_by_id(user_id)
        if account is None:
            return None
        return AccountProfile(
            login_provider=_login_provider(self._repo, user_id),
            created_at=account.created_at,
        )

    def get_consents(self, user_id: str) -> Consents | None:
        account = self._repo.get_by_id(user_id)
        if account is None:
            return None
        return Consents(
            privacy_policy_agreed=account.privacy_policy_agreed,
            terms_of_service_agreed=account.terms_of_service_agreed,
            nightly_push_agreed=account.nightly_push_agreed,
        )

    def set_nightly_push(self, user_id: str, agreed: bool) -> Consents | None:
        account = self._repo.get_by_id(user_id)
        if account is None:
            return None
        account.nightly_push_agreed = agreed
        account.nightly_push_agreed_at = datetime.now(UTC)
        self._repo.update_account(account)
        return Consents(
            privacy_policy_agreed=account.privacy_policy_agreed,
            terms_of_service_agreed=account.terms_of_service_agreed,
            nightly_push_agreed=account.nightly_push_agreed,
        )
