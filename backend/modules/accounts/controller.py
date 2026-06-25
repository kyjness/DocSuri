import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from backend.middleware.rate_limit import InProcessWindowLimiter, RedisRateLimiter
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .guard import AuthorizationGuard, Decision
from .integrations.email import get_email_client
from .integrations.oidc import GoogleOidcVerifier, pkce_challenge
from .integrations.recaptcha import RecaptchaClient
from .models import (
    DomainException,
    OidcProvider,
    Principal,
    SessionExpiredException,
    SessionStoreUnavailableException,
    SocialLinkConfirmationRequired,
    UnauthorizedException,
    UserRole,
    normalize_email,
)
from .repository.credential import CredentialRepository
from .repository.session import SessionRepository
from .schemas import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionInfo,
    SignupRequest,
    SignupResult,
)
from .services.account_deletion import AccountDeletionService
from .services.account_management import AccountManagementService
from .services.auth import AuthenticationService
from .services.password_reset import PasswordResetService
from .services.session_manager import SessionManager
from .services.signup import SignupService
from .services.social_login import SocialLoginService
from .services.totp import TotpService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Accounts/Auth"])


# U3-내부 관리자 MFA DTO (공유 SSOT 계약 아님 — admin MFA는 U3-private이라 docsuri_shared에 없음).
class MfaVerifyRequest(BaseModel):
    code: str

# 인증 메일 재발송 요청 DTO (U3-내부 — 가입 후 메일 미수신 복구 경로용).
class ResendVerificationRequest(BaseModel):
    email: str

# 비밀번호 변경 DTO (U3-내부 — 로그인 사용자 자가 관리, FR-28/BR-A10).
class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str

# 이메일 변경 요청 DTO (U3-내부 — 로그인 사용자 자가 관리, FR-28/BR-A10).
# currentPassword: 비밀번호 계정은 재인증 필수(감사 H7); 소셜-only는 생략 가능.
class EmailChangeRequestBody(BaseModel):
    newEmail: str
    currentPassword: str | None = None

# 계정 삭제(탈퇴) 요청 DTO (U3-내부, FR-28/BR-A11). 비밀번호 계정은 재인증 필수(감사 H7).
class DeleteAccountRequest(BaseModel):
    currentPassword: str | None = None


def _verification_link_base(request: Request) -> str:
    """이메일 인증 링크의 공개(클릭 가능) 베이스 URL을 만든다.

    프로덕션: 브라우저는 백엔드 호스트를 알 수 없고 `request.base_url`은 CloudFront/BFF/ALB
    뒤의 내부 호스트라 메일에 그대로 넣으면 클릭 불가 링크가 된다. 따라서 공개 앱 URL
    (`PUBLIC_APP_URL`, 예: https://docsuri.org)의 **프런트엔드 인증 페이지**(`/verify-email`)로
    링크한다 → 사용자가 클릭하면 프런트 페이지가 BFF 경유로 백엔드 GET /auth/verify-email를
    호출하고 친화적 결과 UI를 보여준다(원시 JSON 노출 금지). 로컬/개발: `PUBLIC_APP_URL`
    미설정 시 백엔드를 직접 부르는 기존 동작으로 폴백."""
    public = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if public:
        return f"{public}/verify-email"
    return str(request.base_url) + "auth/verify-email"

# DB 세션 디펜던시 스텁 (메인 App shell에서 오버라이드 예정)
def get_db_session() -> Session:
    raise NotImplementedError("Database session dependency must be overridden by app shell")

# 레포지토리 및 서비스 조립 디펜던시
def get_credential_repo(db: Session = Depends(get_db_session)) -> CredentialRepository:
    return CredentialRepository(db)

# 세션 저장소는 프로세스 단위 싱글톤으로 구성한다.
# 요청마다 SessionRepository()를 새로 만들면 그때마다 Redis ConnectionPool(max_connections=50)이
# 생성되어 커넥션 처닝/고갈을 유발하므로, lru_cache로 단일 인스턴스를 재사용한다.
# 풀 teardown은 App shell의 shutdown 이벤트에서 SessionRepository.close()로 1회 수행한다.
@lru_cache(maxsize=1)
def get_session_repo() -> SessionRepository:
    # REDIS_HOST 미설정 → localhost(로컬/테스트). 프로덕션은 App shell이 ElastiCache
    # 엔드포인트를 주입한다. REDIS_TLS: ElastiCache transit_encryption 클러스터는 TLS 필수.
    return SessionRepository(
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT") or "6379"),
        use_tls=os.getenv("REDIS_TLS", "").strip().lower() in {"1", "true", "yes", "on"},
    )

