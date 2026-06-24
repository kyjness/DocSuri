"""FR-17 store round-trip against a real Postgres (B — real SQL, no AWS).

Validates ``S3RdsAssetStore`` end to end: S3 binaries written first (P8 write-order), then
the ``paper_asset`` manifest, with CHANGED-version idempotency (re-store replaces, not
duplicates) and remove. S3 is a fake boto3 client (monkeypatched), so no AWS is touched;
the RDS side runs the real psycopg/SQL against a live Postgres. Gated on
``DOCSURI_TEST_PG_DSN`` (skips otherwise); CI/dev set it to a throwaway Postgres.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

DSN = os.environ.get("DOCSURI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set DOCSURI_TEST_PG_DSN to a test Postgres")

from docsuri_ingestion.domain.assets import (  # noqa: E402
    ExtractedAsset,
    FigureTableAsset,
    asset_id,
)
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType  # noqa: E402

_DDL = """
CREATE TABLE IF NOT EXISTS paper_asset (
    paper_id TEXT NOT NULL, version INTEGER NOT NULL, asset_id TEXT NOT NULL,
    type TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', section_ref TEXT,
    ordinal INTEGER NOT NULL, source_mode TEXT NOT NULL, object_ref TEXT NOT NULL,
    page_ref INTEGER, bbox JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (paper_id, version, asset_id)
);
"""

_PAPER = "TEST-STORE-WRITE"


class _FakeS3:
    """Records S3 calls so the test can assert keys / content-type / SSE without AWS."""

    def __init__(self) -> None:
        self.puts: list[dict] = []
        self.deletes: list[dict] = []

    def put_object(self, **kw) -> dict:
        self.puts.append(kw)
        return {}

    def delete_object(self, **kw) -> dict:
        self.deletes.append(kw)
        return {}


@pytest.fixture
def fake_s3(monkeypatch):
    import boto3

    fake = _FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    return fake


def _clean() -> None:
    with psycopg.connect(DSN) as c:
        c.execute(_DDL)
        c.execute("DELETE FROM paper_asset WHERE paper_id = %s", (_PAPER,))
        c.commit()


def _rows() -> list[tuple]:
    with psycopg.connect(DSN) as c:
        return c.execute(
            "SELECT asset_id, type, object_ref, page_ref, bbox FROM paper_asset "
            "WHERE paper_id = %s ORDER BY type, ordinal",
            (_PAPER,),
        ).fetchall()


def _asset(kind: AssetType, ordinal: int) -> ExtractedAsset:
    meta = FigureTableAsset(
        asset_id=asset_id(_PAPER, 1, kind, ordinal),
        paper_id=_PAPER,
        version=1,
        type=kind,
        ordinal=ordinal,
        source_mode=AssetSourceMode.PAGE_CROP,
        caption=f"{kind.value} {ordinal}",
        page_ref=ordinal,
        bbox=(0.0, 0.0, 10.0, 10.0),
    )
    return ExtractedAsset(meta=meta, image=b"RIFF....WEBP-fake-bytes")


def test_store_writes_s3_then_rds_and_is_idempotent(fake_s3):
    from docsuri_ingestion.adapters.assets import S3RdsAssetStore

    _clean()
    store = S3RdsAssetStore(bucket="bkt", control_plane_dsn=DSN, prefix="assets")
    assets = (_asset(AssetType.FIGURE, 0), _asset(AssetType.TABLE, 0))

    manifest = store.store_assets(_PAPER, 1, assets)

    # S3: one object per asset, WebP content-type, server-side encryption set.
    assert len(fake_s3.puts) == 2
    assert {p["ContentType"] for p in fake_s3.puts} == {"image/webp"}
    assert all("ServerSideEncryption" in p for p in fake_s3.puts)
    assert {p["Key"] for p in fake_s3.puts} == {
        f"assets/{_PAPER}/v1/{a.meta.asset_id}.webp" for a in assets
    }
    # Manifest carries the s3:// object_refs the store derived from the writes (P8: S3 first).
    assert all(a.object_ref.startswith(f"s3://bkt/assets/{_PAPER}/v1/") for a in manifest.assets)

    # RDS manifest rows persisted with the same object_refs + nullable columns mapped.
    rows = _rows()
    assert len(rows) == 2
    assert {r[2] for r in rows} == {a.object_ref for a in manifest.assets}

    # CHANGED idempotency: storing the same version again replaces (still 2 rows, not 4).
    store.store_assets(_PAPER, 1, assets)
    assert len(_rows()) == 2

    # Remove clears the manifest (and best-effort deletes the objects).
    store.remove_assets(_PAPER)
    assert _rows() == []
    assert fake_s3.deletes  # at least one object delete was attempted
