"""U10 — AccountService: read the account-backed profile + consents (REAL U3 accounts data).

Mirrors ``SubscriptionService``: maps the domain entities (``AccountProfile`` / ``Consents``)
to the module-local wire DTOs. Returns ``None`` when the account does not exist so the
controller can map to 404 (fail-closed). Ownership is the repository's backstop — every method
takes the principal's ``user_id`` (SEC-8 single decision point).
"""

from __future__ import annotations

from backend.modules.accounts.models import Principal

from ..models import AccountProfile, Consents
from ..ports import AccountRepository
from ..schemas import AccountProfileDTO, ConsentsDTO


def _profile_to_dto(profile: AccountProfile) -> AccountProfileDTO:
    return AccountProfileDTO(
        loginProvider=profile.login_provider,
        createdAt=profile.created_at,
    )


def _consents_to_dto(consents: Consents) -> ConsentsDTO:
    return ConsentsDTO(
        privacyPolicyAgreed=consents.privacy_policy_agreed,
        termsOfServiceAgreed=consents.terms_of_service_agreed,
        nightlyPushAgreed=consents.nightly_push_agreed,
    )


class AccountService:
    def __init__(self, repo: AccountRepository) -> None:
        self._repo = repo

    def get_profile(self, principal: Principal) -> AccountProfileDTO | None:
        profile = self._repo.get_profile(principal.user_id)
        return _profile_to_dto(profile) if profile is not None else None

    def get_consents(self, principal: Principal) -> ConsentsDTO | None:
        consents = self._repo.get_consents(principal.user_id)
        return _consents_to_dto(consents) if consents is not None else None

    def set_nightly_push(self, principal: Principal, agreed: bool) -> ConsentsDTO | None:
        consents = self._repo.set_nightly_push(principal.user_id, agreed)
        return _consents_to_dto(consents) if consents is not None else None
