"""FR-28 / BR-A11 — AccountDeletionService (soft-delete + grace purge + AccountDeleted).

Covers: soft delete (DEACTIVATED + all-session invalidation, NO event yet — H2), grace
purge job (publishes AccountDeleted, permanently deletes credentials + cascade artifacts,
idempotent), not-yet-due skip, and reactivation within grace (M1).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.modules.accounts.models import AccountStatus, DomainException
from backend.modules.accounts.password import get_password_hasher
from backend.modules.accounts.repository.credential import Base, CredentialRepository
from backend.modules.accounts.services.account_deletion import AccountDeletionService


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
async def test_purge_job_isolates_failing_publish(session):
    # 한 계정의 발행 실패가 나머지 due 계정의 파기를 막지 않는다(HOL 제거·행별 트랜잭션·at-least-once).
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
async def test_purge_writes_5y_withdrawal_backup_without_credentials(session):
    # 감사 #4 / PR #193 복원: 하드 파기 직전 5년 보관 스냅샷 적재(시크릿 제외).
    from backend.modules.accounts.repository.credential import (
        WITHDRAWAL_BACKUP_RETENTION_DAYS,
        AccountWithdrawalBackupTable,
    )

    repo = CredentialRepository(session)
    acct = _active_account(repo, session)
    acct_id, email = acct.id, acct.email
    svc = AccountDeletionService(repo, AsyncMock(), AsyncMock(), grace_days=0)
    await svc.request_deletion(acct_id, "OldPw123!@x")
    session.commit()

    await svc.purge_job(now=_naive(days=1))
    session.commit()

    backups = (
        session.query(AccountWithdrawalBackupTable)
        .filter(AccountWithdrawalBackupTable.original_account_id == acct_id)
        .all()
    )
    assert len(backups) == 1
    b = backups[0]
    assert b.email == email
    assert b.status == AccountStatus.DEACTIVATED.value
    assert (b.purge_after - b.withdrawn_at).days == WITHDRAWAL_BACKUP_RETENTION_DAYS  # 5년 보관
    # 백업 테이블에는 password_hash/totp_secret 컬럼이 없다(크리덴셜 비보관).
    assert not hasattr(b, "password_hash")
    assert repo.get_by_id(acct_id) is None  # 계정은 하드 파기됨


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
