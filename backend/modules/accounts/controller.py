import os
from datetime import UTC, datetime, timedelta
from functools import lru_cache

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .guard import AuthorizationGuard, Decision
from .integrations.email import get_email_client
from .integrations.recaptcha import RecaptchaClient
from .models import (
    DomainException,
    SessionExpiredException,
    SessionStoreUnavailableException,
    UnauthorizedException,
)
from .repository.credential import CredentialRepository
from .repository.session import SessionRepository
from .schemas import LoginRequest, SessionInfo, SignupRequest, SignupResult
from .services.auth import AuthenticationService
from .services.session_manager import SessionManager
from .services.signup import SignupService
from .services.totp import TotpService

router = APIRouter(prefix="/auth", tags=["Accounts/Auth"])


# U3-내부 관리자 MFA DTO (공유 SSOT 계약 아님 — admin MFA는 U3-private이라 docsuri_shared에 없음).
class MfaVerifyRequest(BaseModel):
    code: str

# 인증 메일 재발송 요청 DTO (U3-내부 — 가입 후 메일 미수신 복구 경로용).
class ResendVerificationRequest(BaseModel):
    email: str


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
            recaptcha_token=x_recaptcha_token
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
        except Exception:
            pass # 로그아웃 예외는 무시하고 클라이언트 쿠키 클리어 진행

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
