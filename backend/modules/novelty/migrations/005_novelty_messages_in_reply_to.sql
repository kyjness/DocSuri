-- 온디맨드 턴 멱등 판정 근거(코드 리뷰 반영) — 에이전트 답장이 어느 사용자
-- 메시지에 대한 것인지 명시한다. "대상 뒤 아무 에이전트 행" 추정은 동시 요청에서
-- 남의 답장을 내 답장으로 오인해 요청이 무응답으로 사라진다.
ALTER TABLE novelty_messages
    ADD COLUMN in_reply_to UUID;
