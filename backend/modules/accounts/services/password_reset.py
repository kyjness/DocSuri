"""비밀번호 분실 복구 서비스 (FR-26 / BR-A8).

- 요청(`request_reset`)은 **계정 열거를 막기 위해 항상 일반 응답**으로 끝난다(부재/비활성
  계정이어도 예외 없이 no-op). 활성 계정에만 단일 사용·30분 만료 토큰을 발급해 Resend로 발송한다.
- 확정(`confirm_reset`)은 토큰을 해시로 조회·만료/단일사용 검증 후 BR-A1 정책을 재적용하고,
  성공 시 토큰을 즉시 파기(단일 사용)하며 **해당 계정의 전 세션을 무효화**한다(BR-A8).
- 토큰은 평문이 아닌 SHA-256 해시로만 저장된다(DB 유출 시 토큰 무력화).
"""

import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from ..integrations.email import EmailClientInterface
from ..models import AccountStatus, DomainException, normalize_email
from ..password import PasswordPolicy, get_password_hasher
from ..repository.credential import CredentialRepository
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

RESET_TOKEN_TTL = timedelta(minutes=30)  # BR-A8: 단일 사용·짧은 만료


def _hash_token(token: str) -> str:
    """재설정 토큰의 저장/조회용 SHA-256 해시(평문 비저장)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class PasswordResetService:
    def __init__(
        self,
        credential_repo: CredentialRepository,
        session_manager: SessionManager,
        email_client: EmailClientInterface,
    ):
        self._repo = credential_repo
        self._session_manager = session_manager
        self._email_client = email_client
        self._hasher = get_password_hasher()

    async def request_reset(self, email: str, reset_link_base: str) -> None:
        """재설정 토큰 발급 + 메일 발송. 계정 부재/비활성이어도 조용히 종료(열거 방지, SEC-9)."""
        email_norm = normalize_email(email)
        account = self._repo.get_by_email(email_norm)
        # 활성 계정에만 실제 발급/발송. 그 외(부재/PENDING/DEACTIVATED)는 no-op로 동일 응답 유지.
        if not account or account.status != AccountStatus.ACTIVE.value:
            return
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC).replace(tzinfo=None) + RESET_TOKEN_TTL
        self._repo.create_reset_token(email_norm, _hash_token(token), expires_at)
        sent = await self._email_client.send_password_reset_email(
            email=email_norm, token=token, reset_link=reset_link_base
        )
        if not sent:
            logger.warning("Password reset email dispatch failed (soft-fallback); token remains valid.")

    async def confirm_reset(self, token: str, new_password: str) -> None:
        """토큰 검증 → 새 비밀번호 설정 → 단일 사용 토큰 파기 → 전 세션 무효화(BR-A8)."""
        if not token:
            raise DomainException("유효하지 않은 재설정 토큰입니다.")
        token_hash = _hash_token(token)
        record = self._repo.get_reset_token(token_hash)
        invalid_msg = "유효하지 않거나 만료된 재설정 링크입니다. 다시 요청해 주세요."
        if not record:
            raise DomainException(invalid_msg)
        if datetime.now(UTC).replace(tzinfo=None) > record.expires_at:
            self._repo.delete_reset_token(token_hash)
            raise DomainException(invalid_msg)
        # BR-A1 정책 재적용 (10자+복잡도+로컬 블랙리스트). evaluate는 위반 시
        # InvalidPasswordException(=DomainException)을 raise하고 통과 시 True를 반환하므로
        # 직접 호출한다(change_password와 동일 — 죽은 `if not` 분기 제거).
        PasswordPolicy.evaluate(new_password)
        account = self._repo.get_by_email(record.email)
        if not account:
            self._repo.delete_reset_token(token_hash)
            raise DomainException(invalid_msg)
        # CPU 바운드 Argon2id 해싱은 워커 스레드에 위임(이벤트 루프 비차단).
        new_hash = await asyncio.to_thread(self._hasher.hash, new_password)
        account.password_hash = new_hash
        account.failure_count = 0
        account.last_failed_at = None
        self._repo.update_account(account)
        self._repo.delete_reset_token(token_hash)  # 단일 사용 강제
        await self._session_manager.invalidate_all_for_user(account.id)  # BR-A8: 전 세션 무효화
        logger.info(f"Password reset completed for account {account.id}; all sessions invalidated.")
