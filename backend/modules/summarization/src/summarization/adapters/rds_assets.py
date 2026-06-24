"""RdsS3AssetReader — real ``AssetReadPort`` (FR-17, BR-S15).

Reads the figure/table manifest from ``paper_asset`` on the shared RDS PostgreSQL
(written by U1; read-only here) and presigns each S3 ``object_ref`` to a short-lived GET
URL. Only the signed URL leaves U7 — ``object_ref`` and internal columns are never
exposed (SEC-9).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..domain.models import StoredAsset


class RdsS3AssetReader:
    def __init__(
        self,
        *,
        dsn: str | None = None,
        connection: Any | None = None,
        s3_client: Any | None = None,
        signed_url_ttl_seconds: int = 600,
    ) -> None:
        self._dsn = dsn
        self._conn = connection
        self._s3 = s3_client
        self._ttl = signed_url_ttl_seconds

    def _connect(self) -> Any:
        if self._conn is not None:
            return self._conn
        import psycopg  # lazy: only the `real` extra needs psycopg

        return psycopg.connect(self._dsn)

    def _client(self) -> Any:
        if self._s3 is None:
            import boto3  # lazy

            self._s3 = boto3.client("s3")
        return self._s3

    def list_assets(self, paper_id: str, version: int) -> Sequence[StoredAsset]:
        sql = (
            "SELECT asset_id, type, ordinal, caption, source_mode, object_ref, page_ref, bbox "
            "FROM paper_asset WHERE paper_id = %s AND version = %s ORDER BY type, ordinal"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (paper_id, version))
            return [
                StoredAsset(
                    asset_id=row[0],
                    type=row[1],
                    ordinal=int(row[2]),
                    caption=row[3] or "",
                    source_mode=row[4],
                    object_ref=row[5],
                    page_ref=int(row[6]) if row[6] is not None else None,
                    bbox=row[7],
                )
                for row in cur.fetchall()
            ]

    def presign(self, object_ref: str) -> str | None:
        """Presign an ``s3://bucket/key`` ref. Returns ``None`` for a non-S3 ref so the
        caller skips the asset — the raw ``object_ref`` (internal path/identifier) must never
        leave U7 (SEC-9). Stays off the raising path so one bad row can't fail the whole list."""
        bucket, key = _split_s3_ref(object_ref)
        if bucket is None:
            return None
        return self._client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=self._ttl,
        )


def _split_s3_ref(object_ref: str) -> tuple[str | None, str | None]:
    if not object_ref or not object_ref.startswith("s3://"):
        return None, None
    rest = object_ref[len("s3://") :]
    bucket, _, key = rest.partition("/")
    if not bucket or not key:
        return None, None
    return bucket, key
