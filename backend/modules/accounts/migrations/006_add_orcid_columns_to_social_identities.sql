-- 006_add_orcid_columns_to_social_identities.sql
-- develop의 003_create_lifecycle_tables.sql이 만든 social_identities는 provider/provider_subject
-- 범용 구조라 Google(provider='GOOGLE')은 그대로 연동되지만, ORCID(provider='ORCID')는 공개
-- API에서 가져오는 이름/소속 같은 프로필 정보를 캐시할 곳이 없다. works(논문 목록)는 1:N이라
-- 컬럼으로 두지 않고 마이페이지 조회 시마다 ORCID API에서 다시 가져온다. 세 컬럼 모두
-- provider != 'ORCID'인 행에서는 항상 NULL이다.
-- 참고: SQLAlchemy ORM 매핑(SocialIdentityTable)은 develop 머지 후 추가한다 — 이 브랜치에는
-- 그 클래스가 아직 없어 여기서 정의하면 머지 시 중복 선언으로 충돌한다.

ALTER TABLE social_identities ADD COLUMN IF NOT EXISTS orcid_name VARCHAR(255);
ALTER TABLE social_identities ADD COLUMN IF NOT EXISTS orcid_affiliation VARCHAR(255);
ALTER TABLE social_identities ADD COLUMN IF NOT EXISTS orcid_synced_at TIMESTAMP;
