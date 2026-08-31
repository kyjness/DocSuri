"""요청한 개정판이 없을 때 저장된 판으로 떨어지는 폴백 (domain/version_fallback.py).

전문·요약·번역·그림은 넷 다 ``(paperId, version)``으로 키잉된 산출물을 읽고, 화면은 그
version을 검색 카드의 ``arxivId`` 접미사에서 읽는다. 접미사가 유실된 색인 레코드에서는
화면이 v1을 요청하는데 저장된 것은 v7뿐이라, 빌드 큐가 없는 배포에서 넷이 한꺼번에
``source_unavailable``로 굳었다(배포 색인 3,248편 중 1,023편).

그래서 **네 자리를 함께** 덮는다 — 하나만 고치면 전문은 열리고 그림이 빠진다.
"""

from __future__ import annotations

from docsuri_shared.docmodel_contract import DOCMODEL_PARSER_VERSION
from docsuri_shared.dtos import DocModel

from summarization.domain.models import (
    Persona,
    Scope,
    SourceKind,
    StoredAsset,
    SummaryRequest,
    TargetLang,
    Task,
)
from summarization.domain.source_selector import SourceSelector
from summarization.domain.version_fallback import fallback_version
from tests.stubs import make_orchestrator

PAPER = "1706.03762"
STORED_VERSION = 7  # 실제로 저장된 판
ASKED_VERSION = 1  # 접미사가 유실된 카드 id에서 화면이 계산해 보내는 판


def _doc(version: int, parser_version: str = DOCMODEL_PARSER_VERSION) -> DocModel:
    return DocModel.model_validate(
        {
            "meta": {
                "paperId": PAPER,
                "version": version,
                "title": "Attention Is All You Need",
                "provenance": {
                    "sourceTier": "ar5iv",
                    "parserVersion": parser_version,
                    "schemaVersion": "1.0.0",
                    "generatedAt": "2026-06-23T00:00:00Z",
                },
            },
            "fullText": "Intro",
            "sections": [{"id": "s1", "title": "Intro", "blocks": []}],
        }
    )


class _VersionedDocReader:
    """판별로 저장된 doc-model. 실 어댑터처럼 ``latest_version``을 갖는다."""

    def __init__(self, docs: dict[int, DocModel], *, latest: int | None = None) -> None:
        self._docs = docs
        self._latest = latest if latest is not None else (max(docs) if docs else None)
        self.reads: list[tuple[str, int]] = []
        self.latest_calls = 0

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        self.reads.append((paper_id, version))
        return self._docs.get(version)

    def latest_version(self, paper_id: str) -> int | None:
        self.latest_calls += 1
        return self._latest


class _NoLatestReader:
    """``latest_version``이 없는 리더 — 폴백이 조용히 꺼져야 한다."""

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        return None


class _VersionedFullText:
    def __init__(self, by_version: dict[int, str]) -> None:
        self._by_version = by_version
        self.reads: list[int] = []

    def get_full_text(self, paper_id: str, version: int) -> str | None:
        self.reads.append(version)
        return self._by_version.get(version)


class _VersionedAssetReader:
    def __init__(self, by_version: dict[int, list[StoredAsset]]) -> None:
        self._by_version = by_version
        self.reads: list[int] = []

    def list_assets(self, paper_id: str, version: int) -> list[StoredAsset]:
        self.reads.append(version)
        return self._by_version.get(version, [])

    def presign(self, object_ref: str) -> str | None:
        return "https://signed.example/x"


class _SpyQueue:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def enqueue_build(self, paper_id: str, version: int) -> None:
        self.calls.append((paper_id, version))


def _asset(asset_id: str = "a1") -> StoredAsset:
    return StoredAsset(
        asset_id=asset_id,
        type="figure",
        ordinal=1,
        caption="Figure 1",
        source_mode="page-crop",
        object_ref="s3://bucket/assets/x.png",
    )


def _request(task: Task = Task.SUMMARY, scope: Scope = Scope.FULL) -> SummaryRequest:
    return SummaryRequest(
        paper_id=PAPER,
        version=ASKED_VERSION,
        task=task,
        target_lang=TargetLang.KO,
        persona=Persona.EXPERT,
        scope=scope,
    )


# --- fallback_version 자체 ------------------------------------------------


def test_returns_the_stored_version_when_it_differs() -> None:
    reader = _VersionedDocReader({STORED_VERSION: _doc(STORED_VERSION)})
    assert fallback_version(reader, PAPER, ASKED_VERSION) == STORED_VERSION


def test_returns_none_when_the_stored_version_is_the_one_already_asked_for() -> None:
    """폴백이 같은 판을 다시 읽게 만들면 미스마다 왕복이 하나씩 늘 뿐이다."""
    reader = _VersionedDocReader({ASKED_VERSION: _doc(ASKED_VERSION)})
    assert fallback_version(reader, PAPER, ASKED_VERSION) is None


def test_returns_none_when_the_reader_has_no_latest_version() -> None:
    """덕타이핑이라 포트를 넓히지 않는다 — 그 메서드가 없는 리더에서는 폴백이 꺼진다."""
    assert fallback_version(_NoLatestReader(), PAPER, ASKED_VERSION) is None
    assert fallback_version(None, PAPER, ASKED_VERSION) is None


def test_a_failing_lookup_is_no_fallback_not_a_failed_request() -> None:
    """이미 미스인 경로의 보정이다. 여기서 예외를 올리면 source_unavailable이 500이 된다."""

    class _Boom:
        def latest_version(self, paper_id: str) -> int:
            raise RuntimeError("s3 down")

    assert fallback_version(_Boom(), PAPER, ASKED_VERSION) is None


