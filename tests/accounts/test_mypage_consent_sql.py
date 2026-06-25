"""감사 N3 — SqlAccountRepository.set_nightly_push가 nightly_push_agreed_at를 기록하는지 검증.

CI는 mypage in-memory 어댑터로 돌아가는데 그 경로엔 agreed_at 기록이 없어, 프로덕션 SQL 경로의
타임스탬프 기록 회귀가 조용히 통과하던 갭(감사 N3)을 이 테스트로 막는다.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.mypage.repository.sql import SqlAccountRepository


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def test_sql_set_nightly_push_stamps_agreed_at(session):
    repo = CredentialRepository(session)
    acct = repo.create_account("consent-sql@docsuri.org", "x")
    session.commit()

    result = SqlAccountRepository(session).set_nightly_push(acct.id, True)
    session.commit()

    assert result is not None and result.nightly_push_agreed is True
    refreshed = repo.get_by_id(acct.id)
    assert refreshed.nightly_push_agreed is True
    assert refreshed.nightly_push_agreed_at is not None  # 프로덕션 경로가 동의 시각을 기록한다