def get_recaptcha_client() -> RecaptchaClient:
    secret_key = os.getenv("RECAPTCHA_SECRET_KEY", "")
    return RecaptchaClient(secret_key=secret_key)

def get_session_manager(repo: SessionRepository = Depends(get_session_repo)) -> SessionManager:
    return SessionManager(repo)

def get_signup_service(
    request: Request,
    repo: CredentialRepository = Depends(get_credential_repo),
) -> SignupService:
    # 메인 App Shell 또는 DI 컨테이너에서 설정 주입. default는 로컬 모킹 클라이언트.
    # 프로덕션(ENV!=local·SES_MOCK!=true)은 SES — 발신자(SES_SENDER_EMAIL)·리전을 주입한다.
    # 발신자 미설정 시 SES Source가 비어 발송 실패하므로 검증된 도메인 주소를 기본값으로 둔다.
    observability = getattr(request.app.state, "observability", None)
    email_client = get_email_client(
        env=os.getenv("ENV", "local"),
        sender_email=os.getenv("SES_SENDER_EMAIL", "no-reply@docsuri.org"),
        region=os.getenv("SES_REGION", "ap-northeast-2"),
        observability_hub=observability,
    )
    return SignupService(repo, email_client, observability_hub=observability)

def get_auth_service(
    request: Request,
    repo: CredentialRepository = Depends(get_credential_repo),
    manager: SessionManager = Depends(get_session_manager),
    recaptcha: RecaptchaClient = Depends(get_recaptcha_client)
) -> AuthenticationService:
    observability = getattr(request.app.state, "observability", None)
    return AuthenticationService(repo, manager, recaptcha, observability_hub=observability)

def get_totp_service(
    repo: CredentialRepository = Depends(get_credential_repo),
) -> TotpService:
    return TotpService(repo)


def _reset_link_base(request: Request) -> str:
    """비밀번호 재설정 링크의 공개 베이스 URL. 프로덕션은 프런트 재설정 페이지(`/reset-password`),
    로컬은 백엔드 confirm 경로로 폴백(메일은 Mock가 콘솔에 출력)."""
    public = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if public:
        return f"{public}/reset-password"
    return str(request.base_url) + "auth/password-reset/confirm"


def get_password_reset_service(
    request: Request,
    repo: CredentialRepository = Depends(get_credential_repo),
    manager: SessionManager = Depends(get_session_manager),
) -> PasswordResetService:
    observability = getattr(request.app.state, "observability", None)
    email_client = get_email_client(
        env=os.getenv("ENV", "local"),
        sender_email=os.getenv("SES_SENDER_EMAIL", "no-reply@docsuri.org"),
        region=os.getenv("SES_REGION", "ap-northeast-2"),
        observability_hub=observability,
    )
    return PasswordResetService(repo, manager, email_client)


def _email_change_confirm_link_base(request: Request) -> str:
    """이메일 변경 확인 링크의 공개 베이스 URL. 프로덕션은 프런트 페이지(`/email-change/confirm`),
    로컬은 백엔드 confirm 경로로 폴백(메일은 Mock가 콘솔에 출력)."""
    public = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if public:
        return f"{public}/email-change/confirm"
    return str(request.base_url) + "auth/email-change/confirm"


def _email_change_revoke_link_base(request: Request) -> str:
    """이메일 변경 취소(revoke) 링크의 공개 베이스 URL. 현(기존) 주소로 보내는 알림 메일에 실린다.
    프로덕션은 프런트 페이지(`/email-change/revoke`), 로컬은 백엔드 revoke 경로로 폴백."""
    public = os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")
    if public:
        return f"{public}/email-change/revoke"
    return str(request.base_url) + "auth/email-change/revoke"


def get_account_management_service(
    request: Request,
    repo: CredentialRepository = Depends(get_credential_repo),
    manager: SessionManager = Depends(get_session_manager),
) -> AccountManagementService:
    observability = getattr(request.app.state, "observability", None)
    email_client = get_email_client(
        env=os.getenv("ENV", "local"),
        sender_email=os.getenv("SES_SENDER_EMAIL", "no-reply@docsuri.org"),
        region=os.getenv("SES_REGION", "ap-northeast-2"),
        observability_hub=observability,
    )
    return AccountManagementService(repo, manager, email_client)


def get_account_deletion_service(
    repo: CredentialRepository = Depends(get_credential_repo),
    manager: SessionManager = Depends(get_session_manager),
) -> AccountDeletionService:
    # AccountDeleted 발행자는 기본 LoggingAccountDeletedPublisher(실 EventBridge는 인프라 이월).
    return AccountDeletionService(repo, manager)


