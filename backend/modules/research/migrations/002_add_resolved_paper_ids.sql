ALTER TABLE research_messages
    ADD COLUMN IF NOT EXISTS resolved_paper_ids JSONB NOT NULL DEFAULT '[]'::jsonb;
