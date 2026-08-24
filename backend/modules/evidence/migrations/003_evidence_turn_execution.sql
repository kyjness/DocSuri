-- U11 v3 PR 2 — 턴 실행 경로 통합(설계 evidence-agent-v3 §5)
--
-- 세 가지가 달라진다.
--   1. 취소 플래그와 실행자 하트비트가 턴 행에 생긴다. 취소는 novelty BR-RA8과 같은
--      협조적 방식 — API가 플래그만 세우고 실행자가 super-step 경계에서 읽는다.
--      하트비트는 실행자가 죽은 턴을 API가 발견해 마지막 체크포인트로 마감하는 근거다.
--   2. 세션당 진행 중 턴은 하나다(§5.4). 겹치면 체크포인트가 갈라지므로 부분 유니크
--      인덱스로 DB가 막는다 — 두 API 태스크가 동시에 받아도 하나만 들어간다.
--   3. job_id가 사라진다. 폴링·이벤트·취소가 전부 turn_id 하나로 가고, SQS 메시지 id는
--      로그에만 남는다(행에 복제할 이유가 없어졌다).
--   4. 체크포인트 정리 도장(checkpoints_pruned_at)이 생긴다. 도장이 없으면 "오래된 종단 턴"
--      질의가 매번 같은 앞쪽 N건을 돌려줘 영원히 다시 지우고, N을 넘긴 뒤는 영영 안 지워진다.
--
-- 체크포인트 테이블(checkpoints·checkpoint_blobs·checkpoint_writes)은 여기 없다 —
-- langgraph-checkpoint-postgres가 자기 원장(checkpoint_migrations)으로 만든다
-- (backend/wiring.py _mount_evidence, 같은 부팅 게이트 아래).

ALTER TABLE evidence_turns
    ADD COLUMN cancel_requested BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN heartbeat_at TIMESTAMPTZ,
    ADD COLUMN checkpoints_pruned_at TIMESTAMPTZ;

DROP INDEX IF EXISTS idx_evidence_turns_job;
ALTER TABLE evidence_turns DROP COLUMN IF EXISTS job_id;

-- 부분 유니크 인덱스는 **기존 행**에도 걸린다. 구 경로(동기·SQS)는 세션당 pending 수를 제한한
-- 적이 없어 죽은 실행자가 남긴 pending이 한 세션에 둘 이상일 수 있고, 그러면 인덱스 생성이
-- 실패해 부팅 자가 마이그레이션이 매번 죽는다. 세션당 가장 최근 것만 남기고 나머지는 닫는다 —
-- 어차피 실행자가 없는 행이라 결과가 올 일이 없다.
UPDATE evidence_turns t
   SET status = 'error', result = '{"errorCode": "internal_error"}'::jsonb
 WHERE t.status = 'pending'
   AND t.turn_id <> (
       SELECT u.turn_id FROM evidence_turns u
        WHERE u.session_id = t.session_id AND u.status = 'pending'
        ORDER BY u.created_at DESC, u.turn_id DESC LIMIT 1
   );

CREATE UNIQUE INDEX uq_evidence_turns_session_pending
    ON evidence_turns(session_id) WHERE status = 'pending';

-- 정리 대상 스캔용 — 아직 안 지운 종단 턴만, 오래된 순으로. 종전 질의는 created_at 선두
-- 인덱스가 없어 턴이 끝날 때마다 seq scan을 돌았다.
CREATE INDEX idx_evidence_turns_prunable
    ON evidence_turns(created_at ASC)
    WHERE status <> 'pending' AND checkpoints_pruned_at IS NULL;
