"""U3 — 가입 없이 둘러보기(`POST /auth/demo`) HTTP 계약.

가입 장벽을 없애는 **공개 표면**이라 세 가지가 동시에 참이어야 한다:
1. 기본은 꺼져 있고 꺼졌을 때 **404**다(405나 403이 아니다 — 존재를 알리지 않는다),
2. 켜면 세션 쿠키가 로그인과 **같은 속성**으로 나간다(SEC-12),
3. 호출마다 **다른 계정**이 생긴다 — 공유 계정이면 에이전트 일일 쿼터를 나눠 쓰게 된다.

프론트 버튼만 숨기는 것으로는 숨긴 것이 아니다: 주소만 알면 호출된다. 그래서 게이트가
백엔드에도 있고, 이 파일이 그쪽을 본다(프론트는 `frontend/test/demoLoginGate.test.tsx`).
"""

from __future__ import annotations

import pytest

from backend.modules.accounts import controller
from backend.modules.accounts.models import AccountStatus
from backend.modules.accounts.repository.credential import AccountTable, SOCIAL_NO_PASSWORD_HASH
from tests.accounts.test_controller_http import _client, _session_cookies


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(controller, "_DEMO_LOGIN_ENABLED", True)


def test_demo_login_is_404_when_disabled(make_app, monkeypatch):
    """꺼졌을 때 404 — 405/403이면 '있는데 막혔다'를 알려 주는 셈이다."""
    monkeypatch.setattr(controller, "_DEMO_LOGIN_ENABLED", False)
    ctx = make_app()

    res = _client(ctx.app).post("/auth/demo")

    assert res.status_code == 404
    assert _session_cookies(res) == [], "거부인데 세션이 나갔다"


def test_demo_login_issues_a_session_cookie_like_login(make_app, demo_on):
    ctx = make_app()

    res = _client(ctx.app).post("/auth/demo")

    assert res.status_code == 200
    cookies = _session_cookies(res)
    assert cookies, "세션 쿠키가 안 나갔다"
    raw = cookies[0].lower()
    # 로그인과 같은 속성이어야 한다 — 여기만 다르면 데모 세션이 다르게 만료되거나
    # SameSite가 갈려 조용히 끊긴다.
    assert "httponly" in raw
    assert "secure" in raw
    assert "samesite=lax" in raw


def test_each_call_creates_its_own_account(make_app, demo_on, db_session):
    """공유 계정이면 먼저 온 한 명이 그날의 에이전트 쿼터를 다 쓰고 나머지가 429를 받는다."""
    client = _client(make_app().app)

    first = client.post("/auth/demo")
    client.cookies.clear()
    second = client.post("/auth/demo")

    assert first.status_code == second.status_code == 200
    emails = [row.email for row in db_session.query(AccountTable).all()]
    assert len(emails) == 2, f"계정이 하나로 합쳐졌다: {emails}"
    assert len(set(emails)) == 2


def test_demo_accounts_are_active_and_have_no_usable_password(make_app, demo_on, db_session):
    """비밀번호 로그인으로 다시 열리면 안 된다 — 소셜 계정과 같은 센티넬 해시를 쓴다.

    ACTIVE여야 하는 이유는 그 반대다: PENDING이면 이메일 인증을 기다리게 되어 '가입 없이'가
    성립하지 않는다.
    """
    _client(make_app().app).post("/auth/demo")

    account = db_session.query(AccountTable).one()
    assert account.status == AccountStatus.ACTIVE.value
    assert account.password_hash == SOCIAL_NO_PASSWORD_HASH
    # 실제로 메일이 나갈 수 없는 예약 TLD여야 한다(RFC 2606).
    assert account.email.endswith("@demo.invalid")


def test_the_route_path_is_the_one_the_frontend_calls():
    """경로가 두 언어에 나뉘어 있다 — 여기(`/auth/demo`)와 `HeroLanding.tsx`(`/bff/auth/demo`).

    한쪽만 보면 못 잡는다. 프론트가 `/bff/api/auth/demo`로 부르던 동안 백엔드 테스트 4건은
    전부 초록이었고, **배포본에서만 401**이었다 — 그 경로는 라우터에 없어 미들웨어가 끊는다.
    라우터 접두어를 옮기면 이 검사가 먼저 빨개져 프론트도 같이 고쳐야 한다는 것을 알린다.
    """
    paths = {r.path for r in controller.router.routes if hasattr(r, "path")}

    assert "/auth/demo" in paths, f"프론트가 부르는 경로가 사라졌다: {sorted(paths)[:5]}"
    assert "/api/auth/demo" not in paths
