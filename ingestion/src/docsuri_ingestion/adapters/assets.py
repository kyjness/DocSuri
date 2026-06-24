"""FR-17 asset adapters: arXiv source bytes + S3(binary)/RDS(manifest) store.

Binary→S3 ``assets/`` prefix (private, SSE-KMS); manifest→shared RDS ``paper_asset``.
Write order is S3 PutObject then RDS upsert so a manifest row never points at a missing
object (P8). All failures are best-effort upstream (BR-27).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docsuri_ingestion.domain.assets import AssetManifest, ExtractedAsset, FigureTableAsset
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType
from docsuri_ingestion.domain.models import MetadataRecord


class ArxivAssetSource:
    """Fetch PDF / e-print bytes from arXiv for asset extraction (best-effort)."""

    def __init__(
        self, *, base_url: str = "https://arxiv.org", timeout_seconds: float = 20.0
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def fetch_eprint(self, metadata: MetadataRecord) -> bytes | None:
        return self._get(f"{self._base}/e-print/{metadata.identifier.arxiv_id}")

    def fetch_pdf(self, metadata: MetadataRecord) -> bytes | None:
        return self._get(f"{self._base}/pdf/{metadata.identifier.arxiv_id}")

    def _get(self, url: str) -> bytes | None:
        import httpx

        try:
            response = httpx.get(url, timeout=self._timeout, follow_redirects=True)
            response.raise_for_status()
            return response.content
        except Exception:  # noqa: BLE001 - best-effort: missing source → no assets
            return None


class S3RdsAssetStore:
    """Composite asset store: S3 binaries + RDS ``paper_asset`` manifest."""

    def __init__(
        self,
        *,
        bucket: str,
        control_plane_dsn: str,
        prefix: str = "assets",
        kms_key_id: str | None = None,
    ) -> None:
        import boto3

        self._s3 = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id
        self._dsn = control_plane_dsn
        self._pool: Any = None

    # ---- public port surface ----

    def store_assets(
        self, paper_id: str, version: int, assets: Sequence[ExtractedAsset]
    ) -> AssetManifest:
        stored: list[FigureTableAsset] = []
        # Replace any prior rows/objects for this exact version first (CHANGED idempotency).
        self._delete_version(paper_id, version)
        for asset in assets:
            object_ref = self._put_object(asset)  # (1) S3 binary first (P8)
            stored.append(_with_object_ref(asset.meta, object_ref))
        self._upsert_rows(stored)  # (2) RDS manifest after binaries exist
        return AssetManifest(paper_id=paper_id, version=version, assets=tuple(stored))

    def remove_assets(self, paper_id: str) -> None:
        keys = self._delete_rows(paper_id)  # rows first, then objects (orphans tolerated)
        for key in keys:
            try:
                self._s3.delete_object(Bucket=self._bucket, Key=key)
            except Exception:  # noqa: BLE001 - orphan object GC is non-critical
                continue

    # ---- S3 ----

    def _put_object(self, asset: ExtractedAsset) -> str:
        meta = asset.meta
        key = f"{self._prefix}/{meta.paper_id}/v{meta.version}/{meta.asset_id}.webp"
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": asset.image,
            "ContentType": "image/webp",
            "ServerSideEncryption": "aws:kms" if self._kms_key_id else "AES256",
        }
        if self._kms_key_id:
            kwargs["SSEKMSKeyId"] = self._kms_key_id
        self._s3.put_object(**kwargs)
        return f"s3://{self._bucket}/{key}"

    # ---- RDS ----

    def _conn(self) -> Any:
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(self._dsn, min_size=1, max_size=4)
        return self._pool.connection()

    def _upsert_rows(self, assets: Sequence[FigureTableAsset]) -> None:
        if not assets:
            return
        with self._conn() as conn:
            for a in assets:
                conn.execute(
                    """
                    INSERT INTO paper_asset (
                        paper_id, version, asset_id, type, caption, section_ref,
                        ordinal, source_mode, object_ref, page_ref, bbox
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (paper_id, version, asset_id) DO UPDATE SET
                        type = EXCLUDED.type, caption = EXCLUDED.caption,
                        section_ref = EXCLUDED.section_ref, ordinal = EXCLUDED.ordinal,
                        source_mode = EXCLUDED.source_mode, object_ref = EXCLUDED.object_ref,
                        page_ref = EXCLUDED.page_ref, bbox = EXCLUDED.bbox
                    """,
                    (
                        a.paper_id, a.version, a.asset_id, a.type.value, a.caption,
                        a.section_ref, a.ordinal, a.source_mode.value, a.object_ref,
                        a.page_ref, json.dumps(a.bbox) if a.bbox else None,
                    ),
                )
            conn.commit()

    def _delete_version(self, paper_id: str, version: int) -> None:
        with self._conn() as conn:
            rows = conn.execute(
                "DELETE FROM paper_asset WHERE paper_id = %s AND version = %s RETURNING object_ref",
                (paper_id, version),
            ).fetchall()
            conn.commit()
        for row in rows:
            self._delete_object_ref(row[0])

    def _delete_rows(self, paper_id: str) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "DELETE FROM paper_asset WHERE paper_id = %s RETURNING object_ref",
                (paper_id,),
            ).fetchall()
            conn.commit()
        return [_key_from_ref(row[0]) for row in rows if row[0]]

    def _delete_object_ref(self, object_ref: str | None) -> None:
        key = _key_from_ref(object_ref)
        if not key:
            return
        try:
            self._s3.delete_object(Bucket=self._bucket, Key=key)
        except Exception:  # noqa: BLE001
            pass


def _with_object_ref(meta: FigureTableAsset, object_ref: str) -> FigureTableAsset:
    from dataclasses import replace

    return replace(meta, object_ref=object_ref)


def _key_from_ref(object_ref: str | None) -> str:
    if not object_ref or not object_ref.startswith("s3://"):
        return ""
    return object_ref.split("/", 3)[3] if object_ref.count("/") >= 3 else ""


# Re-exported for callers building candidates outside the extractor (kept minimal).
__all__ = ["ArxivAssetSource", "S3RdsAssetStore", "AssetType", "AssetSourceMode"]
