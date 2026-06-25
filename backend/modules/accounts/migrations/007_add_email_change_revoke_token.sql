-- 007_add_email_change_revoke_token.sql
-- 이메일 변경 요청(email_change_requests)에 취소(revoke) 토큰 해시 컬럼을 추가한다 (FR-28/BR-A10, 감사 H5).
-- 변경 시도 시 현(기존) 주소로 보내는 알림 메일에 revoke 링크를 실어, 세션 없이도 본인이 변경을
-- 취소할 수 있게 한다(탈취 방어). 토큰은 평문이 아닌 SHA-256 해시로만 저장한다(SEC-BR-1).
-- 기존 행(이 컬럼 이전 생성분)은 NULL — revoke 링크 없는 레거시 요청이며 만료(30분)로 자연 소멸한다.

ALTER TABLE email_change_requests ADD COLUMN IF NOT EXISTS revoke_token_hash VARCHAR(64);

CREATE INDEX IF NOT EXISTS idx_email_change_requests_revoke_token_hash
    ON email_change_requests(revoke_token_hash);
