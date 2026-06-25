import logging
import secrets
from datetime import UTC, datetime, timedelta

from ..models import (
    Principal,
    SessionExpiredException,
    SessionRecord,
    SessionStoreUnavailableException,
    UnauthorizedException,
    UserRole,
)
from ..repository.session import SessionRepository

logger = logging.getLogger(__name__)

class SessionManager:
    """세션의 생성, 만료 검증 및 sliding expiration 수명 제어를 전담하는 매니저 (US-A2, BR-A3)"""
    
    def __init__(self, session_repo: SessionRepository, idle_timeout_hours: int = 2, max_lifetime_days: int = 30):
        self._repo = session_repo
        self._idle_timeout_hours = idle_timeout_hours
        self._max_lifetime_days = max_lifetime_days

    async def issue(self, principal: Principal) -> SessionRecord:
        """새로운 보안 세션을 발급하여 Redis 저장소에 영속화합니다."""
        # 32바이트의 보안 난수로 유일무이한 세션 핸들 생성 (값 객체화)
        session_handle = secrets.token_hex(32)
        
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self._max_lifetime_days)
        last_active_at = now
        
        session = SessionRecord(
            handle=session_handle,
            user_id=principal.user_id,
            created_at=now,
            last_active_at=last_active_at,
            expires_at=expires_at,
            role=principal.role.value,  # 발급 시 역할을 세션에 보존 (verify에서 복원)
            mfa_verified=principal.mfa_verified,  # BR-A7: MFA 통과 여부도 세션에 보존
        )
        
        # Redis 세션 저장
        await self._repo.save(session)
        logger.info(f"New session issued successfully for user {principal.user_id}.")
        return session

    async def verify(self, session_token: str) -> Principal:
        """
        요청 토큰의 유효성을 검사합니다.
        Sliding 만료 정책 및 Absolute 만료 정책을 물리적으로 강제합니다. (BR-A3)
        Fail-Closed 원칙에 따라, Redis 장애 시 PostgreSQL로 폴백하지 않고 거부합니다. (Q1 NFR Design)
        """
        if not session_token:
            raise UnauthorizedException("인증 토큰이 누락되었습니다.")

        try:
            session = await self._repo.get(session_token)
        except SessionStoreUnavailableException as e:
            # 피드백 ② 반영: Redis 연결 장애 시 Fail-Closed 정책 적용 (DB 폴백 배제, 즉각 거부)
            logger.critical(f"Redis session storage failure (Fail-Closed triggered): {str(e)}")
            raise UnauthorizedException("세션 저장소 일시 장애로 인해 서비스를 이용할 수 없습니다.") from e

        if not session:
            raise SessionExpiredException("세션이 유효하지 않거나 만료되었습니다.")

        now = datetime.now(UTC)

        # 1. Sliding Expiration 만료 검사 (BR-A3 Idle Timeout)
        if now > session.last_active_at + timedelta(hours=self._idle_timeout_hours):
            await self._repo.delete(session_token)
            raise SessionExpiredException("비활성화 상태가 2시간 이상 지속되어 세션이 만료되었습니다.")

        # 2. Absolute Expiration 만료 검사 (BR-A3 Max Lifetime)
        if now > session.expires_at:
            await self._repo.delete(session_token)
            raise SessionExpiredException("세션의 최대 사용 기간(30일)이 만료되었습니다. 다시 로그인해 주세요.")

        # 3. Sliding Expiration 활성 시각 갱신
        session.last_active_at = now
        try:
            await self._repo.save(session)
        except SessionStoreUnavailableException as e:
            # 갱신 저장 실패 시에도 보안을 위해 Fail-Closed 정책 적용
            logger.critical(f"Failed to update session active timestamp: {str(e)}")
            raise UnauthorizedException("세션 만료 갱신 실패로 인증을 거부합니다.") from e

        # 발급 시 세션에 보존해 둔 역할을 복원한다 (USER 하드코딩 제거 — 그래야 ADMIN 인가가 세션으로 전파된다).
        # 알 수 없는/누락된 값은 최소 권한(USER)으로 안전하게 폴백한다 (Fail-safe).
        try:
            role = UserRole(session.role)
        except ValueError:
            role = UserRole.USER
        return Principal(
            user_id=session.user_id,
            role=role,
            mfa_verified=session.mfa_verified,  # BR-A7: 세션에 보존된 MFA 통과 여부 복원
        )

    async def elevate_mfa(self, session_token: str) -> Principal:
        """BR-A7: TOTP 검증 통과 후 현재 세션을 MFA 통과 상태로 승격한다 (2단계 인증).
        세션을 먼저 재검증(만료/sliding 갱신)한 뒤 mfa_verified=True로 저장한다."""
        principal = await self.verify(session_token)  # 만료 검증 + sliding 갱신
        session = await self._repo.get(session_token)
        if not session:
            raise SessionExpiredException("세션이 유효하지 않거나 만료되었습니다.")
        session.mfa_verified = True
        try:
            await self._repo.save(session)
        except SessionStoreUnavailableException as e:
            logger.critical(f"Failed to persist MFA elevation: {str(e)}")
            raise UnauthorizedException("MFA 승격 저장 실패로 인증을 거부합니다.") from e
        return Principal(user_id=principal.user_id, role=principal.role, mfa_verified=True)

    async def invalidate(self, session_token: str) -> None:
        """세션을 즉각 파기하여 로그아웃 처리합니다."""
        if session_token:
            try:
                await self._repo.delete(session_token)
                logger.info("Session successfully invalidated (logout).")
            except SessionStoreUnavailableException as e:
                # 무효화 과정 중 장애 발생 시 로그 적재 후 무시 (사용자 입장에선 어차피 세션이 유실/만료된 것과 같음)
                logger.error(f"Error invalidating session: {str(e)}")

    async def invalidate_all_for_user(self, user_id: str) -> None:
        """해당 사용자의 모든 활성 세션을 파기한다 (FR-26/BR-A8 — 비밀번호 재설정 성공 시
        전 세션 무효화로 탈취 세션을 강제 종료한다)."""
        await self._repo.invalidate_all_for_user(user_id)
