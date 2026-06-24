-- FR-17 multimodal figure/table asset manifest (display-only).
-- Binary lives in S3 (assets/ prefix); this table is the display source of truth (P8).
-- U1 ingestion worker writes (PUT/UPDATE/DELETE); U7 read API reads (SELECT) and presigns.
CREATE TABLE IF NOT EXISTS paper_asset (
    paper_id    TEXT        NOT NULL,
    version     INTEGER     NOT NULL,
    asset_id    TEXT        NOT NULL,
    type        TEXT        NOT NULL,   -- 'figure' | 'table'
    caption     TEXT        NOT NULL DEFAULT '',
    section_ref TEXT,
    ordinal     INTEGER     NOT NULL,
    source_mode TEXT        NOT NULL,   -- 'structured' | 'page-crop'
    object_ref  TEXT        NOT NULL,   -- s3://bucket/assets/{paper}/v{n}/{assetId}.webp
    page_ref    INTEGER,
    bbox        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (paper_id, version, asset_id)
);

-- Read path: U7 fetches a paper's assets in display order.
CREATE INDEX IF NOT EXISTS idx_paper_asset_lookup ON paper_asset (paper_id, version, ordinal);
