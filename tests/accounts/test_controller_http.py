"""U3 — accounts controller HTTP integration (TestClient) — QA 2026-07 P2 #6.

기존 accounts 테스트는 전부 서비스 레벨이라 HTTP 레이어 계약이 무단언 상태였다. U4 library의
HTTP 테스트 패턴(tests/library/conftest.py + test_controller.py)을 미러링한다: bare FastAPI 앱에
accounts 라우터만 올리고 DI 시임을 오버라이드 — 인메모리 SQLite(실 레포지토리), 가짜
SessionManager(Redis 불요), 테스트 전용 InProcessWindowLimiter, Google 왕복은 httpx.MockTransport.

커버 항목 (전부 엔드포인트 레벨):
1. 로그인/세션 쿠키 플래그 (secure / httpOnly / sameSite=lax, SEC-12) + 쿠키 라운드트립,
2. 가입 레이트리밋 429 와이어링 (SEC-11 — per-email·per-IP 키 분리, X-Forwarded-For 첫 홉),
3. Google OIDC 콜백 실패 복구 경로 (FR-27 — 401·no 500·세션 미발급·state 단일 사용),
4. 재설정 토큰 30분 만료 브랜치 (FR-26/BR-A8 — 만료 토큰 400 거부, 유효 토큰 성공 대조).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.middleware.rate_limit import InProcessWindowLimiter
from backend.modules.accounts import controller
from backend.modules.accounts.integrations import oidc as oidc_module
from backend.modules.accounts.models import (
    AccountStatus,
    SessionExpiredException,
    normalize_email,
)
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.password_reset import RESET_TOKEN_TTL, _hash_token

EMAIL = "user@docsuri.org"
PASSWORD = "ValidPassword123!"
SESSION_MAX_AGE = 30 * 24 * 60 * 60  # 30일 절대 만료 (BR-A3)


class FakeSessionManager:
    """SessionManager 대역 — Redis 없이 issue/verify/invalidate를 인메모리로 재현한다.

    컨트롤러가 사용하는 표면(issue→.handle, verify, invalidate, invalidate_all_for_user)만 구현.
    """

    def __init__(self):
        self.sessions: dict[str, object] = {}  # handle -> Principal
        self.invalidated_users: list[str] = []

    async def issue(self, principal):
        handle = f"sess-{len(self.sessions) + 1:04d}"
        self.sessions[handle] = principal
        return SimpleNamespace(handle=handle)

    async def verify(self, session_token: str):
        principal = self.sessions.get(session_token)
        if principal is None:
            raise SessionExpiredException("세션이 유효하지 않거나 만료되었습니다.")
        return principal

    async def invalidate(self, session_token: str) -> None:
        self.sessions.pop(session_token, None)

    async def invalidate_all_for_user(self, user_id: str) -> None:
        self.invalidated_users.append(user_id)
        self.sessions = {h: p for h, p in self.sessions.items() if p.user_id != user_id}


@pytest.fixture
def db_session():
    # TestClient는 앱을 별도 스레드에서 구동한다. 기본 풀의 sqlite :memory:는 스레드마다 새(빈)
    # DB 커넥션을 주므로(no such table), 단일 커넥션 공유(StaticPool + check_same_thread=False)로 고정.
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture
def make_app(db_session, monkeypatch):
    """accounts 라우터만 올린 bare app + DI 시임 오버라이드 (U4 library conftest 패턴 미러).

    반환: SimpleNamespace(app, session_manager, state_store, repo).
    """
    monkeypatch.setenv("ENV", "local")  # 이메일 클라이언트 = MockEmailClient (실 SES/Resend 금지)
    monkeypatch.delenv("PUBLIC_APP_URL", raising=False)  # 소셜 리다이렉트 폴백 "/" 고정
    monkeypatch.delenv("REDIS_HOST", raising=False)

    def _build():
        app = FastAPI()
        app.include_router(controller.router)
        session_manager = FakeSessionManager()
        state_store = controller._InProcessOidcStateStore()
        app.dependency_overrides[controller.get_db_session] = lambda: db_session
        app.dependency_overrides[controller.get_session_manager] = lambda: session_manager
        app.dependency_overrides[controller.get_oidc_state_store] = lambda: state_store
        # 테스트 전용 fresh limiter — lru_cache된 프로세스 전역 공유 limiter 오염 방지.
        limiter = InProcessWindowLimiter()
        monkeypatch.setattr(controller, "_get_email_rate_limiter", lambda: limiter)
        return SimpleNamespace(
            app=app,
            session_manager=session_manager,
            state_store=state_store,
            repo=CredentialRepository(db_session),
        )

    return _build


def _client(app) -> TestClient:
    # Secure 쿠키는 http 스킴 쿠키 자에 저장/전송되지 않으므로 https base_url이 필수다.
    return TestClient(app, base_url="https://testserver")


def _active_account(db_session, email: str = EMAIL, password: str = PASSWORD):
    repo = CredentialRepository(db_session)
    account = repo.create_account(email, get_password_hasher().hash(password))
    account.status = AccountStatus.ACTIVE.value
    repo.update_account(account)
    db_session.commit()
    return account


def _session_cookies(response) -> list[str]:
    return [c for c in response.headers.get_list("set-cookie") if c.startswith("session_id=")]


# ── 1. 로그인/세션 쿠키 플래그 (SEC-12) ─────────────────────────────────────────


def test_login_sets_secure_httponly_lax_session_cookie(make_app, db_session):
    """POST /auth/login 성공 시 세션 쿠키가 httpOnly·Secure·SameSite=lax·30일 Max-Age로 발급된다."""
    _active_account(db_session)
    ctx = make_app()
    client = _client(ctx.app)

    r = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert r.status_code == 200
    assert r.json()["status"] == "success"
    cookies = _session_cookies(r)
    assert len(cookies) == 1
    cookie = cookies[0].lower()
    assert "httponly" in cookie  # SEC-12: JS 접근 차단
    assert "secure" in cookie  # HTTPS 전용
    assert "samesite=lax" in cookie  # CSRF 완화
    assert f"max-age={SESSION_MAX_AGE}" in cookie  # 30일 절대 만료 (BR-A3)
    # 쿠키의 핸들이 실제 세션 저장소에 존재한다 (half-issued 아님)
    handle = cookies[0].split(";")[0].split("=", 1)[1]
    assert handle in ctx.session_manager.sessions
    # 세션 토큰은 쿠키 전송 전용 — 응답 바디에 노출 금지 (SEC-12)
    assert handle not in r.text


def test_login_failure_sets_no_session_cookie(make_app, db_session):
    """잘못된 자격증명 → 일반화된 401, 세션 쿠키 미발급·세션 미생성 (SEC-BR-2)."""
    _active_account(db_session)
    ctx = make_app()
    client = _client(ctx.app)

    r = client.post("/auth/login", json={"email": EMAIL, "password": "WrongPassword1!"})

    assert r.status_code == 401
    assert _session_cookies(r) == []
    assert ctx.session_manager.sessions == {}


def test_session_endpoint_round_trips_login_cookie(make_app, db_session):
    """GET /auth/session — 쿠키 없으면 401, 로그인 쿠키 라운드트립 시 200 + userId (US-A2/BR-A3)."""
    account = _active_account(db_session)
    ctx = make_app()
    client = _client(ctx.app)

    assert client.get("/auth/session").status_code == 401  # 쿠키 없음 → 401

    assert client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).status_code == 200
    r = client.get("/auth/session")  # Secure 쿠키는 https base_url이라 쿠키 자에서 전송된다

    assert r.status_code == 200
    assert r.json()["userId"] == account.id


# ── 2. 가입 레이트리밋 429 와이어링 (SEC-11) ────────────────────────────────────


def test_signup_per_email_rate_limit_returns_429(make_app, monkeypatch):
    """같은 이메일 반복 가입 시도는 per-email 한도 초과 시 429. 다른 이메일 키는 독립."""
    monkeypatch.setattr(controller, "_RL_EMAIL_LIMIT", 3)
    monkeypatch.setattr(controller, "_RL_IP_LIMIT", 100)
    ctx = make_app()
    client = _client(ctx.app)
    body = {"email": "burst@docsuri.org", "password": PASSWORD}

    r1 = client.post("/auth/signup", json=body)
    assert r1.status_code == 201
    assert r1.json()["accountId"]
    # 2·3번째 — 한도 내. 중복 이메일도 열거-안전 일반 201(무작위 accountId)로 응답하며,
    # limiter는 서비스 호출 전에 소모된다.
    assert client.post("/auth/signup", json=body).status_code == 201
    assert client.post("/auth/signup", json=body).status_code == 201

    r4 = client.post("/auth/signup", json=body)
    assert r4.status_code == 429
    assert r4.json()["detail"] == "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."

    # per-email 키 분리: 같은 IP라도 다른 이메일은 여전히 허용
    r_other = client.post("/auth/signup", json={"email": "other@docsuri.org", "password": PASSWORD})
    assert r_other.status_code == 201


def test_signup_per_ip_rate_limit_returns_429(make_app, monkeypatch):
    """서로 다른 이메일이라도 같은 IP의 가입 시도는 per-IP 한도 초과 시 429 (대량 PENDING 생성 방어).
    IP 키는 X-Forwarded-For 첫 홉 기준이므로 다른 XFF는 독립 카운트된다."""
    monkeypatch.setattr(controller, "_RL_EMAIL_LIMIT", 100)
    monkeypatch.setattr(controller, "_RL_IP_LIMIT", 2)
    ctx = make_app()
    client = _client(ctx.app)

    assert client.post("/auth/signup", json={"email": "ip1@docsuri.org", "password": PASSWORD}).status_code == 201
    assert client.post("/auth/signup", json={"email": "ip2@docsuri.org", "password": PASSWORD}).status_code == 201

    r3 = client.post("/auth/signup", json={"email": "ip3@docsuri.org", "password": PASSWORD})
    assert r3.status_code == 429
    assert r3.json()["detail"] == "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."

    # 다른 클라이언트 IP(XFF 첫 홉)는 독립 버킷 → 허용
    r_other_ip = client.post(
        "/auth/signup",
        json={"email": "ip3@docsuri.org", "password": PASSWORD},
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert r_other_ip.status_code == 201


# ── 3. Google OIDC 콜백 실패 복구 경로 (FR-27) ──────────────────────────────────


def _install_google_transport(monkeypatch, handler) -> None:
    """oidc 모듈의 httpx.AsyncClient를 MockTransport로 바꿔 실 네트워크 없이 Google 왕복을 재현."""
    real_async_client = httpx.AsyncClient

    def _factory(*args, **kwargs):
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(oidc_module.httpx, "AsyncClient", _factory)


def _seed_oidc_state(client: TestClient, store, *, state="st-123", nonce="n-123", verifier="v-123") -> str:
    """start 단계가 남겼을 서버측 state 레코드와 브라우저 oidc_state 쿠키를 심는다."""
    asyncio.run(store.put(state, provider="GOOGLE", nonce=nonce, code_verifier=verifier))
    client.cookies.set("oidc_state", state)
    return state


def test_google_start_sets_short_lived_state_cookie(make_app):
    """GET /auth/social/google/start → Google 인가 페이지 302 + 10분 단명 oidc_state 쿠키."""
    ctx = make_app()
    client = _client(ctx.app)

    r = client.get("/auth/social/google/start", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"].startswith(oidc_module.GOOGLE_AUTH_URL)
    state_cookies = [c for c in r.headers.get_list("set-cookie") if c.startswith("oidc_state=")]
    assert len(state_cookies) == 1
    cookie = state_cookies[0].lower()
    for flag in ("httponly", "secure", "samesite=lax", "max-age=600"):
        assert flag in cookie


@pytest.mark.parametrize(
    ("fail_at", "expected_detail"),
    [
        ("token-exchange", "소셜 로그인 토큰 교환에 실패했습니다."),
        ("tokeninfo", "소셜 로그인 토큰 검증에 실패했습니다."),
    ],
)
def test_google_callback_failure_is_recoverable(make_app, monkeypatch, fail_at, expected_detail):
    """콜백에서 Google 왕복(토큰 교환/tokeninfo 검증)이 실패하면: 500이 아닌 401 + 복구 안내
    메시지, 세션 미발급(half-created 세션 없음), state는 단일 사용으로 소비(재시도 → 400)."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            if fail_at == "token-exchange":
                return httpx.Response(500, json={"error": "internal_failure"})
            return httpx.Response(200, json={"id_token": "stub.jwt.token"})
        # tokeninfo — id_token 서명/만료 검증 실패
        return httpx.Response(400, json={"error_description": "Invalid Value"})

    _install_google_transport(monkeypatch, handler)
    ctx = make_app()
    client = _client(ctx.app)
    state = _seed_oidc_state(client, ctx.state_store)

    r = client.get(
        f"/auth/social/google/callback?code=auth-code&state={state}", follow_redirects=False
    )

    assert r.status_code == 401  # DomainException → 복구 가능한 인증 오류 (Fail-Closed, no 500)
    assert r.json()["detail"] == expected_detail
    assert _session_cookies(r) == []  # 세션 쿠키 미발급
    assert ctx.session_manager.sessions == {}  # half-created 세션 없음

    # state는 단일 사용 — 동일 콜백 재전송은 상태 검증 실패(400)로 거부된다 (재생 방어)
    replay = client.get(
        f"/auth/social/google/callback?code=auth-code&state={state}", follow_redirects=False
    )
    assert replay.status_code == 400
    assert ctx.session_manager.sessions == {}


