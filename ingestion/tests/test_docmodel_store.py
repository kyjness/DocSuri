"""S3DocModelStore (BR-30, Infra §1.1b): doc-model/{paperId}/v{ver}.json round-trip + miss."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime

import pytest
from docsuri_shared.dtos import DocModel, SourceTier

from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel

_HTML = (
    '<article class="ltx_document"><section class="ltx_section" id="S1">'
    '<h2 class="ltx_title ltx_title_section">Intro</h2>'
    '<div class="ltx_para"><p class="ltx_p">Body.</p></div></section></article>'
)


def _doc() -> DocModel:
    return parse_html_to_docmodel(
        _HTML,
        paper_id="2401.00001",
        version=3,
        title="t",
        abstract=None,
        source_tier=SourceTier.native_html,
        parser_version="docmodel-parser@1",
        schema_version="1.0.0",
        generated_at=datetime(2026, 6, 23, tzinfo=UTC),
    )


class _FakeS3:
    """Minimal in-memory S3 double for the doc-model store paths."""

    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def put_object(self, **kwargs) -> None:
        self.objects[kwargs["Key"]] = kwargs

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        if Key not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}

    def get_paginator(self, name: str):
        objects = self.objects

        class _Paginator:
            def paginate(self, *, Bucket: str, Prefix: str):
                contents = [{"Key": k} for k in objects if k.startswith(Prefix)]
                yield {"Contents": contents}

        return _Paginator()

    def delete_objects(self, *, Bucket: str, Delete: dict) -> None:
        for obj in Delete["Objects"]:
            self.objects.pop(obj["Key"], None)


@pytest.fixture
def store(monkeypatch):
    import boto3

    fake = _FakeS3()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: fake)
    from docsuri_ingestion.adapters.aws import S3DocModelStore

    return S3DocModelStore(bucket="papers", kms_key_id="key-1"), fake


def test_get_returns_none_on_cache_miss(store) -> None:
    s3_store, _ = store
    assert s3_store.get("2401.00001", 3) is None


def test_put_then_get_round_trips(store) -> None:
    s3_store, fake = store
    ref = s3_store.put(_doc())
    assert ref == "s3://papers/doc-model/2401.00001/v3.json"

    stored = fake.objects["doc-model/2401.00001/v3.json"]
    assert stored["ServerSideEncryption"] == "aws:kms"
    assert stored["SSEKMSKeyId"] == "key-1"
    # Body is the serialized DocModel JSON (no pixels embedded).
    body = json.loads(stored["Body"])
    assert body["meta"]["paperId"] == "2401.00001"

    fetched = s3_store.get("2401.00001", 3)
    assert fetched is not None
    assert fetched.meta.version == 3
    assert fetched.sections[0].blocks[0].root.text == "Body."


def test_remove_drops_all_cached_versions(store) -> None:
    s3_store, fake = store
    s3_store.put(_doc())
    assert fake.objects
    s3_store.remove("2401.00001")
    assert fake.objects == {}
