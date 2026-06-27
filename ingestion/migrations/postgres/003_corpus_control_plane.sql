CREATE TABLE IF NOT EXISTS canonical_dedup_state (
    canonical_key TEXT PRIMARY KEY,
    paper_id TEXT NOT NULL,
    winning_source_tier TEXT NOT NULL,
    winning_version INTEGER NOT NULL CHECK (winning_version >= 1),
    fingerprint TEXT NOT NULL,
    seen_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_version_state (
    paper_id TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    doc_model_ref TEXT,
    generation_id TEXT,
    status TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (paper_id, version)
);

CREATE TABLE IF NOT EXISTS corpus_generation (
    generation_id TEXT PRIMARY KEY,
    index_alias TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('BUILDING', 'VALIDATED', 'ACTIVE', 'RETIRED', 'ROLLED_BACK')),
    docmodel_schema_version TEXT NOT NULL,
    chunker_version TEXT NOT NULL,
    vector_spec_ref TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS corpus_job_item (
    item_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    source_name TEXT,
    canonical_key TEXT,
    paper_id TEXT,
    version INTEGER,
    stage TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_reason TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_canonical_dedup_paper ON canonical_dedup_state(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_version_generation ON paper_version_state(generation_id);
CREATE INDEX IF NOT EXISTS idx_corpus_job_item_job ON corpus_job_item(job_id);
