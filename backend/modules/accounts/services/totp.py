"""TOTP (RFC 6238) MFA service for the admin control plane (BR-A7).

Admins enroll a TOTP secret (returned as an ``otpauth://`` provisioning URI for a QR code), then
prove possession via /auth/mfa/verify to elevate their session (mfa_verified=True). The plaintext
secret MUST NOT be logged or returned in any response (SEC-3).

At-rest encryption (S6, 감사 #4): ``totp_secret`` is encrypted at rest with Fernet (AES-128-CBC +
HMAC) keyed by the ``TOTP_SECRET_KEY`` env, so a DB/backup/snapshot leak does not expose admin MFA
seeds. Stored values are prefixed ``fernet:``. Legacy/plaintext rows (no prefix) are still accepted
on verify (transitional). If the column is encrypted but the key is missing, verify Fail-Closes
(returns False) rather than trusting an unverifiable seed. Local/dev without a key falls back to
plaintext (with a warning). Remaining infra step: source ``TOTP_SECRET_KEY`` from AWS Secrets
Manager / KMS (same secret-via-ARN pattern as the OIDC secrets) instead of a raw env value."""

from __future__ import annotations

import logging
import os

import pyotp
from cryptography.fernet import Fernet, InvalidToken

from ..repository.credential import AccountTable, CredentialRepository

logger = logging.getLogger(__name__)

_ISSUER = "DocSuri"
_ENC_PREFIX = "fernet:"  # 암호화된 시크릿 식별자(레거시 평문 행과 구분).


def _cipher() -> Fernet | None:
    """TOTP_SECRET_KEY(Fernet 키)로 암호기를 구성한다. 미설정이면 None — 로컬/개발은 평문 저장으로
    폴백하되 경보를 남긴다(프로덕션은 키 주입 필수, S6)."""
    key = os.getenv("TOTP_SECRET_KEY", "").strip()
    if not key:
        logger.warning(
            "TOTP_SECRET_KEY 미설정 — TOTP 시크릿을 평문으로 저장합니다(로컬/개발 한정). 프로덕션은 키 주입 필수."
        )
        return None
    return Fernet(key.encode("utf-8"))


def _encrypt_secret(secret: str) -> str:
    """저장용 암호문(``fernet:`` 접두)으로 변환한다. 키 없으면 평문 그대로(로컬)."""
    cipher = _cipher()
    if cipher is None:
        return secret
    return _ENC_PREFIX + cipher.encrypt(secret.encode("utf-8")).decode("ascii")


def _decrypt_secret(stored: str) -> str | None:
    """저장값에서 평문 시크릿을 복원한다. 접두 없으면 레거시 평문으로 간주(그대로 사용).
    암호문인데 키가 없거나 복호화 실패면 None(Fail-Closed — 검증 불가)."""
    if not stored:
        return None
    if not stored.startswith(_ENC_PREFIX):
        return stored  # 레거시 평문 행 또는 로컬 평문
    cipher = _cipher()
    if cipher is None:
        logger.error("암호화된 TOTP 시크릿이지만 TOTP_SECRET_KEY가 없습니다 — MFA 검증 불가(Fail-Closed).")
        return None
    try:
        return cipher.decrypt(stored[len(_ENC_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        logger.error("TOTP 시크릿 복호화 실패(InvalidToken) — MFA 검증 불가(Fail-Closed).")
        return None


class TotpService:
    def __init__(self, credential_repo: CredentialRepository):
        self._repo = credential_repo

    def enroll(self, account: AccountTable) -> str:
        """새 TOTP 시크릿을 생성·저장하고 otpauth:// 프로비저닝 URI(QR용)를 반환한다.
        재등록 시 기존 시크릿을 교체한다(분실 복구). 평문 시크릿 자체는 응답/로그에 노출하지 않는다."""
        secret = pyotp.random_base32()
        account.totp_secret = _encrypt_secret(secret)  # S6: at-rest 암호화(키 없으면 평문 폴백)
        self._repo.update_account(account)
        return pyotp.totp.TOTP(secret).provisioning_uri(name=account.email, issuer_name=_ISSUER)

    def verify(self, account: AccountTable, code: str) -> bool:
        """제출된 코드를 계정의 TOTP 시크릿으로 검증한다. 미등록 계정/빈 코드는 항상 False(Fail-Closed).
        valid_window=1로 ±1 타임스텝(30초) 시계 오차를 허용한다."""
        if not account.totp_secret or not code:
            return False
        secret = _decrypt_secret(account.totp_secret)  # S6: 복호화(레거시 평문 호환·실패 시 None)
        if not secret:
            return False
        return pyotp.TOTP(secret).verify(code, valid_window=1)
