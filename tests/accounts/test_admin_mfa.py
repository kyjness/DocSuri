"""BR-A7: 관리자 역할 + TOTP MFA — 시딩·TOTP·세션 MFA 전파·역할-from-DB·인가 가드 검증."""

import uuid

import pyotp
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.guard import AuthorizationGuard, Decision
from backend.modules.accounts.models import (
    AccountStatus,
    DomainException,
    Principal,
    SessionRecord,
    UserRole,
)
from backend.modules.accounts.repository.credential import AccountTable, Base, CredentialRepository
from backend.modules.accounts.seed_admin import seed_admin
from backend.modules.accounts.services.auth import AuthenticationService
from backend.modules.accounts.services.session_manager import SessionManager
from backend.modules.accounts.services.totp import TotpService


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


class InMemorySessionRepo:
    """Redis 대신 dict 기반 인메모리 세션 저장소 (테스트용 — SessionRecord 그대로 보존)."""

    def __init__(self):
        self._store: dict[str, SessionRecord] = {}

    async def save(self, session: SessionRecord) -> None:
        self._store[session.handle] = session

    async def get(self, handle: str) -> SessionRecord | None:
        return self._store.get(handle)

    async def delete(self, handle: str) -> None:
        self._store.pop(handle, None)


class _FakeRecaptcha:
    async def verify_token(self, token, remote_ip=None):
        return True


def _admin_row(db_session, email="admin@docsuri.dev"):
    account = AccountTable(
        email=email,
        password_hash="x",
        status=AccountStatus.ACTIVE.value,
        role=UserRole.ADMIN.value,
    )
    db_session.add(account)
    db_session.flush()
    return account


# --- TotpService ---

def test_totp_enroll_then_verify_roundtrip(db_session):
    account = _admin_row(db_session)
    svc = TotpService(CredentialRepository(db_session))

    uri = svc.enroll(account)
    assert uri.startswith("otpauth://totp/")
    assert account.totp_secret  # 시크릿 저장됨
    assert svc.verify(account, pyotp.TOTP(account.totp_secret).now()) is True  # 올바른 코드 통과
    assert svc.verify(account, "000000") is False  # 잘못된 코드 거부


def test_totp_verify_unenrolled_is_false(db_session):
    account = AccountTable(email="u@docsuri.dev", password_hash="x", status=AccountStatus.ACTIVE.value)
    db_session.add(account)
    db_session.flush()
    assert TotpService(CredentialRepository(db_session)).verify(account, "123456") is False


# --- seed_admin idempotency ---

def test_seed_admin_is_idempotent_and_creates_admin(db_session):
    email, pw = "seed-admin@docsuri.dev", "SeedAdminPass123!"
    id1 = seed_admin(db_session, email, pw)
    id2 = seed_admin(db_session, email, pw)
    assert id1 == id2  # 중복 생성 없음
    rows = db_session.query(AccountTable).filter(AccountTable.email == email).all()
    assert len(rows) == 1
    assert rows[0].role == UserRole.ADMIN.value
    assert rows[0].status == AccountStatus.ACTIVE.value


def _seed_existing_user(db_session):
    existing = AccountTable(
        email="promote@docsuri.dev",
        password_hash="x",
        status=AccountStatus.PENDING.value,
        role=UserRole.USER.value,
    )
    db_session.add(existing)
    db_session.commit()


def test_seed_admin_refuses_existing_user_without_optin(db_session, monkeypatch):
    # 권한 상승 가드: 비-ADMIN 기존 계정은 명시 opt-in 없이는 승격하지 않는다(선점 가입 방어).
    monkeypatch.delenv("DOCSURI_ADMIN_PROMOTE_EXISTING", raising=False)
    _seed_existing_user(db_session)
    with pytest.raises(DomainException):
        seed_admin(db_session, "promote@docsuri.dev", "StrongPass123!")
    row = CredentialRepository(db_session).get_by_email("promote@docsuri.dev")
    assert row.role == UserRole.USER.value  # 승격되지 않음


def test_seed_admin_promotes_existing_user_with_optin(db_session, monkeypatch):
    monkeypatch.setenv("DOCSURI_ADMIN_PROMOTE_EXISTING", "true")
    _seed_existing_user(db_session)
    seed_admin(db_session, "promote@docsuri.dev", "StrongPass123!")
    row = CredentialRepository(db_session).get_by_email("promote@docsuri.dev")
    assert row.role == UserRole.ADMIN.value
    assert row.status == AccountStatus.ACTIVE.value


# --- guard admin authz ---

def _principal(role, mfa):
    return Principal(user_id=str(uuid.uuid4()), role=role, mfa_verified=mfa)


def test_authorize_admin_requires_admin_and_mfa():
    assert AuthorizationGuard.authorize_admin(_principal(UserRole.USER, True), mfa_verified=True) == Decision.DENY
    assert AuthorizationGuard.authorize_admin(_principal(UserRole.ADMIN, False), mfa_verified=False) == Decision.DENY
    assert AuthorizationGuard.authorize_admin(_principal(UserRole.ADMIN, True), mfa_verified=True) == Decision.ALLOW
    assert AuthorizationGuard.authorize_admin(None) == Decision.DENY


# --- session MFA threading (issue → verify → elevate) ---

@pytest.mark.asyncio
async def test_session_preserves_role_and_mfa_elevation():
    mgr = SessionManager(InMemorySessionRepo())
    admin = _principal(UserRole.ADMIN, False)
    rec = await mgr.issue(admin)

    p = await mgr.verify(rec.handle)
    assert p.role == UserRole.ADMIN  # 역할 보존
    assert p.mfa_verified is False  # 발급 시 MFA 미통과

    p2 = await mgr.elevate_mfa(rec.handle)
    assert p2.mfa_verified is True  # 승격됨
    assert (await mgr.verify(rec.handle)).mfa_verified is True  # 후속 verify에도 보존


# --- role-from-DB at login (USER 하드코딩 제거 검증) ---

@pytest.mark.asyncio
async def test_admin_login_issues_admin_session(db_session):
    email, pw = "login-admin@docsuri.dev", "AdminLogin123!"
    seed_admin(db_session, email, pw)
    mgr = SessionManager(InMemorySessionRepo())
    auth = AuthenticationService(CredentialRepository(db_session), mgr, _FakeRecaptcha())

    handle = await auth.authenticate(email, pw)
    principal = await mgr.verify(handle)
    assert principal.role == UserRole.ADMIN  # role-from-DB (하드코딩 USER였다면 실패)
    assert principal.mfa_verified is False  # 로그인만으론 MFA 미통과 — 2단계 승격 필요
