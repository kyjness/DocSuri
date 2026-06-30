"""계정 삭제 — 소프트 삭제 + 유예 비동기 파기 (FR-28 / BR-A11).

2상 삭제:
  ① 동기 소프트 삭제(``request_deletion``): ``DEACTIVATED`` 전이 + 전 세션 즉시 무효화(로그인
     차단) + 삭제 레코드(``purge_after``) 생성. **이 시점에 owner-scoped 데이터를 보존**(복구
     가능) — ``AccountDeleted``는 발행하지 않는다(H2).
  ② 비동기 유예 파기(``purge_job``): ``purge_after`` 경과분을 일괄 처리. 각 계정에 대해
     **``AccountDeleted`` 이벤트 발행**(U4/U2/U11이 구독해 각자 owner-scoped 파기 — 직접 호출
     아님, 코드 DAG 비순환) → 자격증명 영구 삭제 → ``PURGED`` 전이(멱등).

유예 중 ``reactivate``(소유자 복구, M1) 가능.

실제 EventBridge 발행 트랜스포트는 인프라 슬라이스로 이월하고(FR-27 OIDC 트랜스포트 분리와
동일 패턴), 코어 파기 로직은 발행자 포트로 분리해 단위 테스트 가능하게 둔다.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

from argon2.exceptions import InvalidHash, VerificationError
from docsuri_shared.events import AccountDeleted  # 발행 페이로드를 SSOT 계약에 바인딩(계약 준수).

from ..models import AccountStatus, DomainException
from ..password import get_password_hasher
from ..repository.credential import CredentialRepository, has_usable_password
from .session_manager import SessionManager

logger = logging.getLogger(__name__)

DEFAULT_GRACE_DAYS = 30  # 유예 기간 N (events.md 기본 제안 30일; 운영/법적 요건으로 조정).
MAX_PURGE_ATTEMPTS = 5  # S2: 파기 반복 실패가 이 횟수에 도달하면 PURGE_FAILED(DLQ)로 격리한다.

# AccountDeleted event_id를 account_id로부터 결정적으로 파생하기 위한 네임스페이스(고정).
# 재시도 시에도 동일 account_id → 동일 event_id가 되어 구독자가 event_id로 중복 제거할 수 있다.
_ACCOUNT_DELETED_NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://docsuri.org/events/AccountDeleted")


class AccountDeletedPublisher(Protocol):
    """``AccountDeleted`` 캐스케이드 이벤트 발행자 포트 (shared/events.md 계약)."""

    async def publish(self, account_id: str, occurred_at: datetime, event_id: str) -> None: ...


class OwnerDataPurger(Protocol):
    """동일 RDS 안의 owner-scoped 데이터 파기 포트.

    EventBridge 발행은 외부/비동기 구독자를 위한 계약이고, 이 포트는 현재 모놀리식 DB에 이미
    존재하는 owner-scoped 테이블을 같은 트랜잭션에서 정리하는 운영 backstop이다.
    """

    def purge(self, account_id: str) -> None: ...


class NoopOwnerDataPurger:
    def purge(self, account_id: str) -> None:
        return None


def _build_payload(account_id: str, occurred_at: datetime, event_id: str) -> dict:
    """발행 detail을 SSOT 계약(``AccountDeleted``)으로 검증·직렬화한다 — 계약 드리프트를 발행
    시점에 잡는다. ``occurred_at``은 tz-aware여야 한다(계약은 AwareDatetime)."""
    return AccountDeleted(
        accountId=account_id, occurredAt=occurred_at, eventId=event_id
    ).model_dump(mode="json")


class LoggingAccountDeletedPublisher:
    """기본 발행자 — 구조화 로그로만 기록한다. 실 EventBridge 트랜스포트는 인프라 슬라이스로 이월.
    멱등 키는 ``account_id``; ``event_id``는 account_id로부터 결정적으로 파생되므로(uuid5) 재시도
    시에도 동일해 중복 식별 키로도 쓸 수 있다 (at-least-once)."""

    async def publish(self, account_id: str, occurred_at: datetime, event_id: str) -> None:
        logger.info({"event": "AccountDeleted", **_build_payload(account_id, occurred_at, event_id)})


class EventBridgeAccountDeletedPublisher:
    """실 발행자 — AWS EventBridge에 AccountDeleted를 put_events한다 (TD-U3-9).
    구독자(U4/U2/U11)는 버스 규칙으로 라우팅된다. boto3는 동기 호출이라 to_thread로 위임하고,
    발행 실패(FailedEntryCount>0 또는 예외)는 상위로 올려 purge_job이 다음 회차에 재시도하게
    한다(DEACTIVATED 유지·at-least-once)."""

    def __init__(self, event_bus_name: str, source: str = "docsuri.accounts", region: str | None = None):
        self._bus = event_bus_name
        self._source = source
        self._region = region
        self._client = None

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("events", region_name=self._region)
        return self._client

    async def publish(self, account_id: str, occurred_at: datetime, event_id: str) -> None:
        detail = json.dumps(_build_payload(account_id, occurred_at, event_id))

        def _put():
            return self._get_client().put_events(
                Entries=[
                    {
                        "Source": self._source,
                        "DetailType": "AccountDeleted",
                        "Detail": detail,
                        "EventBusName": self._bus,
                    }
                ]
            )

        resp = await asyncio.to_thread(_put)
        if resp.get("FailedEntryCount", 0):
            raise RuntimeError(f"EventBridge put_events 실패: {resp.get('Entries')}")


def build_account_deleted_publisher() -> AccountDeletedPublisher:
    """환경 기반 발행자 선택: ACCOUNT_EVENTS_BUS 설정 시 EventBridge, 아니면 Logging(로컬 전용).

    S3: 비-local 환경에서 버스가 비면 Logging으로 *조용히* 폴백하던 동작은, 단 하나의 env 누락으로
    AccountDeleted가 발행되지 않아 U4/U2/U11이 owner-scoped 데이터를 영구히 파기하지 못하게 한다
    (사일런트 크로스모듈 데이터 고아화·GDPR 파기 누락). 따라서 프로덕션에선 페일패스트한다 — 로컬/
    테스트(ENV in {local,test,dev})에서만 Logging 발행자를 허용한다."""
    bus = os.getenv("ACCOUNT_EVENTS_BUS", "").strip()
    if bus:
        return EventBridgeAccountDeletedPublisher(event_bus_name=bus, region=os.getenv("AWS_REGION") or None)
    env = os.getenv("ENV", "local").strip().lower()
    if env not in {"local", "test", "dev"}:
        raise RuntimeError(
            f"ACCOUNT_EVENTS_BUS가 설정되지 않았습니다 (ENV={env}). 프로덕션 파기 워커는 AccountDeleted를 "
            "발행해야 U4/U2/U11이 owner-scoped 데이터를 파기합니다(GDPR). 버스를 설정하거나 ENV=local로 "
            "실행하세요."
        )
    return LoggingAccountDeletedPublisher()


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class AccountDeletionService:
    def __init__(
        self,
        credential_repo: CredentialRepository,
        session_manager: SessionManager | None,  # purge_job 경로는 미사용 → 워커는 None 주입.
        publisher: AccountDeletedPublisher | None = None,
        owner_data_purger: OwnerDataPurger | None = None,
        grace_days: int = DEFAULT_GRACE_DAYS,
    ):
        self._repo = credential_repo
        self._session_manager = session_manager
        self._publisher = publisher or LoggingAccountDeletedPublisher()
        self._owner_data_purger = owner_data_purger or NoopOwnerDataPurger()
        self._grace_days = grace_days
        self._hasher = get_password_hasher()

    async def request_deletion(self, account_id: str, current_password: str | None = None) -> None:
        """소프트 삭제: DEACTIVATED 전이 + 전 세션 무효화 + 유예 레코드 생성 (멱등).
        비밀번호 계정은 현재 비밀번호 재인증을 요구한다(파괴적 작업 CSRF·세션탈취 방어, 감사 H7);
        소셜-only 계정은 제공할 비밀번호가 없어 건너뛴다(세션 소유로 충분)."""
        account = self._repo.get_by_id(account_id)
        if account is None:
            raise DomainException("계정을 찾을 수 없습니다.")
        if has_usable_password(account):
            if not current_password:
                raise DomainException("현재 비밀번호를 입력해 주세요.")
            try:
                ok = await asyncio.to_thread(self._hasher.verify, account.password_hash, current_password)
            except (VerificationError, InvalidHash):
                ok = False
            if not ok:
                raise DomainException("현재 비밀번호가 올바르지 않습니다.")
        account.status = AccountStatus.DEACTIVATED.value
        self._repo.update_account(account)
        purge_after = _now() + timedelta(days=self._grace_days)
        self._repo.create_account_deletion(account.id, purge_after)  # 멱등: 기존 미파기 레코드 재사용
        await self._session_manager.invalidate_all_for_user(account.id)  # 즉시 로그인 차단
        # SEC-14: 추가전용 감사 로그(구조화 로그로 기록; 전용 감사 스토어는 인프라 이월).
        logger.info({"event": "AccountDeactivated", "accountId": account.id, "purgeAfter": purge_after.isoformat()})
        # H2: AccountDeleted는 여기서 발행하지 않는다(유예 동안 데이터 보존·복구 가능).

    async def reactivate(self, account_id: str) -> None:
        """유예 중 소유자 재활성화(복구): DEACTIVATED→ACTIVE, 삭제 레코드 제거 (M1)."""
        rec = self._repo.get_account_deletion(account_id)
        if rec is None or rec.state != AccountStatus.DEACTIVATED.value:
            raise DomainException("복구할 수 없는 계정입니다.")
        account = self._repo.get_by_id(account_id)
        if account is None:
            raise DomainException("복구할 수 없는 계정입니다.")
        account.status = AccountStatus.ACTIVE.value
        self._repo.update_account(account)
        self._repo.delete_account_deletion(account_id)
        logger.info({"event": "AccountReactivated", "accountId": account_id})

    async def purge_job(self, now: datetime | None = None) -> int:
        """유예 경과 계정을 영구 파기한다(비동기 잡). 멱등 — 이미 PURGED는 제외.

        각 계정을 **독립 트랜잭션**으로 처리한다: AccountDeleted 발행(구독자 owner-scoped 파기) →
        자격증명 영구 삭제 → PURGED → **행별 커밋**. 한 계정의 실패(발행/삭제)는 롤백 후 로그를
        남기고 다음 계정으로 넘어간다 — 한 독성 레코드가 나머지 due 계정을 막던 머리물림(HOL)을
        제거한다. 실패한 계정은 DEACTIVATED로 남아 다음 회차에 재시도된다(at-least-once).
        event_id는 account_id에서 결정적으로 파생되어(uuid5) 재시도에도 동일하다.
        반환: 파기한 계정 수."""
        now = now or _now()
        purged = 0
        for rec in self._repo.get_due_deletions(now):
            account_id = rec.account_id
            event_id = str(uuid.uuid5(_ACCOUNT_DELETED_NS, account_id))
            try:
                # 발행을 먼저 — 발행 성공 후에만 파기를 커밋한다. 커밋이 실패하면 이벤트는 이미
                # 나갔어도 계정은 DEACTIVATED로 남아 다음 회차에 동일 event_id로 재시도된다(멱등).
                # 발행 자체가 실패하면 except로 빠져 파기를 건너뛴다(이벤트 유실→캐스케이드 누락 방지).
                await self._publisher.publish(account_id, datetime.now(UTC), event_id)
                self._owner_data_purger.purge(account_id)
                self._repo.delete_account_permanently(account_id)
                self._repo.mark_deletion_purged(account_id)
                self._repo.commit()
            except Exception:
                # 실패한 파기 트랜잭션을 롤백하고, 시도 횟수만 별도 트랜잭션으로 누적한다. 임계 초과 시
                # PURGE_FAILED(DLQ)로 격리해 무한 재시도를 끊고 운영 경보를 띄운다(S2). 격리된 행은
                # get_due_deletions(state=DEACTIVATED만)에서 자동 제외되므로 다음 회차부터 건너뛴다.
                self._repo.rollback()
                try:
                    attempts = self._repo.increment_deletion_attempts(account_id)
                    if attempts >= MAX_PURGE_ATTEMPTS:
                        self._repo.mark_deletion_failed(account_id)
                        logger.error(
                            "Purge permanently failing for account after %s attempts; "
                            "quarantined to PURGE_FAILED (DLQ) — manual reconciliation required.",
                            attempts,
                        )
                    else:
                        logger.exception(
                            "Purge failed for one account (attempt %s); left DEACTIVATED for next run "
                            "(at-least-once).",
                            attempts,
                        )
                    self._repo.commit()
                except Exception:
                    self._repo.rollback()
                    logger.exception("Failed to record purge attempt for account; will retry next run.")
                continue
            purged += 1
            logger.info({"event": "AccountPurged", "accountId": account_id, "eventId": event_id})
        return purged
