"""RdsGlossaryRepository — real ``GlossaryRepositoryPort`` (TD-S6), owner-scoped (SEC-8).

Personal term overrides live in ``user_glossary`` on the inherited RDS PostgreSQL. Every
query is owner-scoped (``WHERE user_id = :user_id``) so one user can never read another's
preferences. ``glossary_ver`` is the per-user version that folds into the immutable cache
key (Q7); a preference upsert bumps it, invalidating that user's keys.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..domain.models import TermMapping


class RdsGlossaryRepository:
    def __init__(self, *, dsn: str | None = None, connection: Any | None = None) -> None:
        self._dsn = dsn
        self._conn = connection

    def _connect(self) -> Any:
        if self._conn is not None:
            # Injected connection (tests use a fake). The call site's ``with self._connect()``
            # drives its context manager — for a real psycopg connection that commits/closes on
            # exit, so inject a fresh (or fake) connection, not a long-lived shared one.
            return self._conn
        from ._pg import connection  # lazy: only the `real` extra needs psycopg

        return connection(self._dsn)  # pooled (graceful fallback to direct connect)

    def get_user_glossary(self, user_id: str) -> Sequence[TermMapping]:
        sql = (
            "SELECT term_from, term_to, prompt_enforced FROM user_glossary "
            "WHERE user_id = %s ORDER BY term_from"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            return [
                TermMapping(term_from=row[0], term_to=row[1], prompt_enforced=bool(row[2]))
                for row in cur.fetchall()
            ]

    def get_glossary_version(self, user_id: str) -> int:
        sql = "SELECT COALESCE(MAX(glossary_ver), 0) FROM user_glossary WHERE user_id = %s"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (user_id,))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def upsert_term(
        self, user_id: str, term_from: str, term_to: str, *, prompt_enforced: bool
    ) -> int:
        """Owner-scoped upsert; bumps the user's ``glossary_ver`` (feedback loop, §9.1)."""
        sql = (
            "INSERT INTO user_glossary "
            "(user_id, term_from, term_to, glossary_ver, prompt_enforced) "
            "VALUES (%s, %s, %s, "
            "(SELECT COALESCE(MAX(glossary_ver), 0) + 1 "
            "FROM user_glossary WHERE user_id = %s), %s) "
            "ON CONFLICT (user_id, term_from) DO UPDATE SET "
            "term_to = EXCLUDED.term_to, glossary_ver = EXCLUDED.glossary_ver, "
            "prompt_enforced = EXCLUDED.prompt_enforced, updated_at = now() "
            "RETURNING glossary_ver"
        )
        with self._connect() as conn, conn.cursor() as cur:
            # Serialize concurrent upserts for the SAME user so the MAX(glossary_ver)+1 read-then-
            # write can't race two edits onto one version (which would leave the second edit not
            # invalidating cached results, BR-S1). Transaction-scoped — auto-released at commit.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (user_id,))
            cur.execute(sql, (user_id, term_from, term_to, user_id, prompt_enforced))
            conn.commit()
            row = cur.fetchone()
            return int(row[0]) if row else 1
