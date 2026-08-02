-- U11 v2 — 자율 루프 저장 스키마 (FD 게이트 Q6=A)
--
-- 세 가지가 달라진다.
--   1. 턴 결과가 전용 컬럼으로 온다. v1은 result를 attachments JSONB 안에 욱여넣고
--      content 컬럼을 상태 문자열로 썼다 — 조회·인덱스가 모두 그 구조에 묶여 있었다.
--   2. 결정 트레이스 테이블이 생긴다(FR-46). 진행 활동 피드의 유일한 원천이고,
--      append 빈도가 높아 턴 행에 실으면 스트리밍 중 결과 쓰기와 경합한다.
--   3. research_jobs·research_messages를 드롭한다. 껍데기 표면이 사라지고
--      /api/evidence 한 벌만 남는다(요구사항 게이트 Q6=B·Q7=A).
--
-- 로컬 개발 데이터는 이관하지 않는다(2026-07-28 확인) — 보존할 세션이 없다.

-- 1. 턴 테이블 재작성 --------------------------------------------------------
DROP TABLE IF EXISTS evidence_turns;

CREATE TABLE evidence_turns (
    turn_id      UUID PRIMARY KEY,
    session_id   UUID NOT NULL REFERENCES evidence_sessions(session_id) ON DELETE CASCADE,
    owner_id     UUID NOT NULL,
    -- 사용자 질문(EvidenceRequest.topic).
    topic        TEXT NOT NULL DEFAULT '',
    -- 터미널 상태: ok | abstain | pending | error. D5 union 2종 + 실행 상태 2종.
    status       TEXT NOT NULL DEFAULT 'pending',
    -- EvidenceResult 또는 EvidenceAbstainResult 직렬화(D5 계약 그대로).
    result       JSONB,
    -- 비동기 잡 폴링 키. 생성 시점에 고정한다 — result 안에 두면 완료 시 사라져
    -- 폴링이 영구 404가 된다(v1이 겪은 결함).
    job_id       UUID,
    attachments  JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_evidence_turns_session_created
    ON evidence_turns(owner_id, session_id, created_at ASC);
CREATE INDEX idx_evidence_turns_job
    ON evidence_turns(owner_id, job_id) WHERE job_id IS NOT NULL;

-- 2. 결정 트레이스 (FR-46, BR-EV-16) ------------------------------------------
CREATE TABLE evidence_trace (
    trace_id     BIGSERIAL PRIMARY KEY,
    turn_id      UUID NOT NULL REFERENCES evidence_turns(turn_id) ON DELETE CASCADE,
    owner_id     UUID NOT NULL,
    seq          INTEGER NOT NULL,
    tool         TEXT NOT NULL,
    -- sanitized 요약만 — 도구 인자 원문·자격증명은 저장하지 않는다(INV-EV-5).
    args_summary TEXT NOT NULL DEFAULT '',
    outcome      TEXT NOT NULL,
    result_summary TEXT NOT NULL DEFAULT '',
    cost_usd     DOUBLE PRECISION,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (turn_id, seq)
);

CREATE INDEX idx_evidence_trace_turn ON evidence_trace(owner_id, turn_id, seq ASC);

-- 3. 껍데기 표면 제거 ---------------------------------------------------------
DROP TABLE IF EXISTS research_messages;
DROP TABLE IF EXISTS research_jobs;
