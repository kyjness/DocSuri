-- 003_create_lifecycle_tables.sql
-- U3 Accounts 프로덕션화 — 계정 라이프사이클 신규 테이블 DDL (FR-26/27/28).
-- 컬럼/타입은 backend/modules/accounts/repository/credential.py 의 SQLAlchemy 모델과 일치한다.
-- accounts.status 의 'DEACTIVATED'(BR-A11)는 기존 VARCHAR 컬럼의 신규 허용값일 뿐 DDL 변경 불요.

-- 1. password_reset_tokens — 비밀번호 재설정 토큰 (FR-26/BR-A8).
--    토큰은 평문이 아닌 SHA-256 해시로만 저장(DB 유출 시 무력화). 단일 사용은 confirm 시 즉시 삭제로 강제.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    token_hash VARCHAR(64) PRIMARY KEY,
    email VARCHAR(254) NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_email ON password_reset_tokens(email);

-- 2. social_identities — 소셜 신원 연결 (FR-27/BR-A9). (provider, provider_subject) 전역 유일.
--    status: LINKED | PENDING_CONFIRMATION(H1 — 기존 비밀번호 계정 명시적 연결 대기).
CREATE TABLE IF NOT EXISTS social_identities (
    provider VARCHAR(20) NOT NULL,
    provider_subject VARCHAR(255) NOT NULL,
    account_id VARCHAR(36) NOT NULL,
    email_at_link VARCHAR(254) NOT NULL,
    linked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(24) NOT NULL DEFAULT 'LINKED',
    PRIMARY KEY (provider, provider_subject)
);
CREATE INDEX IF NOT EXISTS idx_social_identities_account_id ON social_identities(account_id);

-- 3. email_change_requests — 이메일 변경 요청 (FR-28/BR-A10). 검증 완료 전까지 로그인 식별자 미반영.
--    토큰 해시만 저장하며 계정당 활성 요청은 1개로 제한(생성 시 선삭제).
CREATE TABLE IF NOT EXISTS email_change_requests (
    token_hash VARCHAR(64) PRIMARY KEY,
    account_id VARCHAR(36) NOT NULL,
    new_email VARCHAR(254) NOT NULL,
    expires_at TIMESTAMP NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_email_change_requests_account_id ON email_change_requests(account_id);

-- 4. account_deletions — 계정 삭제 레코드 (FR-28/BR-A11). 소프트삭제(DEACTIVATED) → 유예 경과 후 PURGED.
--    purge_after 인덱스로 유예 파기 잡(get_due_deletions)이 경과분을 효율 조회한다.
CREATE TABLE IF NOT EXISTS account_deletions (
    account_id VARCHAR(36) PRIMARY KEY,
    requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    purge_after TIMESTAMP NOT NULL,
    state VARCHAR(20) NOT NULL DEFAULT 'DEACTIVATED'
);
CREATE INDEX IF NOT EXISTS idx_account_deletions_purge_after ON account_deletions(purge_after);
