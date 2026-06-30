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
구글 RTT/가용성 의존을 없앨 수 있다. `cryptography`는 이제 backend 의존성으로 설치돼 있고(아래
ORCID 검증기 `OrcidOidcVerifier`가 로컬 JWKS/RS256으로 이미 사용 중) 새 의존성·재빌드는 더 이상
필요 없다 — 남은 일은 Google에 동일 방식을 적용하고 `GOOGLE_OIDC_VERIFY_MODE` env로 게이트하는
것뿐이다(후속 작업).
"""

import base64
import binascii
import hashlib
import json
import logging
import time
from urllib.parse import urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

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


# ── ORCID OIDC 트랜스포트 (FR-27 / BR-A13) ──────────────────────────────────────
# ORCID는 Google과 달리 (1) tokeninfo 엔드포인트가 없고 (2) OIDC가 이메일 클레임을 반환하지
# 않는다(scopes=[openid], claims=[sub, name, given_name, family_name, ...]). 따라서 ORCID JWKS로
# id_token RS256 서명을 로컬 검증한 뒤 iss/aud/nonce/exp를 강제한다.
ORCID_BASES = {
    "prod": ("https://orcid.org", "https://pub.orcid.org/v3.0"),
    "sandbox": ("https://sandbox.orcid.org", "https://pub.sandbox.orcid.org/v3.0"),
}


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _decode_jwt_json(segment: str) -> dict:
    try:
        return json.loads(_b64url_decode(segment))
    except (ValueError, binascii.Error, json.JSONDecodeError) as e:
        raise DomainException("소셜 로그인 토큰 형식이 올바르지 않습니다.") from e


def _split_jwt(token: str) -> tuple[dict, dict, bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        raise DomainException("소셜 로그인 토큰 형식이 올바르지 않습니다.")
    header = _decode_jwt_json(parts[0])
    payload = _decode_jwt_json(parts[1])
    try:
        signature = _b64url_decode(parts[2])
    except (ValueError, binascii.Error) as e:
        raise DomainException("소셜 로그인 토큰 형식이 올바르지 않습니다.") from e
    return header, payload, f"{parts[0]}.{parts[1]}".encode("ascii"), signature


def _rsa_public_key_from_jwk(jwk: dict):
    if jwk.get("kty") != "RSA":
        raise DomainException("소셜 로그인 토큰 키 형식이 올바르지 않습니다.")
    try:
        n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
        e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    except (KeyError, ValueError, binascii.Error) as exc:
        raise DomainException("소셜 로그인 토큰 키 형식이 올바르지 않습니다.") from exc
    return rsa.RSAPublicNumbers(e, n).public_key()


class OrcidOidcVerifier:
    """ORCID 인가 코드 흐름 트랜스포트. GoogleOidcVerifier와 인터페이스(build_authorization_url·
    exchange_and_verify)는 같지만 검증은 로컬 JWKS/RS256이고 이메일을 받지 않는다."""

    def __init__(self, client_id: str, client_secret: str, *, env: str = "prod", timeout: float = 10.0):
        self._client_id = client_id
        self._client_secret = client_secret
        self._base, self._pub_base = ORCID_BASES.get(env, ORCID_BASES["prod"])
        self._jwks_url = f"{self._base}/oauth/jwks"
        self._jwks_cache: dict | None = None
        self._jwks_cached_at = 0.0
        self._timeout = timeout

    @property
    def pub_base(self) -> str:
        return self._pub_base

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def build_authorization_url(
        self, redirect_uri: str, state: str, nonce: str, code_challenge: str | None = None
    ) -> str:
        """ORCID 인가 엔드포인트 URL. ORCID OIDC는 scope=openid만 지원한다."""
        params = {
            "client_id": self._client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "state": state,
            "nonce": nonce,
        }
        if code_challenge:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"
        return f"{self._base}/oauth/authorize?{urlencode(params)}"

    async def _exchange_code(self, code: str, redirect_uri: str, code_verifier: str | None = None) -> str:
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
            resp = await client.post(
                f"{self._base}/oauth/token", data=data, headers={"Accept": "application/json"}
            )
        if resp.status_code != 200:
            logger.warning("ORCID token exchange failed: status=%s", resp.status_code)
            raise DomainException("소셜 로그인 토큰 교환에 실패했습니다.")
        id_token = resp.json().get("id_token")
        if not id_token:
            raise DomainException("소셜 로그인 응답에 id_token이 없습니다.")
        return id_token

    async def _fetch_jwks(self, *, force: bool = False) -> dict:
        now = time.time()
        if self._jwks_cache is not None and not force and now - self._jwks_cached_at < 3600:
            return self._jwks_cache
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(self._jwks_url)
            if resp.status_code != 200:
                logger.warning("ORCID JWKS fetch failed: status=%s", resp.status_code)
                raise DomainException("소셜 로그인 토큰 검증 키를 가져오지 못했습니다.")
            jwks = resp.json()
        except httpx.HTTPError as e:
            raise DomainException("소셜 로그인 토큰 검증 키를 가져오지 못했습니다.") from e
        if not isinstance(jwks.get("keys"), list):
            raise DomainException("소셜 로그인 토큰 검증 키 형식이 올바르지 않습니다.")
        self._jwks_cache = jwks
        self._jwks_cached_at = now
        return jwks

    async def _jwk_for_kid(self, kid: str) -> dict:
        for force in (False, True):
            jwks = await self._fetch_jwks(force=force)
            for key in jwks["keys"]:
                if key.get("kid") == kid:
                    return key
        raise DomainException("소셜 로그인 토큰 검증 키를 찾을 수 없습니다.")

    async def _verify_id_token(self, token: str) -> dict:
        header, payload, signing_input, signature = _split_jwt(token)
        if header.get("alg") != "RS256":
            raise DomainException("소셜 로그인 토큰 서명 알고리즘이 올바르지 않습니다.")
        kid = header.get("kid")
        if not kid:
            raise DomainException("소셜 로그인 토큰 검증 키가 누락되었습니다.")
        public_key = _rsa_public_key_from_jwk(await self._jwk_for_kid(kid))
        try:
            public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature as e:
            raise DomainException("소셜 로그인 토큰 서명 검증에 실패했습니다.") from e
        return payload

    async def exchange_and_verify(
        self, code: str, redirect_uri: str, expected_nonce: str, code_verifier: str | None = None
    ) -> OidcClaims:
        """code → id_token → 검증된 클레임. aud/iss/nonce/exp 불일치 또는 sub 부재 시 거부.
        ORCID는 이메일을 제공하지 않으므로 email=None·name만 채운다(BR-A13)."""
        if not code_verifier:
            raise DomainException("PKCE 증명(code_verifier)이 누락되었습니다. (보안 정책)")
        id_token = await self._exchange_code(code, redirect_uri, code_verifier)
        info = await self._verify_id_token(id_token)
        if info.get("aud") != self._client_id:
            raise DomainException("소셜 로그인 토큰의 대상(aud)이 일치하지 않습니다.")
        if info.get("iss") != self._base:
            raise DomainException("소셜 로그인 토큰 발급자(iss)가 올바르지 않습니다.")
        if not expected_nonce or info.get("nonce") != expected_nonce:
            raise DomainException("소셜 로그인 검증에 실패했습니다. 다시 시도해 주세요.")
        exp = info.get("exp")
        if not isinstance(exp, (int, float)) or exp < time.time():
            raise DomainException("소셜 로그인 토큰이 만료되었습니다. 다시 시도해 주세요.")
        subject = info.get("sub")  # ORCID iD (예: 0000-0002-1825-0097)
        if not subject:
            raise DomainException("소셜 로그인 토큰에 필수 클레임이 없습니다.")
        given, family = info.get("given_name"), info.get("family_name")
        name = info.get("name") or " ".join(p for p in (given, family) if p) or None
        return OidcClaims(subject=subject, email=None, email_verified=False, name=name)


async def fetch_orcid_public_record(
    orcid_id: str, *, pub_base: str = "https://pub.orcid.org/v3.0", timeout: float = 10.0
) -> dict:
    """ORCID Public API(/record, 무료·인증 불요)에서 소속·저작물을 best-effort로 가져온다.
    반환: {"affiliation": str|None, "works": [{"title": str, "year": int|None}]}. 호출부는 필요한
    것만 사용(로그인=affiliation 캐시, 마이페이지=works 라이브). 실패 시 빈 결과로 저하."""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(
                f"{pub_base}/{orcid_id}/record", headers={"Accept": "application/json"}
            )
        if resp.status_code != 200:
            return {"affiliation": None, "works": []}
        rec = resp.json()
    except (httpx.HTTPError, ValueError):
        return {"affiliation": None, "works": []}

    summary = rec.get("activities-summary") or {}
    affiliation = None
    try:
        groups = (summary.get("employments") or {}).get("affiliation-group") or []
        summaries = (groups[0].get("summaries") or []) if groups else []
        org = ((summaries[0].get("employment-summary") or {}).get("organization") or {}) if summaries else {}
        affiliation = org.get("name") or None
    except (IndexError, AttributeError, TypeError):
        affiliation = None

    works: list[dict] = []
    try:
        for group in (summary.get("works") or {}).get("group") or []:
            ws = (group.get("work-summary") or [{}])[0]
            title = (((ws.get("title") or {}).get("title") or {}).get("value")) or None
            year_raw = (((ws.get("publication-date") or {}).get("year") or {}).get("value"))
            if title:
                works.append({"title": title, "year": int(year_raw) if year_raw else None})
            if len(works) >= 50:  # ponytail: 표시용 상한, 페이지네이션은 필요 시
                break
    except (AttributeError, TypeError, ValueError):
        pass
    return {"affiliation": affiliation, "works": works}
