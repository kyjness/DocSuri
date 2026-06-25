import asyncio
import logging
from datetime import UTC, datetime

from argon2.exceptions import InvalidHash, VerificationError

from ..integrations.recaptcha import RecaptchaClient
from ..models import AccountStatus, DomainException, Principal, UserRole, normalize_email
from ..password import get_password_hasher
from ..repository.credential import CredentialRepository
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

# 봇 방지(CAPTCHA) 강제 시작 임계치 (BR-A4). 자동 계정 잠금(LOCKED)은 BR-A4에 의해 금지된다.
CAPTCHA_THRESHOLD = 10

class AuthenticationService:
    """로그인 자격증명 비교, 무차별 대입 방어(Exponential Backoff), reCAPTCHA 검증 및 해시 자동 업그레이드를 관리하는 서비스 (US-A2)"""

    def __init__(
        self,
        credential_repo: CredentialRepository,
        session_manager: SessionManager,
        recaptcha_client: RecaptchaClient,
        observability_hub = None,
    ):
        self._repo = credential_repo
        self._session_manager = session_manager
        self._recaptcha_client = recaptcha_client
        self._observability_hub = observability_hub
        # OWASP 권장 강도 해싱 파라미터 (m=65536, t=3, p=4) — password.py의 단일 팩토리 공유
        self._hasher = get_password_hasher()

    async def authenticate(self, email: str, password: str, recaptcha_token: str | None = None, remote_ip: str | None = None, reactivate: bool = False) -> str:
        """
        사용자 자격증명을 검증하고 보안 세션을 발급합니다.
        실패 횟수에 따라 지수 백오프 및 reCAPTCHA 검증을 강제합니다. (BR-A4)

        ``reactivate=True``는 유예 중 DEACTIVATED 계정의 **소유자 본인 복구(M1)** 경로다:
        자격증명이 검증된(타인 도달 불가) 뒤 미파기 삭제 레코드가 있으면 ACTIVE로 되살리고
        세션을 발급한다. 일반 로그인(기본 False)은 DEACTIVATED를 계속 차단한다.
        """
        # 트러스트 바운더리 정규화: 저장/조회 이메일을 동일 규칙(trim+lowercase)으로 맞춰
        # 대소문자 차이로 정상 자격증명이 거부되는 사일런트 401을 막는다 (normalize_email).
        email = normalize_email(email)
        account = self._repo.get_by_email(email)

        # 1. 봇 및 브루트포스 남용 방어: reCAPTCHA 검증 강제 (실패 횟수 >= 임계치) (BR-A4)
        if account and account.failure_count >= CAPTCHA_THRESHOLD:
            if not recaptcha_token:
                raise DomainException("보안 강화를 위해 봇 방지 인증(CAPTCHA)이 필요합니다.")
            
            captcha_ok = await self._recaptcha_client.verify_token(recaptcha_token, remote_ip)
            if not captcha_ok:
                raise DomainException("봇 방지(CAPTCHA) 검증에 실패했습니다. (Fail-Closed)")

        # 2. 자격증명 비교 및 타이밍 공격 방어 (Constant-Time Verification) (SEC-12)
        target_hash = account.password_hash if account else self._repo.dummy_hash
        
        is_verified = False
        needs_rehash = False
        
        try:
            # 해시 비교 연산 실행. Argon2 KDF(m=64MB)는 수십 ms를 소모하는 CPU 바운드 동기 작업이므로
            # asyncio.to_thread로 워커 스레드에 위임해 이벤트 루프 차단(동시 로그인 직렬화/DoS)을 방지한다.
            is_verified = await asyncio.to_thread(self._hasher.verify, target_hash, password)
            # 해시 강도 업그레이드 필요 여부 체크 (인코딩 파라미터 파싱만 하므로 KDF 미수행 → 동기 호출로 충분)
            needs_rehash = self._hasher.check_needs_rehash(target_hash)
        except (VerificationError, InvalidHash):
            # 자격증명 불일치 혹은 해시 깨짐
            is_verified = False
        
        # 실제 데이터베이스에 계정이 존재하지 않는 경우, 
        # 비교 연산 결과가 True 일지라도 강제로 False 처리하여 계정 부존재 상태를 숨깁니다 (타이밍 공격 차단)
        if not account:
            is_verified = False

        if not is_verified:
            # 3. 인증 실패 처리 및 브루트포스 exponential backoff 지연 (BR-A4)
            delay_seconds = 0
            if account:
                account.failure_count += 1
                account.last_failed_at = datetime.now(UTC)
                # BR-A4: 계정을 자동으로 잠그지 않는다 — 자동 LOCKED 전환은 타인의 정상 계정을 겨냥한
                # DoS를 유발하므로 금지(점진적 backoff + 10회차 CAPTCHA로 방어). LOCKED는 관리자 수동
                # 잠금 경로에서만 설정될 수 있다.
                self._repo.update_account(account)

                # 실패 횟수 3회차부터 지수 백오프 지연 계산
                # 3회: 1초, 4회: 2초, 5회: 4초, 6회: 8초 ... (최대 120초 상한 설정으로 무한 락 방어)
                if account.failure_count >= 3:
                    delay_seconds = min(2 ** (account.failure_count - 3), 120)

            # 관측성 신호 수집(SEC-12): 어떤 자격증명이 틀렸는지/이메일 파생값을 싣지 않고,
            # shared/events/account-signals.schema.json 의 AuthFailureSignal 규약대로 일반화된 'reason'만 발행한다.
            # (Python builtin hash()는 PYTHONHASHSEED로 프로세스마다 달라져 상관관계 분석이 불가능하고
            #  이메일 파생 식별자는 SEC-3 PII 최소화 원칙에 위배되므로 사용하지 않는다.)
            if self._observability_hub:
                self._observability_hub.emit_metric("AuthFailureSignal", 1, {"reason": "invalid_credentials"})
                self._observability_hub.emit_log({
                    "event": "AuthFailureSignal",
                    "reason": "invalid_credentials",
                })

            # 피드백 ③ 반영: 동기 time.sleep() 대신 asyncio.sleep()을 활용하여 
            # 동기 워커 스레드가 차단되는 Thread Exhaustion DoS 공격을 방어함 (비동기 리소스 양보)
            if delay_seconds > 0:
                logger.warning(f"Authentication failed. Applying non-blocking backoff delay of {delay_seconds} seconds.")
                await asyncio.sleep(delay_seconds)

            raise DomainException("이메일 또는 비밀번호가 올바르지 않습니다.")

        # 4. 자격증명 일치 성공 시 계정 상태 검증
        if account.status == AccountStatus.PENDING.value:
            raise DomainException("이메일 인증이 완료되지 않았습니다. 메일함의 인증 링크를 확인해 주세요. (BR-A5)")
        elif account.status == AccountStatus.LOCKED.value:
            # 자동 잠금은 BR-A4로 금지 — 이 분기는 관리자 수동 잠금 계정만 처리한다.
            raise DomainException("관리자에 의해 잠긴 계정입니다. 관리자에게 문의해 주세요.")
        elif account.status == AccountStatus.DEACTIVATED.value:
            # BR-A11: 소프트 삭제(탈퇴) 계정은 유예 동안 로그인 차단. 이 분기는 자격증명이 이미
            # 검증된 뒤라(타인 도달 불가) 본인에게 비활성 상태와 복구 경로를 안내해도 열거 위험이 없다.
            rec = self._repo.get_account_deletion(account.id)
            if reactivate and rec is not None and rec.state == AccountStatus.DEACTIVATED.value:
                # M1: 자격증명을 증명한 소유자가 명시적으로 복구를 요청 → ACTIVE 복원 + 삭제 레코드 제거.
                # 이후 4단계 통과로 떨어져 정상 세션을 발급한다(복구 즉시 로그인).
                account.status = AccountStatus.ACTIVE.value
                self._repo.update_account(account)
                self._repo.delete_account_deletion(account.id)
                logger.info({"event": "AccountReactivated", "accountId": account.id})
            else:
                raise DomainException("탈퇴 처리된 계정입니다. 복구를 원하시면 계정 복구 절차를 이용해 주세요.")

        # 5. 성공 시 실패 통계 초기화
        if account.failure_count > 0:
            account.failure_count = 0
            account.last_failed_at = None
            self._repo.update_account(account)

        # 6. 해시 자동 업그레이드 (Rehash) (SEC-12)
        if needs_rehash:
            try:
                # 해싱도 CPU 바운드 동기 작업이므로 워커 스레드에 위임 (이벤트 루프 비차단)
                new_hash = await asyncio.to_thread(self._hasher.hash, password)
                account.password_hash = new_hash
                self._repo.update_account(account)
                logger.info(f"Password hash upgraded to latest security standard for account: {account.id}")
            except Exception as rehash_err:
                logger.error(f"Failed to upgrade password hash silently: {str(rehash_err)}")

        # 7. 세션 생성
        # 권한 상승(ADMIN)은 이메일 접두사 같은 사용자 제어 입력으로 절대 부여하지 않는다.
        # 공개 가입(US-A1)에서 'admin@...' 주소를 등록하면 누구나 관리자가 되는 권한 상승 결함이 되므로,
        # ADMIN은 별도 관리자 프로비저닝 경로(시딩/콘솔)로만 부여한다.
        # 역할은 DB(account.role)가 단일 출처 — USER 하드코딩 제거(시딩된 ADMIN이 세션으로 전파되게).
        # 알 수 없는/누락 값은 최소 권한(USER)으로 안전 폴백. MFA는 로그인 시점엔 항상 미통과(False):
        # ADMIN 제어 평면은 별도 /auth/mfa/verify 2단계 TOTP 승격을 통과해야만 접근 가능하다 (BR-A7).
        try:
            account_role = UserRole(account.role)
        except (ValueError, TypeError):
            account_role = UserRole.USER
        principal = Principal(
            user_id=account.id,
            role=account_role,
            mfa_verified=False
        )
        
        session_info = await self._session_manager.issue(principal)
        
        if self._observability_hub:
            self._observability_hub.emit_log({
                "event": "LoginSuccess",
                "accountId": account.id,
                "role": principal.role
            })
            
        return session_info.handle
