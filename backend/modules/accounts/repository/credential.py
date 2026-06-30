from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String
from sqlalchemy.orm import Session, declarative_base

from ..models import AccountStatus, DomainException, OidcProvider

Base = declarative_base()

# 회원탈퇴 스냅샷 보관 기간 (분쟁/법적 대응) — 5년. 하드 파기 시점에 accounts-owned 최소 스냅샷을
# 이 기간만큼 보관하고, purge_after 경과 후 별도 배치가 하드 삭제한다(배치는 후속 작업).
WITHDRAWAL_BACKUP_RETENTION_DAYS = 365 * 5

class AccountTable(Base):
    __tablename__ = "accounts"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    # BR-A13: 이메일을 제공하지 않는 프로바이더(ORCID) 가입 계정은 email=NULL. UNIQUE는 유지하되
    # Postgres는 다중 NULL을 유일성 위반으로 보지 않으므로 ORCID 계정 다수가 공존한다.
    email = Column(String(254), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    status = Column(String(20), default=AccountStatus.PENDING.value, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    failure_count = Column(Integer, default=0, nullable=False)
    last_failed_at = Column(DateTime, nullable=True)
    # BR-A7: 역할 단일 출처는 DB(공개 가입=USER; ADMIN은 시딩만). totp_secret은 MFA 등록 시 채워진다.
    role = Column(String(20), default="USER", nullable=False)
    totp_secret = Column(String(64), nullable=True)
    # U10: 동의 항목 — 개인정보처리방침/이용약관은 필수(가입 시 거부하면 가입 자체가 안 되므로
    # 항상 True), 야간 푸시(이메일, 최신/관심 논문 등재 알림)만 선택이라 실제로 토글된다.
    privacy_policy_agreed = Column(Boolean, default=True, nullable=False)
    privacy_policy_agreed_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    terms_of_service_agreed = Column(Boolean, default=True, nullable=False)
    terms_of_service_agreed_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    nightly_push_agreed = Column(Boolean, default=False, nullable=False)
    nightly_push_agreed_at = Column(DateTime, nullable=True)


class VerificationTokenTable(Base):
    __tablename__ = "verification_tokens"

    token = Column(String(64), primary_key=True)
    email = Column(String(254), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)


class PasswordResetTokenTable(Base):
    """비밀번호 재설정 토큰 (FR-26 / BR-A8). 토큰은 평문이 아닌 SHA-256 해시로 저장한다
    (DB 유출 시 토큰 무력화). 단일 사용은 확정(confirm) 시 즉시 삭제로 강제한다."""
    __tablename__ = "password_reset_tokens"

    token_hash = Column(String(64), primary_key=True)
    email = Column(String(254), nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)


# 소셜 전용(비밀번호 없는) 계정의 password_hash 센티넬. 유효한 argon2 인코딩이 아니므로
# 비밀번호 로그인 검증(verify)은 항상 실패한다 → 소셜-only 계정은 비밀번호로 로그인 불가.
# has_usable_password()가 이 값을 "사용 가능한 비밀번호 없음"으로 판정한다 (H1/BR-A9).
SOCIAL_NO_PASSWORD_HASH = "!"


def has_usable_password(account: "AccountTable") -> bool:
    """계정이 *사용 가능한 비밀번호 자격증명*을 가졌는지 (H1 자동연결 가드용)."""
    return bool(account.password_hash) and account.password_hash != SOCIAL_NO_PASSWORD_HASH


class SocialIdentityTable(Base):
    """소셜 신원 연결 (FR-27 / BR-A9·BR-A13). (provider, provider_subject)는 전역 유일.
    status: LINKED | PENDING_CONFIRMATION(H1 — 기존 비밀번호 계정 명시적 연결 대기).
    orcid_*: ORCID(provider='ORCID') 공개 프로필 캐시 — 마이그레이션 006이 추가, provider!='ORCID'
    행에서는 항상 NULL. works(논문 1:N)는 캐시하지 않고 마이페이지 조회 시마다 ORCID API에서 취득."""
    __tablename__ = "social_identities"

    provider = Column(String(20), primary_key=True)
    provider_subject = Column(String(255), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    # BR-A13: 이메일 미제공 프로바이더(ORCID)는 NULL (마이그레이션 009가 NOT NULL 해제).
    email_at_link = Column(String(254), nullable=True)
    linked_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    status = Column(String(24), default="LINKED", nullable=False)
    orcid_name = Column(String(255), nullable=True)
    orcid_affiliation = Column(String(255), nullable=True)
    orcid_synced_at = Column(DateTime, nullable=True)


class EmailChangeRequestTable(Base):
    """이메일 변경 요청 (FR-28 / BR-A10). 검증 완료(confirm) 전까지 Account.email(로그인
    식별자)은 그대로 두고, 토큰 검증 시에만 newEmail로 반영한다(지연 반영). 토큰은 SHA-256
    해시로만 저장하며, 계정당 활성 요청은 1개로 제한(생성 시 선삭제)."""
    __tablename__ = "email_change_requests"

    token_hash = Column(String(64), primary_key=True)
    account_id = Column(String(36), nullable=False, index=True)
    new_email = Column(String(254), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    # 현(기존) 주소 소유자가 변경을 취소(revoke)할 수 있게 하는 별도 단일사용 토큰의 SHA-256 해시.
    # 알림 메일에 이 토큰 링크를 실어, 세션 없이도 탈취 시도를 본인이 차단할 수 있게 한다(H5).
    revoke_token_hash = Column(String(64), nullable=True, index=True)


class AccountDeletionTable(Base):
    """계정 삭제 레코드 (FR-28 / BR-A11). 소프트 삭제 시점에 DEACTIVATED로 생성하고,
    purge_after 경과 후 비동기 잡이 PURGED로 전이하며 자격증명을 영구 삭제한다. state로
    멱등성을 보장(이미 PURGED면 재처리 안 함)."""
    __tablename__ = "account_deletions"

    account_id = Column(String(36), primary_key=True)
    requested_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)
    purge_after = Column(DateTime, nullable=False, index=True)
    state = Column(String(20), default=AccountStatus.DEACTIVATED.value, nullable=False)
    # S2: 파기 반복 실패 횟수. 임계 초과 시 state=PURGE_FAILED(DLQ)로 격리해 무한 재시도를 끊는다.
    purge_attempts = Column(Integer, default=0, nullable=False)


class AccountWithdrawalBackupTable(Base):
    """회원탈퇴 시점 accounts 스냅샷 (5년 보관, purge_after 이후 하드 삭제 대상). 감사 #4 / PR #193 복원.

    하드 파기(영구 삭제) 직전에 accounts가 *소유한* 데이터만 담는다. 분쟁/법적 대응용 최소 기록이며,
    password_hash·totp_secret은 재로그인 복구 목적이 아니므로 의도적으로 제외한다(크리덴셜 비보관).
    라이브러리(U4)·행동/관심(U9)·social_identities(1:N)는 여기 담을 수 없고 각 모듈이 AccountDeleted
    이벤트를 구독해 자기 데이터를 따로 백업/정리한다(이 테이블 범위 밖, 후속 작업)."""

    __tablename__ = "account_withdrawal_backups"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid4()))
    original_account_id = Column(String(36), nullable=False, index=True)
    email = Column(String(254), nullable=True)
    status = Column(String(20), nullable=False)
    signed_up_at = Column(DateTime, nullable=False)
    withdrawn_at = Column(DateTime, nullable=False)
    purge_after = Column(DateTime, nullable=False, index=True)
    backed_up_at = Column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class CredentialRepository:
    """SQLAlchemy 기반의 Credential 및 계정 영속성 저장소 (PostgreSQL 매핑)"""
    
    def __init__(self, db_session: Session):
        self._session = db_session
        # 타이밍 공격 방어용 더미 해시 (argon2 KDF로 미리 만들어둔 일반적인 형태의 더미 값)
        # 실제 계정이 없을 때 이 더미 해시와 입력 패스워드를 대조 연산함으로써 시간 유추를 불가능하게 함
        self.dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$abcdefghijklmnopqrstuvwxyz0123456789abcd"

    def commit(self) -> None:
        """현재 트랜잭션을 커밋한다 (파기 잡의 행별 커밋 등 유닛-오브-워크 경계용)."""
        self._session.commit()

    def rollback(self) -> None:
        """현재 트랜잭션을 롤백한다 (행별 실패 격리용)."""
        self._session.rollback()

    def get_by_email(self, email: str) -> AccountTable | None:
        """이메일로 계정을 조회합니다."""
        return self._session.query(AccountTable).filter(AccountTable.email == email).first()

    def get_by_id(self, account_id: str) -> AccountTable | None:
        """식별자로 계정을 조회합니다."""
        return self._session.query(AccountTable).filter(AccountTable.id == account_id).first()

    def create_account(self, email: str, password_hash: str) -> AccountTable:
        """
        신규 계정을 생성합니다.
        verify-all-then-commit 원칙에 따라, 본 메서드는 DB 메모리에 기록만 수행하며
        실제 commit은 서비스 레이어의 검증이 모두 끝난 최종 시점에 외부 세션에 의해 수행됩니다.
        """
        # 이메일 중복 최종 확인
        existing = self.get_by_email(email)
        if existing:
            raise DomainException("이미 등록된 이메일 주소입니다.")

        account = AccountTable(
            id=str(uuid4()),
            email=email,
            password_hash=password_hash,
            status=AccountStatus.PENDING.value,
            created_at=datetime.now(UTC),
            failure_count=0
        )
        self._session.add(account)
        self._session.flush() # ID 등 임시 생성을 위해 메모리 플러시
        return account

    def update_account(self, account: AccountTable) -> None:
        """계정 정보를 업데이트합니다. (실패 횟수 누적, 상태 변경, 해시 재설정 등)"""
        self._session.add(account)
        self._session.flush()

    def create_verification_token(self, email: str, token: str, expires_at: datetime) -> VerificationTokenTable:
        """이메일 인증 토큰을 생성합니다."""
        # 기존 해당 이메일의 만료된 토큰이 있다면 삭제
        self._session.query(VerificationTokenTable).filter(VerificationTokenTable.email == email).delete()
        
        token_record = VerificationTokenTable(
            token=token,
            email=email,
            expires_at=expires_at
        )
        self._session.add(token_record)
        self._session.flush()
        return token_record

    def get_verification_token(self, token: str) -> VerificationTokenTable | None:
        """토큰 값으로 이메일 인증 토큰 레코드를 조회합니다."""
        return self._session.query(VerificationTokenTable).filter(VerificationTokenTable.token == token).first()

    def delete_verification_token(self, token: str) -> None:
        """인증 완료 후 사용한 이메일 인증 토큰을 파기합니다."""
        self._session.query(VerificationTokenTable).filter(VerificationTokenTable.token == token).delete()
        self._session.flush()

    def create_reset_token(self, email: str, token_hash: str, expires_at: datetime) -> PasswordResetTokenTable:
        """비밀번호 재설정 토큰을 생성합니다 (FR-26/BR-A8). 토큰 해시만 저장하며,
        같은 이메일의 기존 미사용 토큰은 선삭제하여 활성 토큰을 1개로 제한합니다."""
        self._session.query(PasswordResetTokenTable).filter(PasswordResetTokenTable.email == email).delete()
        rec = PasswordResetTokenTable(token_hash=token_hash, email=email, expires_at=expires_at)
        self._session.add(rec)
        self._session.flush()
        return rec

    def get_reset_token(self, token_hash: str) -> PasswordResetTokenTable | None:
        """토큰 해시로 재설정 토큰 레코드를 조회합니다."""
        return (
            self._session.query(PasswordResetTokenTable)
            .filter(PasswordResetTokenTable.token_hash == token_hash)
            .first()
        )

    def delete_reset_token(self, token_hash: str) -> None:
        """사용/만료된 재설정 토큰을 파기합니다 (단일 사용 강제)."""
        self._session.query(PasswordResetTokenTable).filter(
            PasswordResetTokenTable.token_hash == token_hash
        ).delete()
        self._session.flush()

    def get_social_identity(self, provider: str, subject: str) -> SocialIdentityTable | None:
        """(provider, provider_subject)로 소셜 신원 연결을 조회합니다 (FR-27)."""
        return (
            self._session.query(SocialIdentityTable)
            .filter(
                SocialIdentityTable.provider == provider,
                SocialIdentityTable.provider_subject == subject,
            )
            .first()
        )

    def list_social_identities(self, account_id: str) -> list[SocialIdentityTable]:
        """계정에 연결된 소셜 신원 전부를 조회합니다 (U10 로그인 경로 표기용)."""
        return (
            self._session.query(SocialIdentityTable)
            .filter(SocialIdentityTable.account_id == account_id)
            .all()
        )

    def create_social_identity(
        self, provider: str, subject: str, account_id: str, email_at_link: str | None, status: str = "LINKED"
    ) -> SocialIdentityTable:
        """소셜 신원을 계정에 연결합니다 (FR-27/BR-A9·BR-A13). email_at_link은 이메일 미제공
        프로바이더(ORCID)에서 None."""
        rec = SocialIdentityTable(
            provider=provider,
            provider_subject=subject,
            account_id=account_id,
            email_at_link=email_at_link,
            status=status,
        )
        self._session.add(rec)
        self._session.flush()
        return rec

    def confirm_social_links_for_account(self, account_id: str) -> int:
        """유예(PENDING_CONFIRMATION) 소셜 신원을 LINKED로 승격한다 (H1 명시 연결, BR-A9).
        소유권은 호출 측(비밀번호 로그인 세션)이 이미 증명했다. 승격한 행 수를 반환한다."""
        rows = (
            self._session.query(SocialIdentityTable)
            .filter(
                SocialIdentityTable.account_id == account_id,
                SocialIdentityTable.status == "PENDING_CONFIRMATION",
            )
            .all()
        )
        for r in rows:
            r.status = "LINKED"
            self._session.add(r)
        self._session.flush()
        return len(rows)

    def create_social_account(self, email: str | None) -> AccountTable:
        """소셜 가입 — 비밀번호 없는 ACTIVE 계정 생성. 이메일 제공 프로바이더(Google)는 BR-A9
        (검증 이메일이므로 PENDING 우회), 이메일 미제공 프로바이더(ORCID)는 BR-A13 (email=NULL).
        password_hash는 매칭 불가 센티넬이라 비밀번호 로그인은 불가."""
        if email is not None and self.get_by_email(email):
            raise DomainException("이미 등록된 이메일 주소입니다.")
        account = AccountTable(
            id=str(uuid4()),
            email=email,
            password_hash=SOCIAL_NO_PASSWORD_HASH,
            status=AccountStatus.ACTIVE.value,
            created_at=datetime.now(UTC),
            failure_count=0,
        )
        self._session.add(account)
        self._session.flush()
        return account

    def update_orcid_profile(self, subject: str, name: str | None, affiliation: str | None) -> None:
        """ORCID 신원의 캐시 프로필(이름·소속)을 갱신한다 (BR-A13 / 마이페이지). 콜백 시 ORCID
        Public API 결과를 캐시. 신원이 없으면 무시(멱등)."""
        rec = self.get_social_identity(OidcProvider.ORCID.value, subject)
        if rec is None:
            return
        rec.orcid_name = name
        rec.orcid_affiliation = affiliation
        rec.orcid_synced_at = datetime.now(UTC)
        self._session.add(rec)
        self._session.flush()

    def get_orcid_identity(self, account_id: str) -> SocialIdentityTable | None:
        """계정의 LINKED ORCID 신원을 반환한다 (마이페이지 ORCID 카드용). 없으면 None."""
        return (
            self._session.query(SocialIdentityTable)
            .filter(
                SocialIdentityTable.account_id == account_id,
                SocialIdentityTable.provider == OidcProvider.ORCID.value,
                SocialIdentityTable.status == "LINKED",
            )
            .first()
        )

    # ── 이메일 변경 (FR-28 / BR-A10) ────────────────────────────────────────────
    def create_email_change_request(
        self,
        account_id: str,
        new_email: str,
        token_hash: str,
        expires_at: datetime,
        revoke_token_hash: str | None = None,
    ) -> EmailChangeRequestTable:
        """이메일 변경 요청을 생성한다. 계정당 활성 요청 1개로 제한(기존 선삭제)."""
        self._session.query(EmailChangeRequestTable).filter(
            EmailChangeRequestTable.account_id == account_id
        ).delete()
        rec = EmailChangeRequestTable(
            token_hash=token_hash,
            account_id=account_id,
            new_email=new_email,
            expires_at=expires_at,
            revoke_token_hash=revoke_token_hash,
        )
        self._session.add(rec)
        self._session.flush()
        return rec

    def get_email_change_request(self, token_hash: str) -> EmailChangeRequestTable | None:
        return (
            self._session.query(EmailChangeRequestTable)
            .filter(EmailChangeRequestTable.token_hash == token_hash)
            .first()
        )

    def get_email_change_request_by_revoke_hash(
        self, revoke_token_hash: str
    ) -> EmailChangeRequestTable | None:
        """취소(revoke) 토큰 해시로 이메일 변경 요청을 조회한다 (현 주소 소유자 취소 경로)."""
        return (
            self._session.query(EmailChangeRequestTable)
            .filter(EmailChangeRequestTable.revoke_token_hash == revoke_token_hash)
            .first()
        )

    def delete_email_change_request(self, token_hash: str) -> None:
        self._session.query(EmailChangeRequestTable).filter(
            EmailChangeRequestTable.token_hash == token_hash
        ).delete()
        self._session.flush()

    # ── 계정 삭제·유예 파기 (FR-28 / BR-A11) ────────────────────────────────────
    def create_account_deletion(self, account_id: str, purge_after: datetime) -> AccountDeletionTable:
        """소프트 삭제 레코드를 생성한다(DEACTIVATED). 멱등: 기존 미파기 레코드가 있으면 재사용."""
        existing = self.get_account_deletion(account_id)
        if existing is not None:
            return existing
        rec = AccountDeletionTable(
            account_id=account_id,
            requested_at=datetime.now(UTC),
            purge_after=purge_after,
            state=AccountStatus.DEACTIVATED.value,
        )
        self._session.add(rec)
        self._session.flush()
        return rec

    def get_account_deletion(self, account_id: str) -> AccountDeletionTable | None:
        return (
            self._session.query(AccountDeletionTable)
            .filter(AccountDeletionTable.account_id == account_id)
            .first()
        )

    def get_due_deletions(self, now: datetime) -> list[AccountDeletionTable]:
        """유예(purge_after)가 경과한 미파기(DEACTIVATED) 삭제 레코드를 반환한다(파기 잡 입력)."""
        return (
            self._session.query(AccountDeletionTable)
            .filter(
                AccountDeletionTable.state == AccountStatus.DEACTIVATED.value,
                AccountDeletionTable.purge_after <= now,
            )
            .all()
        )

    def delete_account_permanently(self, account_id: str) -> None:
        """계정과 그에 딸린 모든 자격증명 잔여물을 영구 삭제한다(파기). 멱등.

        accounts + 이메일 키 토큰(verification/reset) + 소셜 신원 + 이메일 변경 요청을 제거한다.
        owner-scoped 콘텐츠(라이브러리·이력·연구세션) 파기는 U3가 직접 하지 않고
        AccountDeleted 이벤트로 U4/U2/U11이 각자 수행한다(코드 DAG 비순환)."""
        account = self.get_by_id(account_id)
        if account is not None:
            self._create_withdrawal_backup(account)  # 시크릿 제외 5년 보관 스냅샷 (감사 #4)
            email = account.email
            self._session.query(VerificationTokenTable).filter(
                VerificationTokenTable.email == email
            ).delete()
            self._session.query(PasswordResetTokenTable).filter(
                PasswordResetTokenTable.email == email
            ).delete()
        self._session.query(SocialIdentityTable).filter(
            SocialIdentityTable.account_id == account_id
        ).delete()
        self._session.query(EmailChangeRequestTable).filter(
            EmailChangeRequestTable.account_id == account_id
        ).delete()
        self._session.query(AccountTable).filter(AccountTable.id == account_id).delete()
        self._session.flush()

    def _create_withdrawal_backup(self, account: AccountTable) -> None:
        """하드 파기 직전, accounts가 소유한 최소 스냅샷을 5년 보관 테이블에 적재한다(감사 #4 / PR #193
        복원). password_hash·totp_secret은 의도적으로 제외(크리덴셜 비보관). withdrawn_at은 소프트삭제
        시점(삭제 레코드 requested_at), purge_after는 +5년."""
        # 멱등: 파기 잡이 at-least-once로 재시도되면 동일 계정에 대해 다시 호출될 수 있다.
        # 이미 백업 행이 있으면 건너뛴다(중복 5년 보관 행 누적 방지). original_account_id에
        # UNIQUE 제약이 없어 앱 레벨에서 가드한다 — purge는 계정별 단일 트랜잭션이라 경합 없음.
        existing = (
            self._session.query(AccountWithdrawalBackupTable)
            .filter(AccountWithdrawalBackupTable.original_account_id == account.id)
            .first()
        )
        if existing is not None:
            return
        deletion = self.get_account_deletion(account.id)
        raw = deletion.requested_at if deletion is not None else datetime.now(UTC)
        withdrawn_at = raw.replace(tzinfo=None) if raw.tzinfo else raw
        backup = AccountWithdrawalBackupTable(
            original_account_id=account.id,
            email=account.email,
            status=account.status,
            signed_up_at=account.created_at,
            withdrawn_at=withdrawn_at,
            purge_after=withdrawn_at + timedelta(days=WITHDRAWAL_BACKUP_RETENTION_DAYS),
        )
        self._session.add(backup)
        self._session.flush()

    def mark_deletion_purged(self, account_id: str) -> None:
        """삭제 레코드를 PURGED로 전이해 재처리를 막는다(멱등 보증)."""
        rec = self.get_account_deletion(account_id)
        if rec is not None:
            rec.state = "PURGED"
            self._session.add(rec)
            self._session.flush()

    def increment_deletion_attempts(self, account_id: str) -> int:
        """파기 시도 횟수를 1 증가시키고 새 값을 반환한다(S2 — 독성 레코드 DLQ 가드용).
        실패한 파기 트랜잭션을 롤백한 뒤 별도 트랜잭션에서 호출해 시도 횟수를 영속화한다."""
        rec = self.get_account_deletion(account_id)
        if rec is None:
            return 0
        rec.purge_attempts = (rec.purge_attempts or 0) + 1
        self._session.add(rec)
        self._session.flush()
        return rec.purge_attempts

    def mark_deletion_failed(self, account_id: str) -> None:
        """반복 실패한 삭제 레코드를 PURGE_FAILED(DLQ)로 격리한다(S2). due 조회는 DEACTIVATED만
        보므로 격리된 행은 자동 제외되어 무한 재시도가 끊긴다. 운영의 수동 재조정 대상."""
        rec = self.get_account_deletion(account_id)
        if rec is not None:
            rec.state = "PURGE_FAILED"
            self._session.add(rec)
            self._session.flush()

    def delete_account_deletion(self, account_id: str) -> None:
        """유예 중 재활성화(복구) 시 삭제 레코드를 제거한다(M1)."""
        self._session.query(AccountDeletionTable).filter(
            AccountDeletionTable.account_id == account_id
        ).delete()
        self._session.flush()
