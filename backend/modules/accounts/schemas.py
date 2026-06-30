"""Accounts request/response DTOs — re-exported from the shared SSOT (docsuri_shared).

Previously hand-defined here, which forked the contract. They now come from
``docsuri_shared.dtos`` so U3 and U5 (whose TS types are generated from the SAME schema) agree
on one contract: camelCase fields (accountId/userId/expiresAt). Do not redefine these locally —
change the JSON Schema in shared/ and regenerate (§5-B).

extra-field policy is split by direction (FR-29/BR-A12): RESPONSE DTOs (SignupResult, SessionInfo)
are ``extra='forbid'`` (no internal-field leakage), while public auth INPUT DTOs (SignupRequest,
LoginRequest, PasswordResetRequest/Confirm) intentionally OMIT model_config → pydantic default
``extra='ignore'``, so an unknown body field from front/back version skew is ignored rather than
causing a 422 auth outage. Don't add ``extra='forbid'`` to the input schemas."""

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
