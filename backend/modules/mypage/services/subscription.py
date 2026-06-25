"""U10 — SubscriptionService: get/subscribe/cancel a mock subscription (no real PG/billing).

subscribe()/cancel() are both idempotent — re-calling in the already-target state is a no-op
that returns the current snapshot (mirrors U4's idempotent add/save pattern). Cancellation
retains the PREMIUM benefit through ``current_period_end`` rather than cutting access
immediately (confirmed decision: 해지 신청 시 결제 주기 종료일까지 유지).
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.modules.accounts.models import Principal

from ..models import BILLING_PERIOD, Subscription
from ..ports import SubscriptionRepository
from ..schemas import SubscriptionDTO, SubscriptionPlan, SubscriptionStatusValue


def _to_dto(sub: Subscription) -> SubscriptionDTO:
    return SubscriptionDTO(
        plan=sub.plan,
        status=sub.status,
        startedAt=sub.started_at,
        currentPeriodEnd=sub.current_period_end,
        canceledAt=sub.canceled_at,
    )


class SubscriptionService:
    def __init__(self, repo: SubscriptionRepository) -> None:
        self._repo = repo

    def get(self, principal: Principal) -> SubscriptionDTO:
        sub = self._repo.get(principal.user_id) or Subscription(owner_id=principal.user_id)
        return _to_dto(sub)

    def subscribe(self, principal: Principal) -> SubscriptionDTO:
        owner = principal.user_id
        existing = self._repo.get(owner)
        if existing is not None and existing.status == SubscriptionStatusValue.ACTIVE:
            return _to_dto(existing)  # idempotent — already active, no-op

        now = datetime.now(UTC)
        sub = Subscription(
            owner_id=owner,
            plan=SubscriptionPlan.PREMIUM,
            status=SubscriptionStatusValue.ACTIVE,
            started_at=existing.started_at if existing and existing.started_at else now,
            current_period_end=now + BILLING_PERIOD,
            canceled_at=None,
        )
        return _to_dto(self._repo.upsert(sub))

    def cancel(self, principal: Principal) -> SubscriptionDTO:
        owner = principal.user_id
        existing = self._repo.get(owner)
        if existing is None or existing.status != SubscriptionStatusValue.ACTIVE:
            return _to_dto(existing or Subscription(owner_id=owner))  # idempotent no-op

        existing.status = SubscriptionStatusValue.CANCELED
        existing.canceled_at = datetime.now(UTC)
        return _to_dto(self._repo.upsert(existing))