def test_google_callback_rejects_forged_or_missing_state(make_app):
    """oidc_state 쿠키 부재/서버 저장소에 없는 state → 400 (CSRF 방어), 500·세션 발급 없음."""
    ctx = make_app()
    client = _client(ctx.app)

    # 쿠키 자체가 없음 → 400
    r_no_cookie = client.get(
        "/auth/social/google/callback?code=c&state=whatever", follow_redirects=False
    )
    assert r_no_cookie.status_code == 400

    # 쿠키는 있으나 서버 저장소에 없는(위조된) state → 400
    client.cookies.set("oidc_state", "forged-state")
    r_forged = client.get(
        "/auth/social/google/callback?code=c&state=forged-state", follow_redirects=False
    )
    assert r_forged.status_code == 400
    assert ctx.session_manager.sessions == {}


def test_google_callback_success_issues_session_cookie_and_redirects(
    make_app, monkeypatch, db_session
):
    """대조군(실패 테스트가 공허하게 통과하지 않음을 증명): 정상 tokeninfo 클레임이면 신규 ACTIVE
    계정으로 세션이 발급되고, 세션 쿠키 플래그는 로그인과 동일(httpOnly/Secure/lax)하다."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(200, json={"id_token": "stub.jwt.token"})
        return httpx.Response(
            200,
            json={
                "aud": "test-client-id",
                "iss": "https://accounts.google.com",
                "nonce": "n-123",
                "sub": "google-sub-1",
                "email": "social@docsuri.org",
                "email_verified": "true",
            },
        )

    _install_google_transport(monkeypatch, handler)
    monkeypatch.setenv("GOOGLE_OIDC_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_OIDC_CLIENT_SECRET", "test-secret")
    ctx = make_app()
    client = _client(ctx.app)
    state = _seed_oidc_state(client, ctx.state_store)

    r = client.get(f"/auth/social/google/callback?code=good&state={state}", follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["location"] == "/"  # PUBLIC_APP_URL 미설정 → 루트 폴백
    cookies = _session_cookies(r)
    assert len(cookies) == 1
    for flag in ("httponly", "secure", "samesite=lax"):
        assert flag in cookies[0].lower()
    # reconcile이 신규 ACTIVE 계정을 만들고 세션이 그 계정으로 발급됐다 (BR-A9)
    account = ctx.repo.get_by_email("social@docsuri.org")
    assert account is not None
    assert account.status == AccountStatus.ACTIVE.value
    assert [p.user_id for p in ctx.session_manager.sessions.values()] == [account.id]
    # oidc 임시 쿠키(state)는 정리된다
    cleared = [c for c in r.headers.get_list("set-cookie") if c.startswith("oidc_state=")]
    assert cleared and 'max-age=0' in cleared[0].lower()


# ── 4. 재설정 토큰 30분 만료 브랜치 (FR-26/BR-A8) ───────────────────────────────


def _seed_reset_token(db_session, email: str, *, age: timedelta) -> str:
    """`age` 전에 발급된 것처럼 재설정 토큰을 심는다 (expires_at = 발급시각 + 30분 TTL)."""
    token = "reset-token-under-test"
    issued_at = datetime.now(UTC).replace(tzinfo=None) - age
    repo = CredentialRepository(db_session)
    repo.create_reset_token(normalize_email(email), _hash_token(token), issued_at + RESET_TOKEN_TTL)
    db_session.commit()
    return token


def test_password_reset_confirm_rejects_expired_token(make_app, db_session):
    """31분 전 발급(=30분 TTL 경과) 토큰 → 400 + 일반화 메시지, 비밀번호 불변·세션 무효화 없음."""
    account = _active_account(db_session)
    old_hash = account.password_hash
    token = _seed_reset_token(db_session, EMAIL, age=timedelta(minutes=31))
    ctx = make_app()
    client = _client(ctx.app)

    r = client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "BrandNewPw9!@"}
    )

    assert r.status_code == 400
    assert r.json()["detail"] == "유효하지 않거나 만료된 재설정 링크입니다. 다시 요청해 주세요."
    repo = CredentialRepository(db_session)
    assert repo.get_by_email(EMAIL).password_hash == old_hash  # 비밀번호 불변
    assert ctx.session_manager.invalidated_users == []  # 세션 무효화 미발생
    # 재시도해도 계속 거부된다 (만료 브랜치는 영구적)
    retry = client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "BrandNewPw9!@"}
    )
    assert retry.status_code == 400


def test_password_reset_confirm_accepts_token_within_ttl(make_app, db_session):
    """대조군: 29분 전 발급(TTL 이내) 토큰은 성공 — 비밀번호 변경 + 단일 사용 소비 + 전 세션
    무효화(BR-A8). 만료 테스트와 발급 시각만 다르므로 실패가 정확히 만료 브랜치임을 증명한다."""
    account = _active_account(db_session)
    old_hash = account.password_hash
    token = _seed_reset_token(db_session, EMAIL, age=timedelta(minutes=29))
    ctx = make_app()
    client = _client(ctx.app)

    r = client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "BrandNewPw9!@"}
    )

    assert r.status_code == 200
    assert r.json()["status"] == "success"
    repo = CredentialRepository(db_session)
    assert repo.get_by_email(EMAIL).password_hash != old_hash  # 비밀번호 변경됨
    assert repo.get_reset_token(_hash_token(token)) is None  # 단일 사용 소비
    assert ctx.session_manager.invalidated_users == [account.id]  # BR-A8 전 세션 무효화
    # 소비된 토큰 재사용 → 400
    reuse = client.post(
        "/auth/password-reset/confirm", json={"token": token, "newPassword": "AnotherPw9!@"}
    )
    assert reuse.status_code == 400
