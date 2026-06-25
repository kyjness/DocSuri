import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


def normalize_email(raw: str) -> str:
    """Canonical email form for storage and lookup: trimmed + lowercased.

    Email addresses are treated case-insensitively by every real provider, so we
    normalize at the trust boundary (signup/login/verify/resend). Without this, an
    account stored as ``Park@x.com`` is unreachable when the user later types
    ``park@x.com`` — a silent "valid credentials rejected" 401. Idempotent."""
    return raw.strip().lower() if raw else raw


class DomainException(Exception):
    """Base domain exception for Accounts module"""
    pass

class InvalidEmailException(DomainException):
    pass

class InvalidPasswordException(DomainException):
    pass

class SessionExpiredException(DomainException):
    pass

class UnauthorizedException(DomainException):
    pass

class SessionStoreUnavailableException(DomainException):
    """Fail-Closed error when ElastiCache Redis is down"""
    pass

class SocialLinkConfirmationRequired(DomainException):
    """H1 (BR-A9): 검증된 소셜 신원의 이메일이 *비밀번호를 가진* 기존 계정과 일치할 때,
    자동 병합하지 않고 명시적 연결(현 비밀번호/소유 확인)을 요구하기 위해 발생시킨다.
    계정 선점(pre-hijacking) 방어 — 공격자가 선점한 비밀번호 계정에 피해자 소셜 로그인이
    자동 병합되는 것을 차단한다."""
    pass

class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"
    # BR-A11: 소프트 삭제(탈퇴) — 즉시 로그인 차단·유예 동안 보존(복구 가능)·유예 경과 후 영구 파기(PURGED).
    DEACTIVATED = "DEACTIVATED"

class UserRole(str, Enum):
    USER = "USER"
    ADMIN = "ADMIN"

class OidcProvider(str, Enum):
    """소셜 로그인 신원공급자 (FR-27). v1=GOOGLE; GITHUB/APPLE은 차기 사이클."""
    GOOGLE = "GOOGLE"

class Action(str, Enum):
    READ = "READ"
    WRITE = "WRITE"
    DELETE = "DELETE"
    RERUN = "RERUN"

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
class EmailAddress:
    value: str

    # RFC 5322 email regex pattern
    _pattern = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

    def __post_init__(self):
        if not self.value or "@" not in self.value:
            raise InvalidEmailException("Email must contain '@'")
        if len(self.value) > 254:
            raise InvalidEmailException("Email exceeds maximum allowed length of 254 characters")
        
        parts = self.value.split("@")
        local_part = parts[0]
        domain = parts[-1]
        if len(local_part) > 64:
            raise InvalidEmailException("Email local-part exceeds maximum allowed length of 64 characters")
        if len(domain) > 255:
            raise InvalidEmailException("Email domain exceeds maximum allowed length of 255 characters")

        if not self._pattern.match(self.value):
            raise InvalidEmailException(f"Email violates RFC 5322 formatting: {self.value}")

@dataclass(frozen=True)
class PasswordHash:
    value: str

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

@dataclass
class SessionRecord:
    handle: str
    user_id: str
    created_at: datetime
    last_active_at: datetime
    expires_at: datetime
    # 발급 시점의 역할을 세션에 보존해 verify() 가 실제 역할을 복원할 수 있게 한다 (하드코딩 USER 제거).
    role: str = UserRole.USER.value
    # BR-A7: TOTP MFA 통과 여부를 세션에 보존 — 관리자 제어 평면 인가(authorize_admin)가 이 값을 읽는다.
    mfa_verified: bool = False
