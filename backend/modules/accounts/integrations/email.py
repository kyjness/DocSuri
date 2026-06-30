import asyncio
import logging
import os
from abc import ABC, abstractmethod

import httpx

logger = logging.getLogger(__name__)


def _render_verification_email(link: str) -> tuple[str, str, str]:
    """(subject, text, html) for the account-verification email. Shared by every provider
    so the wording and link format can't drift between SES and Resend."""
    subject = "[DocSuri] 계정 활성화를 위한 이메일 인증 링크"
    body_text = (
        "안녕하세요. DocSuri 가입을 완료하려면 다음 링크를 24시간 이내에 클릭해 주세요.\n\n"
        f"{link}"
    )
    body_html = f"""
        <html>
            <body>
                <h3>DocSuri 가입을 환영합니다!</h3>
                <p>아래 링크를 클릭하여 계정 활성화를 완료해 주세요 (24시간 동안 유효합니다).</p>
                <p><a href="{link}">계정 활성화하기</a></p>
                <p>만약 링크 클릭이 안 된다면 다음 주소를 브라우저에 복사해 넣어주세요:</p>
                <p>{link}</p>
            </body>
        </html>
    """
    return subject, body_text, body_html


def _render_password_reset_email(link: str) -> tuple[str, str, str]:
    """(subject, text, html) for the forgot-password reset email (FR-26/BR-A8).
    Shared by every provider so wording/link format can't drift."""
    subject = "[DocSuri] 비밀번호 재설정 링크"
    body_text = (
        "비밀번호 재설정을 요청하셨습니다. 다음 링크를 30분 이내에 클릭해 새 비밀번호를 설정해 주세요.\n"
        "요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.\n\n"
        f"{link}"
    )
    body_html = f"""
        <html>
            <body>
                <h3>DocSuri 비밀번호 재설정</h3>
                <p>아래 링크를 클릭해 새 비밀번호를 설정해 주세요 (30분 동안 유효합니다).</p>
                <p><a href="{link}">비밀번호 재설정하기</a></p>
                <p>요청하지 않으셨다면 이 메일을 무시하셔도 됩니다.</p>
                <p>링크가 동작하지 않으면 다음 주소를 브라우저에 복사해 넣어주세요:</p>
                <p>{link}</p>
            </body>
        </html>
    """
    return subject, body_text, body_html


def _render_email_change_verification(link: str) -> tuple[str, str, str]:
    """(subject, text, html) — 새 이메일로 보내는 변경 확인 링크 (FR-28/BR-A10)."""
    subject = "[DocSuri] 새 이메일 주소 확인 링크"
    body_text = (
        "DocSuri 계정의 이메일 주소를 이 주소로 변경하려면 다음 링크를 30분 이내에 클릭해 주세요.\n"
        "본인이 요청하지 않았다면 이 메일을 무시하셔도 됩니다.\n\n"
        f"{link}"
    )
    body_html = f"""
        <html>
            <body>
                <h3>DocSuri 이메일 변경 확인</h3>
                <p>이 주소로 계정 이메일을 변경하려면 아래 링크를 클릭해 주세요 (30분 동안 유효합니다).</p>
                <p><a href="{link}">이메일 변경 확인하기</a></p>
                <p>본인이 요청하지 않았다면 이 메일을 무시하셔도 됩니다.</p>
                <p>{link}</p>
            </body>
        </html>
    """
    return subject, body_text, body_html


def _esc(value: str) -> str:
    """수신자 파생 값을 HTML 본문에 넣기 전 이스케이프(방어적, XSS — 감사 L3).
    EmailAddress 정규식이 이미 <>"'를 막지만, 본문 보간값은 항상 이스케이프한다."""
    import html as _html

    return _html.escape(value, quote=True)