def test_a_nonsense_latest_version_is_ignored() -> None:
    reader = _VersionedDocReader({}, latest=0)
    assert fallback_version(reader, PAPER, ASKED_VERSION) is None


# --- 자리 1: 전문(rich view) ----------------------------------------------


def test_doc_model_serves_the_stored_version_when_the_asked_one_is_missing() -> None:
    reader = _VersionedDocReader({STORED_VERSION: _doc(STORED_VERSION)})
    orch = make_orchestrator(doc_model_reader=reader)

    result = orch.doc_model(PAPER, ASKED_VERSION)

    assert result.doc is not None
    assert result.doc.meta.version == STORED_VERSION
    assert result.building is False
    assert reader.reads == [(PAPER, ASKED_VERSION), (PAPER, STORED_VERSION)]


def test_doc_model_heals_the_version_it_actually_served() -> None:
    """옛 파서로 지어진 판을 폴백으로 서빙했으면 재빌드도 **그 판**을 향해야 한다.

    요청받은 판(없는 판)으로 enqueue하면 매 조회가 재빌드를 부르고도 영원히 안 낫는다.
    """
    reader = _VersionedDocReader({STORED_VERSION: _doc(STORED_VERSION, "docmodel-parser@2")})
    queue = _SpyQueue()
    orch = make_orchestrator(doc_model_reader=reader, doc_model_build_queue=queue)

    assert orch.doc_model(PAPER, ASKED_VERSION).doc is not None
    assert queue.calls == [(PAPER, STORED_VERSION)]


def test_doc_model_still_reports_a_genuine_miss() -> None:
    """폴백은 없는 논문을 만들어 내지 않는다 — 아무 판도 없으면 그대로 미스다."""
    reader = _VersionedDocReader({})
    orch = make_orchestrator(doc_model_reader=reader)

    result = orch.doc_model(PAPER, ASKED_VERSION)

    assert result.doc is None
    assert result.building is False


def test_doc_model_hit_does_not_pay_for_a_version_lookup() -> None:
    """정상 경로에 왕복을 더하지 않는다 — 프리픽스 목록은 미스일 때만 돈다."""
    reader = _VersionedDocReader({ASKED_VERSION: _doc(ASKED_VERSION)})
    orch = make_orchestrator(doc_model_reader=reader)

    assert orch.doc_model(PAPER, ASKED_VERSION).doc is not None
    assert reader.latest_calls == 0


# --- 자리 2: 그림·도표 ------------------------------------------------------


def test_list_assets_falls_back_to_the_stored_version() -> None:
    """자산 API의 ``[]``는 '그림 없음'과 '그림을 못 찾았음'을 구분하지 못한다 —
    화면에는 둘 다 그림 없는 논문으로 보이므로 빈 목록으로 판정한다."""
    doc_reader = _VersionedDocReader({STORED_VERSION: _doc(STORED_VERSION)})
    assets = _VersionedAssetReader({STORED_VERSION: [_asset()]})
    orch = make_orchestrator(doc_model_reader=doc_reader, asset_reader=assets)

    refs = orch.list_assets(PAPER, ASKED_VERSION)

    assert refs is not None and [r.asset_id for r in refs] == ["a1"]
    assert assets.reads == [ASKED_VERSION, STORED_VERSION]


def test_list_assets_keeps_an_empty_manifest_empty_when_nothing_is_stored() -> None:
    doc_reader = _VersionedDocReader({})
    assets = _VersionedAssetReader({})
    orch = make_orchestrator(doc_model_reader=doc_reader, asset_reader=assets)

    assert orch.list_assets(PAPER, ASKED_VERSION) == []


# --- 자리 3·4: 요약/번역 입력 (doc-model, 그리고 옛 평문) -------------------


def test_source_selector_falls_back_for_the_doc_model_input() -> None:
    reader = _VersionedDocReader({STORED_VERSION: _doc(STORED_VERSION)})
    selector = SourceSelector(_VersionedFullText({}), doc_model_reader=reader)

    source = selector.select(_request())

    assert source is not None
    assert source.kind is SourceKind.FULL_TEXT
    assert source.doc_model is not None
    assert source.doc_model.meta.version == STORED_VERSION


def test_source_selector_falls_back_for_the_legacy_plain_text_input() -> None:
    """doc-model이 아예 없는 옛 논문도 평문이 같은 판 키를 쓴다 — 둘 다 덮어야 한다."""
    reader = _VersionedDocReader({}, latest=STORED_VERSION)
    full_text = _VersionedFullText({STORED_VERSION: "legacy body"})
    selector = SourceSelector(full_text, doc_model_reader=reader)

    source = selector.select(_request())

    assert source is not None
    assert source.kind is SourceKind.FULL_TEXT
    assert source.raw == "legacy body"
    assert full_text.reads == [ASKED_VERSION, STORED_VERSION]


def test_source_selector_resolves_the_version_once_for_both_inputs() -> None:
    """doc-model과 평문이 서로 다른 개정판을 섞으면 안 되고, 조회도 한 번이면 된다."""
    reader = _VersionedDocReader({}, latest=STORED_VERSION)
    selector = SourceSelector(_VersionedFullText({}), doc_model_reader=reader)

    assert selector.select(_request()) is None  # 초록도 없으니 소스 없음
    assert reader.latest_calls == 1


def test_source_selector_hit_does_not_pay_for_a_version_lookup() -> None:
    reader = _VersionedDocReader({ASKED_VERSION: _doc(ASKED_VERSION)})
    selector = SourceSelector(_VersionedFullText({}), doc_model_reader=reader)

    assert selector.select(_request()) is not None
    assert reader.latest_calls == 0
