# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class AccountDeleted(BaseModel):
    """
    Producer: U3.AccountDeletionService.purge_job — published at PERMANENT-PURGE time (H2: NOT at soft-delete; the grace window must stay recoverable). Consumers: U4 (library/saved-searches), U2 (history), U11 (research sessions) — each subscribes by topic and purges its own owner-scoped data (BR-A11 cascade, dependency-inverted: U3 never calls them). Delivery: at-least-once → consumers MUST be idempotent, keyed on `eventId` (deterministic uuid5(account_id), stable across retries). NO secrets/PII beyond the account id (SEC-3). Trace: FR-28, US-A6, BR-A11, SEC-8/14.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    accountId: str = Field(
        ...,
        description='Identifier of the permanently-purged account whose owner-scoped data subscribers must erase. Trace: BR-A11, FR-28.',
    )
    occurredAt: AwareDatetime = Field(
        ..., description='Permanent-purge time (date-time). Trace: BR-A11.'
    )
    eventId: str = Field(
        ...,
        description='Idempotency key — deterministic uuid5(account_id), identical across at-least-once retries so consumers de-dup the cascade. Trace: BR-A11 (멱등·재시도·DLQ).',
    )


class AccountCreated(BaseModel):
    """
    Producer: U3.SignupService — published after policy/uniqueness validation, hashing, and persistence succeed (services.md register orchestration). Consumer: U6 Observability/Ops (signup telemetry + audit fan-out). Delivery: at-least-once → consumer idempotent (suppress duplicate signup telemetry). PII minimized (SEC-3); plaintext password/credentials NEVER included (FR-7/SEC-12 invariant). Trace: FR-7, US-A1, NFR-O1.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    userId: str = Field(
        ...,
        description='Identifier of the newly created account (no credentials; PII-minimized — SEC-3). Trace: events.md §3.1, FR-7.',
    )
    timestamp: AwareDatetime = Field(
        ...,
        description='Account creation time (date-time; concrete wire format is Infra Design). Trace: events.md §3.1.',
    )


class SignupAbuseSignal(BaseModel):
    """
    Producer: U3.SignupService — emitted on abuse indications (rate/duplicate, etc.). Consumer: U6 Ops (signup-abuse mitigation, coupled with gateway rate-limiting SEC-11). Delivery: at-least-once → consumer idempotent (duplicate-signal safe). NO secrets/PII exposed (SEC-3); reason generalized. Trace: SEC-11, RES-11.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    timestamp: AwareDatetime | None = Field(
        None,
        description='Time the abuse indication was observed (date-time). Trace: events.md §3.2.',
    )
    reason: str = Field(
        ...,
        description='Generalized abuse-indication category (e.g. rate/duplicate — non-sensitive label; no PII/secrets, SEC-3). Trace: events.md §3.2, SEC-11.',
    )


class AuthFailureSignal(BaseModel):
    """
    Producer: U3.AuthenticationService — emitted on credential-verification failure (preserving the 'do not reveal credential existence' invariant). Consumer: U6 Ops (brute-force detection → lockout/delay/CAPTCHA enforcement + alerting). Delivery: at-least-once → consumer idempotent. Failure reason GENERALIZED — MUST NOT reveal which credential was wrong, and MUST NOT carry plaintext credentials (SEC-12). Trace: SEC-12, RES-11.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    timestamp: AwareDatetime | None = Field(
        None,
        description='Time of the authentication-failure event (date-time). Trace: events.md §3.3.',
    )
    reason: str = Field(
        ...,
        description='Generalized failure reason — does NOT reveal which credential was wrong; no plaintext credentials (SEC-12). Trace: events.md §3.3, SEC-12.',
    )


class U3AccountAuthSignals(
    RootModel[AccountCreated | SignupAbuseSignal | AuthFailureSignal | AccountDeleted]
):
    root: AccountCreated | SignupAbuseSignal | AuthFailureSignal | AccountDeleted = (
        Field(
            ...,
            description='🟡 PROVISIONAL (events.md §3 — shapes finalized in U3 FD; here only the fact-of-publish, producer/consumer, meaning, and security invariants are fixed). U3 SignupService/AuthenticationService emit these after domain processing (services.md). Contains: AccountCreated, SignupAbuseSignal, AuthFailureSignal, AccountDeleted. All payloads: NO plaintext passwords/credentials (FR-7/SEC-12 invariant), PII minimized (SEC-3), generalized failure reasons (SEC-12). Use $defs root selection to validate a specific shape.',
            title='U3 Account / Auth Signals',
        )
    )
