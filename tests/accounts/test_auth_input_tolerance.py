"""FR-29 / BR-A12 — public auth INPUT DTOs must IGNORE unknown body fields so a
frontend/backend version skew (e.g. a stale bundle posting an extra field) cannot
422-block login/signup. Response DTOs must stay strict (extra=forbid).

This is the regression guard for the live "문제가 발생했습니다" login outage: a
`/auth/login` 422 caused by `LoginRequest`'s former `extra='forbid'`.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from docsuri_shared.dtos import LoginRequest, SessionInfo, SignupRequest, SignupResult


def test_login_request_ignores_unknown_fields() -> None:
    # A stale client posting an extra field must NOT raise (was 422 before FR-29).
    req = LoginRequest(email="a@b.com", password="pw", recaptchaToken="stale", junk=1)
    assert req.email == "a@b.com"
    assert req.password == "pw"
    # extra=ignore => the unknown field is dropped, not retained.
    assert getattr(req, "recaptchaToken", None) is None


def test_signup_request_ignores_unknown_fields() -> None:
    req = SignupRequest(email="a@b.com", password="pw", junk="y")
    assert req.email == "a@b.com"


def test_response_dtos_still_forbid_extra() -> None:
    # Responses must not silently accept/echo unexpected fields (SEC-9).
    with pytest.raises(ValidationError):
        SignupResult(accountId="acc-1", leaked="secret")
    with pytest.raises(ValidationError):
        SessionInfo(userId="u-1", expiresAt=datetime.now(UTC), leaked="secret")
