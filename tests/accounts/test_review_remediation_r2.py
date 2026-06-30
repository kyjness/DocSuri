"""U3 리뷰 2차 리메디에이션 회귀 테스트 (S1/S2/S3/S5/S6 + N7 커버리지 갭).

- S1: 가입 이메일 열거-안전(중복 가입이 신규와 동일 응답·소유자 안내 메일·중복 미생성)
- S2: 유예 파기 독성 레코드 DLQ 격리(PURGE_FAILED) + 시도 카운트
- S3: 프로덕션 AccountDeleted 발행자 페일패스트
- S5: SES 소프트 폴백(발송 실패 시 False·트랜잭션 유지)
- S6: TOTP 시크릿 at-rest 암호화(라운드트립·레거시 평문·키 없음 Fail-Closed)
- N7: reCAPTCHA Fail-Closed 분기, signup.verify_email 만료/이미-활성 분기
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pyotp
import pytest
from cryptography.fernet import Fernet

import backend.modules.accounts.integrations.recaptcha as recaptcha_mod
from backend.modules.accounts.integrations.email import EmailClientInterface, SESEmailClient
from backend.modules.accounts.integrations.recaptcha import RecaptchaClient
from backend.modules.accounts.models import AccountStatus, DomainException
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.account_deletion import (
    MAX_PURGE_ATTEMPTS,
    AccountDeletionService,
    EventBridgeAccountDeletedPublisher,
    LoggingAccountDeletedPublisher,
    build_account_deleted_publisher,
)
from backend.modules.accounts.services.signup import SignupService, _hash_token
from backend.modules.accounts.services.totp import TotpService
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

_PW = "ValidPass123!@"


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _naive(days=0):
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(days=days)


def _active_account(repo, session, email="user@docsuri.org"):
    acct = repo.create_account(email, get_password_hasher().hash(_PW))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    session.commit()
    return acct


class _FakeEmail(EmailClientInterface):
    """발송 호출만 기록하는 가짜 이메일 클라이언트(모두 성공 반환)."""

    def __init__(self):
        self.verification: list[str] = []
        self.notices: list[str] = []

    async def send_verification_email(self, email, token, signup_link):
        self.verification.append(email)
        return True

    async def send_password_reset_email(self, email, token, reset_link):
        return True

    async def _send(self, to, subject, text, html):
        return True

    async def send_account_exists_notice_email(self, email):
        self.notices.append(email)
        return True


# ── S1: 가입 이메일 열거-안전 ──────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_signup_duplicate_is_enumeration_safe(session):
    repo = CredentialRepository(session)
    fake = _FakeEmail()
    svc = SignupService(repo, fake)
    email = "dup@docsuri.org"

    first_id = await svc.register(email, _PW, "https://x/verify")
    session.commit()
    assert fake.verification == [email]

    # 동일 이메일 + 강한 비번 재가입: 예외 없이 일반 결과 반환, 소유자 안내 메일, 중복 계정 미생성.
    second_id = await svc.register(email, _PW, "https://x/verify")
    session.commit()
    assert second_id != first_id
    assert fake.notices == [email]
    assert repo.get_by_email(email).id == first_id  # 원본 계정 불변·중복 없음
    assert fake.verification == [email]  # 두 번째엔 인증메일이 아니라 안내메일만


# ── S2: 유예 파기 독성 레코드 DLQ 격리 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_purge_job_quarantines_poison_record_to_dlq(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    await AccountDeletionService(repo, AsyncMock()).request_deletion(acct.id, _PW)
    session.commit()
    rec = repo.get_account_deletion(acct.id)
    rec.purge_after = _naive(days=-1)  # 이미 due
    session.commit()

    failing_pub = AsyncMock()
    failing_pub.publish.side_effect = RuntimeError("publish down")
    svc = AccountDeletionService(repo, None, publisher=failing_pub)

    for _ in range(MAX_PURGE_ATTEMPTS):
        assert await svc.purge_job(now=_naive()) == 0  # 매 회차 파기 0건

    rec2 = repo.get_account_deletion(acct.id)
    assert rec2.state == "PURGE_FAILED"  # DLQ 격리
    assert rec2.purge_attempts >= MAX_PURGE_ATTEMPTS
    assert repo.get_by_id(acct.id) is not None  # 격리됐을 뿐 계정은 파기되지 않음
    assert repo.get_due_deletions(_naive(days=1)) == []  # 이후 due에서 제외(무한 재시도 종료)


# ── S3: 프로덕션 발행자 페일패스트 ──────────────────────────────────────────────
def test_build_publisher_failfast_in_prod(monkeypatch):
    monkeypatch.delenv("ACCOUNT_EVENTS_BUS", raising=False)
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(RuntimeError):
        build_account_deleted_publisher()

    monkeypatch.setenv("ENV", "local")  # 로컬은 Logging 허용
    assert isinstance(build_account_deleted_publisher(), LoggingAccountDeletedPublisher)

    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("ACCOUNT_EVENTS_BUS", "docsuri-events")  # 버스 있으면 EventBridge
    assert isinstance(build_account_deleted_publisher(), EventBridgeAccountDeletedPublisher)


# ── S6: TOTP 시크릿 at-rest 암호화 ─────────────────────────────────────────────
def test_totp_secret_encrypted_at_rest(monkeypatch, session):
    monkeypatch.setenv("TOTP_SECRET_KEY", Fernet.generate_key().decode())
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = TotpService(repo)

    uri = svc.enroll(acct)
    session.commit()
    enc = acct.totp_secret
    assert enc.startswith("fernet:")  # 평문 아님

    raw = pyotp.parse_uri(uri).secret
    assert svc.verify(acct, pyotp.TOTP(raw).now()) is True  # 암호문 복호화 후 검증

    acct.totp_secret = raw  # 레거시 평문 행도 그대로 검증
    assert svc.verify(acct, pyotp.TOTP(raw).now()) is True

    acct.totp_secret = enc  # 암호문인데 키가 사라지면 Fail-Closed
    monkeypatch.delenv("TOTP_SECRET_KEY")
    assert svc.verify(acct, "000000") is False


# ── S5: SES 소프트 폴백 ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ses_soft_fallback_returns_false_on_error():
    client = SESEmailClient(sender_email="no-reply@docsuri.org")

    class _Boom:
        def send_email(self, **kwargs):
            raise RuntimeError("ses down")

    client._client = _Boom()  # _get_client 우회(이미 주입)
    assert await client.send_verification_email("u@docsuri.org", "tok", "https://x/verify") is False


# ── N7: reCAPTCHA Fail-Closed 분기 ─────────────────────────────────────────────
class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        if self._exc is not None:
            raise self._exc
        return self._resp


@pytest.mark.asyncio
async def test_recaptcha_fail_closed_branches(monkeypatch):
    assert await RecaptchaClient(secret_key="").verify_token("tok") is False  # 시크릿 없음
    assert await RecaptchaClient(secret_key="k").verify_token("") is False  # 토큰 없음

    monkeypatch.setattr(
        recaptcha_mod.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(exc=recaptcha_mod.httpx.TimeoutException("t")),
    )
    assert await RecaptchaClient(secret_key="k").verify_token("tok") is False  # 통신 오류

    monkeypatch.setattr(
        recaptcha_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp=_FakeResp(500, {}))
    )
    assert await RecaptchaClient(secret_key="k").verify_token("tok") is False  # status!=200

    monkeypatch.setattr(
        recaptcha_mod.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(resp=_FakeResp(200, {"success": True, "score": 0.1})),
    )
    assert await RecaptchaClient(secret_key="k").verify_token("tok") is False  # 점수 미달

    monkeypatch.setattr(
        recaptcha_mod.httpx, "AsyncClient",
        lambda *a, **k: _FakeClient(resp=_FakeResp(200, {"success": True, "score": 0.9})),
    )
    assert await RecaptchaClient(secret_key="k").verify_token("tok") is True  # 통과


# ── N7: signup.verify_email 만료/이미-활성 분기 ────────────────────────────────
@pytest.mark.asyncio
async def test_verify_email_expired_token_rejected_and_deleted(session):
    repo = CredentialRepository(session)
    svc = SignupService(repo, _FakeEmail())
    token = "expired-token"
    repo.create_verification_token("u@docsuri.org", _hash_token(token), _naive(days=-1))
    session.commit()

    with pytest.raises(DomainException):
        await svc.verify_email(token)
    assert repo.get_verification_token(_hash_token(token)) is None  # 만료 토큰 파기


@pytest.mark.asyncio
async def test_verify_email_already_active_is_idempotent(session):
    repo = CredentialRepository(session)
    svc = SignupService(repo, _FakeEmail())
    acct = _active_account(repo, session, email="active@docsuri.org")
    token = "active-token"
    repo.create_verification_token(acct.email, _hash_token(token), _naive(days=1))
    session.commit()

    assert await svc.verify_email(token) is True  # 이미 ACTIVE → 멱등 성공
    assert repo.get_verification_token(_hash_token(token)) is None  # 토큰 소비
