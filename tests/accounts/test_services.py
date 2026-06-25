import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.repository.credential import Base, CredentialRepository, VerificationTokenTable
from backend.modules.accounts.models import DomainException, AccountStatus
from backend.modules.accounts.services.signup import SignupService
from backend.modules.accounts.services.auth import AuthenticationService
from backend.modules.accounts.services.session_manager import SessionManager
from backend.modules.accounts.integrations.email import MockEmailClient
from backend.modules.accounts.integrations.recaptcha import RecaptchaClient

# 인메모리 SQLite DB를 활용하여 가볍고 독립적인 DB 세션 통합 환경 구성
@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionClass = sessionmaker(bind=engine)
    session = SessionClass()
    yield session
    session.close()

@pytest.fixture
def credential_repo(db_session):
    return CredentialRepository(db_session)

@pytest.fixture
def email_client():
    return MockEmailClient()

@pytest.fixture
def session_manager():
    # SessionManager 및 Redis Repository 모킹
    manager = MagicMock(spec=SessionManager)
    manager.issue = AsyncMock()
    return manager

@pytest.fixture
def recaptcha_client():
    client = MagicMock(spec=RecaptchaClient)
    client.verify_token = AsyncMock(return_value=True)
    return client

@pytest.fixture
def mock_observability():
    hub = MagicMock()
    hub.emit_metric = MagicMock()
    hub.emit_log = MagicMock()
    return hub


@pytest.mark.asyncio
async def test_signup_flow_success(credential_repo, email_client, mock_observability, db_session):
    """정상 가입 요청 시 PENDING 상태 등록 및 토큰 검증 후 ACTIVE 전환 검증 (US-A1, BR-A5)"""
    service = SignupService(
        credential_repo=credential_repo,
        email_client=email_client,
        observability_hub=mock_observability
    )

    # 1. 회원가입 신청
    email = "test@docsuri.dev"
    password = "SecurePass123!" # 복잡도 충족
    verification_link = "https://localhost/auth/verify-email"
    
    account_id = await service.register(email, password, verification_link)
    db_session.commit()
    
    assert account_id is not None

    # 가입 직후 PENDING 상태 확인
    account = credential_repo.get_by_id(account_id)
    assert account.status == AccountStatus.PENDING.value
    assert account.email == email
    assert account.failure_count == 0

    # 2. 이메일 토큰 조회 및 검증
    token_record = db_session.query(VerificationTokenTable).filter(VerificationTokenTable.email == email).first()
    assert token_record is not None
    
    # 토큰은 at-rest 해시로 저장되므로(SEC-BR-1) DB 값이 아닌 메일로 발송된 원문 토큰으로 검증한다.
    assert token_record.token != email_client.last_verification_token  # 저장값은 해시
    verified = await service.verify_email(email_client.last_verification_token)
    db_session.commit()
    
    assert verified is True
    
    # 활성화 상태 및 토큰 소멸 확인
    account = credential_repo.get_by_id(account_id)
    assert account.status == AccountStatus.ACTIVE.value
    
    token_record_after = db_session.query(VerificationTokenTable).filter(VerificationTokenTable.token == token_record.token).first()
    assert token_record_after is None


@pytest.mark.asyncio
async def test_signup_invalid_password(credential_repo, email_client):
    """비밀번호 복잡도 요건 미달 시 회원가입이 즉각 차단되는지 검증 (US-A1, BR-A1)"""
    service = SignupService(credential_repo=credential_repo, email_client=email_client)

    # 대문자 결여 및 10자 미만 비밀번호
    with pytest.raises(DomainException) as excinfo:
        await service.register("test@docsuri.dev", "weak123!", "http://localhost")
    assert "비밀번호는 최소 10자 이상이어야 합니다" in str(excinfo.value)


