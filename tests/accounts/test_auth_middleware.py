from backend.middleware.auth import _is_public


def test_orcid_oidc_routes_are_public_but_social_link_is_not():
    assert _is_public("/auth/social/orcid/start")
    assert _is_public("/auth/social/orcid/callback")
    assert not _is_public("/auth/social/link")
