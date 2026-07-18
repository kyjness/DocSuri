-- Novelty v2 (자율 도구 호출 루프) — 스키마 재정의.
-- 설계: aidlc-docs/construction/novelty-agent-v2/ (TD-NV2-5, NFR-NV2-12/13).
-- 배포 회수로 프로덕션 데이터 없음 전제의 drop/recreate — 구 11-상태 파이프라인
-- 스키마(progress_events·stage 산출물)를 폐기하고 루프·트레이스 스키마로 대체한다.
-- AgentLoopRun은 잡 aggregate 1:1이므로 별도 테이블 대신 JSONB로 embed한다.

DROP TABLE IF EXISTS novelty_progress_events;
DROP TABLE IF EXISTS novelty_tool_call_records;
DROP TABLE IF EXISTS novelty_artifacts;
DROP TABLE IF EXISTS novelty_messages;
DROP TABLE IF EXISTS novelty_notion_exports;
DROP TABLE IF EXISTS novelty_notion_connections;
DROP TABLE IF EXISTS novelty_jobs;

CREATE TABLE novelty_jobs (
    job_id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    request JSONB NOT NULL,
    state TEXT NOT NULL,
    loop_run JSONB,
    degraded_sources JSONB NOT NULL DEFAULT '{}'::jsonb,
    cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_novelty_jobs_owner_created
    ON novelty_jobs(owner_id, created_at DESC);

-- 결정 트레이스(FR-46) — 잡 귀속, (job_id, seq) 유일, 잡 삭제 시 cascade(BR-NV18).
-- 보존 기간 = 잡 수명(별도 TTL 없음, NFR-NV2-12).
CREATE TABLE novelty_tool_call_records (
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    seq BIGINT NOT NULL,
    tool_name TEXT NOT NULL,
    args_summary TEXT NOT NULL,
    decision_note TEXT,
    result_summary TEXT NOT NULL,
    outcome TEXT NOT NULL,
    cost_estimate_usd DOUBLE PRECISION,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job_id, seq)
);

-- 산출물 — 종류별 최신 검증본(구 stage_snapshots 대체). 저장은 게이트 경유 전용.
CREATE TABLE novelty_artifacts (
    artifact_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    kind TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_novelty_artifacts_job_kind UNIQUE (job_id, kind)
);

CREATE INDEX idx_novelty_artifacts_owner_job
    ON novelty_artifacts(owner_id, job_id);

-- 잡 내 대화(FR-44) — kind(steering/on_demand_request/agent_reply/notice) 추가.
CREATE TABLE novelty_messages (
    message_id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES novelty_jobs(job_id) ON DELETE CASCADE,
    owner_id UUID NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    resulting_artifact_ref TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_novelty_messages_job_created
    ON novelty_messages(owner_id, job_id, created_at ASC);

-- Notion export·연결 — v1 형태 승계(승인 게이트 불변, BR-NV17/RA12).
CREATE TABLE novelty_notion_exports (
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

CREATE TABLE novelty_notion_connections (
    owner_id UUID PRIMARY KEY,
    token_encrypted TEXT NOT NULL,
    parent_page_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
