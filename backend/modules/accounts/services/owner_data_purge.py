"""Owner-scoped data purge backstop for account hard-delete.

AccountDeleted is still published for asynchronous subscribers. This adapter handles
the same-RDS tables that already exist in the deployed monolith so the purge worker
does not leave first-party user data behind while subscriber infra catches up.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# SQL 식별자(테이블·컬럼)는 바인딩이 불가능하므로 f-string으로 보간된다. 값(account_id)은 항상
# :account_id로 바인딩되어 주입면은 식별자뿐이다. 호출부가 임의 spec을 넘기더라도 안전한 형태만
# 허용하도록 화이트리스트 정규식으로 검증한다(N2 — 심층 방어).
_SQL_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


@dataclass(frozen=True)
class OwnerScopedTable:
    table: str
    owner_column: str = "owner_id"


# Child tables first, then parent/summary rows.
OWNER_SCOPED_TABLES: tuple[OwnerScopedTable, ...] = (
    OwnerScopedTable("research_messages"),
    OwnerScopedTable("research_jobs"),
    OwnerScopedTable("novelty_messages"),
    OwnerScopedTable("novelty_progress_events"),
    OwnerScopedTable("novelty_artifacts"),
    OwnerScopedTable("novelty_notion_exports"),
    OwnerScopedTable("novelty_jobs"),
    OwnerScopedTable("saved_searches"),
    OwnerScopedTable("library_items"),
    OwnerScopedTable("search_history"),
    OwnerScopedTable("user_behavior_events"),
    OwnerScopedTable("user_interest_profiles"),
    OwnerScopedTable("personalization_settings"),
    OwnerScopedTable("mypage_subscriptions"),
    OwnerScopedTable("user_glossary", "user_id"),
)


class SqlOwnerDataPurger:
    def __init__(
        self,
        session: Session,
        tables: Iterable[OwnerScopedTable] = OWNER_SCOPED_TABLES,
    ) -> None:
        self._session = session
        tables = tuple(tables)
        # N2: 식별자 화이트리스트 검증을 생성 시점에 강제한다 — 안전하지 않은 spec은 즉시 거부.
        for spec in tables:
            if not _SQL_IDENT_RE.match(spec.table) or not _SQL_IDENT_RE.match(spec.owner_column):
                raise ValueError(f"Unsafe SQL identifier in OwnerScopedTable: {spec!r}")
        self._tables = tables
        self._schema: dict[str, set[str]] | None = None  # table -> column 집합 (1회 캐시)

    def _schema_map(self) -> dict[str, set[str]]:
        """존재하는 테이블과 각 컬럼 집합을 1회 반영해 캐시한다(N3). purge가 계정마다 호출돼도
        reflection은 한 번만 수행하며, owner_column 존재 검증에도 사용한다."""
        if self._schema is None:
            insp = inspect(self._session.get_bind())
            self._schema = {t: {c["name"] for c in insp.get_columns(t)} for t in insp.get_table_names()}
        return self._schema

    def purge(self, account_id: str) -> None:
        schema = self._schema_map()
        deleted_rows = 0

        for spec in self._tables:
            cols = schema.get(spec.table)
            if cols is None:
                continue  # 이 배포에 없는 테이블 — 건너뜀
            if spec.owner_column not in cols:
                # N3: 잘못된 owner 컬럼은 DELETE에서 터져 계정 파기를 영구 실패(→무한 재시도)시킨다.
                # 스킵 + 경보로 격리해 나머지 테이블 파기는 진행한다.
                logger.error(
                    "OwnerScopedTable %s has no column %s; skipping (check OWNER_SCOPED_TABLES).",
                    spec.table, spec.owner_column,
                )
                continue
            result = self._session.execute(
                text(f"DELETE FROM {spec.table} WHERE {spec.owner_column} = :account_id"),
                {"account_id": account_id},
            )
            deleted_rows += int(result.rowcount or 0)

        self._session.flush()
        logger.info(
            {"event": "OwnerScopedDataPurged", "accountId": account_id, "deletedRows": deleted_rows}
        )
