-- 009_make_email_nullable_for_orcid.sql
-- BR-A13 (FR-27 ORCID): ORCID OIDC는 이메일 클레임을 반환하지 않아(scopes=[openid]) ORCID로
-- 가입한 계정은 이메일이 없다. accounts.email의 NOT NULL을 해제한다(UNIQUE는 유지 — Postgres는
-- 다중 NULL을 유일성 위반으로 보지 않으므로 ORCID 계정이 다수 공존 가능). 마찬가지로 소셜 신원
-- 연결 시점 이메일 스냅샷(email_at_link)도 ORCID는 NULL이므로 NOT NULL을 해제한다.
-- 멱등: DROP NOT NULL은 이미 nullable이어도 에러 없이 통과한다.

ALTER TABLE accounts ALTER COLUMN email DROP NOT NULL;
ALTER TABLE social_identities ALTER COLUMN email_at_link DROP NOT NULL;
