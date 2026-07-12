"""FR-28 / BR-A11 — AccountDeletionService (soft-delete + grace purge + AccountDeleted).

Covers: soft delete (DEACTIVATED + all-session invalidation, NO event yet — H2), grace
purge job (publishes AccountDeleted, permanently deletes credentials + cascade artifacts,
idempotent), not-yet-due skip, and reactivation within grace (M1).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from backend.modules.accounts.models import AccountStatus, DomainException
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.account_deletion import AccountDeletionService
from backend.modules.accounts.services.owner_data_purge import SqlOwnerDataPurger
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def _naive(days=0):
    return datetime.now(UTC).replace(tzinfo=None) + timedelta(days=days)


def _active_account(repo: CredentialRepository, session, email="user@docsuri.org"):
    acct = repo.create_account(email, get_password_hasher().hash("OldPw123!@x"))
    acct.status = AccountStatus.ACTIVE.value
    repo.update_account(acct)
    session.commit()
    return acct


@pytest.mark.asyncio
async def test_request_deletion_soft_deletes_invalidates_no_event(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    sm = AsyncMock()
    publisher = AsyncMock()
    svc = AccountDeletionService(repo, sm, publisher)

    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    assert repo.get_by_id(acct.id).status == AccountStatus.DEACTIVATED.value
    assert repo.get_account_deletion(acct.id) is not None
    sm.invalidate_all_for_user.assert_awaited_once_with(acct.id)  # immediate login block
    publisher.publish.assert_not_awaited()  # H2: AccountDeleted only at purge, not soft-delete


@pytest.mark.asyncio
async def test_purge_job_publishes_event_and_permanently_deletes(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    publisher = AsyncMock()
    svc = AccountDeletionService(repo, AsyncMock(), publisher, grace_days=30)
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    purged = await svc.purge_job(now=_naive(days=31))
    session.commit()

    assert purged == 1
    publisher.publish.assert_awaited_once()
    assert publisher.publish.call_args.args[0] == acct.id  # accountId is the idempotency key
    assert repo.get_by_id(acct.id) is None  # credentials permanently deleted
    assert repo.get_account_deletion(acct.id).state == "PURGED"

    # idempotent: re-running does not re-publish or re-process (PURGED excluded)
    again = await svc.purge_job(now=_naive(days=31))
    assert again == 0
    assert publisher.publish.await_count == 1


@pytest.mark.asyncio
async def test_purge_job_cascades_credential_artifacts(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    repo.create_social_identity("GOOGLE", "sub-1", acct.id, acct.email)
    repo.create_reset_token(acct.email, "resethash1", _naive(days=0) + timedelta(minutes=30))
    session.commit()
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock(), grace_days=0)
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    await svc.purge_job(now=_naive(days=1))
    session.commit()

    assert repo.get_social_identity("GOOGLE", "sub-1") is None
    assert repo.get_reset_token("resethash1") is None


@pytest.mark.asyncio
async def test_purge_job_cascades_owner_scoped_same_rds_tables(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    other = _active_account(repo, session, email="other@docsuri.org")
    session.execute(
        text("CREATE TABLE saved_searches (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)")
    )
    session.execute(
        text("CREATE TABLE user_behavior_events (id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)")
    )
    session.execute(
        text("CREATE TABLE novelty_jobs (job_id TEXT PRIMARY KEY, owner_id TEXT NOT NULL)")
    )
    session.execute(text("CREATE TABLE user_glossary (id TEXT PRIMARY KEY, user_id TEXT NOT NULL)"))
    for table, id_col, owner_col in (
        ("saved_searches", "id", "owner_id"),
        ("user_behavior_events", "id", "owner_id"),
        ("novelty_jobs", "job_id", "owner_id"),
        ("user_glossary", "id", "user_id"),
    ):
        session.execute(
            text(f"INSERT INTO {table} ({id_col}, {owner_col}) VALUES (:id, :owner)"),
            {"id": f"{table}-owned", "owner": acct.id},
        )
        session.execute(
            text(f"INSERT INTO {table} ({id_col}, {owner_col}) VALUES (:id, :owner)"),
            {"id": f"{table}-other", "owner": other.id},
        )
    session.commit()

    svc = AccountDeletionService(
        repo,
        AsyncMock(),
        AsyncMock(),
        owner_data_purger=SqlOwnerDataPurger(session),
        grace_days=0,
    )
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    await svc.purge_job(now=_naive(days=1))
    session.commit()

    for table, owner_col in (
        ("saved_searches", "owner_id"),
        ("user_behavior_events", "owner_id"),
        ("novelty_jobs", "owner_id"),
        ("user_glossary", "user_id"),
    ):
        assert session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {owner_col} = :owner"),
            {"owner": acct.id},
        ).scalar_one() == 0
        assert session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {owner_col} = :owner"),
            {"owner": other.id},
        ).scalar_one() == 1


@pytest.mark.asyncio
async def test_purge_job_isolates_failing_publish(session):
    # 한 계정의 발행 실패가 나머지 due 계정의 파기를 막지 않는다.
    # HOL 제거·행별 트랜잭션·at-least-once.
    repo = CredentialRepository(session)
    good = _active_account(repo, session, email="good@docsuri.org")
    bad = _active_account(repo, session, email="bad@docsuri.org")
    publisher = AsyncMock()

    async def _publish(account_id, occurred_at, event_id):
        if account_id == bad.id:
            raise RuntimeError("eventbridge down")

    publisher.publish.side_effect = _publish
    svc = AccountDeletionService(repo, AsyncMock(), publisher, grace_days=0)
    await svc.request_deletion(good.id, "OldPw123!@x")
    await svc.request_deletion(bad.id, "OldPw123!@x")
    session.commit()

    purged = await svc.purge_job(now=_naive(days=1))

    assert purged == 1
    assert repo.get_by_id(good.id) is None  # 정상 계정은 파기됨
    assert repo.get_by_id(bad.id) is not None  # 실패 계정은 살아남아 다음 회차 재시도 대상
    assert repo.get_account_deletion(bad.id).state == AccountStatus.DEACTIVATED.value


@pytest.mark.asyncio
async def test_purge_job_event_id_is_deterministic(session):
    # event_id는 account_id에서 결정적으로 파생 → 재시도에도 동일(구독자 중복 제거 가능).
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    publisher = AsyncMock()
    svc = AccountDeletionService(repo, AsyncMock(), publisher, grace_days=0)
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    import uuid as _uuid

    from backend.modules.accounts.services.account_deletion import _ACCOUNT_DELETED_NS

    await svc.purge_job(now=_naive(days=1))
    emitted_event_id = publisher.publish.call_args.args[2]
    assert emitted_event_id == str(_uuid.uuid5(_ACCOUNT_DELETED_NS, acct.id))


@pytest.mark.asyncio
async def test_purge_job_skips_not_yet_due(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock(), grace_days=30)
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    purged = await svc.purge_job()  # now ~= request time; purge_after = +30d → not due
    assert purged == 0
    assert repo.get_by_id(acct.id) is not None


@pytest.mark.asyncio
async def test_reactivate_restores_within_grace(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock())
    await svc.request_deletion(acct.id, "OldPw123!@x")
    session.commit()

    await svc.reactivate(acct.id)
    session.commit()

    assert repo.get_by_id(acct.id).status == AccountStatus.ACTIVE.value
    assert repo.get_account_deletion(acct.id) is None


@pytest.mark.asyncio
async def test_reactivate_non_deleted_rejected(session):
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.reactivate(acct.id)


@pytest.mark.asyncio
async def test_request_deletion_requires_correct_password(session):
    # 감사 H7: 비밀번호 계정 탈퇴는 현재 비밀번호 재인증 필수(CSRF·세션탈취 방어).
    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock())
    with pytest.raises(DomainException):
        await svc.request_deletion(acct.id, "WrongPw1!@x")  # 틀린 비번
    with pytest.raises(DomainException):
        await svc.request_deletion(acct.id)  # 비번 미제공
    assert repo.get_by_id(acct.id).status == AccountStatus.ACTIVE.value  # 삭제되지 않음


@pytest.mark.asyncio
async def test_authenticate_reactivates_deactivated_owner_within_grace(session):
    # M1: 소프트 삭제로 세션이 전부 무효화되고 로그인이 차단된 뒤, 소유자가 자격증명을 재증명하면
    # (reactivate=True) ACTIVE로 복원되고 즉시 세션이 발급된다(리뷰: reactivate 라우트 도달성).
    from types import SimpleNamespace

    from backend.modules.accounts.services.auth import AuthenticationService

    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    sm = AsyncMock()
    sm.issue = AsyncMock(return_value=SimpleNamespace(handle="sess-1"))

    await AccountDeletionService(repo, sm).request_deletion(acct.id, "OldPw123!@x")
    session.commit()
    assert repo.get_by_id(acct.id).status == AccountStatus.DEACTIVATED.value

    auth = AuthenticationService(repo, sm, AsyncMock())
    # 일반 로그인은 DEACTIVATED를 계속 차단한다
    with pytest.raises(DomainException):
        await auth.authenticate(acct.email, "OldPw123!@x")
    # 복구 플래그 + 올바른 자격증명 → 복원 + 세션 발급
    handle = await auth.authenticate(acct.email, "OldPw123!@x", reactivate=True)
    session.commit()
    assert handle == "sess-1"
    assert repo.get_by_id(acct.id).status == AccountStatus.ACTIVE.value
    assert repo.get_account_deletion(acct.id) is None  # 삭제 레코드 제거됨
