"""계정 유예 파기 워커 (FR-28 / BR-A11) — 스케줄(EventBridge rule/cron)로 주기 실행한다.

    DATABASE_URL=postgresql+psycopg://… ACCOUNT_EVENTS_BUS=docsuri-events \\
        python -m backend.modules.accounts.purge_worker

purge_after가 경과한 DEACTIVATED 계정을 영구 파기하고 AccountDeleted를 발행한다(멱등·재시도).
세션 무효화는 소프트 삭제 시점에 이미 끝났으므로 본 워커는 Redis(SessionManager)가 필요 없다.
ACCOUNT_EVENTS_BUS 미설정 시 발행자는 Logging(콘솔)로 폴백한다 — 로컬/드라이런용.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .repository.credential import CredentialRepository
from .services.account_deletion import AccountDeletionService, build_account_deleted_publisher

logger = logging.getLogger(__name__)


async def run_purge(session) -> int:
    """주어진 DB 세션으로 유예 파기 1회 실행 후 커밋한다. 파기 계정 수를 반환한다."""
    repo = CredentialRepository(session)
    # purge_job은 SessionManager를 쓰지 않는다(세션 무효화는 소프트삭제 시점에 완료) → None.
    svc = AccountDeletionService(repo, session_manager=None, publisher=build_account_deleted_publisher())
    purged = await svc.purge_job()
    session.commit()
    return purged


def main() -> int:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        logger.error("DATABASE_URL 환경변수가 필요합니다.")
        return 2
    engine = create_engine(database_url)
    session = sessionmaker(bind=engine)()
    try:
        purged = asyncio.run(run_purge(session))
        logger.info("purge worker complete: purged=%s", purged)
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())
