"""doc-model read endpoint + S3DocModelReader (BR-30, D4/D6, SEC-9).

Mirrors the assets endpoint tests: routes are invoked directly with a fake Request
(carrying ``state.principal`` + ``query_params``) as the gateway stand-in. The endpoint is
read-only and OA-license-gated (off by default); the doc-model it returns is url-free —
figure signed URLs come from the parallel ``/assets`` manifest (joined by assetId on the client).
"""

from __future__ import annotations

import io
import json
from typing import Any

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from docsuri_shared.dtos import DocModel

from summarization.adapters.s3_docmodel import S3DocModelReader
from summarization.api.router import build_router
from summarization.domain.models import DocModelLookup


class _FakeState:
    def __init__(self, principal: Any) -> None:
        self.principal = principal


class _FakeQuery:
    def __init__(self, params: dict[str, str]) -> None:
        self._p = params

    def get(self, key: str, default: str | None = None) -> str | None:
        return self._p.get(key, default)


class _FakeRequest:
    def __init__(self, principal: Any, query: dict[str, str] | None = None) -> None:
        self.state = _FakeState(principal)
        self.headers: dict[str, str] = {}
        self.query_params = _FakeQuery(query or {})


def _doc_model(paper_id: str = "2401.00001", version: int = 1) -> DocModel:
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": paper_id,
                "version": version,
                "title": "A Paper",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": DOCMODEL_PARSER_VERSION,
                    "schemaVersion": DOCMODEL_SCHEMA_VERSION,
                    "generatedAt": "2026-06-23T00:00:00Z",
                },
            },
            "fullText": "Introduction\n\nBody.",
            "sections": [
                {
                    "id": "s1",
                    "title": "Introduction",
                    "blocks": [{"id": "s1.p1", "type": "paragraph", "text": "Body."}],
                }
            ],
        }
    )


class _FakeOrchestrator:
    def __init__(self, lookup: DocModelLookup) -> None:
        self._lookup = lookup
        self.calls: list[tuple] = []

    def doc_model(self, paper_id: str, version: int) -> DocModelLookup:
        self.calls.append((paper_id, version))
        return self._lookup


def _endpoint(orch, *, en: bool):
    router = build_router(orch, docmodel_enabled=en)
    for route in router.routes:
        if getattr(route, "path", None) == "/api/papers/{paper_id}/doc-model" and "GET" in getattr(
            route, "methods", set()
        ):
            return route.endpoint
    raise AssertionError("GET /api/papers/{paper_id}/doc-model not found")


def _call(orch, *, principal, enabled, version="1"):
    endpoint = _endpoint(orch, en=enabled)
    resp = endpoint(_FakeRequest(principal, {"version": version}), "2401.00001")
    return resp.status_code, json.loads(resp.body)


# --- endpoint -------------------------------------------------------------


def test_requires_principal() -> None:
    orch = _FakeOrchestrator(DocModelLookup(doc=_doc_model()))
    status, body = _call(orch, principal=None, enabled=True)
    assert status == 401
    assert body == {"status": "unauthorized"}


def test_license_gated_when_disabled() -> None:
    orch = _FakeOrchestrator(DocModelLookup(doc=_doc_model()))
    _, body = _call(orch, principal={"user_id": "u1"}, enabled=False)
    assert body == {"status": "license_unavailable"}
    assert orch.calls == []  # never touched the reader behind the gate


def test_source_unavailable_when_no_build_queue() -> None:
    # Empty lookup (miss + no build queue wired) → source_unavailable (prior behavior).
    orch = _FakeOrchestrator(DocModelLookup())
    _, body = _call(orch, principal={"user_id": "u1"}, enabled=True, version="2")
    assert body == {"status": "source_unavailable"}
    assert orch.calls == [("2401.00001", 2)]


def test_building_when_lazy_build_triggered() -> None:
    # Miss with a build queue wired → building + poll hint (client polls again).
    orch = _FakeOrchestrator(DocModelLookup(building=True, retry_after_ms=2000))
    status, body = _call(orch, principal={"user_id": "u1"}, enabled=True, version="2")
    assert status == 200
    assert body == {"status": "building", "retryAfterMs": 2000}


