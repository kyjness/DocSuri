-- US-NV8(#258) — 사용자별 Notion 명시 연결. 토큰은 Fernet 암호문만 저장(SEC-8/SEC-12).
CREATE TABLE IF NOT EXISTS novelty_notion_connections (
    owner_id UUID PRIMARY KEY,
    token_encrypted TEXT NOT NULL,
    parent_page_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
