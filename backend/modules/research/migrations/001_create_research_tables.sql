CREATE TABLE IF NOT EXISTS research_jobs (
    job_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    title TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_jobs_owner_updated
    ON research_jobs(owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS research_messages (
    message_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES research_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_research_messages_job_created
    ON research_messages(owner_id, job_id, created_at ASC);