def _render_email_change_notice(new_email: str, revoke_link: str = "") -> tuple[str, str, str]:
    """(subject, text, html) — 현재(기존) 이메일로 보내는 변경 시도 알림 (M2 — 계정 탈취 탐지).
    revoke_link가 있으면 '변경 취소' 링크를 포함해, 세션 없이도 현 주소 소유자가 변경을 차단할 수
    있게 한다(감사 H5)."""
    subject = "[DocSuri] 계정 이메일 변경이 요청되었습니다"
    revoke_text = f"\n본인이 요청하지 않았다면 다음 링크로 즉시 취소하세요:\n{revoke_link}\n" if revoke_link else ""
    body_text = (
        f"회원님 계정의 이메일 주소를 '{new_email}'(으)로 변경하려는 요청이 접수되었습니다.\n"
        "본인이 요청한 것이 맞다면 새 주소로 보낸 확인 메일의 링크를 클릭해 주세요.\n"
        "본인이 요청하지 않았다면 즉시 비밀번호를 변경하고 고객센터에 알려주세요.\n"
        f"{revoke_text}"
    )
    safe_email = _esc(new_email)
    revoke_html = (
        f'<p><b>본인이 요청하지 않았다면</b> 아래 링크로 즉시 변경을 취소하세요:</p>'
        f'<p><a href="{revoke_link}">이메일 변경 취소하기</a></p>'
        if revoke_link
        else ""
    )
    body_html = f"""
        <html>
            <body>
                <h3>계정 이메일 변경 요청 알림</h3>
                <p>회원님 계정의 이메일을 <b>{safe_email}</b>(으)로 변경하려는 요청이 접수되었습니다.</p>
                <p>본인이 요청했다면 새 주소로 보낸 확인 메일의 링크를 클릭해 주세요.</p>
                {revoke_html}
                <p>본인이 요청하지 않았다면 즉시 비밀번호를 변경하고 고객센터에 알려주세요.</p>
            </body>
        </html>
    """
    return subject, body_text, body_html


def _render_account_exists_notice() -> tuple[str, str, str]:
    """(subject, text, html) — 이미 가입된 주소로 가입이 재시도될 때 기존 소유자에게 보내는 안내
    (S1/SEC-BR-2 — 계정 열거 방지). 가입 응답은 신규와 동일하게 일반화하고, '계정이 이미 있다'는
    사실은 오직 등록된 본인 메일함으로만 알린다. 링크는 PUBLIC_APP_URL 설정 시에만 포함한다."""
    app = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    login_text = (
        f"\n로그인: {app}/login\n비밀번호 재설정: {app}/reset-password\n" if app else ""
    )
    login_html = (
        f'<p><a href="{app}/login">로그인</a> · '
        f'<a href="{app}/reset-password">비밀번호 재설정</a></p>'
        if app
        else ""
    )
    subject = "[DocSuri] 이미 가입된 계정이 있습니다"
    body_text = (
        "회원님의 이메일 주소로 이미 DocSuri 계정이 등록되어 있습니다.\n"
        "새로 가입하실 필요 없이 로그인하시거나, 비밀번호가 기억나지 않으면 비밀번호 재설정을 이용해 주세요.\n"
        "본인이 가입을 시도하지 않으셨다면 이 메일을 무시하셔도 됩니다.\n"
        f"{login_text}"
    )
    body_html = f"""
        <html>
            <body>
                <h3>이미 가입된 계정이 있습니다</h3>
                <p>회원님의 이메일로 이미 DocSuri 계정이 등록되어 있습니다. 새로 가입하실 필요 없이
                   로그인하시거나, 비밀번호가 기억나지 않으면 비밀번호 재설정을 이용해 주세요.</p>
                {login_html}
                <p>본인이 가입을 시도하지 않으셨다면 이 메일을 무시하셔도 됩니다.</p>
            </body>
        </html>
    """
    return subject, body_text, body_html


def _emit_email_failure(observability_hub, e: Exception, provider: str) -> None:
    """소프트 폴백 실패 신호(EmailDeliveryFailureSignal) 발행 — 공통 헬퍼."""
    if not observability_hub:
        return
    try:
        # 진단용: error_type 차원 분해.
        observability_hub.emit_metric("EmailDeliveryFailureSignal", 1, {"error_type": type(e).__name__})
        # 알람용: 무차원 합계. CloudWatch 메트릭 알람은 SEARCH(차원 와일드카드)를 지원하지 않으므로,
        # 모든 error_type을 단일 알람으로 잡으려면 차원 없는 스트림이 필요하다(감사 인시던트 2026-06-25).
        observability_hub.emit_metric("EmailDeliveryFailureSignal", 1, {})
        observability_hub.emit_log({
            "event": "EmailDeliveryFailureSignal",
            "error_type": type(e).__name__,
            "provider": provider,
            "message": "Email dispatch failed. Account remains PENDING.",
        })
    except Exception as trace_err:
        logger.critical(f"ObservabilityHub 수집기 마저 장애 상태 발생: {str(trace_err)}")


