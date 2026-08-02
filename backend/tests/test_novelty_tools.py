"""corpus_search·form_evidence·view_figure 도구 어댑터 계약 + Notion 부재(BR-RA12)."""

from __future__ import annotations

import base64

import pytest

from backend.modules.novelty.adapters.corpus import CorpusSearchTool
from backend.modules.novelty.adapters.evidence import FormEvidenceTool
from backend.modules.novelty.adapters.external.datasets import DatasetSearchTool
from backend.modules.novelty.adapters.external.github import GithubSearchTool
from backend.modules.novelty.adapters.figures import ViewFigureTool
from backend.modules.novelty.domain.gate import evaluate_artifact
from backend.modules.novelty.domain.models import ArtifactKind
from backend.modules.novelty.ports.tools import ToolContext, ToolRegistry
from backend.modules.paper_assets import FigureAsset

from .novelty_fakes import FakeFigureAssetPort

_CTX = ToolContext(owner_id="o1", job_id="j1")


def _page_response(cards: list[dict], degraded: bool = False):
    from docsuri_shared._generated.dtos.search_schema import (
        ResultCardVM,
        ResultMeta,
        SearchResponse,
        SearchResultPageDTO,
    )

    page = SearchResultPageDTO(
        cards=[ResultCardVM(**card) for card in cards],
        meta=ResultMeta(resultCount=len(cards), degraded=degraded),
    )
    return SearchResponse(root=page)


def _card(arxiv_id: str = "2401.00001") -> dict:
    return {
        "title": "Sparse retrieval under DP",
        "authors": ["A. Researcher"],
        "year": 2024,
        "arxivId": arxiv_id,
        "abstractSnippet": "…",
        "relevance": "high",
        "arxivUrl": f"https://arxiv.org/abs/{arxiv_id}",
    }


def test_corpus_tool_exposes_record_refs_for_gate() -> None:
    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: _page_response([_card()]),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    assert result.ok is True
    assert result.record_refs == ("2401.00001",)
    assert result.content["items"][0]["sourceName"] == "arXiv"


def test_corpus_tool_abstain_and_validation_paths() -> None:
    from docsuri_shared._generated.dtos.search_schema import AbstainDTO, SearchResponse

    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: SearchResponse(root=AbstainDTO(reason="out_of_corpus")),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    assert result.ok is True and result.content["items"] == []
    assert tool.invoke({"query": "  "}, _CTX).ok is False


class _FakeEvidencePort:
    def __init__(self, result) -> None:
        self._result = result

    async def form_evidence(self, request, ctx):
        return self._result


def _evidence_result():
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
        SourceRef,
    )

    return EvidenceResult(
        state="ok",
        claims=[
            EvidenceItem(
                statement="DP retrieval degrades nDCG modestly",
                supporting=[
                    SourceRef(paperId="2401.00001", recordRef="rec:2401.00001", quote="…")
                ],
                conflicting=[],
            )
        ],
        coverage=EvidenceCoverage(paperCount=1, queryUsed="dp retrieval"),
    )


def test_form_evidence_snapshot_passes_gate_and_exposes_refs() -> None:
    tool = FormEvidenceTool(_FakeEvidencePort(_evidence_result()))
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is True
    assert result.record_refs == ("rec:2401.00001",)
    snapshot = result.content["evidence"]
    # 루프 자동 보존 경로와 동일 — 스냅샷은 게이트를 통과해야 한다.
    assert evaluate_artifact(
        ArtifactKind.EVIDENCE, snapshot, frozenset(result.record_refs)
    ) is None


