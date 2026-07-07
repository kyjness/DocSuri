CREATE TABLE IF NOT EXISTS evidence_sessions (
    session_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_sessions_owner_updated
    ON evidence_sessions(owner_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS evidence_turns (
    turn_id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES evidence_sessions(session_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_evidence_turns_session_created
    ON evidence_turns(owner_id, session_id, created_at ASC);
