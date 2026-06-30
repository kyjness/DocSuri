-- 011_add_purge_attempts.sql
-- BR-A11 (FR-28): 유예 파기 잡(purge_job)의 독성 레코드 방어(리뷰 finding S2). 한 계정의 파기가
-- 반복 실패(발행 장애·잘못된 owner 컬럼 등)하면 매 회차 재시도되며 무한 루프가 된다. 시도 횟수를
-- 누적해 임계 초과 시 state=PURGE_FAILED(DLQ)로 격리하고 운영 경보를 띄운다. due 조회는
-- state=DEACTIVATED만 보므로 격리된 행은 자동 제외된다.
-- 멱등: ADD COLUMN IF NOT EXISTS는 이미 존재해도 에러 없이 통과한다.

ALTER TABLE account_deletions
    ADD COLUMN IF NOT EXISTS purge_attempts INTEGER NOT NULL DEFAULT 0;
