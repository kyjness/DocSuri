CREATE TABLE IF NOT EXISTS novelty_messages (
    message_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_novelty_messages_job_created
    ON novelty_messages(owner_id, job_id, created_at ASC);