def get_social_verifier() -> GoogleOidcVerifier:
    # client_id/secret은 ECS 환경변수로 주입(미설정 시 토큰 교환이 실패 → Fail-Closed).
    return GoogleOidcVerifier(
        client_id=os.getenv("GOOGLE_OIDC_CLIENT_ID", ""),
        client_secret=os.getenv("GOOGLE_OIDC_CLIENT_SECRET", ""),
    )


def get_social_login_service(repo: CredentialRepository = Depends(get_credential_repo)) -> SocialLoginService:
    return SocialLoginService(repo)


def _app_base() -> str:
    """공개 앱(프런트) 베이스 URL — 소셜 로그인 후 리다이렉트 대상."""
    return os.getenv("PUBLIC_APP_URL", "").strip().rstrip("/")


def _social_redirect_uri(request: Request) -> str:
    """Google에 등록된 콜백 URI. 명시 env 우선, 없으면 공개 앱/요청 베이스에서 파생."""
    explicit = os.getenv("GOOGLE_OIDC_REDIRECT_URI", "").strip()
    if explicit:
        return explicit
    base = _app_base()
    if base:
        return f"{base}/auth/social/google/callback"
    return str(request.base_url) + "auth/social/google/callback"


def _clear_oidc_cookies(resp: RedirectResponse) -> None:
    resp.delete_cookie("oidc_state")
    resp.delete_cookie("oidc_nonce")
    resp.delete_cookie("oidc_verifier")


def _clear_session_cookie(resp: Response) -> None:
    """세션 쿠키를 set_cookie와 동일한 속성(httponly/secure/samesite=lax)으로 삭제한다.
    삭제 시 속성을 비우면 일부 브라우저/프록시에서 set과 매칭되지 않아 쿠키가 남을 수 있어,
    set_cookie와 동일 속성을 명시해 일관되게 제거한다."""
    resp.delete_cookie(key="session_id", httponly=True, secure=True, samesite="lax")


def _client_ip(request: Request) -> str | None:
    """reCAPTCHA remoteip 신호용 클라이언트 IP. ALB/CloudFront 뒤이므로 X-Forwarded-For의
    첫 홉(원 클라이언트)을 우선 사용하고, 없으면 직접 연결 주소로 폴백한다."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.client.host if request.client else None


# 이메일 발송/가입 엔드포인트 레이트리밋 (SEC-11, 감사 M1/M6) — 이메일 폭탄·대량 PENDING 생성 방어.
# 한도는 env로 조정 가능. per-email은 짧은 창의 엄격 한도, per-IP는 더 긴 창의 완화 한도.
_RL_EMAIL_LIMIT = int(os.getenv("EMAIL_RATELIMIT_PER_EMAIL") or "5")
_RL_EMAIL_WINDOW = int(os.getenv("EMAIL_RATELIMIT_EMAIL_WINDOW_SECONDS") or "900")  # 15분
_RL_IP_LIMIT = int(os.getenv("EMAIL_RATELIMIT_PER_IP") or "20")
_RL_IP_WINDOW = int(os.getenv("EMAIL_RATELIMIT_IP_WINDOW_SECONDS") or "3600")  # 1시간


@lru_cache(maxsize=1)
def _get_email_rate_limiter():
    """REDIS_HOST 설정 시 워커 간 공유 RedisRateLimiter, 아니면 프로세스 내 폴백(로컬/테스트)."""
    host = os.getenv("REDIS_HOST", "").strip()
    if host:
        return RedisRateLimiter(
            redis_host=host,
            redis_port=int(os.getenv("REDIS_PORT") or "6379"),
            use_tls=os.getenv("REDIS_TLS", "").strip().lower() in {"1", "true", "yes", "on"},
        )
    return InProcessWindowLimiter()


async def _enforce_email_rate_limit(request: Request, scope: str, email: str | None) -> None:
    """이메일 키(있으면)와 IP 키 양쪽에 레이트리밋을 적용한다. 초과 시 429.
    Redis 장애 시 limiter는 fail-open(가용성 우선) — 게이트웨이 per-IP 한도가 백스톱."""
    limiter = _get_email_rate_limiter()
    too_many = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요."
    norm = normalize_email(email) if email else ""
    if norm and not await limiter.allow(
        f"{scope}:email:{norm}", limit=_RL_EMAIL_LIMIT, window_seconds=_RL_EMAIL_WINDOW
    ):
        raise HTTPException(status_code=429, detail=too_many)
    ip = _client_ip(request) or "unknown"
    if not await limiter.allow(f"{scope}:ip:{ip}", limit=_RL_IP_LIMIT, window_seconds=_RL_IP_WINDOW):
        raise HTTPException(status_code=429, detail=too_many)


@router.post("/password-reset/request")
async def password_reset_request(
    req: PasswordResetRequest,
    request: Request,
    reset_svc: PasswordResetService = Depends(get_password_reset_service),
    db: Session = Depends(get_db_session),
):
    """비밀번호 재설정 요청 (FR-26/BR-A8). 계정 열거 방지 — 가입/상태와 무관하게 항상 동일 응답."""
    # 레이트리밋(SEC-11)은 try 밖에서 — 429는 열거방지 일반응답에 삼켜지지 않고 그대로 전파돼야 한다.
    await _enforce_email_rate_limit(request, "password-reset", req.email)
    base_url = _reset_link_base(request)
    try:
        await reset_svc.request_reset(req.email, base_url)
        db.commit()
    except Exception:
        # 어떤 경우에도 계정 존재/상태를 추론할 단서를 주지 않는다 (Fail-Closed, 일반 응답 유지).
        db.rollback()
    return {
        "status": "success",
        "message": "해당 이메일로 가입된 활성 계정이 있다면 비밀번호 재설정 링크를 보냈습니다. 메일함을 확인해 주세요.",
    }


@router.post("/password-reset/confirm")
async def password_reset_confirm(
    req: PasswordResetConfirm,
    reset_svc: PasswordResetService = Depends(get_password_reset_service),
    db: Session = Depends(get_db_session),
):
    """재설정 토큰으로 새 비밀번호 확정 (FR-26/BR-A8). 성공 시 해당 계정 전 세션 무효화."""
    try:
        await reset_svc.confirm_reset(req.token, req.newPassword)
        db.commit()
        return {"status": "success", "message": "비밀번호가 재설정되었습니다. 새 비밀번호로 로그인해 주세요."}
    except SessionStoreUnavailableException as e:
        # 세션 일괄 무효화 중 Redis 장애 — 401 위장 금지, 503으로 매핑 (DomainException 핸들러보다 먼저).
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="일시적으로 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.",
        ) from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="비밀번호 재설정 처리 중 서버 장애가 발생했습니다. (Fail-Closed)"
        ) from None


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    request: Request,
    response: Response,
    session_mgr: SessionManager = Depends(get_session_manager),
    mgmt_svc: AccountManagementService = Depends(get_account_management_service),
    db: Session = Depends(get_db_session),
):
    """로그인 사용자 비밀번호 변경 (FR-28/BR-A10). 성공 시 전 세션 무효화 + 쿠키 삭제(재로그인 필요)."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        await mgmt_svc.change_password(principal.user_id, req.currentPassword, req.newPassword)
        db.commit()
        _clear_session_cookie(response)
        return {"status": "success", "message": "비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인해 주세요."}
    except (UnauthorizedException, SessionExpiredException) as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except SessionStoreUnavailableException as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="일시적으로 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="비밀번호 변경 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.post("/email-change/request")