@pytest.mark.asyncio
async def test_authentication_backoff_on_failure(credential_repo, session_manager, recaptcha_client, mock_observability, db_session):
    """로그인 3회 이상 실패 시 지수 백오프 비동기 지연(asyncio.sleep)이 작동하는지 검증 (US-A2, BR-A4)"""
    auth_service = AuthenticationService(
        credential_repo=credential_repo,
        session_manager=session_manager,
        recaptcha_client=recaptcha_client,
        observability_hub=mock_observability
    )
    
    # 계정 사전 생성 및 ACTIVE 활성화
    email = "user@docsuri.dev"
    password = "ValidPassword123!"
    
    # 가입
    signup_svc = SignupService(credential_repo, MockEmailClient())
    account_id = await signup_svc.register(email, password, "http://localhost")
    account = credential_repo.get_by_id(account_id)
    account.status = AccountStatus.ACTIVE.value
    credential_repo.update_account(account)
    db_session.commit()

    # 1. 1~2회 로그인 실패 시 지연 없음
    with pytest.raises(DomainException):
        await auth_service.authenticate(email, "WrongPassword1!")
    assert credential_repo.get_by_id(account_id).failure_count == 1

    with pytest.raises(DomainException):
        await auth_service.authenticate(email, "WrongPassword1!")
    assert credential_repo.get_by_id(account_id).failure_count == 2

    # 2. 3회 로그인 실패 시 백오프 지연 적용 (2^(3-3) = 1초)
    # asyncio.sleep() 호출을 모킹하여 스레드가 차단되지 않음을 추적
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(DomainException):
            await auth_service.authenticate(email, "WrongPassword1!")
        
        # 3회 실패 시 2^0 = 1초 지연 호출 감지
        mock_sleep.assert_called_once_with(1)
        assert credential_repo.get_by_id(account_id).failure_count == 3


@pytest.mark.asyncio
async def test_authentication_recaptcha_enforcement(credential_repo, session_manager, recaptcha_client, db_session):
    """로그인 10회 실패 시 reCAPTCHA 검증 요구 및 Fail-Closed 작동 검증 (US-A2, BR-A4)"""
    auth_service = AuthenticationService(
        credential_repo=credential_repo,
        session_manager=session_manager,
        recaptcha_client=recaptcha_client,
        observability_hub=MagicMock()
    )
    
    email = "bot@docsuri.dev"
    password = "ValidPassword123!"
    
    signup_svc = SignupService(credential_repo, MockEmailClient())
    account_id = await signup_svc.register(email, password, "http://localhost")
    account = credential_repo.get_by_id(account_id)
    account.status = AccountStatus.ACTIVE.value
    # 실패 카운트 강제 10회 주입
    account.failure_count = 10
    credential_repo.update_account(account)
    db_session.commit()

    # 토큰 없이 로그인 시도 시 즉각 에러
    with pytest.raises(DomainException) as excinfo:
        await auth_service.authenticate(email, password)
    assert "CAPTCHA" in str(excinfo.value)

    # 토큰 검증 실패 모킹 시 거부 (Fail-Closed)
    recaptcha_client.verify_token.return_value = False
    with pytest.raises(DomainException) as excinfo:
        await auth_service.authenticate(email, password, recaptcha_token="bad_token")
    assert "CAPTCHA" in str(excinfo.value)

    # 토큰 검증 통과 시 로그인 허용
    recaptcha_client.verify_token.return_value = True
    session_manager.issue.return_value = MagicMock(handle="test_session_token")
    
    token = await auth_service.authenticate(email, password, recaptcha_token="good_token")
    assert token == "test_session_token"


