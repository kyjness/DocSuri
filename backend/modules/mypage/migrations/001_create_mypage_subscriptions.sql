-- 001_create_mypage_subscriptions.sql
-- U10 My Page — mock subscription state (no real PG/billing). Tracks only plan/status/period
-- so the UI can render "구독중 / 해지예약 / 없음" without a payment gateway behind it.

CREATE TABLE IF NOT EXISTS mypage_subscriptions (
    owner_id VARCHAR(36) PRIMARY KEY,
    plan VARCHAR(20) NOT NULL DEFAULT 'FREE',
    status VARCHAR(20) NOT NULL DEFAULT 'NONE',
    started_at TIMESTAMP NULL,
    current_period_end TIMESTAMP NULL,
    canceled_at TIMESTAMP NULL
);
