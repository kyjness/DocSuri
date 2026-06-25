# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from typing import Any
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class U3AccountsAuthDtos(RootModel[Any]):
    root: Any = Field(
        ...,
        description='🟡 PROVISIONAL (refined in U3 FD). U3 Accounts/Auth body DTO contract (dtos.md §2). Producer: U3 (AccountController.signup(req: SignupRequest, ctx) -> HttpResponse<SignupResult>; login(req: LoginRequest, ctx) -> HttpResponse<SessionCookie>; currentSession(ctx) -> HttpResponse<SessionInfo>). Consumer: U5. INVARIANT (SEC-12/SEC-3): plaintext `password` is REQUEST-INPUT-ONLY, never logged, and NEVER present in any response. The session token material is delivered via a secure cookie (secure/httpOnly/sameSite) — SessionCookie is TRANSPORT, NOT a body DTO, so it is intentionally NOT modeled as an object schema here. Credential existence is not disclosed (generalized errors). All DTOs defined in $defs for per-track type generation. Trace: FR-7, US-A1, US-A2, SEC-3, SEC-9, SEC-12.',
        title='U3 Accounts/Auth DTOs',
    )


class SignupRequest(BaseModel):
    """
    Self-signup input. Source: AccountController.signup(req: SignupRequest, ctx) (component-methods U3). `password` is INPUT-ONLY and NOT logged (SEC-3); policy/breach checks are server-side (PasswordPolicy). Trace: dtos.md §2, FR-7, US-A1, SEC-12.
    """

    email: str = Field(
        ..., description='Account email (signup identity). Trace: FR-7, US-A1.'
    )
    password: str = Field(
        ...,
        description='INPUT-ONLY plaintext password. NEVER returned in any response and NEVER logged (SEC-12/SEC-3). Policy/breach validation is server-side (PasswordPolicy). Trace: FR-7, SEC-3, SEC-12.',
    )


class SignupResult(BaseModel):
    """
    Signup success response — returns the new account identifier only. No credentials or internal state exposed; conflicts/policy violations surface as generalized errors (409/400/429 — non-normative API-Design hint). Trace: dtos.md §2, FR-7, US-A1, SEC-9.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    accountId: Any = Field(
        ...,
        description='Created account identifier (success identity only). Trace: FR-7, US-A1, SEC-9.',
    )


class LoginRequest(BaseModel):
    """
    Login input. Source: AccountController.login(req: LoginRequest, ctx) (component-methods U3). `password` is INPUT-ONLY and NOT logged. Failures surface as a generalized auth error (401/429 — credential existence not disclosed). Trace: dtos.md §2, FR-7, US-A2, SEC-12.
    """

    email: str = Field(
        ..., description='Account email (login identity). Trace: FR-7, US-A2.'
    )
    password: str = Field(
        ...,
        description='INPUT-ONLY plaintext password. NEVER returned in any response and NEVER logged (SEC-12/SEC-3). Trace: FR-7, SEC-3, SEC-12.',
    )


class SessionInfo(BaseModel):
    """
    currentSession non-sensitive session info (front-end session sync). Source: AccountController.currentSession(ctx) -> HttpResponse<SessionInfo>. Token/credentials/internal handles NOT exposed (SEC-9). NOTE: the session token itself is carried by the secure SessionCookie (transport), NOT by this body DTO. Trace: dtos.md §2, FR-7, US-A2, SEC-9.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    userId: str = Field(
        ...,
        description='Authenticated user identifier (non-sensitive). Trace: FR-7, US-A2, SEC-9.',
    )
    expiresAt: AwareDatetime = Field(
        ...,
        description='Session expiry instant (serialized as RFC 3339 / ISO 8601 date-time — concrete wire format is API/Infra Design). Trace: FR-7, US-A2.',
    )


class PasswordResetRequest(BaseModel):
    """
    Forgot-password request input (FR-26/BR-A8). Enumeration-safe: the response is identical regardless of account existence/state. `email` only. Public auth input → unknown fields ignored (FR-29/BR-A12). Trace: FR-26, US-A3, SEC-9.
    """

    email: str = Field(
        ..., description='Account email to send the reset link to. Trace: FR-26, US-A3.'
    )


class PasswordResetConfirm(BaseModel):
    """
    Forgot-password confirm input (FR-26/BR-A8). Single-use token + new password (re-validated against BR-A1); on success all sessions are invalidated. Public auth input → unknown fields ignored (FR-29/BR-A12). Trace: FR-26, US-A3, SEC-12.
    """

    token: str = Field(
        ...,
        description='Single-use reset token from the emailed link. INPUT-ONLY, never logged (SEC-3). Trace: FR-26.',
    )
    newPassword: str = Field(
        ...,
        description='INPUT-ONLY new plaintext password; policy/breach validated server-side (PasswordPolicy/BR-A1). Never logged/returned (SEC-3/SEC-12). Trace: FR-26, SEC-12.',
    )
