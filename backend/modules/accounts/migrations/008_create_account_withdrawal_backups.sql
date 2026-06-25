-- 008_create_account_withdrawal_backups.sql
-- 회원탈퇴 5년 보관 백업 테이블 (감사 #4 / PR #193 복원). 하드 파기(영구 삭제) 직전에 accounts가
-- *소유한* 최소 스냅샷을 적재해 분쟁/법적 대응을 위해 5년 보관하고, purge_after 경과 후 별도 배치가
-- 하드 삭제한다(정리 배치는 후속). password_hash·totp_secret은 재로그인 복구 목적이 아니므로 의도적
-- 으로 제외한다(크리덴셜 비보관). 1:N 데이터(라이브러리·행동/관심·소셜연동)는 여기 담지 않고 각
-- 모듈이 AccountDeleted 이벤트로 자기 데이터를 따로 백업/정리한다.
--
-- 참고: 이 테이블은 한때 004로 추가됐다가(PR #193) 평행 탈퇴 메커니즘 제거 시 함께 삭제됐다. 정식
-- 탈퇴(status=DEACTIVATED + account_deletions) 파기 경로에 연결해 008로 재도입한다.

CREATE TABLE IF NOT EXISTS account_withdrawal_backups (
    id VARCHAR(36) PRIMARY KEY,
    original_account_id VARCHAR(36) NOT NULL,
    email VARCHAR(254) NOT NULL,
    status VARCHAR(20) NOT NULL,
    signed_up_at TIMESTAMP NOT NULL,
    withdrawn_at TIMESTAMP NOT NULL,
    purge_after TIMESTAMP NOT NULL,
    backed_up_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 탈퇴한 원본 계정으로 백업 행을 찾는 조회 인덱스.
CREATE INDEX IF NOT EXISTS idx_account_withdrawal_backups_original_account_id
    ON account_withdrawal_backups(original_account_id);

-- 5년 보관 만료분을 찾아 하드 삭제하는 배치용 인덱스(배치 자체는 후속 작업).
CREATE INDEX IF NOT EXISTS idx_account_withdrawal_backups_purge_after
    ON account_withdrawal_backups(purge_after);
