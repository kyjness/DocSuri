-- BR-30 2026-08-10: 코퍼스 제외(EXCLUDED) 상태 도입.
-- begin_upsert의 버전 범프는 doc-model 빌드보다 먼저 커밋되므로, 모든 단이 실패해 논문이
-- 코퍼스에서 제외되면 원장이 "청크도 doc-model도 전문도 없는 버전"을 INDEXED로 주장한 채
-- 남는다. 제외 시 mark_excluded가 반쯤 열린 클레임(fingerprint IS NULL)을 EXCLUDED로
-- 뒤집는다 — 이 CHECK 확장이 그 값을 허용한다.
ALTER TABLE dedup_state DROP CONSTRAINT IF EXISTS dedup_state_state_check;
ALTER TABLE dedup_state ADD CONSTRAINT dedup_state_state_check
    CHECK (state IN ('INDEXED', 'TOMBSTONED', 'EXCLUDED'));