@pytest.mark.asyncio
async def test_no_account_lockout_after_many_failures(credential_repo, session_manager, recaptcha_client, db_session):
    """BR-A4: 반복 로그인 실패가 계정을 LOCKED로 만들지 않는다(타인 정상 계정 DoS 방지).
    방어는 점진적 backoff + 10회차 CAPTCHA뿐 — 자동 잠금 없음."""
    auth_service = AuthenticationService(credential_repo, session_manager, recaptcha_client)
    email = "victim@docsuri.dev"
    password = "ValidPassword123!"
    signup_svc = SignupService(credential_repo, MockEmailClient())
    account_id = await signup_svc.register(email, password, "http://localhost")
    account = credential_repo.get_by_id(account_id)
    account.status = AccountStatus.ACTIVE.value
    credential_repo.update_account(account)
    db_session.commit()

    # 12회 연속 실패 (recaptcha_client fixture는 True 반환 → 10회차 이후 CAPTCHA 게이트 통과)
    with patch("asyncio.sleep", new_callable=AsyncMock):
        for _ in range(12):
            with pytest.raises(DomainException):
                await auth_service.authenticate(email, "WrongPassword1!", recaptcha_token="ok")

    account = credential_repo.get_by_id(account_id)
    assert account.failure_count >= 12
    # 핵심 단언: 자동 LOCKED 전환 없음 (BR-A4)
    assert account.status == AccountStatus.ACTIVE.value


@pytest.mark.asyncio
async def test_login_is_case_insensitive_on_email(credential_repo, session_manager, recaptcha_client, db_session):
    """대소문자/공백 차이가 있어도 정상 자격증명이면 로그인된다 (normalize_email — 사일런트 401 방지)."""
    signup_svc = SignupService(credential_repo, MockEmailClient())
    account_id = await signup_svc.register("mixed@docsuri.dev", "ValidPassword123!", "http://localhost")
    account = credential_repo.get_by_id(account_id)
    account.status = AccountStatus.ACTIVE.value
    credential_repo.update_account(account)
    db_session.commit()
    # 가입은 소문자로 저장됨을 먼저 확인
    assert account.email == "mixed@docsuri.dev"

    session_manager.issue.return_value = MagicMock(handle="sess_tok")
    auth_service = AuthenticationService(credential_repo, session_manager, recaptcha_client)
    # 로그인은 대문자+양끝 공백으로 시도 → 정규화되어 매칭
    token = await auth_service.authenticate("  Mixed@DocSuri.DEV  ", "ValidPassword123!")
    assert token == "sess_tok"


@pytest.mark.asyncio
async def test_resend_verification_pending_reissues_and_sends(credential_repo, db_session):
    """PENDING 계정 재발송: 정규화된 주소로 새 토큰을 발급(기존 교체)하고 새 베이스 링크로 발송한다."""
    email_client = AsyncMock()
    email_client.send_verification_email = AsyncMock(return_value=True)
    svc = SignupService(credential_repo, email_client)
    await svc.register("pending@docsuri.dev", "ValidPassword123!", "http://localhost/auth/verify-email")
    db_session.commit()

    ok = await svc.resend_verification("  Pending@DocSuri.dev ", "https://docsuri.org/bff/auth/verify-email")
    db_session.commit()
    assert ok is True
    sent = email_client.send_verification_email.await_args.kwargs
    assert sent["email"] == "pending@docsuri.dev"
    assert sent["signup_link"] == "https://docsuri.org/bff/auth/verify-email"
    tokens = (
        db_session.query(VerificationTokenTable)
        .filter(VerificationTokenTable.email == "pending@docsuri.dev")
        .all()
    )
    assert len(tokens) == 1  # 재발급이 기존 토큰을 교체 (중복 누적 없음)


@pytest.mark.asyncio
async def test_resend_verification_is_noop_for_unknown_or_active(credential_repo, db_session):
    """계정 열거 방지: 미가입/이미 활성 계정에는 재발송하지 않고 False를 반환한다(호출부는 동일 일반 응답)."""
    email_client = AsyncMock()
    email_client.send_verification_email = AsyncMock(return_value=True)
    svc = SignupService(credential_repo, email_client)

    assert await svc.resend_verification("nobody@docsuri.dev", "https://x/bff/auth/verify-email") is False

    aid = await svc.register("active@docsuri.dev", "ValidPassword123!", "http://localhost")
    acc = credential_repo.get_by_id(aid)
    acc.status = AccountStatus.ACTIVE.value
    credential_repo.update_account(acc)
    db_session.commit()
    email_client.send_verification_email.reset_mock()
    assert await svc.resend_verification("active@docsuri.dev", "https://x/bff/auth/verify-email") is False
    email_client.send_verification_email.assert_not_awaited()