class EmailClientInterface(ABC):
    @abstractmethod
    async def send_verification_email(self, email: str, token: str, signup_link: str) -> bool:
        """이메일 인증 링크를 사용자에게 발송합니다."""
        pass

    @abstractmethod
    async def send_password_reset_email(self, email: str, token: str, reset_link: str) -> bool:
        """비밀번호 재설정 링크를 사용자에게 발송합니다 (FR-26/BR-A8)."""
        pass

    @abstractmethod
    async def _send(self, to: str, subject: str, text: str, html: str) -> bool:
        """일반 발송 프리미티브(프로바이더별 1회 구현). 신규 메일 종류는 렌더 → _send로 위임한다.
        ponytail: 기존 send_verification/reset는 자체 구현 유지(작동 중 코드 미변경)."""
        pass

    async def send_email_change_verification_email(self, email: str, token: str, confirm_link: str) -> bool:
        """새 이메일로 변경 확인 링크를 발송한다 (FR-28/BR-A10)."""
        link = f"{confirm_link}?token={token}"
        subject, text, html = _render_email_change_verification(link)
        return await self._send(email, subject, text, html)

    async def send_email_change_notice_email(self, email: str, new_email: str, revoke_link: str = "") -> bool:
        """현재(기존) 이메일로 변경 시도 알림 + 취소(revoke) 링크를 발송한다 (M2/H5 — 계정 탈취 방어)."""
        subject, text, html = _render_email_change_notice(new_email, revoke_link)
        return await self._send(email, subject, text, html)

    async def send_account_exists_notice_email(self, email: str) -> bool:
        """이미 가입된 주소로 가입이 재시도될 때 기존 소유자에게 안내를 보낸다 (S1/SEC-BR-2 — 가입
        응답을 신규와 동일하게 일반화하면서도 본인에게는 계정 존재를 알린다)."""
        subject, text, html = _render_account_exists_notice()
        return await self._send(email, subject, text, html)


class MockEmailClient(EmailClientInterface):
    """로컬 테스트를 위해 실제 이메일을 발송하지 않고 터미널 콘솔에 출력하는 Mock 이메일 클라이언트"""

    # 인증 토큰이 at-rest 해시로 저장된 뒤로 DB에서 원문을 복구할 수 없으므로, 로컬/테스트에서
    # 원문 토큰을 여기 보관해 전체 가입→검증 플로우를 검증할 수 있게 한다(SEC-BR-1 보완).
    last_verification_token: str | None = None
    last_password_reset_token: str | None = None

    async def send_verification_email(self, email: str, token: str, signup_link: str) -> bool:
        self.last_verification_token = token
        logger.info("================ [MOCK EMAIL DELIVERY] ================")
        logger.info("To: [redacted]")
        logger.info("Subject: DocSuri 이메일 인증 안내")
        logger.info("Verification token captured in MockEmailClient.last_verification_token.")
        logger.info("Verification link omitted from logs because it contains a bearer token.")
        logger.info("=========================================================")
        return True

    async def send_password_reset_email(self, email: str, token: str, reset_link: str) -> bool:
        self.last_password_reset_token = token
        logger.info("================ [MOCK PASSWORD RESET EMAIL] ================")
        logger.info("To: [redacted]")
        logger.info("Reset token captured in MockEmailClient.last_password_reset_token.")
        logger.info("Reset link omitted from logs because it contains a bearer token.")
        logger.info("=============================================================")
        return True

    async def _send(self, to: str, subject: str, text: str, html: str) -> bool:
        logger.info("================ [MOCK EMAIL DELIVERY] ================")
        logger.info("To: [redacted]")
        logger.info(f"Subject: {subject}")
        logger.info("Body omitted from logs because transactional email can contain recipient secrets.")
        logger.info("=========================================================")
        return True


