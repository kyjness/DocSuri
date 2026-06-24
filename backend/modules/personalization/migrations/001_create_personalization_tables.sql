-- U9 Personalization — active behavior events, aggregate profiles, settings.
-- No backup table: user-requested raw-log deletion deletes active rows directly.

CREATE TABLE IF NOT EXISTS user_behavior_events (
    id           VARCHAR(36)  PRIMARY KEY,
    owner_id     VARCHAR(36)  NOT NULL,
    event_type   VARCHAR(64)  NOT NULL,
    subject      JSONB        NOT NULL,
    metadata     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    source       VARCHAR(32)  NOT NULL,
    dedupe_key   VARCHAR(160) NOT NULL,
    occurred_at  TIMESTAMPTZ  NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_behavior_owner_dedupe
    ON user_behavior_events (owner_id, dedupe_key);
CREATE INDEX IF NOT EXISTS ix_behavior_owner_occurred
    ON user_behavior_events (owner_id, occurred_at ASC, id ASC);
CREATE INDEX IF NOT EXISTS ix_behavior_occurred
    ON user_behavior_events (occurred_at ASC);

CREATE TABLE IF NOT EXISTS user_interest_profiles (
    owner_id             VARCHAR(36) PRIMARY KEY,
    category_weights     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    keyword_weights      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    paper_signals        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    summary_defaults     JSONB       NOT NULL DEFAULT '{}'::jsonb,
    translation_defaults JSONB       NOT NULL DEFAULT '{}'::jsonb,
    glossary_version     VARCHAR(64),
    updated_at           TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS personalization_settings (
    owner_id              VARCHAR(36) PRIMARY KEY,
    enabled               BOOLEAN     NOT NULL DEFAULT TRUE,
    raw_events_deleted_at TIMESTAMPTZ,
    profile_reset_at      TIMESTAMPTZ,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

