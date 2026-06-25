"""Accounts request/response DTOs — re-exported from the shared SSOT (docsuri_shared).

Previously hand-defined here, which forked the contract. They now come from
``docsuri_shared.dtos`` so U3 and U5 (whose TS types are generated from the SAME schema) agree
on one contract: camelCase fields (accountId/userId/expiresAt) with ``extra='forbid'``. Do not
redefine these locally — change the JSON Schema in shared/ and regenerate (§5-B)."""

from docsuri_shared.dtos import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionInfo,
    SignupRequest,
    SignupResult,
    ValidationErrorDTO,
)

__all__ = [
    "SignupRequest",
    "SignupResult",
    "LoginRequest",
    "SessionInfo",
    "ValidationErrorDTO",
    "PasswordResetRequest",
    "PasswordResetConfirm",
]
