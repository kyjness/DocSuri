"""FR-17 reader round-trip against a real Postgres (B — real SQL, no AWS).

Validates ``RdsS3AssetReader`` against a live ``paper_asset`` table: the SELECT column
mapping into ``StoredAsset`` (types, ordinals, JSONB bbox, null page_ref) and the presign
call shape. S3 is a fake client (the reader accepts ``s3_client`` injection), so no AWS is
touched. Gated on ``DOCSURI_TEST_PG_DSN`` (skips otherwise — same convention as
``test_integration_real.py``); CI/dev set it to a throwaway Postgres.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")

DSN = os.environ.get("DOCSURI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set DOCSURI_TEST_PG_DSN to a test Postgres")

from summarization.adapters.rds_assets import RdsS3AssetReader  # noqa: E402

_DDL = """
CREATE TABLE IF NOT EXISTS paper_asset (
    paper_id TEXT NOT NULL, version INTEGER NOT NULL, asset_id TEXT NOT NULL,
    type TEXT NOT NULL, caption TEXT NOT NULL DEFAULT '', section_ref TEXT,
    ordinal INTEGER NOT NULL, source_mode TEXT NOT NULL, object_ref TEXT NOT NULL,
    page_ref INTEGER, bbox JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (paper_id, version, asset_id)
);
"""

_PAPER = "TEST-RDS-READ"


class _FakeS3:
    def generate_presigned_url(self, op: str, *, Params: dict, ExpiresIn: int) -> str:
        assert op == "get_object"
        return f"https://signed.example/{Params['Bucket']}/{Params['Key']}?X-Amz-Expires={ExpiresIn}"


@pytest.fixture
def seeded():
    # Seed via a short-lived connection; the reader opens its own per call (dsn path) so we
    # exercise the real ``psycopg.connect(dsn)`` lifecycle (commit + close each call).
    with psycopg.connect(DSN) as c:
        c.execute(_DDL)
        c.execute("DELETE FROM paper_asset WHERE paper_id = %s", (_PAPER,))
        # Seed a type="formula" page-crop alongside figure/table — the reader must filter it out
        # (it belongs to the doc-model viewer, not the summary asset gallery / AssetView enum).
        c.execute(
            "INSERT INTO paper_asset (paper_id,version,asset_id,type,caption,ordinal,"
            "source_mode,object_ref,page_ref,bbox) VALUES "
            "(%s,1,%s,'figure','Figure 1: demo',0,'page-crop',%s,3,%s),"
            "(%s,1,%s,'table','Table 1: demo',0,'page-crop',%s,NULL,NULL),"
            "(%s,1,%s,'formula','',0,'page-crop',%s,4,NULL)",
            (
                _PAPER, f"{_PAPER}:v1:figure:0",
                f"s3://bkt/assets/{_PAPER}/v1/fig.webp", "[0, 0, 612, 92]",
                _PAPER, f"{_PAPER}:v1:table:0",
                f"s3://bkt/assets/{_PAPER}/v1/tbl.webp",
                _PAPER, f"{_PAPER}:v1:formula:0",
                f"s3://bkt/assets/{_PAPER}/v1/eq.webp",
            ),
        )
    yield
    with psycopg.connect(DSN) as c:
        c.execute("DELETE FROM paper_asset WHERE paper_id = %s", (_PAPER,))


def test_list_assets_maps_rows_in_display_order(seeded):
    reader = RdsS3AssetReader(dsn=DSN, s3_client=_FakeS3())
    assets = reader.list_assets(_PAPER, 1)

    assert [a.type for a in assets] == ["figure", "table"]  # ORDER BY type, ordinal
    fig, tbl = assets
    assert fig.asset_id == f"{_PAPER}:v1:figure:0"
    assert fig.ordinal == 0 and fig.source_mode == "page-crop"
    assert fig.page_ref == 3 and fig.bbox == [0, 0, 612, 92]  # JSONB → list
    assert fig.object_ref.startswith("s3://bkt/")  # internal — presigned before leaving U7
    assert tbl.page_ref is None and tbl.bbox is None  # nullable columns


def test_presign_signs_s3_ref_and_drops_non_s3():
    reader = RdsS3AssetReader(dsn=DSN, s3_client=_FakeS3(), signed_url_ttl_seconds=900)
    url = reader.presign(f"s3://bkt/assets/{_PAPER}/v1/fig.webp")
    assert "bkt" in url and f"assets/{_PAPER}/v1/fig.webp" in url and "900" in url
    # SEC-9: a non-s3 ref must never be returned raw — None so the caller skips the asset.
    assert reader.presign("https://arxiv.org/abs/2401.00001") is None
