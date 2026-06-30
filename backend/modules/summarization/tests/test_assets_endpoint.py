"""FR-17 asset read endpoint + RdsS3AssetReader (BR-S15/S17, SEC-9).

Routes are invoked directly with a fake Request (carrying ``state.principal`` and
``query_params``) — the gateway stand-in — matching the glossary endpoint tests.
"""

from __future__ import annotations

import json
from typing import Any

from summarization.adapters.rds_assets import RdsS3AssetReader, _split_s3_ref
from summarization.api.router import build_router
from summarization.domain.models import AssetRef, StoredAsset
from summarization.service.orchestrator import SummarizationOrchestrationService


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


class _FakeOrchestrator:
    def __init__(self, refs: list[AssetRef] | None) -> None:
        self._refs = refs
        self.calls: list[tuple] = []

    def list_assets(self, paper_id: str, version: int):
        self.calls.append((paper_id, version))
        return self._refs


def _endpoint(orch, path: str, method: str, *, en: bool = False):
    router = build_router(orch, assets_enabled=en)
    for route in router.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"{method} {path} not found")


def _ref(asset_id: str = "a1", ordinal: int = 0) -> AssetRef:
    return AssetRef(
        asset_id=asset_id,
        type="figure",
        ordinal=ordinal,
        caption="Figure 1",
        source_mode="page-crop",
        url="https://signed.example/x",
    )


# --- endpoint -------------------------------------------------------------


def _call_assets(orch, *, principal, assets_enabled, version="1"):
    endpoint = _endpoint(orch, "/api/papers/{paper_id}/assets", "GET", en=assets_enabled)
    resp = endpoint(_FakeRequest(principal, {"version": version}), "2401.00001")
    return resp.status_code, json.loads(resp.body)


def test_assets_requires_principal() -> None:
    status, body = _call_assets(_FakeOrchestrator([]), principal=None, assets_enabled=True)
    assert status == 401
    assert body == {"status": "unauthorized"}


def test_assets_license_gated_when_disabled() -> None:
    orch = _FakeOrchestrator([_ref()])
    _, body = _call_assets(orch, principal={"user_id": "u1"}, assets_enabled=False)
    assert body == {"status": "license_unavailable"}


def test_assets_fail_closed_503_when_orchestrator_raises() -> None:
    # An RDS/S3 fault must return a generic 503 (fail-closed, INV-4/SEC-15), not a raw 500
    # leaking internals — parity with the doc-model handler.
    class _Boom:
        def list_assets(self, paper_id: str, version: int):
            raise RuntimeError("rds down")

    endpoint = _endpoint(_Boom(), "/api/papers/{paper_id}/assets", "GET", en=True)
    resp = endpoint(_FakeRequest({"user_id": "u1"}, {"version": "1"}), "2401.00001")
    assert resp.status_code == 503
    assert json.loads(resp.body) == {"status": "unavailable"}


def test_assets_ok_returns_signed_refs_without_internal_fields() -> None:
    orch = _FakeOrchestrator([_ref("a1", 0), _ref("a2", 1)])
    status, body = _call_assets(orch, principal={"user_id": "u1"}, assets_enabled=True, version="3")
    assert status == 200
    assert body["status"] == "ok"
    assert [a["assetId"] for a in body["assets"]] == ["a1", "a2"]
    # SEC-9: only the signed url is exposed; no object_ref / internal columns.
    assert all("object_ref" not in a and "objectRef" not in a for a in body["assets"])
    assert all(a["url"].startswith("https://") for a in body["assets"])
    assert orch.calls == [("2401.00001", 3)]


def test_assets_reader_not_configured_is_license_unavailable() -> None:
    orch = _FakeOrchestrator(None)
    _, body = _call_assets(orch, principal={"user_id": "u1"}, assets_enabled=True)
    assert body == {"status": "license_unavailable"}


# --- gap #2: summarize validation_error carries a message -----------------


class _NoopOrchestrator:
    def run(self, *a, **k):  # pragma: no cover - not reached on a rejected request
        raise AssertionError("should not run on invalid input")


def test_summarize_validation_error_has_message() -> None:
    endpoint = _endpoint(_NoopOrchestrator(), "/api/summarize", "POST")
    resp = endpoint(_FakeRequest({"user_id": "u1"}), {})  # missing task/paperId
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body["status"] == "validation_error"
    assert isinstance(body.get("message"), str) and body["message"]


# --- adapter: RdsS3AssetReader (RDS read + S3 presign, SEC-9) --------------


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: tuple | None = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params):
        self.executed = (sql, params)

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple]) -> None:
        self._cur = _FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def cursor(self):
        return self._cur


class _FakeS3:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate_presigned_url(self, op, *, Params, ExpiresIn):
        self.calls.append({"op": op, "params": Params, "ttl": ExpiresIn})
        return f"https://signed/{Params['Key']}?e={ExpiresIn}"


def test_list_assets_query_excludes_formula_crops() -> None:
    """The manifest query must restrict to AssetView kinds (figure | table). U1 also writes
    type="formula" page-crop rows (doc-model viewer display assets) into paper_asset; surfacing
    them here breaks GET /assets validation and pollutes the U5 figure gallery."""
    conn = _FakeConn([])
    reader = RdsS3AssetReader(connection=conn, s3_client=_FakeS3())
    list(reader.list_assets("2401.00001", 1))
    sql = conn._cur.executed[0]
    assert "type IN ('figure', 'table')" in sql


def test_reader_lists_and_presigns() -> None:
    rows = [
        ("2401.00001:v1:figure:0", "figure", 0, "Figure 1", "page-crop",
         "s3://bkt/assets/2401.00001/v1/a0.webp", 2, None),
    ]
    s3 = _FakeS3()
    reader = RdsS3AssetReader(connection=_FakeConn(rows), s3_client=s3, signed_url_ttl_seconds=300)
    assets = list(reader.list_assets("2401.00001", 1))
    assert len(assets) == 1
    a = assets[0]
    assert isinstance(a, StoredAsset) and a.object_ref.startswith("s3://")  # internal
    url = reader.presign(a.object_ref)
    assert url.startswith("https://signed/assets/2401.00001/v1/a0.webp")
    assert s3.calls[0]["params"] == {"Bucket": "bkt", "Key": "assets/2401.00001/v1/a0.webp"}
    assert s3.calls[0]["ttl"] == 300


class _PartialFakeReader:
    """Lists two assets; only the s3:// one is presignable (the other returns None)."""

    def list_assets(self, paper_id: str, version: int):
        return [
            StoredAsset("a1", "figure", 0, "F1", "page-crop", "s3://bkt/ok.webp", 1, None),
            StoredAsset("a2", "table", 1, "T1", "page-crop", "/internal/leak.webp", 2, None),
        ]

    def presign(self, object_ref: str):
        return f"https://signed/{object_ref}" if object_ref.startswith("s3://") else None


def test_orchestrator_skips_non_presignable_assets() -> None:
    # SEC-9: a row whose object_ref can't be presigned is dropped, not leaked as a raw url.
    orch = SummarizationOrchestrationService.__new__(SummarizationOrchestrationService)
    orch._asset_reader = _PartialFakeReader()
    refs = orch.list_assets("2401.00001", 1)
    assert [r.asset_id for r in refs] == ["a1"]  # a2 dropped (non-s3 ref)
    assert all(r.url.startswith("https://") for r in refs)


def test_split_s3_ref() -> None:
    assert _split_s3_ref("s3://b/k/v.webp") == ("b", "k/v.webp")
    assert _split_s3_ref("not-s3") == (None, None)
    assert _split_s3_ref("s3://b") == (None, None)