async def email_change_request(
    req: EmailChangeRequestBody,
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
    mgmt_svc: AccountManagementService = Depends(get_account_management_service),
    db: Session = Depends(get_db_session),
):
    """로그인 사용자 이메일 변경 요청 (FR-28/BR-A10). 새 주소로 확인 링크 + 현 주소로 알림(M2).
    이미 사용 중인 주소는 존재를 노출하지 않기 위해 동일 일반 응답을 반환한다(열거 방지)."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    await _enforce_email_rate_limit(request, "email-change", req.newEmail)
    confirm_base = _email_change_confirm_link_base(request)
    revoke_base = _email_change_revoke_link_base(request)
    try:
        principal = await session_mgr.verify(session_id)
        await mgmt_svc.request_email_change(
            principal.user_id, req.newEmail, confirm_base,
            current_password=req.currentPassword, revoke_link_base=revoke_base,
        )
        db.commit()
        return {"status": "success", "message": "새 이메일 주소로 확인 링크를 보냈습니다. 메일함을 확인해 주세요."}
    except (UnauthorizedException, SessionExpiredException) as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="이메일 변경 요청 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.get("/email-change/confirm")
async def email_change_confirm(
    token: str = Query(..., description="이메일 변경 확인 토큰"),
    mgmt_svc: AccountManagementService = Depends(get_account_management_service),
    db: Session = Depends(get_db_session),
):
    """이메일 변경 확인 링크 엔드포인트 (FR-28/BR-A10). 토큰 검증 후 로그인 식별자에 새 주소 반영."""
    try:
        await mgmt_svc.confirm_email_change(token)
        db.commit()
        return {"status": "success", "message": "이메일 주소가 변경되었습니다."}
    except SessionStoreUnavailableException as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="일시적으로 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="이메일 변경 확인 중 서버 장애가 발생했습니다.") from None


@router.get("/email-change/revoke")
async def email_change_revoke(
    token: str = Query(..., description="이메일 변경 취소 토큰"),
    mgmt_svc: AccountManagementService = Depends(get_account_management_service),
    db: Session = Depends(get_db_session),
):
    """이메일 변경 취소 링크 엔드포인트 (FR-28/BR-A10, 감사 H5). 현(기존) 주소 소유자가 세션 없이도
    보류 중인 변경을 차단할 수 있다. 토큰은 알림 메일에만 실리며 단일 사용."""
    try:
        await mgmt_svc.revoke_email_change(token)
        db.commit()
        return {"status": "success", "message": "이메일 변경 요청이 취소되었습니다."}
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="이메일 변경 취소 중 서버 장애가 발생했습니다.") from None


@router.post("/account/delete")
async def delete_account(
    request: Request,
    response: Response,
    req: DeleteAccountRequest | None = None,
    session_mgr: SessionManager = Depends(get_session_manager),
    deletion_svc: AccountDeletionService = Depends(get_account_deletion_service),
    db: Session = Depends(get_db_session),
):
    """로그인 사용자 계정 삭제(탈퇴) 요청 (FR-28/BR-A11). 소프트 삭제 + 전 세션 즉시 무효화.
    유예 기간 내 복구 가능; 영구 파기는 유예 경과 후 비동기 잡이 수행한다. 비밀번호 계정은
    현재 비밀번호 재인증을 요구한다(감사 H7)."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        await deletion_svc.request_deletion(
            principal.user_id, current_password=req.currentPassword if req else None
        )
        db.commit()
        _clear_session_cookie(response)
        return {"status": "success", "message": "계정이 탈퇴 처리되었습니다. 유예 기간 내에는 복구할 수 있습니다."}
    except (UnauthorizedException, SessionExpiredException) as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except SessionStoreUnavailableException as e:
        db.rollback()
        raise HTTPException(status_code=503, detail="일시적으로 처리할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="계정 삭제 처리 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.get("/social/google/start")
async def social_google_start(
    request: Request,
    verifier: GoogleOidcVerifier = Depends(get_social_verifier),
):
    """소셜 로그인 시작 (FR-27) — state·nonce 발급(httpOnly 쿠키) 후 Google 인가 페이지로 리다이렉트."""
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    # PKCE(감사 #8): verifier는 쿠키로만 보관하고 challenge(S256)만 Google에 보낸다.
    code_verifier = secrets.token_urlsafe(64)
    auth_url = verifier.build_authorization_url(
        _social_redirect_uri(request), state, nonce, pkce_challenge(code_verifier)
    )
    resp = RedirectResponse(auth_url, status_code=302)
    # samesite=lax라야 Google 콜백 복귀 GET에 쿠키가 실린다. 10분 단명.
    cookie = {"httponly": True, "secure": True, "samesite": "lax", "max_age": 600}
    resp.set_cookie("oidc_state", state, **cookie)
    resp.set_cookie("oidc_nonce", nonce, **cookie)
    resp.set_cookie("oidc_verifier", code_verifier, **cookie)
    return resp


@router.get("/social/google/callback")
async def social_google_callback(
    request: Request,
    code: str = Query(...),
    state: str = Query(...),
    verifier: GoogleOidcVerifier = Depends(get_social_verifier),
    social_svc: SocialLoginService = Depends(get_social_login_service),
    session_mgr: SessionManager = Depends(get_session_manager),
    repo: CredentialRepository = Depends(get_credential_repo),
    db: Session = Depends(get_db_session),
):
    """소셜 로그인 콜백 (FR-27/BR-A9) — CSRF(state)·nonce 검증 → 신원 조정 → 세션 발급 →
    앱으로 리다이렉트. 기존 *비밀번호* 계정과 충돌(H1)하면 자동 병합 없이 연결 안내 페이지로 보낸다."""
    cookie_state = request.cookies.get("oidc_state")
    cookie_nonce = request.cookies.get("oidc_nonce")
    cookie_verifier = request.cookies.get("oidc_verifier")
    # CSRF: 쿼리 state와 쿠키 state가 일치해야 한다(상수시간 비교).
    if not cookie_state or not secrets.compare_digest(cookie_state, state):
        raise HTTPException(status_code=400, detail="소셜 로그인 상태 검증에 실패했습니다. 다시 시도해 주세요.")
    try:
        claims = await verifier.exchange_and_verify(
            code, _social_redirect_uri(request), cookie_nonce or "", cookie_verifier
        )
        account_id = social_svc.reconcile(OidcProvider.GOOGLE, claims)
        db.commit()
    except SocialLinkConfirmationRequired:
        db.commit()  # PENDING_CONFIRMATION 신원 기록됨(추후 비밀번호 로그인 후 연결 — 이월).
        resp = RedirectResponse((_app_base() or "") + "/social-link-required", status_code=302)
        _clear_oidc_cookies(resp)
        return resp
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="소셜 로그인 처리 중 서버 장애가 발생했습니다. (Fail-Closed)") from None

    account = repo.get_by_id(account_id)
    if account is None:
        raise HTTPException(status_code=500, detail="소셜 로그인 계정 조회에 실패했습니다.")
    try:
        role = UserRole(account.role)
    except (ValueError, TypeError):
        role = UserRole.USER
    # 소셜 로그인은 로그인 시점 MFA 미통과(관리자 제어 평면은 별도 TOTP 승격 필요, BR-A7).
    principal = Principal(user_id=account_id, role=role, mfa_verified=False)
    try:
        session = await session_mgr.issue(principal)
    except SessionStoreUnavailableException as e:
        raise HTTPException(status_code=503, detail="일시적으로 로그인할 수 없습니다. 잠시 후 다시 시도해 주세요.") from e

    resp = RedirectResponse(_app_base() or "/", status_code=302)
    resp.set_cookie(
        key="session_id", value=session.handle, httponly=True, secure=True,
        samesite="lax", max_age=30 * 24 * 60 * 60,
    )
    _clear_oidc_cookies(resp)
    return resp


