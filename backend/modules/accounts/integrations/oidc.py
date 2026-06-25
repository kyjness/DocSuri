"""Google OIDC 트랜스포트 (FR-27).

인가 코드 흐름의 트랜스포트 절반(인가 URL 생성·code↔token 교환·id_token 검증)을 담는다.
신원 조정(계정 연결/생성)은 SocialLoginService.reconcile가 담당한다(코어 분리 유지 — 테스트 가능).

인가 코드 흐름은 PKCE(S256, RFC 7636)를 사용한다(감사 #8) — verifier는 백엔드 쿠키로만 보관하고
challenge만 Google에 보내, 인가 코드 가로채기/주입을 방어한다.

id_token 서명 검증은 Google tokeninfo 엔드포인트에 위임한다 — 새 crypto 의존성 없이 httpx만
사용한다. tokeninfo는 서명·만료를 서버측에서 검증하고 클레임을 JSON으로 돌려준다. 우리는
aud(우리 client_id)·iss(google)·nonce(재생 방어) 일치를 추가로 강제한다. id_token은 *서버 대 서버*
토큰 교환으로 직접 받으므로 이는 검증 우회가 아니다(감사 #9: tokeninfo는 우회가 아니라 운영상
취약점).
SECURITY-DEBT(감사 #9, deferred): 로컬 JWKS(RS256) 검증으로 _fetch_tokeninfo를 대체하면 로그인당
구글 RTT/가용성 의존을 없앨 수 있으나 `cryptography` 의존성 추가 + 이미지 재빌드가 필요하다(현
환경 미설치 → 테스트 불가). `GOOGLE_OIDC_VERIFY_MODE` env 게이트로 도입하는 것을 후속 작업으로 둔다.
"""

import base64
import hashlib
import logging
from urllib.parse import urlencode

import httpx

from ..models import DomainException
from ..services.social_login import OidcClaims

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_ISS = {"https://accounts.google.com", "accounts.google.com"}


def pkce_challenge(code_verifier: str) -> str:
    """PKCE S256 코드 챌린지 = base64url(sha256(code_verifier)) (패딩 제거, RFC 7636).
    인가 코드 가로채기/주입(감사 #8) 방어 — 교환 시 원본 verifier 제시를 강제한다."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class GoogleOidcVerifier:
    def __init__(self, client_id: str, client_secret: str, *, timeout: float = 10.0):
        self._client_id = client_id
        self._client_secret = client_secret
        self._timeout = timeout

    def build_authorization_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str | None = None
    ) -> str:
        """Google 인가 엔드포인트 URL을 만든다(start 단계 리다이렉트 대상).
        code_challenge가 주어지면 PKCE(S256)를 함께 요청한다(감사 #8)."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    async def _exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> str:
        """인가 코드를 토큰으로 교환하고 id_token(JWT)을 반환한다.
        code_verifier가 있으면 PKCE 증명으로 함께 전송한다."""
        data = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            data["code_verifier"] = code_verifier
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
        if resp.status_code != 200:
            logger.warning("OIDC token exchange failed: status=%s", resp.status_code)
            raise DomainException("소셜 로그인 토큰 교환에 실패했습니다.")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise DomainException("소셜 로그인 응답에 id_token이 없습니다.")
        return id_token

    async def _fetch_tokeninfo(self, id_token: str) -> dict:
        """tokeninfo로 id_token 서명·만료를 검증하고 클레임(JSON)을 받는다."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(GOOGLE_TOKENINFO_URL, params={"id_token": id_token})
        if resp.status_code != 200:
            logger.warning("OIDC tokeninfo verification failed: status=%s", resp.status_code)
            raise DomainException("소셜 로그인 토큰 검증에 실패했습니다.")
        return resp.json()

    async def exchange_and_verify(
        self, code: str, redirect_uri: str, expected_nonce: str, code_verifier: str | None = None
    ) -> OidcClaims:
        """code → id_token → 검증된 클레임. aud/iss/nonce 불일치 또는 필수 클레임 부재 시 거부.
        PKCE(S256) code_verifier는 **필수**다 — 미래 호출부가 PKCE를 조용히 누락하지 못하게
        막는다(감사 #8). 정상 콜백 경로는 항상 공급한다."""
        if not code_verifier:
            raise DomainException("PKCE 증명(code_verifier)이 누락되었습니다. (보안 정책)")
        id_token = await self._exchange_code(code, redirect_uri, code_verifier)
        info = await self._fetch_tokeninfo(id_token)
        if info.get("aud") != self._client_id:
            raise DomainException("소셜 로그인 토큰의 대상(aud)이 일치하지 않습니다.")
        if info.get("iss") not in GOOGLE_ISS:
            raise DomainException("소셜 로그인 토큰 발급자(iss)가 올바르지 않습니다.")
        if not expected_nonce or info.get("nonce") != expected_nonce:
            # nonce 불일치 = 재생/주입 의심 — Fail-Closed.
            raise DomainException("소셜 로그인 검증에 실패했습니다. 다시 시도해 주세요.")
        subject = info.get("sub")
        email = info.get("email")
        if not subject or not email:
            raise DomainException("소셜 로그인 토큰에 필수 클레임이 없습니다.")
        # tokeninfo는 email_verified를 문자열 'true'/'false' 또는 불리언으로 줄 수 있다 — 둘 다 수용.
        ev = info.get("email_verified")
        email_verified = ev is True or str(ev).lower() == "true"
        return OidcClaims(subject=subject, email=email, email_verified=email_verified)
