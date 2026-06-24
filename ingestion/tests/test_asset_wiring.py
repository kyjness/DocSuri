"""FR-17 application wiring: assets are best-effort and never block indexing (BR-27)."""

from __future__ import annotations

from docsuri_ingestion.adapters.local import (
    CapturingObservabilityHub,
    FakeArxivSource,
    FakeEmbeddingPort,
    InMemoryControlPlaneStore,
    InMemoryFullTextStore,
    InMemoryQueue,
    InMemoryVectorIndex,
    sample_metadata,
)
from docsuri_ingestion.application import IngestionPipelineService
from docsuri_ingestion.domain.assets import (
    AssetManifest,
    ExtractedAsset,
    FigureTableAsset,
)
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType, DedupDecision, JobKind
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.resilience import (
    IngestFailureHandler,
    IngestionResilienceService,
    RetryPolicy,
)


class FakeAssetSource:
    def fetch_eprint(self, metadata):
        return b"eprint"

    def fetch_pdf(self, metadata):
        return b"pdf"


class _Extracted:
    def __init__(self, assets, *, raises=False):
        self._assets = assets
        self._raises = raises

    def extract(self, *, paper_id, version, pdf, eprint):
        if self._raises:
            raise RuntimeError("boom")
        return self._assets


class RecordingAssetStore:
    def __init__(self):
        self.stored: list[tuple[str, int, int]] = []
        self.removed: list[str] = []

    def store_assets(self, paper_id, version, assets):
        self.stored.append((paper_id, version, len(assets)))
        return AssetManifest(paper_id=paper_id, version=version, assets=())

    def remove_assets(self, paper_id):
        self.removed.append(paper_id)


def _one_asset() -> ExtractedAsset:
    meta = FigureTableAsset(
        asset_id="a", paper_id="2401.00001", version=1, type=AssetType.FIGURE,
        ordinal=0, source_mode=AssetSourceMode.PAGE_CROP,
    )
    return ExtractedAsset(meta=meta, image=b"webp")


def _build(*, extractor=None, store=None, source=None):
    observability = CapturingObservabilityHub()
    resilience = IngestionResilienceService(
        observability,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0, jitter_ratio=0.0),
        timeout_seconds=2.0,
    )
    control = InMemoryControlPlaneStore()
    index = InMemoryVectorIndex()
    pipeline = IngestionPipelineService(
        arxiv=FakeArxivSource([sample_metadata()]),
        full_text_store=InMemoryFullTextStore(),
        embedding=FakeEmbeddingPort(),
        vector_index=index,
        control_plane=control,
        observability=observability,
        resilience=resilience,
        failure_handler=IngestFailureHandler(InMemoryQueue(), observability),
        asset_extractor=extractor,
        asset_store=store,
        asset_source=source,
    )
    return pipeline, index


def _job() -> IngestionJob:
    return IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")


def test_assets_disabled_by_default_does_not_touch_asset_path() -> None:
    pipeline, index = _build()  # no asset components injected
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records  # indexing unaffected


def test_assets_stored_on_success() -> None:
    store = RecordingAssetStore()
    pipeline, index = _build(
        extractor=_Extracted((_one_asset(),)), store=store, source=FakeAssetSource()
    )
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records  # paper still indexed
    assert store.stored == [("2401.00001", 1, 1)]


def test_asset_failure_never_blocks_indexing() -> None:
    store = RecordingAssetStore()
    pipeline, index = _build(
        extractor=_Extracted((), raises=True), store=store, source=FakeAssetSource()
    )
    # Extractor raises, but the paper is still indexed successfully (BR-27).
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records
    assert store.stored == []  # store never reached, no crash
