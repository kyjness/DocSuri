import asyncio
import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta

from docsuri_shared.events import AccountCreated

from ..integrations.email import EmailClientInterface
from ..models import AccountStatus, DomainException, EmailAddress, normalize_email
from ..password import PasswordPolicy, get_password_hasher
from ..repository.credential import CredentialRepository

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    """이메일 인증 토큰을 저장 전 SHA-256으로 해시한다(평문 비저장·비로깅, SEC-BR-1) — 재설정/
    이메일변경 토큰과 동일한 at-rest 해싱 정책. 원문 토큰만 메일 링크로 발송한다."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SignupService:
    """사용자 자격증명 생성 및 회원가입 비즈니스 오케스트레이션 서비스 (US-A1)"""

    def __init__(self, credential_repo: CredentialRepository, email_client: EmailClientInterface, observability_hub = None):
        self._repo = credential_repo
        self._email_client = email_client
        self._observability_hub = observability_hub
        # OWASP 권장 Argon2id KDF 파라미터 (BR-A2) — password.py의 단일 팩토리 공유
        self._hasher = get_password_hasher()

    async def register(self, email: str, password: str, verification_link_base: str) -> str:
        """
        신규 회원가입을 처리합니다.
        비밀번호 정책 검증, Argon2id 해싱, PENDING 계정 영속화 및 이메일 인증 발송을 일괄 수행합니다.
        verify-all-then-commit 규칙에 따라, 모든 DB 쓰기는 flush만 수행되며 commit은 호출부의 트랜잭션 관리자가 담당합니다.
        """
        # 이메일 주소 값 객체 검증 (저장 전 trim+lowercase 정규화 — 로그인 조회와 동일 규칙)
        email_vo = EmailAddress(normalize_email(email))
        
        # 1. 비밀번호 정책 검증 (BR-A1)
        PasswordPolicy.evaluate(password)

        # 2. Argon2id 단방향 암호학적 해싱 (BR-A2)
        # 해싱을 중복 검사보다 먼저, 그리고 워커 스레드에서 수행한다:
        #  - 이메일 존재 여부에 따라 해싱 비용(~수십 ms)이 빠지는 타이밍 차이(계정 열거 오라클)를 줄이고,
        #  - CPU 바운드 KDF가 이벤트 루프를 차단하지 않게 한다.
        password_hash = await asyncio.to_thread(self._hasher.hash, password)

        # 3. 이메일 중복 검증
        existing_account = self._repo.get_by_email(email_vo.value)
        if existing_account:
            # 가입 충돌 신호 수집: SEC-3 PII 최소화 — 이메일 파생 식별자 대신 일반화된 'reason'만 발행한다
            # (shared/events/account-signals.schema.json 의 SignupAbuseSignal 규약).
            if self._observability_hub:
                self._observability_hub.emit_metric("SignupAbuseSignal", 1, {"reason": "duplicate_email"})
            raise DomainException("이미 등록된 이메일 주소입니다. 다른 이메일을 입력하거나 비밀번호 찾기를 이용해 주세요.")

        # 4. PENDING 상태로 계정 생성 (BR-A5)
        account = self._repo.create_account(email_vo.value, password_hash)

        # 5. 이메일 인증 링크용 보안 토큰 생성 (24시간 유효) (BR-A5)
        token = secrets.token_urlsafe(32)
        # naive UTC — matches SQLAlchemy DateTime(timezone=False) column storage.
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24)
        self._repo.create_verification_token(email_vo.value, _hash_token(token), expires_at)

        # 6. 이메일 발송 (SES 소프트 폴백 적용)
        # 이메일 발송 결과와 무관하게 DB 가입 트랜잭션은 롤백되지 않고 회원가입이 완료됩니다 (소프트 폴백).
        email_sent = await self._email_client.send_verification_email(
            email=email_vo.value,
            token=token,
            signup_link=verification_link_base
        )
        
        if not email_sent:
            logger.warning(f"Verification email sending failed for {email_vo.value}, but registration transaction continues.")

        # 7. 관측성 이벤트/감사 로깅 (SEC-BR-1 민감정보 제외)
        if self._observability_hub:
            # 공유 SSOT 이벤트 모델로 페이로드를 검증해 발행한다(docsuri_shared.events.AccountCreated).
            account_created = AccountCreated(
                userId=account.id, timestamp=datetime.now(UTC)
            )
            self._observability_hub.emit_log(account_created.model_dump(mode="json"))
            # 운영 메트릭(스키마 이벤트와 별개): 상태/메일 발송 결과는 차원(dimension)으로만 집계
            self._observability_hub.emit_metric("AccountCreated", 1, {"status": account.status, "email_sent": str(email_sent)})

        return account.id

    async def resend_verification(self, email: str, verification_link_base: str) -> bool:
        """PENDING 계정에 한해 인증 토큰을 재발급하고 인증 메일을 재발송한다 (가입 후 메일 미수신 복구 경로).

        계정 부존재/이미 활성·잠금/형식 오류는 조용히 no-op 처리한다 — 호출부가 항상 동일한
        일반 응답을 반환하게 하여 이메일 가입 여부 열거(account enumeration)를 막는다 (SEC).
        새 토큰 발급은 해당 이메일의 기존 토큰을 교체한다(create_verification_token가 선삭제)."""
        try:
            email_vo = EmailAddress(normalize_email(email))
        except DomainException:
            return False

        account = self._repo.get_by_email(email_vo.value)
        if not account or account.status != AccountStatus.PENDING.value:
            # 부존재 또는 이미 활성/잠금 — 재발송하지 않음 (열거 방지 위해 호출부는 동일 응답)
            return False

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24)
        self._repo.create_verification_token(email_vo.value, _hash_token(token), expires_at)

        email_sent = await self._email_client.send_verification_email(
            email=email_vo.value, token=token, signup_link=verification_link_base
        )
        if not email_sent:
            logger.warning(f"Resend verification email failed for {email_vo.value}; account remains PENDING.")
        return email_sent

    async def verify_email(self, token: str) -> bool:
        """이메일 인증 링크로 전달된 토큰을 검증하고 계정을 ACTIVE 상태로 활성화합니다."""
        if not token:
            raise DomainException("유효하지 않은 인증 토큰입니다.")

        token_record = self._repo.get_verification_token(_hash_token(token))
        if not token_record:
            raise DomainException("인증 토큰이 존재하지 않거나 만료되었습니다.")

        # 토큰 유효 기간 검증 (24시간)
        if datetime.now(UTC).replace(tzinfo=None) > token_record.expires_at:
            self._repo.delete_verification_token(_hash_token(token))
            raise DomainException("인증 링크 유효 기간(24시간)이 만료되었습니다. 다시 가입해 주십시오.")

        # 계정 ACTIVE 상태 업데이트
        account = self._repo.get_by_email(token_record.email)
        if not account:
            raise DomainException("활성화할 계정을 찾을 수 없습니다.")

        if account.status == AccountStatus.ACTIVE.value:
            # 이미 활성화된 상태인 경우 성공으로 간주
            self._repo.delete_verification_token(_hash_token(token))
            return True

        account.status = AccountStatus.ACTIVE.value
        self._repo.update_account(account)
        self._repo.delete_verification_token(_hash_token(token))

        logger.info(f"Account {account.id} successfully activated via email verification.")
        
        if self._observability_hub:
            self._observability_hub.emit_log({
                "event": "AccountActivated",
                "accountId": account.id
            })
            
        return True
