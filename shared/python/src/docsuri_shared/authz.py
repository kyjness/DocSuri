"""Cross-Unit authorization contract (#167) — the neutral home for the identity and
authorization primitives that U4/U6/U8 (and others) share.

Why here: ``unit-of-work-dependency.md`` requires U1–U5 to take *code* dependencies only
on ``shared``; a cross-Unit contract must not live inside a peer Unit. These types were
originally defined inside U3 (accounts) and imported directly by U4/U6/U8, which leaked
the accounts module boundary (#167). They are pure data + a *stateless* policy — no I/O,
no account state — so they belong in the shared contract layer alongside
``ports.GroundingDecision``.

U3 remains the definitional owner: ``accounts.models`` / ``accounts.guard`` re-export these
names for their own internal use and for back-compat (``except DomainException`` in U3 keeps
catching, because the class identity is preserved through the re-export).

``AuthorizationGuard`` is stateless by design (BR-A6/BR-A7): every decision is a pure
function of ``(principal, action, resource_owner_id)``. That is exactly why it moves cleanly
here rather than requiring a runtime delegation back to U3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID

__all__ = [
    "DomainException",
    "UserRole",
    "Action",
    "Decision",
    "AccountId",
    "Principal",
    "AuthorizationGuard",
]


class DomainException(Exception):
    """Base exception for authorization-contract validation failures (a malformed UUID in
    ``AccountId`` / ``Principal``). U3 (accounts) re-exports this as the base of its own
    domain-exception hierarchy, so ``except DomainException`` in accounts keeps catching
    these — the class identity is shared, not duplicated."""


# These string enums are moved verbatim from U3 (accounts). We keep the ``(str, Enum)`` base
# rather than switching to ``enum.StrEnum`` (which UP042 suggests): this is a faithful
# relocation of a security/authorization contract, and StrEnum changes ``str(member)`` from
# ``"UserRole.USER"`` to ``"USER"``. Modernizing is a separate, owner-reviewed follow-up.
class UserRole(str, Enum):  # noqa: UP042
    USER = "USER"
    ADMIN = "ADMIN"


class Action(str, Enum):  # noqa: UP042
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    RERUN = "RERUN"


class Decision(str, Enum):  # noqa: UP042
    ALLOW = "ALLOW"
    DENY = "DENY"


@dataclass(frozen=True)
class AccountId:
    value: str

    def __post_init__(self):
        try:
            # Validate UUID v4 format
            UUID(self.value)
        except ValueError as e:
            raise DomainException(f"Invalid AccountId UUID format: {self.value}") from e


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: UserRole
    mfa_verified: bool = False

    def __post_init__(self):
        # Validate user_id has valid UUID format
        try:
            UUID(self.user_id)
        except ValueError as e:
            raise DomainException(f"Invalid Principal user_id format: {self.user_id}") from e


class AuthorizationGuard:
    """
    객체 단위 소유권 및 관리자 권한 인가 결정을 처리하는 단일 권위 가드 (BR-A6, BR-A7)
    피드백 ④ 반영: 타 도메인 데이터 스펙과의 완전한 분리를 위해 Stateless 인가로 설계
    """

    @classmethod
    def authorize(
        cls, principal: Principal | None, action: Action, resource_owner_id: AccountId | None
    ) -> Decision:
        """
        사용자 데이터 관리 액션(READ, WRITE, DELETE, RERUN)에 대해
        객체 소유권을 Stateless 검증합니다.
        피드백 ④ 반영: principal과 함께 타 서비스가 먼저 조회한
        resource_owner_id를 명시적 인자로 받습니다.
        """
        # 1. 기본 거부 정책 (Default Deny - SEC-8)
        if not principal or not principal.user_id:
            return Decision.DENY

        if not resource_owner_id or not resource_owner_id.value:
            return Decision.DENY

        # 2. 소유권 일치 판단 (BR-A6)
        if principal.user_id == resource_owner_id.value:
            return Decision.ALLOW

        # 3. 소유자가 다르면 기본 거부
        return Decision.DENY

    @classmethod
    def authorize_admin(cls, principal: Principal | None, mfa_verified: bool = False) -> Decision:
        """
        관리자(ADMIN) 제어 평면에 대한 접근 및 TOTP MFA 검증을 강제합니다. (BR-A7)
        """
        if not principal:
            return Decision.DENY

        # 1. 역할 검증
        if principal.role != UserRole.ADMIN:
            return Decision.DENY

        # 2. TOTP MFA 인증 여부 검증 (BR-A7)
        if not mfa_verified:
            return Decision.DENY

        return Decision.ALLOW
