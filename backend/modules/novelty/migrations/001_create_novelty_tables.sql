CREATE TABLE IF NOT EXISTS novelty_jobs (
    job_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    input_type TEXT NOT NULL,
    topic TEXT NOT NULL,
    manuscript JSONB,
    state TEXT NOT NULL,
    progress_percent INTEGER NOT NULL DEFAULT 0,
    export_status TEXT NOT NULL DEFAULT 'not_requested',
    error_message TEXT,
    cancelled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_novelty_jobs_owner_created
    ON novelty_jobs(owner_id, created_at DESC);

CREATE TABLE IF NOT EXISTS novelty_progress_events (
    event_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    state TEXT NOT NULL,
    message TEXT NOT NULL,
    progress_percent INTEGER NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_novelty_progress_events_job_created
    ON novelty_progress_events(owner_id, job_id, created_at ASC);

CREATE TABLE IF NOT EXISTS novelty_artifacts (
    artifact_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    object_key TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_novelty_artifacts_job_kind
    ON novelty_artifacts(owner_id, job_id, kind);

CREATE TABLE IF NOT EXISTS novelty_notion_exports (
    export_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    status TEXT NOT NULL,
    preview_object_key TEXT,
    notion_page_id TEXT,
    error_message TEXT,
    approved_at TIMESTAMPTZ,
    exported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_novelty_notion_exports_job UNIQUE (owner_id, job_id)
);