@router.post("/social/link")
async def social_link_confirm(
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
    social_svc: SocialLoginService = Depends(get_social_login_service),
    db: Session = Depends(get_db_session),
):
    """보류 중인 소셜 연결 확정 (FR-27/BR-A9 H1). 비밀번호 로그인으로 소유권을 증명한 사용자가
    자신의 PENDING_CONFIRMATION 소셜 신원을 LINKED로 승격한다."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        linked = social_svc.confirm_pending_links(principal.user_id)
        db.commit()
        message = "소셜 계정 연결이 완료되었습니다." if linked else "연결할 보류 중인 소셜 계정이 없습니다."
        return {"status": "success", "linked": linked, "message": message}
    except (UnauthorizedException, SessionExpiredException) as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="소셜 연결 확정 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.post("/signup", response_model=SignupResult, status_code=201)
async def signup(
    req: SignupRequest,
    request: Request,
    signup_svc: SignupService = Depends(get_signup_service),
    db: Session = Depends(get_db_session)
):
    """
    일반 사용자 공개 회원가입 (US-A1)
    가입 성공 시 PENDING 계정이 생성되며 이메일 인증 발송 처리됩니다.
    """
    # 메일 인증용 공개(클릭 가능) 베이스 링크 생성 (프로덕션은 PUBLIC_APP_URL→BFF 경유)
    await _enforce_email_rate_limit(request, "signup", req.email)
    base_url = _verification_link_base(request)

    try:
        account_id = await signup_svc.register(
            email=req.email,
            password=req.password,
            verification_link_base=base_url
        )
        # verify-all-then-commit: 컨트롤러 엔드포인트 도달 완료 시점에만 세션 최종 commit 강제
        db.commit()
        # 공유 SSOT DTO(docsuri_shared) — 필드명이 곧 wire 키(accountId)다.
        return SignupResult(accountId=account_id)

    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="회원가입 처리 중 알 수 없는 장애가 발생했습니다. (Fail-Closed)") from None


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    req: LoginRequest,
    x_recaptcha_token: str | None = Header(None, alias="X-Recaptcha-Token"),
    auth_svc: AuthenticationService = Depends(get_auth_service),
    db: Session = Depends(get_db_session)
):
    """
    사용자 로그인 및 세션 쿠키 발급 (US-A2)
    인증 성공 시 Sliding(2시간) / Absolute(30일) 만료 속성의 보안 쿠키를 클라이언트에 바인딩합니다.
    """
    try:
        # 인증 검증 및 세션 토큰 획득 (내부에서 reCAPTCHA, 실패 지연, 해시 업그레이드 제어)
        session_handle = await auth_svc.authenticate(
            email=req.email,
            password=req.password,
            recaptcha_token=x_recaptcha_token,
            remote_ip=_client_ip(request),
        )
        db.commit() # 실패 카운트 리셋 등 계정 상태 커밋

        # SEC-12: 보안 세션 토큰은 body DTO가 아닌 httpOnly 쿠키로만 외부 전송
        response.set_cookie(
            key="session_id",
            value=session_handle,
            httponly=True,
            secure=True,          # HTTPS 환경 강제
            samesite="lax",       # CORS CSRF 완화 정책 적용
            max_age=30 * 24 * 60 * 60 # 30일 절대 만료 세션
        )

        return {"status": "success", "message": "로그인에 성공했습니다."}

    except SessionStoreUnavailableException as e:
        # 세션 저장소(Redis) 장애는 인증 실패가 아니라 인프라 가용성 장애다. 자격증명은 이미 검증됐으므로
        # 401(자격증명 오류)로 위장해선 안 된다 — 사용자에겐 "정상 자격증명인데 거부"로 보이고 운영은 장애를
        # 놓친다. SessionStoreUnavailableException은 DomainException 서브클래스이므로 반드시 401 핸들러보다
        # 먼저 잡아 503(일시적 서비스 불가)로 매핑한다 (Fail-Closed지만 올바른 상태코드).
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="일시적으로 로그인할 수 없습니다. 잠시 후 다시 시도해 주세요. (세션 저장소 장애)",
        ) from e
    except DomainException as e:
        db.rollback()
        # 자격증명 비노출(SEC-BR-2): "이메일 또는 비밀번호가 올바르지 않습니다." 등으로 일반화된 401 반환
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="인증 처리 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.post("/account/reactivate")
async def reactivate_account(
    request: Request,
    response: Response,
    req: LoginRequest,
    x_recaptcha_token: str | None = Header(None, alias="X-Recaptcha-Token"),
    auth_svc: AuthenticationService = Depends(get_auth_service),
    db: Session = Depends(get_db_session),
):
    """유예 기간 내 소유자 본인 계정 복구 (FR-28/BR-A11 M1). 세션은 소프트 삭제 시 전부 무효화되고
    로그인은 DEACTIVATED를 차단하므로, 복구는 **자격증명 재증명**으로 소유권을 입증한다(IDOR 방지).
    인증·실패지연·CAPTCHA·계정열거 방어는 로그인과 동일 경로를 재사용한다. 성공 시 ACTIVE로 복원하고
    바로 세션을 발급한다. 잘못된 자격증명/이미 파기/복구 불가는 로그인과 동일한 일반 오류로 응답한다."""
    try:
        session_handle = await auth_svc.authenticate(
            email=req.email,
            password=req.password,
            recaptcha_token=x_recaptcha_token,
            remote_ip=_client_ip(request),
            reactivate=True,
        )
        db.commit()
        response.set_cookie(
            key="session_id",
            value=session_handle,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
        )
        return {"status": "success", "message": "계정이 복구되었습니다."}
    except SessionStoreUnavailableException as e:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="일시적으로 복구할 수 없습니다. 잠시 후 다시 시도해 주세요. (세션 저장소 장애)",
        ) from e
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="계정 복구 중 서버 장애가 발생했습니다. (Fail-Closed)") from None


@router.get("/verify-email")
async def verify_email(
    token: str = Query(..., description="이메일 활성화 토큰"),
    signup_svc: SignupService = Depends(get_signup_service),
    db: Session = Depends(get_db_session)
):
    """PENDING 계정 가입 메일 링크 인증 엔드포인트 (US-A1, BR-A5)"""
    try:
        await signup_svc.verify_email(token)
        db.commit()
        return {"status": "success", "message": "이메일 인증이 성공적으로 완료되었습니다. 이제 로그인할 수 있습니다."}
    except DomainException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="이메일 검증 처리 중 서버 장애가 발생했습니다.") from None


@router.post("/resend-verification")
async def resend_verification(
    req: ResendVerificationRequest,
    request: Request,
    signup_svc: SignupService = Depends(get_signup_service),
    db: Session = Depends(get_db_session),
):
    """PENDING 계정에 인증 메일을 재발송한다 (US-A1 복구 경로 — 가입했지만 메일 미수신 시).

    계정 열거 방지(SEC): 입력 이메일의 가입/상태와 무관하게 항상 동일한 일반 응답을 반환한다.
    재발송 가능 여부(부존재/이미 활성 등)는 노출하지 않는다."""
    await _enforce_email_rate_limit(request, "resend-verification", req.email)
    base_url = _verification_link_base(request)
    try:
        await signup_svc.resend_verification(req.email, base_url)
        db.commit()
    except Exception:
        # 어떤 경우에도 계정 존재/상태를 추론할 단서를 주지 않는다 (Fail-Closed, 일반 응답 유지).
        db.rollback()
    return {
        "status": "success",
        "message": "해당 이메일이 가입되어 있고 인증 전이라면 인증 메일을 다시 보냈습니다. 메일함을 확인해 주세요.",
    }


@router.get("/session", response_model=SessionInfo)
async def get_session(
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """현재 세션의 유효성 검증 및 정보 조회 (Sliding Expiration 갱신 연동) (US-A2, BR-A3)"""
    # 쿠키로부터 세션 토큰 추출
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")

    try:
        # verify() 호출 시 내부적으로 sliding 만료 갱신 및 만료 검증 강제
        principal = await session_mgr.verify(session_id)

        # 30일 절대만료 시점 또는 sliding 2시간 만료 시점 제공
        # 편의상 sliding 2시간 만료 시점으로 expiresAt 반환 (shared SessionInfo는 tz-aware 요구).
        expires_at = datetime.now(UTC) + timedelta(hours=2)

        # 공유 SSOT DTO(docsuri_shared) — 필드명이 곧 wire 키(userId/expiresAt)다.
        return SessionInfo(userId=principal.user_id, expiresAt=expires_at)

    except (UnauthorizedException, SessionExpiredException) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except Exception:
        raise HTTPException(status_code=500, detail="세션 검증 중 서버 오류가 발생했습니다. (Fail-Closed)") from None


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """현재 세션을 수동 파기하고 보안 쿠키를 삭제합니다."""
    session_id = request.cookies.get("session_id")
    if session_id:
        try:
            await session_mgr.invalidate(session_id)
        except SessionStoreUnavailableException:
            # 세션 저장소 장애 중에는 서버측 무효화가 불가능하다(저장소 다운). 쿠키는 지우되 미완료를
            # 명시적으로 로깅한다 — 만료(TTL)로 정리된다. *예상치 못한* 예외는 더 이상 삼키지 않고
            # 전파시켜 500(Fail-Closed)·관측이 되게 한다(기존 `except Exception: pass`의 사일런트 fail-open 제거).
            logger.warning("Logout could not invalidate the server session (store unavailable); cookie cleared, session will expire by TTL.")

    response.delete_cookie(key="session_id")
    return {"status": "success", "message": "로그아웃되었습니다."}


@router.post("/mfa/enroll")
async def mfa_enroll(
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
    credential_repo: CredentialRepository = Depends(get_credential_repo),
    totp_svc: TotpService = Depends(get_totp_service),
    db: Session = Depends(get_db_session),
):
    """현재 로그인 사용자의 TOTP MFA를 등록하고 otpauth:// 프로비저닝 URI(QR용)를 반환한다 (BR-A7).
    관리자 제어 평면 접근 전 1회 등록이 필요하며, 재등록 시 기존 시크릿을 교체한다."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        account = credential_repo.get_by_id(principal.user_id)
        if not account:
            raise HTTPException(status_code=401, detail="유효하지 않은 세션입니다.")
        provisioning_uri = totp_svc.enroll(account)
        db.commit()
        # 평문 시크릿은 응답에 포함하지 않는다 — otpauth URI(QR)만 전달 (SEC-3).
        return {"provisioningUri": provisioning_uri}
    except (UnauthorizedException, SessionExpiredException) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="MFA 등록 중 서버 오류가 발생했습니다. (Fail-Closed)") from None


