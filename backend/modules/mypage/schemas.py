"""U10 My Page — wire DTOs.

Re-exports the shared SSOT DTOs (``docsuri_shared.dtos``, generated from
``shared/dtos/mypage.schema.json``). U10 MUST NOT redefine them — forking the SSOT is exactly
the defect to avoid (mirrors U4's ``schemas.py`` convention).

The account-profile / consents DTOs below are *intentionally* NOT in the shared SSOT: they are
module-local (mirroring the frontend's hand-authored ``types/mypage.ts`` VMs), so their
camelCase field names must match those VMs EXACTLY.
"""

from __future__ import annotations

from datetime import datetime

from docsuri_shared.dtos import SubscriptionDTO, SubscriptionPlan, SubscriptionStatusValue
from pydantic import BaseModel

__all__ = [
    "SubscriptionDTO",
    "SubscriptionPlan",
    "SubscriptionStatusValue",
    "AccountProfileDTO",
    "ConsentsDTO",
    "ConsentsUpdate",
    "OrcidWorkDTO",
    "OrcidProfileDTO",
]


class AccountProfileDTO(BaseModel):
    """로그인 경로 + 가입날짜 (frontend ``AccountProfileVM`` 거울)."""

    loginProvider: str  # 'GOOGLE' | 'ORCID' | 'EMAIL'
    createdAt: datetime


class ConsentsDTO(BaseModel):
    """동의 항목 (frontend ``ConsentSettingsVM`` 거울)."""

    privacyPolicyAgreed: bool
    termsOfServiceAgreed: bool
    nightlyPushAgreed: bool


class ConsentsUpdate(BaseModel):
    """야간 푸시 동의 갱신 요청 바디 (nightlyPush만 토글 가능)."""

    nightlyPushAgreed: bool


class OrcidWorkDTO(BaseModel):
    """ORCID 저작물 1건 (frontend ``OrcidWorkVM`` 거울)."""

    title: str
    year: int | None = None


class OrcidProfileDTO(BaseModel):
    """ORCID 공개 프로필 (frontend ``OrcidProfileVM`` 거울). loginProvider!='ORCID'면 호출하지
    않는다(없으면 404). name/affiliation은 캐시, works는 라이브."""

    orcidId: str
    name: str
    affiliation: str | None = None
    works: list[OrcidWorkDTO] = []
