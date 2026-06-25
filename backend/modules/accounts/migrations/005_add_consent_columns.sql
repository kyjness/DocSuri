-- 005_add_consent_columns.sql
-- U10 마이페이지 설정(선택 동의 철회) + 가입 동의: 개인정보처리방침/서비스 이용약관(필수)과
-- 야간 푸시 알림(선택, 이메일 발송 — 최신/관심 논문 등재 알림) 동의 상태를 accounts에 저장한다.
-- 필수 동의 2종은 가입 시점에 항상 true로 기록되므로(거부 시 가입 불가) bool은 사실상 상수지만,
-- *_agreed_at으로 "언제 동의했는지"를 같이 남겨 약관 변경 시 재동의 추적의 단서로 쓴다.
-- 기존 행(이 컬럼이 생기기 전 가입자)은 과거 가입 절차상 암묵 동의로 간주해 true/현재시각으로
-- 백필한다. 선택 동의(야간 푸시)만 실제로 켜고 끌 수 있고, agreed_at은 마지막으로 켠 시각이다.

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS privacy_policy_agreed BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS privacy_policy_agreed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS terms_of_service_agreed BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS terms_of_service_agreed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS nightly_push_agreed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS nightly_push_agreed_at TIMESTAMP;
