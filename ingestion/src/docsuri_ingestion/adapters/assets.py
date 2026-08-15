"""FR-17 asset adapters: arXiv source bytes + S3(binary)/RDS(manifest) store.

Binary→S3 ``assets/`` prefix (private, SSE-KMS); manifest→shared RDS ``paper_asset``.
Write order is S3 PutObject then RDS upsert so a manifest row never points at a missing
object (P8). All failures are best-effort upstream (BR-27).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docsuri_ingestion.adapters.aws import s3_client, s3_put
from docsuri_ingestion.domain.assets import AssetManifest, ExtractedAsset, FigureTableAsset
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType
from docsuri_ingestion.domain.models import MetadataRecord
from docsuri_ingestion.ports import RawContentStorePort


def _no_nul(value: str | None) -> str | None:
    """Strip NUL (0x00) bytes from text bound for PostgreSQL — psycopg rejects them outright
    (``text fields cannot contain NUL (0x00) bytes``), which fails the whole asset upsert. PDF/TEI
    caption extraction occasionally yields embedded NULs; dropping them is loss-free for display."""
    return value.replace("\x00", "") if value else value


class ArxivAssetSource:
    """Fetch PDF / e-print bytes from arXiv for asset extraction (best-effort)."""

    def __init__(
        self,
        *,
        base_url: str = "https://arxiv.org",
        timeout_seconds: float = 20.0,
        raw_store: RawContentStorePort | None = None,
        raw_cache_mode: str = "off",
        contact: str | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_seconds
        # Same identity every other fetcher sends (BR-23b) — this was the one adapter still going
        # out anonymously, and a host that throttles unidentified clients would surface here as a
        # silent zero-asset paper (the _get below swallows all failures by design).
        self._contact = contact
        # B3 raw-content cache, same store the full-text source primes. Assets and full text are
        # fetched by two different adapters, so an assets-enabled paper that fell back to PDF text
        # downloaded the same multi-MB PDF twice. Reading the cache here makes the second download
        # a cache hit. Default "off" → this source fetches exactly as before.
        self._raw_store = raw_store
        self._raw_cache_mode = raw_cache_mode
        # Single-entry e-print memo (arxiv_id, bytes|None). The asset extractor and the doc-model
        # macro extractor both pull the same multi-MB tarball within one paper's processing, and
        # this source is shared between them (one instance in the wiring), so caching the most
        # recent paper lets the two calls share a single network fetch. Bounded to one tarball in
        # memory — replaced when a different paper is fetched.
        self._eprint_memo: tuple[str, bytes | None] | None = None

    def fetch_eprint(self, metadata: MetadataRecord) -> bytes | None:
        arxiv_id = metadata.identifier.arxiv_id
        if self._eprint_memo is not None and self._eprint_memo[0] == arxiv_id:
            return self._eprint_memo[1]
        data = self._get(f"{self._base}/e-print/{arxiv_id}")
        self._eprint_memo = (arxiv_id, data)
        return data

    def fetch_pdf(self, metadata: MetadataRecord) -> bytes | None:
        from docsuri_ingestion.http_limits import is_pdf_payload

        if self._raw_cache_mode in ("prefer", "only") and self._raw_store is not None:
            cached = self._raw_store.get_raw(metadata.paper_id, metadata.version, "pdf")
            # Same magic-byte check as every other reader of this cache key (BR-23b): an entry
            # written before the check can hold a landing page filed as a PDF, and cropping that
            # yields garbage assets. Poisoned entry -> treated as a miss.
            if cached and is_pdf_payload(cached):
                return cached
            if self._raw_cache_mode == "only":
                return None  # cache-or-nothing: a miss and a poisoned entry both answer None
        body = self._get(f"{self._base}/pdf/{metadata.identifier.arxiv_id}")
        # Best-effort path: a non-PDF body simply means no assets for this paper, never an error.
        return body if body is not None and is_pdf_payload(body) else None

    def _get(self, url: str) -> bytes | None:
        import httpx

        from docsuri_ingestion.http_limits import read_capped, user_agent

        try:
            with (
                httpx.Client(
                    timeout=self._timeout,
                    follow_redirects=True,
                    headers={"User-Agent": user_agent(self._contact)},
                ) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                return read_capped(response)  # caps oversize PDF/e-print (NFR §0.5)
        except Exception:  # noqa: BLE001 - best-effort: missing/oversize source → no assets
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
        client: Any = None,
    ) -> None:
        self._s3 = s3_client(client)
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
        return s3_put(
            self._s3,
            bucket=self._bucket,
            key=f"{self._prefix}/{meta.paper_id}/v{meta.version}/{meta.asset_id}.webp",
            body=asset.image,
            content_type="image/webp",
            kms_key_id=self._kms_key_id,
        )

    # ---- RDS ----

    def _conn(self) -> Any:
        if self._pool is None:
            from psycopg_pool import ConnectionPool

            self._pool = ConnectionPool(self._dsn, min_size=1, max_size=4)
        return self._pool.connection()

    def _upsert_rows(self, assets: Sequence[FigureTableAsset]) -> None:
        if not assets:
            return
        # One round trip for the paper's whole manifest. A figure-rich paper produced dozens of
        # rows, each its own execute; the statement and its conflict clause are identical per row,
        # so executemany sends the parameter sets together instead.
        params = [
            (
                a.paper_id, a.version, a.asset_id, a.type.value, _no_nul(a.caption),
                _no_nul(a.section_ref), a.ordinal, a.source_mode.value, a.object_ref,
                a.page_ref, json.dumps(a.bbox) if a.bbox else None,
            )
            for a in assets
        ]
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.executemany(
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
                    params,
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
