"""소셜 로그인(OIDC) 신원 조정 서비스 (FR-27 / BR-A9).

본 모듈은 **검증된 프로바이더 클레임**(이메일·검증여부·subject)을 받아 계정에 연결/생성하는
*조정(reconciliation)* 로직만 담는다. OIDC 트랜스포트(인가 흐름·코드 교환·id_token JWKS 검증)는
별도 OidcVerifier(차기 슬라이스)로 분리해 본 핵심 로직을 단위 테스트 가능하게 한다.

H1(pre-hijacking) 방어: 검증 이메일이 *비밀번호를 가진* 기존 계정과 일치하면 자동 병합하지 않고
`SocialLinkConfirmationRequired`를 발생시켜 명시적 연결을 요구한다.
"""

import logging
from dataclasses import dataclass

from ..models import (
    DomainException,
    OidcProvider,
    SocialLinkConfirmationRequired,
    normalize_email,
)
from ..repository.credential import CredentialRepository, has_usable_password

logger = logging.getLogger(__name__)


def _account_id_for_existing_link(link) -> str:
    if link.status == "LINKED":
        return link.account_id
    if link.status == "PENDING_CONFIRMATION":
        raise SocialLinkConfirmationRequired(
            "이 이메일은 비밀번호로 가입된 계정입니다. 비밀번호로 로그인한 뒤 소셜 계정을 연결해 주세요."
        )
    raise DomainException("소셜 계정 연결 상태가 올바르지 않습니다.")


@dataclass(frozen=True)
class OidcClaims:
    """프로바이더 id_token에서 서명·nonce 검증 후 추출한 신뢰 클레임 (FR-27).

    이메일 제공 프로바이더(Google)는 email/email_verified를 채운다(BR-A9). 이메일을 제공하지
    않는 프로바이더(ORCID)는 email=None이며 name(표시용)만 채운다(BR-A13)."""

    subject: str
    email: str | None = None
    email_verified: bool = False
    name: str | None = None  # ORCID 마이페이지 표시용 (id_token given_name/family_name)


class SocialLoginService:
    def __init__(self, credential_repo: CredentialRepository):
        self._repo = credential_repo

    def reconcile(self, provider: OidcProvider, claims: OidcClaims) -> str:
        """검증된 클레임을 계정으로 조정하고 account_id를 반환한다 (세션 발급용).

        규칙(BR-A9):
        - `email_verified=False` → 거부(자동 연결 금지).
        - `(provider, subject)` 기존 연결 있음 → 그 계정 사용.
        - 없고, 이메일의 기존 계정이:
            - 비밀번호 있음 → 자동 병합 금지: PENDING_CONFIRMATION 신원 기록 +
              `SocialLinkConfirmationRequired` (H1 pre-hijacking 방어).
            - 비밀번호 없음(소셜-only) → 자동 연결(LINKED).
          이메일의 기존 계정 없음 → ACTIVE 신규 계정 생성 + LINKED.

        이메일을 제공하지 않는 프로바이더(ORCID, claims.email is None)는 BR-A13 경로로 분기한다.
        """
        if claims.email is None:
            return self._reconcile_emailless(provider, claims)
        if not claims.email_verified:
            raise DomainException("프로바이더가 이메일을 검증하지 않아 로그인할 수 없습니다.")
        provider_v = provider.value

        existing_link = self._repo.get_social_identity(provider_v, claims.subject)
        if existing_link is not None:
            return _account_id_for_existing_link(existing_link)

        email = normalize_email(claims.email)
        account = self._repo.get_by_email(email)

        if account is None:
            account = self._repo.create_social_account(email)
            self._repo.create_social_identity(provider_v, claims.subject, account.id, email, status="LINKED")
            logger.info(f"Social signup: new ACTIVE account {account.id} via {provider_v}.")
            return account.id

        if has_usable_password(account):
            # H1: 기존 비밀번호 계정 — 자동 병합 금지. 명시적 연결 대기 신원만 기록.
            self._repo.create_social_identity(
                provider_v, claims.subject, account.id, email, status="PENDING_CONFIRMATION"
            )
            raise SocialLinkConfirmationRequired(
                "이 이메일은 비밀번호로 가입된 계정입니다. 비밀번호로 로그인한 뒤 소셜 계정을 연결해 주세요."
            )

        # 소셜-only(비밀번호 없는) 기존 계정 → 자동 연결.
        self._repo.create_social_identity(provider_v, claims.subject, account.id, email, status="LINKED")
        logger.info(f"Social auto-link: account {account.id} linked to {provider_v}.")
        return account.id

    def _reconcile_emailless(self, provider: OidcProvider, claims: OidcClaims) -> str:
        """BR-A13: 이메일을 제공하지 않는 프로바이더(ORCID)의 신원 조정.

        이메일이 없어 동일인 판정(이메일 매칭·H1 자동 병합)이 불가하므로 `(provider, subject)`
        단독으로 신원을 성립시킨다. 기존 연결이 있으면 그 계정을, 없으면 email=NULL인 ACTIVE
        신규 계정을 생성한다(role=USER, 비밀번호 자격증명 없음)."""
        provider_v = provider.value
        existing_link = self._repo.get_social_identity(provider_v, claims.subject)
        if existing_link is not None:
            return _account_id_for_existing_link(existing_link)
        account = self._repo.create_social_account(None)
        self._repo.create_social_identity(provider_v, claims.subject, account.id, None, status="LINKED")
        logger.info(f"Social signup (emailless): new ACTIVE account {account.id} via {provider_v}.")
        return account.id

    def confirm_pending_links(self, account_id: str) -> int:
        """비밀번호 로그인으로 소유권을 증명한 사용자가 자신의 보류 소셜 연결을 확정한다 (H1, BR-A9).
        승격(PENDING_CONFIRMATION→LINKED)한 신원 수를 반환한다."""
        return self._repo.confirm_social_links_for_account(account_id)
