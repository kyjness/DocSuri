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


def _emit_email_failure(observability_hub, e: Exception, provider: str) -> None:
    """소프트 폴백 실패 신호(EmailDeliveryFailureSignal) 발행 — 공통 헬퍼."""
    if not observability_hub:
        return
    try:
        observability_hub.emit_metric("EmailDeliveryFailureSignal", 1, {"error_type": type(e).__name__})
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


class MockEmailClient(EmailClientInterface):
    """로컬 테스트를 위해 실제 이메일을 발송하지 않고 터미널 콘솔에 출력하는 Mock 이메일 클라이언트"""

    async def send_verification_email(self, email: str, token: str, signup_link: str) -> bool:
        logger.info("================ [MOCK EMAIL DELIVERY] ================")
        logger.info(f"To: {email}")
        logger.info("Subject: DocSuri 이메일 인증 안내")
        logger.info(f"Verification Token: {token}")
        logger.info(f"Verification Link: {signup_link}?token={token}")
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
            # 컨테이너에 투과 주입된 IAM Role 또는 기본 자격 증명 사용
            self._client = boto3.client("ses", region_name=self._region_name)
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
            logger.info(
                f"Verification email sent successfully via SES to {email}. "
                f"MessageId: {response.get('MessageId')}"
            )
            return True
        except Exception as e:
            logger.error(f"Amazon SES 이메일 발송 실패 (Soft-Fallback 활성): {str(e)}")
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
            async with httpx.AsyncClient(timeout=10.0) as client:
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
                logger.info(f"Verification email sent via Resend to {email}.")
                return True
            # 4xx/5xx — 소프트 폴백(가입 트랜잭션 유지) + 실패 신호
            logger.error(f"Resend 이메일 발송 실패 status={resp.status_code} body={resp.text[:200]}")
            _emit_email_failure(self._observability_hub, RuntimeError(f"resend_status_{resp.status_code}"), provider="resend")
            return False
        except Exception as e:
            logger.error(f"Resend 이메일 발송 예외 (Soft-Fallback 활성): {str(e)}")
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