def test_verification_link_base_prefers_public_app_url(monkeypatch):
    """프로덕션 인증 링크는 PUBLIC_APP_URL을 BFF 경유 경로로 구성하고, 미설정 시 요청 호스트로 폴백한다."""
    from backend.modules.accounts import controller

    monkeypatch.setenv("PUBLIC_APP_URL", "https://docsuri.org/")
    assert controller._verification_link_base(MagicMock()) == "https://docsuri.org/verify-email"

    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)
    req = MagicMock()
    req.base_url = "http://localhost:8000/"
    assert controller._verification_link_base(req) == "http://localhost:8000/auth/verify-email"


def test_email_factory_selects_resend_when_configured(monkeypatch):
    """EMAIL_PROVIDER=resend + RESEND_API_KEY → ResendEmailClient; 키 없으면 SES로 폴백."""
    from backend.modules.accounts.integrations import email as email_mod

    monkeypatch.setenv("EMAIL_PROVIDER", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    client = email_mod.get_email_client(env="production", sender_email="no-reply@docsuri.org")
    assert isinstance(client, email_mod.ResendEmailClient)

    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    fallback = email_mod.get_email_client(env="production", sender_email="no-reply@docsuri.org")
    assert isinstance(fallback, email_mod.SESEmailClient)


@pytest.mark.asyncio
async def test_resend_client_posts_verification(monkeypatch):
    """ResendEmailClient는 Resend API로 인증 링크를 POST하고 200에 True를 반환한다."""
    from backend.modules.accounts.integrations import email as email_mod

    captured = {}

    class _Resp:
        status_code = 200
        text = '{"id":"abc"}'

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            captured.update(url=url, headers=headers, json=json)
            return _Resp()

    monkeypatch.setattr(email_mod.httpx, "AsyncClient", _FakeClient)
    client = email_mod.ResendEmailClient(api_key="re_test_key", sender_email="no-reply@docsuri.org")
    ok = await client.send_verification_email("u@example.com", "tok123", "https://docsuri.org/verify-email")

    assert ok is True
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test_key"
    assert captured["json"]["to"] == ["u@example.com"]
    assert captured["json"]["from"] == "no-reply@docsuri.org"
    assert "tok123" in captured["json"]["html"]
    assert "https://docsuri.org/verify-email?token=tok123" in captured["json"]["text"]


@pytest.mark.asyncio
async def test_resend_client_soft_fails_on_error_status(monkeypatch):
    """Resend가 4xx를 반환하면 예외 없이 False(소프트 폴백)를 반환한다 — 가입 트랜잭션 유지."""
    from backend.modules.accounts.integrations import email as email_mod

    class _Resp:
        status_code = 422
        text = '{"message":"domain not verified"}'

    class _FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(email_mod.httpx, "AsyncClient", _FakeClient)
    client = email_mod.ResendEmailClient(api_key="re_test_key", sender_email="no-reply@docsuri.org")
    ok = await client.send_verification_email("u@example.com", "tok", "https://docsuri.org/verify-email")
    assert ok is False


def test_accounts_dtos_are_shared_ssot_not_forked():
    """SSOT 포크 제거 회귀 가드: accounts.schemas 는 docsuri_shared DTO를 재노출할 뿐 재정의하지 않는다."""
    from backend.modules.accounts import schemas
    from docsuri_shared import dtos as shared_dtos

    assert schemas.SignupRequest is shared_dtos.SignupRequest
    assert schemas.SignupResult is shared_dtos.SignupResult
    assert schemas.LoginRequest is shared_dtos.LoginRequest
    assert schemas.SessionInfo is shared_dtos.SessionInfo