def test_ok_returns_docmodel_union() -> None:
    orch = _FakeOrchestrator(DocModelLookup(doc=_doc_model(version=3)))
    status, body = _call(orch, principal={"user_id": "u1"}, enabled=True, version="3")
    assert status == 200
    assert body["status"] == "ok"
    assert body["cached"] is True
    assert body["docModel"]["meta"]["paperId"] == "2401.00001"
    assert body["docModel"]["sections"][0]["blocks"][0]["text"] == "Body."
    assert orch.calls == [("2401.00001", 3)]


def test_fail_closed_503_when_orchestrator_raises() -> None:
    # A store/queue fault must surface as a generic 503 (fail-closed, INV-4/SEC-15), never a raw
    # 500 leaking internals. A bare 500 here was also what the client retried in a tight loop.
    class _Boom:
        def doc_model(self, paper_id: str, version: int) -> DocModelLookup:
            raise RuntimeError("s3 down")

    endpoint = _endpoint(_Boom(), en=True)
    resp = endpoint(_FakeRequest({"user_id": "u1"}, {"version": "1"}), "2401.00001")
    assert resp.status_code == 503
    assert json.loads(resp.body) == {"status": "unavailable"}


# --- adapter: S3DocModelReader (S3 read, read-only) -----------------------


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.calls: list[str] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        self.calls.append(Key)
        if Key not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}


def test_reader_reads_cached_doc_model() -> None:
    body = _doc_model(version=2).model_dump_json(exclude_none=True).encode("utf-8")
    s3 = _FakeS3({"doc-model/2401.00001/v2.json": body})
    reader = S3DocModelReader(bucket="papers", client=s3)
    doc = reader.get_doc_model("2401.00001", 2)
    assert doc is not None
    assert doc.meta.version == 2
    assert s3.calls == ["doc-model/2401.00001/v2.json"]


def test_reader_returns_none_on_miss() -> None:
    reader = S3DocModelReader(bucket="papers", client=_FakeS3({}))
    assert reader.get_doc_model("2401.00001", 9) is None


def test_reader_treats_stale_doc_model_as_miss_before_schema_validation() -> None:
    payload = _doc_model(version=2).model_dump(mode="json", exclude_none=True)
    payload["meta"]["provenance"]["parserVersion"] = "docmodel-parser@0"
    del payload["fullText"]  # old stale shape should rebuild, not fail the read path.
    s3 = _FakeS3({"doc-model/2401.00001/v2.json": json.dumps(payload).encode("utf-8")})
    reader = S3DocModelReader(bucket="papers", client=s3)

    assert reader.get_doc_model("2401.00001", 2) is None


def test_reader_treats_schema_version_mismatch_as_miss() -> None:
    payload = _doc_model(version=2).model_dump(mode="json", exclude_none=True)
    payload["meta"]["provenance"]["schemaVersion"] = "0.9.0"
    s3 = _FakeS3({"doc-model/2401.00001/v2.json": json.dumps(payload).encode("utf-8")})
    reader = S3DocModelReader(bucket="papers", client=s3)

    assert reader.get_doc_model("2401.00001", 2) is None


def test_reader_strips_version_suffix_from_paper_id() -> None:
    # The app carries versioned paper ids (2304.10557v1) but U1 keys the doc-model store on
    # the bare id (doc-model/{bareId}/v{version}.json). The read key must strip the trailing
    # vN or a built artifact is never found (perpetual miss → "no rich source").
    body = _doc_model(version=1).model_dump_json(exclude_none=True).encode("utf-8")
    s3 = _FakeS3({"doc-model/2304.10557/v1.json": body})
    reader = S3DocModelReader(bucket="papers", client=s3)
    doc = reader.get_doc_model("2304.10557v1", 1)
    assert doc is not None
    assert s3.calls == ["doc-model/2304.10557/v1.json"]