def test_form_evidence_abstain_is_a_result_not_error() -> None:
    from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult

    tool = FormEvidenceTool(
        _FakeEvidencePort(EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus"))
    )
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is True
    assert result.content["evidence"]["state"] == "abstain"
    assert evaluate_artifact(
        ArtifactKind.EVIDENCE, result.content["evidence"], frozenset()
    ) is None


def test_form_evidence_engine_failure_returned_as_error() -> None:
    class _DownPort:
        async def form_evidence(self, request, ctx):
            raise RuntimeError("engine down")

    tool = FormEvidenceTool(_DownPort())
    result = tool.invoke({"topic": "dp retrieval"}, _CTX)
    assert result.ok is False
    assert "unavailable" in (result.error or "")


def test_no_buildable_registry_contains_notion() -> None:
    # BR-RA12 — 도구 레지스트리 어디에도 Notion이 없다(구성 가능한 전체 도구 대상).
    registry = ToolRegistry()

    class _Stub:
        def __init__(self, spec):
            self.spec = spec

        def invoke(self, args, ctx):
            raise NotImplementedError

    for tool_cls in (GithubSearchTool, DatasetSearchTool, CorpusSearchTool, FormEvidenceTool):
        registry.register(_Stub(tool_cls.spec))
    assert all("notion" not in name.lower() for name in registry.names())


def test_corpus_cards_carry_the_record_ref_key_the_gate_requires() -> None:
    """카드가 게이트가 요구하는 이름(recordRef)으로 값을 실어야 한다.

    arxivId가 곧 실재성 핸들이지만 카드에 `arxivId`로만 보이면, 모델은 그것을
    source_refs[].recordRef에 넣어야 한다는 걸 알 방법이 없다 — 로컬 실스택
    검증에서 실제로 산출물마다 unknown_source_ref로 거부돼 필수 세트가 완성되지
    않았다. 데이터가 스스로 계약을 담아야 프롬프트 설명에만 기대지 않는다.
    """
    tool = CorpusSearchTool(
        orchestrator=object(),
        grounding_hook=object(),
        runner=lambda *a, **k: _page_response([_card("2401.09999")]),
    )
    result = tool.invoke({"query": "privacy rag"}, _CTX)
    card = result.content["items"][0]
    assert card["recordRef"] == "2401.09999"
    # 게이트가 대조하는 집합과 카드에 보이는 값이 같아야 한다.
    assert card["recordRef"] in result.record_refs
    # paperId도 이름 그대로 실어야 한다 — 게이트는 recordRef만 대조하므로, 이름을
    # 알려주지 않으면 모델이 넣은 엉뚱한 paperId가 걸러지지 않고 저장된다.
    assert card["paperId"] == "2401.09999"


# ── view_figure (BLM §3, BR-RA11) ──

_PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 32


def _asset(asset_id: str, type_: str = "figure", ordinal: int = 1) -> FigureAsset:
    return FigureAsset(
        asset_id=asset_id,
        type=type_,
        ordinal=ordinal,
        caption=f"caption for {asset_id}",
        object_ref=f"s3://bucket/assets/2401.00001/v1/{asset_id}.webp",
    )


def _figure_tool(**kwargs) -> tuple[ViewFigureTool, FakeFigureAssetPort]:
    figure, formula = _asset("fig-1"), _asset("eq-3", "formula", 3)
    port = FakeFigureAssetPort(
        assets={("2401.00001", 1): [figure, formula]},
        blobs={
            figure.object_ref: ("image/webp", _PNG),
            formula.object_ref: ("image/webp", _PNG),
        },
    )
    kwargs.setdefault("max_image_bytes", 4 * 1024 * 1024)
    return ViewFigureTool(port, **kwargs), port


def test_view_figure_without_asset_id_lists_the_manifest() -> None:
    """Q7=A — 목록·캡션을 먼저 보고 필요한 것만 고르게 한다."""
    tool, _ = _figure_tool()
    result = tool.invoke({"record_ref": "2401.00001"}, _CTX)
    assert result.ok
    assert result.images == ()
    ids = [item["assetId"] for item in result.content["assets"]]
    assert ids == ["fig-1", "eq-3"]
    assert result.content["assets"][0]["caption"] == "caption for fig-1"


def test_view_figure_list_never_leaks_the_object_ref() -> None:
    """SEC-9 — 내부 스토리지 핸들은 모델에 보이지 않는다."""
    tool, _ = _figure_tool()
    result = tool.invoke({"record_ref": "2401.00001"}, _CTX)
    assert "s3://" not in str(result.content)


def test_view_figure_with_asset_id_returns_an_image_attachment() -> None:
    tool, port = _figure_tool()
    result = tool.invoke({"record_ref": "2401.00001", "asset_id": "fig-1"}, _CTX)
    assert result.ok
    assert len(result.images) == 1
    image = result.images[0]
    assert image.asset_id == "fig-1"
    assert image.media_type == "image/webp"
    assert base64.b64decode(image.data_b64) == _PNG
    # 텍스트 쪽에는 어느 자산인지만 남는다 — base64는 content로 가지 않는다.
    assert result.content["assetId"] == "fig-1"
    assert image.data_b64 not in str(result.content)
    assert port.fetched == ["s3://bucket/assets/2401.00001/v1/fig-1.webp"]


def test_view_figure_does_not_claim_new_record_refs() -> None:
    """이미 확보한 논문을 들여다보는 도구다 — 게이트 실재성 집합을 넓히지 않는다."""
    tool, _ = _figure_tool()
    result = tool.invoke({"record_ref": "2401.00001", "asset_id": "fig-1"}, _CTX)
    assert result.record_refs == ()


def test_view_figure_serves_formula_crops_unlike_the_u7_reader() -> None:
    """수식 crop 행의 존재 = LaTeX 복원 실패 → crop 서빙이 곧 '수식은 LaTeX 1차,
    crop 폴백'(BLM §3)의 결과다. u7 리더는 formula를 걸러내지만 여기서는 아니다."""
    tool, _ = _figure_tool()
    listed = tool.invoke({"record_ref": "2401.00001"}, _CTX)
    assert any(item["type"] == "formula" for item in listed.content["assets"])
    fetched = tool.invoke({"record_ref": "2401.00001", "asset_id": "eq-3"}, _CTX)
    assert fetched.ok and fetched.images[0].asset_id == "eq-3"


def test_view_figure_rejects_an_asset_that_is_not_in_the_manifest() -> None:
    """BR-RA11 실재 자산만 — 그리고 거부 사유는 다음 행동을 담아야 한다.

    ⑤2 실스택 검증 교훈: 사유가 '무엇이 틀렸는지'를 못 담으면 자율 루프는
    수렴하지 못하고 같은 실수를 반복하며 예산만 태운다.
    """
    tool, port = _figure_tool()
    result = tool.invoke({"record_ref": "2401.00001", "asset_id": "fig-999"}, _CTX)
    assert not result.ok
    assert result.images == ()
    assert "asset_id 없이" in result.error  # 목록을 먼저 받으라는 수리 지시
    assert port.fetched == []  # 실재하지 않는 자산은 스토리지까지 가지 않는다


def test_view_figure_refuses_an_oversized_image_with_an_alternative() -> None:
    """백엔드에 이미지 처리 의존성이 없어 다운스케일 불가 — 거부하되 대안을 준다."""
    tool, _ = _figure_tool(max_image_bytes=8)
    result = tool.invoke({"record_ref": "2401.00001", "asset_id": "fig-1"}, _CTX)
    assert not result.ok
    assert result.images == ()
    assert "다른 자산" in result.error


def test_view_figure_reports_papers_without_assets_instead_of_crashing() -> None:
    tool = ViewFigureTool(FakeFigureAssetPort(), max_image_bytes=4096)
    result = tool.invoke({"record_ref": "2401.77777"}, _CTX)
    assert not result.ok
    assert "자산이 없다" in result.error


def test_view_figure_uses_the_version_suffix_when_the_record_ref_carries_one() -> None:
    """`paper_asset`는 bare paper_id + 별도 version 컬럼이다 — 버전 있는 id로 조회하면
    영구 미스가 된다(u7 리더가 같은 함정을 겪었다)."""
    figure = _asset("fig-1")
    port = FakeFigureAssetPort(
        assets={("2401.00001", 2): [figure]},
        blobs={figure.object_ref: ("image/webp", _PNG)},
    )
    result = ViewFigureTool(port, max_image_bytes=4096).invoke(
        {"record_ref": "2401.00001v2"}, _CTX
    )
    assert result.ok
    assert [item["assetId"] for item in result.content["assets"]] == ["fig-1"]


def test_view_figure_tolerates_a_prefixed_record_ref_from_the_model() -> None:
    """recordRef는 모델이 쓴 값이다 — u7의 rsplit('v') 휴리스틱을 그대로 쓰면
    'arXiv:...'가 paper_id 'arXi'로 잘려 실재하는 논문에 "자산 없다"는 오답이 나간다."""
    tool, _ = _figure_tool()
    result = tool.invoke({"record_ref": "arXiv:2401.00001"}, _CTX)
    assert result.ok
    assert [item["assetId"] for item in result.content["assets"]] == ["fig-1", "eq-3"]


def test_view_figure_falls_back_when_the_requested_version_has_no_assets() -> None:
    """명시 버전 미스 ≠ 논문에 자산 없음. 백필 코퍼스는 버전 하나만 갖고 있어
    recordRef의 vN과 어긋날 수 있다 — 저장된 버전으로 폴백하되 어긋남을 밝힌다."""
    figure = _asset("fig-1")
    port = FakeFigureAssetPort(
        assets={("2401.00001", 1): [figure]},
        blobs={figure.object_ref: ("image/webp", _PNG)},
    )
    tool = ViewFigureTool(port, max_image_bytes=4096)

    listed = tool.invoke({"record_ref": "2401.00001v3"}, _CTX)
    assert listed.ok
    assert "v3" in listed.content["note"] and "v1" in listed.content["note"]

    # 이미지 경로도 같은 폴백을 해야 한다 — 아니면 목록↔조회가 서로를 무한 반복한다.
    fetched = tool.invoke({"record_ref": "2401.00001v3", "asset_id": "fig-1"}, _CTX)
    assert fetched.ok and fetched.images[0].asset_id == "fig-1"


def test_view_figure_separates_store_outage_from_a_missing_asset() -> None:
    """스토어 장애에 "다른 자산을 고르라"고 안내하면 로드될 수 없는 자산들로 캡 8회를
    태운다 — 사유가 곧 수리 지시이므로 둘을 구분한다."""
    figure = _asset("fig-1")
    port = FakeFigureAssetPort(
        assets={("2401.00001", 1): [figure]},
        blobs={figure.object_ref: ("image/webp", _PNG)},
        store_down=True,
    )
    result = ViewFigureTool(port, max_image_bytes=4096).invoke(
        {"record_ref": "2401.00001", "asset_id": "fig-1"}, _CTX
    )
    assert not result.ok
    assert result.result_summary == "view_figure: asset store unavailable"
    assert "반복하지" in result.error  # 다른 자산으로 재시도하라고 하지 않는다
    assert "다른 자산을 고르" not in result.error


# ── SqlS3FigureReader — S3 경계(부재 vs 장애, 상한, 스트림 정리) ──


class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.closed = False
        self.read_sizes: list[int | None] = []

    def read(self, size: int | None = None) -> bytes:
        self.read_sizes.append(size)
        return self._data if size is None else self._data[:size]

    def close(self) -> None:
        self.closed = True


class _FakeS3:
    def __init__(self, body: _FakeBody | None, *, content_length=..., error=None) -> None:
        self._body = body
        self._content_length = content_length
        self._error = error
        self.calls = 0

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 시그니처
        self.calls += 1
        if self._error is not None:
            raise self._error
        response = {"Body": self._body}
        if self._content_length is not ...:
            response["ContentLength"] = self._content_length
        return response


def _reader(s3, **kwargs):
    from backend.modules.paper_assets import SqlS3FigureReader

    return SqlS3FigureReader(lambda: None, s3_client=s3, **kwargs)


_REF = "s3://bucket/assets/2401.00001/v1/fig-1.webp"


def test_reader_never_buffers_past_the_cap_when_content_length_is_absent() -> None:
    """chunked 응답(로컬 s3proxy)에는 ContentLength가 없다 — 그때도 무제한으로 읽지
    않는다. 상한+1까지만 읽어 초과를 판정하고 스트림은 닫는다."""
    body = _FakeBody(b"x" * 5000)
    reader = _reader(_FakeS3(body, content_length=...))
    assert reader.fetch_bytes(_REF, max_bytes=100) is None
    assert body.read_sizes == [101]  # 전체 5000바이트를 버퍼링하지 않았다
    assert body.closed


def test_reader_rejects_on_content_length_before_reading_the_body() -> None:
    body = _FakeBody(b"x" * 5000)
    reader = _reader(_FakeS3(body, content_length=5000))
    assert reader.fetch_bytes(_REF, max_bytes=100) is None
    assert body.read_sizes == []  # 본문 전송 전에 끊었다
    assert body.closed


def test_reader_returns_bytes_within_the_cap() -> None:
    body = _FakeBody(b"x" * 50)
    reader = _reader(_FakeS3(body, content_length=50))
    assert reader.fetch_bytes(_REF, max_bytes=100) == ("image/webp", b"x" * 50)


def test_reader_treats_a_missing_key_as_absence_not_an_outage() -> None:
    """부재는 브레이커의 실패 집계 대상이 아니다 — 없는 자산 몇 건이 스토어를 차단하면
    멀쩡한 자산까지 못 읽는다."""
    from botocore.exceptions import ClientError

    error = ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
    reader = _reader(_FakeS3(None, error=error))
    assert reader.fetch_bytes(_REF, max_bytes=100) is None  # 예외 아님


def test_reader_raises_store_unavailable_on_credential_failure() -> None:
    """AWS_ENDPOINT_URL_S3 미설정 같은 배선 사고는 자산 부재로 위장되면 안 된다 —
    에이전트가 로드될 수 없는 자산들로 캡을 태운다(외부 연동 규칙: 재시도+차단)."""
    from botocore.exceptions import ClientError

    from backend.modules.paper_assets import AssetStoreUnavailable

    error = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
    s3 = _FakeS3(None, error=error)
    reader = _reader(s3)
    with pytest.raises(AssetStoreUnavailable):
        reader.fetch_bytes(_REF, max_bytes=100)
    assert s3.calls == 2  # 기계 재시도 1회(다른 외부 도구와 동일 정책)


def test_reader_skips_formats_no_provider_accepts() -> None:
    s3 = _FakeS3(_FakeBody(b"x"), content_length=1)
    reader = _reader(s3)
    assert reader.fetch_bytes("s3://bucket/assets/a/v1/fig.tiff", max_bytes=100) is None
    assert s3.calls == 0  # 프로바이더가 400을 주기 전에 우리가 막는다


def test_view_figure_never_serves_table_crops() -> None:
    """u1은 표를 구조화해 DocModel에 싣고 **동시에** 페이지 crop도 남기는데, DocModel은
    그 crop을 참조하지 않는다(로컬 코퍼스 표본: 표 crop 772건 중 참조 0건).

    서빙하면 에이전트가 이미 텍스트로 읽을 수 있는 것을 이미지로 다시 받으며 캡 8회를
    태운다 — BLM §3의 "표는 텍스트 경로로 읽힌다"와 BR-RA11의 "DocModel에 실재하는"에
    모두 어긋난다. u7 리더가 표를 서빙하는 것은 표시 갤러리라는 다른 목적이다.
    """
    figure, table = _asset("fig-1"), _asset("tbl-0", "table", 0)
    port = FakeFigureAssetPort(
        assets={("2401.00001", 1): [figure, table]},
        blobs={
            figure.object_ref: ("image/webp", _PNG),
            table.object_ref: ("image/webp", _PNG),
        },
    )
    tool = ViewFigureTool(port, max_image_bytes=4096)

    listed = tool.invoke({"record_ref": "2401.00001"}, _CTX)
    assert [item["assetId"] for item in listed.content["assets"]] == ["fig-1"]

    # 목록에 없으니 직접 지정해도 조회되지 않는다.
    fetched = tool.invoke({"record_ref": "2401.00001", "asset_id": "tbl-0"}, _CTX)
    assert not fetched.ok
    assert fetched.result_summary == "view_figure: unknown asset"