@router.post("/mfa/verify")
async def mfa_verify(
    req: MfaVerifyRequest,
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
    credential_repo: CredentialRepository = Depends(get_credential_repo),
    totp_svc: TotpService = Depends(get_totp_service),
):
    """제출된 TOTP 코드를 검증하고, 통과 시 현재 세션을 MFA 통과 상태로 승격한다 (2단계, BR-A7)."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        account = credential_repo.get_by_id(principal.user_id)
        if not account or not totp_svc.verify(account, req.code):
            # 코드 불일치/미등록 — 자격증명 비노출(SEC-9) 일반화 메시지로 거부 (Fail-Closed)
            raise HTTPException(status_code=401, detail="MFA 코드 검증에 실패했습니다.")
        await session_mgr.elevate_mfa(session_id)
        return {"status": "success", "message": "MFA 인증이 완료되었습니다."}
    except (UnauthorizedException, SessionExpiredException) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="MFA 검증 중 서버 오류가 발생했습니다. (Fail-Closed)") from None


@router.get("/admin/whoami")
async def admin_whoami(
    request: Request,
    session_mgr: SessionManager = Depends(get_session_manager),
):
    """관리자 제어 평면 예시 엔드포인트 — ADMIN 역할 + TOTP MFA 통과 세션만 허용한다 (BR-A7).
    인가 판정은 단일 권위 AuthorizationGuard.authorize_admin에 위임한다 (SEC-8)."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    try:
        principal = await session_mgr.verify(session_id)
        decision = AuthorizationGuard.authorize_admin(principal, mfa_verified=principal.mfa_verified)
        if decision != Decision.ALLOW:
            # 역할 부족 또는 MFA 미통과 — 기본 거부(SEC-8). 구체 사유는 노출하지 않는다(SEC-9).
            raise HTTPException(status_code=403, detail="관리자 권한 또는 MFA 인증이 필요합니다.")
        return {"userId": principal.user_id, "role": principal.role.value, "mfaVerified": True}
    except (UnauthorizedException, SessionExpiredException) as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="관리자 인가 검증 중 서버 오류가 발생했습니다. (Fail-Closed)") from None
