# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from typing import Any
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel
from enum import StrEnum


class U10MyPageDtos(RootModel[Any]):
    root: Any = Field(
        ...,
        description='U10 My Page DTO contract — subscription status only (dtos.md TBD). Producer: U10 (MypageController.getSubscription/subscribe/cancelSubscription). Consumer: U5. MOCK-ONLY: no real payment gateway/billing integration sits behind this contract — subscribe/cancel only flip persisted state. INVARIANT (SEC-8/SEC-9): DTOs do NOT carry the owner userId externally — ownership is enforced server-side (U3 Principal). All DTOs defined in $defs for per-track type generation. Trace: U10 (mypage subscription, mock).',
        title='U10 My Page DTOs',
    )


class SubscriptionPlan(StrEnum):
    """
    Subscription plan tier. Trace: U10.
    """

    FREE = 'FREE'
    PREMIUM = 'PREMIUM'


class SubscriptionStatusValue(StrEnum):
    """
    Lifecycle status. NONE = never subscribed. CANCELED = cancellation requested but the PREMIUM benefit is retained through currentPeriodEnd (no immediate cutoff). Trace: U10.
    """

    NONE = 'NONE'
    ACTIVE = 'ACTIVE'
    CANCELED = 'CANCELED'


class SubscriptionDTO(BaseModel):
    """
    Current subscription snapshot (owner userId NOT exposed, SEC-9). Mock-only — no real PG/billing behind this. Trace: U10.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    plan: SubscriptionPlan
    status: SubscriptionStatusValue
    startedAt: AwareDatetime | None = Field(
        None,
        description='Subscription start instant. Absent when status=NONE. Trace: U10.',
    )
    currentPeriodEnd: AwareDatetime | None = Field(
        None,
        description='Current mock billing-period end. The PREMIUM benefit remains active through this instant even after cancellation (no immediate cutoff). Absent when status=NONE. Trace: U10.',
    )
    canceledAt: AwareDatetime | None = Field(
        None,
        description='Cancellation-request instant. Present only once a cancellation has been requested. Trace: U10.',
    )
