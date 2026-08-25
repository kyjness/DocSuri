from backend.middleware.auth import _is_public


def test_orcid_oidc_routes_are_public_but_social_link_is_not():
    assert _is_public("/auth/social/orcid/start")
    assert _is_public("/auth/social/orcid/callback")
    assert not _is_public("/auth/social/link")


def test_demo_login_is_public_because_it_runs_without_a_session():
    """가입 없이 둘러보기는 **세션이 없는 상태로** 부르는 것이 목적이다.

    공개 목록에 없으면 미들웨어가 401을 내서 "로그인해야 로그인할 수 있는" 상태가 된다
    (2026-08-25 배포본에서 실제로 그랬다). 컨트롤러 테스트는 라우터만 올려 미들웨어를 안 타므로
    **그쪽이 초록이어도 이것을 못 잡는다** — 그래서 여기서 따로 본다.
    """
    assert _is_public("/auth/demo")
    assert not _is_public("/auth/me")
    # **매칭은 접두어다**(`path.startswith`). 즉 `/auth/demo`로 시작하는 경로는 전부 열린다 —
    # 이 아래에 세션이 필요한 라우트를 새로 두면 안 된다. 목록의 다른 항목도 같은 성질이라
    # 여기서만 엄격하게 만들 수 없다(`/auth/social/orcid`가 start·callback 둘을 함께 연다).
    assert _is_public("/auth/demo/anything")