class SESEmailClient(EmailClientInterface):
    """boto3를 활용해 Amazon SES를 통해 이메일을 전송하는 프로덕션 이메일 클라이언트"""

    def __init__(self, sender_email: str, region_name: str = "ap-northeast-2", observability_hub=None):
        self._sender_email = sender_email
        self._region_name = region_name
        self._observability_hub = observability_hub
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            from botocore.config import Config

            # S5: NFR §2.1 SES 3.0s 예산. 기본 botocore 타임아웃(~60s)이면 행이 걸린 SES 엔드포인트가
            # to_thread 워커를 수십 초 잡아 가용성을 해친다. 연결/읽기를 3s로 죄고 재시도는 끈다
            # (소프트 폴백이 상위에서 가입 트랜잭션을 보존하므로 boto3 자체 재시도는 불필요).
            # 컨테이너에 투과 주입된 IAM Role 또는 기본 자격 증명 사용.
            self._client = boto3.client(
                "ses",
                region_name=self._region_name,
                config=Config(connect_timeout=3, read_timeout=3, retries={"max_attempts": 0}),
            )
        return self._client

    async def send_verification_email(self, email: str, token: str, signup_link: str) -> bool:
        """Amazon SES로 인증 메일 전송. 실패 시 소프트 폴백(가입 트랜잭션 유지)."""
        link = f"{signup_link}?token={token}"
        subject, body_text, body_html = _render_verification_email(link)
        try:
            ses = self._get_client()
            # boto3 SES 호출은 동기 블로킹 I/O → asyncio.to_thread로 이벤트 루프 비차단
            response = await asyncio.to_thread(
                lambda: ses.send_email(
                    Source=self._sender_email,
                    Destination={"ToAddresses": [email]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    },
                )
            )
            logger.info("Verification email sent successfully via SES. MessageId: %s", response.get("MessageId"))
            return True
        except Exception as e:
            logger.error(f"Amazon SES 이메일 발송 실패 (Soft-Fallback 활성): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="ses")
            return False

    async def send_password_reset_email(self, email: str, token: str, reset_link: str) -> bool:
        """Amazon SES로 비밀번호 재설정 메일 전송. 실패 시 소프트 폴백."""
        link = f"{reset_link}?token={token}"
        subject, body_text, body_html = _render_password_reset_email(link)
        try:
            ses = self._get_client()
            response = await asyncio.to_thread(
                lambda: ses.send_email(
                    Source=self._sender_email,
                    Destination={"ToAddresses": [email]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": body_text, "Charset": "UTF-8"},
                            "Html": {"Data": body_html, "Charset": "UTF-8"},
                        },
                    },
                )
            )
            logger.info("Password reset email sent via SES. MessageId: %s", response.get("MessageId"))
            return True
        except Exception as e:
            logger.error(f"Amazon SES 재설정 메일 발송 실패 (Soft-Fallback): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="ses")
            return False

    async def _send(self, to: str, subject: str, text: str, html: str) -> bool:
        try:
            ses = self._get_client()
            response = await asyncio.to_thread(
                lambda: ses.send_email(
                    Source=self._sender_email,
                    Destination={"ToAddresses": [to]},
                    Message={
                        "Subject": {"Data": subject, "Charset": "UTF-8"},
                        "Body": {
                            "Text": {"Data": text, "Charset": "UTF-8"},
                            "Html": {"Data": html, "Charset": "UTF-8"},
                        },
                    },
                )
            )
            logger.info("Email sent via SES. MessageId: %s", response.get("MessageId"))
            return True
        except Exception as e:
            logger.error(f"Amazon SES 발송 실패 (Soft-Fallback): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="ses")
            return False


class ResendEmailClient(EmailClientInterface):
    """Resend (https://resend.com) 트랜잭셔널 이메일 클라이언트.

    SES와 달리 '프로덕션 액세스' 심사 게이트가 없다 — 발신 도메인(docsuri.org)을 Resend에서 DNS로
    검증하면 즉시 임의 수신자에게 발송 가능. HTTPS API에 API 키(Bearer)로 발송하며, httpx는 이미
    의존성(reCAPTCHA 클라이언트)이라 새 패키지가 필요 없다. 실패 시 소프트 폴백."""

    _ENDPOINT = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender_email: str, observability_hub=None):
        self._api_key = api_key
        self._sender_email = sender_email
        self._observability_hub = observability_hub

    async def send_verification_email(self, email: str, token: str, signup_link: str) -> bool:
        link = f"{signup_link}?token={token}"
        subject, body_text, body_html = _render_verification_email(link)
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:  # S5: NFR §2.1 메일 발송 예산
                resp = await client.post(
                    self._ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": self._sender_email,
                        "to": [email],
                        "subject": subject,
                        "html": body_html,
                        "text": body_text,
                    },
                )
            if resp.status_code in (200, 201):
                logger.info("Verification email sent via Resend.")
                return True
            # 4xx/5xx — 소프트 폴백(가입 트랜잭션 유지) + 실패 신호
            logger.error("Resend 이메일 발송 실패 status=%s", resp.status_code)
            _emit_email_failure(self._observability_hub, RuntimeError(f"resend_status_{resp.status_code}"), provider="resend")
            return False
        except Exception as e:
            logger.error(f"Resend 이메일 발송 예외 (Soft-Fallback 활성): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="resend")
            return False

    async def send_password_reset_email(self, email: str, token: str, reset_link: str) -> bool:
        link = f"{reset_link}?token={token}"
        subject, body_text, body_html = _render_password_reset_email(link)
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:  # S5: NFR §2.1 메일 발송 예산
                resp = await client.post(
                    self._ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": self._sender_email,
                        "to": [email],
                        "subject": subject,
                        "html": body_html,
                        "text": body_text,
                    },
                )
            if resp.status_code in (200, 201):
                logger.info("Password reset email sent via Resend.")
                return True
            logger.error("Resend 재설정 메일 발송 실패 status=%s", resp.status_code)
            _emit_email_failure(self._observability_hub, RuntimeError(f"resend_status_{resp.status_code}"), provider="resend")
            return False
        except Exception as e:
            logger.error(f"Resend 재설정 메일 발송 예외 (Soft-Fallback): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="resend")
            return False

    async def _send(self, to: str, subject: str, text: str, html: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:  # S5: NFR §2.1 메일 발송 예산
                resp = await client.post(
                    self._ENDPOINT,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "from": self._sender_email,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                        "text": text,
                    },
                )
            if resp.status_code in (200, 201):
                logger.info("Email sent via Resend.")
                return True
            logger.error("Resend 발송 실패 status=%s", resp.status_code)
            _emit_email_failure(self._observability_hub, RuntimeError(f"resend_status_{resp.status_code}"), provider="resend")
            return False
        except Exception as e:
            logger.error(f"Resend 발송 예외 (Soft-Fallback): {str(e)}")
            _emit_email_failure(self._observability_hub, e, provider="resend")
            return False


def get_email_client(
    env: str = "production",
    sender_email: str = "",
    region: str = "ap-northeast-2",
    observability_hub=None,
) -> EmailClientInterface:
    """환경변수/스위치에 따라 이메일 클라이언트를 반환한다.

    우선순위: ``SES_MOCK=true`` 또는 ``env=local`` → Mock; ``EMAIL_PROVIDER=resend``(+``RESEND_API_KEY``)
    → Resend; 그 외 → SES. Resend로 지정됐는데 키가 없으면 크게 경보하고 SES로 폴백한다."""
    is_mock = os.getenv("SES_MOCK", "false").lower() == "true" or env.lower() == "local"
    if is_mock:
        logger.info("Using MockEmailClient for account verification link.")
        return MockEmailClient()

    provider = os.getenv("EMAIL_PROVIDER", "ses").strip().lower()
    if provider == "resend":
        api_key = os.getenv("RESEND_API_KEY", "").strip()
        if api_key:
            logger.info("Using Resend email client for account verification link.")
            return ResendEmailClient(api_key=api_key, sender_email=sender_email, observability_hub=observability_hub)
        logger.error("EMAIL_PROVIDER=resend 이지만 RESEND_API_KEY 미설정 — SES로 폴백합니다.")

    logger.info("Using production SESEmailClient for account verification link.")
    return SESEmailClient(sender_email=sender_email, region_name=region, observability_hub=observability_hub)
