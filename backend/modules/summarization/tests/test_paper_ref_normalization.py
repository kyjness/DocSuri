"""U7 read adapters must key on the bare paper id, not the app's versioned id.

U1 stores under the bare id (full-text/{bareId}/v{ver}.txt, doc-model/{bareId}/v{ver}.json,
paper_asset.paper_id = bareId). The app carries versioned ids (2304.10557v1), so each U7
reader must strip the version suffix or it never finds what U1 wrote (perpetual miss →
"no rich source" / no figures). Doc-model's own version of this is covered in
test_docmodel_endpoint.py / test_docmodel_build_trigger.py.
"""

from __future__ import annotations

import io

from summarization.adapters._paper_ref import bare_paper_id
from summarization.adapters.rds_assets import RdsS3AssetReader
from summarization.adapters.s3_full_text import S3FullTextSource


def test_bare_paper_id_strips_only_trailing_version() -> None:
    assert bare_paper_id("2304.10557v1") == "2304.10557"  # new-style versioned
    assert bare_paper_id("2304.10557") == "2304.10557"  # already bare → unchanged
    assert bare_paper_id("hep-th/9901001v2") == "hep-th/9901001"  # old-style versioned


# --- full-text reader -----------------------------------------------------


class _FakeS3:
    def __init__(self) -> None:
        self.keys: list[str] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.keys.append(Key)
        return {"Body": io.BytesIO(b"full text body")}


def test_full_text_reader_strips_version_suffix() -> None:
    s3 = _FakeS3()
    reader = S3FullTextSource(bucket="papers", client=s3)
    text = reader.get_full_text("2304.10557v1", 1)
    assert text == "full text body"
    assert s3.keys == ["full-text/2304.10557/v1.txt"]


# --- assets reader (RDS) --------------------------------------------------


class _FakeCursor:
    def __init__(self) -> None:
        self.params: tuple | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple) -> None:
        self.params = params

    def fetchall(self) -> list:
        return []


class _FakeConn:
    def __init__(self) -> None:
        self.cur = _FakeCursor()

    def __enter__(self) -> _FakeConn:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def cursor(self) -> _FakeCursor:
        return self.cur


def test_assets_reader_strips_version_suffix_in_query() -> None:
    conn = _FakeConn()
    reader = RdsS3AssetReader(connection=conn)
    reader.list_assets("2304.10557v1", 1)
    assert conn.cur.params == ("2304.10557", 1)  # bare id + separate version
